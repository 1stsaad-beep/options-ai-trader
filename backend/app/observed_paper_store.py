"""Atomic observed-paper ledger, immutable segmented events and fenced ownership.

Financial history is streamed during recovery, not loaded into the active state.
Hashes detect accidental corruption; they do not attest a broker or stop a DB
administrator from deliberately replacing both an entire history and its root.
"""
from datetime import datetime, timedelta, timezone
import json
import re

from .observed_paper import apply, canonical, create, digest, VERSION
from .paper_settlement import stamp
from .observed_option_replay import iso

ZERO = '0' * 64
SEGMENT_BYTES = 4 * 1024 * 1024
SEGMENT_EVENTS = 256
MAX_EVENT_BYTES = 1024 * 1024


class LedgerConflict(ValueError):
    pass


def identity(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,120}', value):
        raise ValueError('Invalid operation identity')
    return value


def event_hash(row):
    return digest({k:row[k] for k in ('account_id','sequence','request_key','fingerprint',
        'receipt_id','payload','previous_hash','after_hash','created','size_bytes')})


def segment_next(current, row):
    rollover = current is not None and (current['last_sequence']-current['first_sequence']+1 >= SEGMENT_EVENTS
        or current['size_bytes']+row['size_bytes'] > SEGMENT_BYTES)
    if current is None or rollover:
        current = {'account_id':row['account_id'],'number':1 if current is None else current['number']+1,
            'first_sequence':row['sequence'],'last_sequence':row['sequence']-1,'size_bytes':0,'sealed':0,'chain_hash':ZERO}
    current = dict(current)
    current.update(last_sequence=row['sequence'],size_bytes=current['size_bytes']+row['size_bytes'],
                   chain_hash=digest([current['chain_hash'],row['digest']]))
    return current, rollover


class ObservedPaperStore:
    def __init__(self, repo, now=None):
        self.repo = repo
        self.now = now or (lambda:datetime.now(timezone.utc))
        self._verified = {}

    def create(self, account, name, initial=1000000, source='fixture', *, version=VERSION):
        state = create(account,name,initial,source,version=version); at=iso(self.now())
        with self.repo.transaction() as db:
            if db.one('SELECT id FROM observed_paper_accounts WHERE id=?',(account,)):
                raise LedgerConflict('Observed-paper account already exists')
            if db.one('SELECT COUNT(*) AS n FROM observed_paper_accounts')['n'] >= 100:
                raise LedgerConflict('Observed-paper account limit reached')
            db.execute('INSERT INTO observed_paper_accounts VALUES(?,?,?,?)',(account,canonical(state),-1,ZERO))
            row=self._append(db,account,-1,ZERO,'create',{'kind':'CREATE','state':state},state,{'kind':'CREATE','externalOrder':False},at)
        self._verified[account]=(0,row['digest'],digest(state))
        return {'version':0,'eventHash':row['digest'],'state':state}

    def accounts(self):
        with self.repo.transaction() as db:
            return [r['id'] for r in db.all('SELECT id FROM observed_paper_accounts ORDER BY id')]

    def experiment(self, source='alpaca'):
        """Explicit, atomic four-account setup; retries never reset an account.

        Membership is bound to the original genesis request key, not a mutable
        name or a matching balance. A colliding or partial set requires review.
        No worker is enabled and no account in another namespace is modified.
        """
        from .observed_paper_experiment import bootstrap
        return bootstrap(self, source)

    def comparison(self, accounts):
        from .observed_paper_experiment import compare
        return compare(self, accounts)

    def snapshot(self, account, *, full=False):
        with self.repo.transaction() as db:
            row,state=self._read(db,account,full=full)
            return {'version':row['version'],'eventHash':row['event_hash'],'state':state}

    def performance(self, account):
        from .observed_paper_performance import summarize
        with self.repo.transaction() as db:
            row,state=self._read(db,account)
            result=summarize(db.stream('SELECT payload FROM observed_paper_events WHERE account_id=? ORDER BY sequence',(account,)),state)
            return result|{'version':row['version'],'eventHash':row['event_hash']}

    def _read(self, db, account, *, full=False):
        row=db.one('SELECT * FROM observed_paper_accounts WHERE id=?',(account,))
        if row is None: raise LedgerConflict('Unknown observed-paper account')
        try:
            state=json.loads(row['payload'])
            marker=(row['version'],row['event_hash'],digest(state))
            if not full and self._verified.get(account)==marker: return row,state
            rebuilt=None; previous=ZERO; sequence=-1; segment=None; segment_count=0
            # DB cursor iteration is bounded by one original event + live state.
            for raw in db.stream('SELECT * FROM observed_paper_events WHERE account_id=? ORDER BY sequence',(account,)):
                e=dict(raw); sequence+=1
                if (e['sequence']!=sequence or e['previous_hash']!=previous or e['digest']!=event_hash(e)
                        or e['size_bytes']!=len(e['payload'].encode()) or e['size_bytes']>MAX_EVENT_BYTES):
                    raise ValueError()
                payload=json.loads(e['payload']); command=payload['command']
                if e['fingerprint']!=digest(command) or e['created']!=payload['at']: raise ValueError()
                if sequence==0:
                    seed=command['state']
                    rebuilt=create(seed['id'],seed['name'],seed['initialCash'],seed['source'],version=seed['contract'])
                    if command!={'kind':'CREATE','state':rebuilt} or seed['id']!=account: raise ValueError()
                    facts={'kind':'CREATE','externalOrder':False}
                else:
                    rebuilt,facts=apply(rebuilt,command,payload['at'])
                if facts!=payload['facts'] or digest(rebuilt)!=e['after_hash']: raise ValueError()
                next_segment, rollover=segment_next(segment,e)
                if rollover:
                    segment['sealed']=1
                    if db.one('SELECT * FROM observed_paper_segments WHERE account_id=? AND number=?',(account,segment['number']))!=segment:
                        raise ValueError()
                    segment_count+=1
                segment=next_segment; previous=e['digest']
            if (rebuilt!=state or sequence!=row['version'] or previous!=row['event_hash'] or segment is None
                    or db.one('SELECT * FROM observed_paper_segments WHERE account_id=? AND number=?',(account,segment['number']))!=segment
                    or db.one('SELECT COUNT(*) AS n FROM observed_paper_segments WHERE account_id=?',(account,))['n']!=segment_count+1):
                raise ValueError()
            self._verified[account]=marker
            return row,state
        except (ValueError,KeyError,TypeError,OverflowError,AttributeError):
            self._verified.pop(account,None)
            raise LedgerConflict('Observed-paper history requires offline review') from None

    def command(self, account, key, command, *, expected_version=None, lease=None):
        identity(key)
        # Canonical size checks also reject NaN before it enters a durable event.
        if len(canonical(command).encode())>MAX_EVENT_BYTES//2: raise ValueError('Command too large')
        fingerprint=digest(command); at=self.now(); at_text=iso(at)
        with self.repo.transaction() as db:
            row,state=self._read(db,account)
            old=db.one('SELECT * FROM observed_paper_events WHERE account_id=? AND request_key=?',(account,key))
            if old:
                if old['fingerprint']!=fingerprint: raise LedgerConflict('Operation identity reused with different input')
                return self._receipt(old)
            if expected_version is not None and (type(expected_version) is not int or expected_version!=row['version']):
                raise LedgerConflict('Observed-paper state changed during capture')
            if command.get('kind')=='CYCLE':
                if expected_version is None or not self._owns(db,lease,at):
                    raise LedgerConflict('Current worker ownership required')
            elif lease is not None:
                raise LedgerConflict('Worker lease is only valid for captured cycles')
            receipt=command.get('request',{}).get('id') if command.get('kind')=='SETTLE' else None
            if receipt and db.one('SELECT sequence FROM observed_paper_events WHERE account_id=? AND receipt_id=?',(account,receipt)):
                raise LedgerConflict('Settlement receipt already recorded')
            updated,facts=apply(state,command,at_text)
            event=self._append(db,account,row['version'],row['event_hash'],key,command,updated,facts,at_text,receipt)
        self._verified[account]=(event['sequence'],event['digest'],digest(updated))
        return self._receipt(event)

    def _append(self, db, account, version, previous, key, command, state, facts, at, receipt=None):
        payload=canonical({'at':at,'command':command,'facts':facts})
        row={'account_id':account,'sequence':version+1,'request_key':key,'fingerprint':digest(command),
             'receipt_id':receipt,'payload':payload,'previous_hash':previous,'after_hash':digest(state),
             'created':at,'size_bytes':len(payload.encode())}
        if row['size_bytes']>MAX_EVENT_BYTES: raise ValueError('Event too large')
        row['digest']=event_hash(row)
        columns=tuple(row)
        db.execute('INSERT INTO observed_paper_events ('+','.join(columns)+') VALUES('+','.join('?' for _ in columns)+')',tuple(row.values()))
        old=db.one('SELECT * FROM observed_paper_segments WHERE account_id=? ORDER BY number DESC LIMIT 1',(account,))
        segment,rollover=segment_next(old,row)
        if rollover:
            db.execute('UPDATE observed_paper_segments SET sealed=1 WHERE account_id=? AND number=?',(account,old['number']))
        if old is None or rollover:
            db.execute('INSERT INTO observed_paper_segments VALUES(?,?,?,?,?,?,?)',tuple(segment.values()))
        else:
            db.execute('UPDATE observed_paper_segments SET last_sequence=?,size_bytes=?,chain_hash=? WHERE account_id=? AND number=?',
                (segment['last_sequence'],segment['size_bytes'],segment['chain_hash'],account,segment['number']))
        db.execute('UPDATE observed_paper_accounts SET payload=?,version=?,event_hash=? WHERE id=?',
            (canonical(state),row['sequence'],row['digest'],account))
        return row

    @staticmethod
    def _receipt(row):
        return {'version':row['sequence'],'eventHash':row['digest'],'afterHash':row['after_hash'],
                'at':row['created'],'facts':json.loads(row['payload'])['facts']}

    def events(self, account, after=-1, limit=50):
        if type(after) is not int or after < -1 or type(limit) is not int or not 1<=limit<=100:
            raise ValueError('Bounded event cursor required')
        with self.repo.transaction() as db:
            self._read(db,account)
            result=[]; size=0
            for raw in db.execute('SELECT * FROM observed_paper_events WHERE account_id=? AND sequence>? ORDER BY sequence LIMIT ?',
                    (account,after,limit)):
                row=dict(raw)
                if size+row['size_bytes']>SEGMENT_BYTES: break
                size+=row['size_bytes']; result.append(self._receipt(row)|{'original':json.loads(row['payload'])})
            return result

    def acquire(self, owner):
        identity(owner); now=self.now()
        with self.repo.transaction() as db:
            row=db.one("SELECT * FROM observed_paper_lease WHERE name='worker'")
            if row and row['owner']!=owner and stamp(row['expires_at'])>now: return None
            generation=1 if row is None else row['generation']+int(row['owner']!=owner or stamp(row['expires_at'])<=now)
            db.execute("INSERT INTO observed_paper_lease VALUES('worker',?,?,?) ON CONFLICT(name) DO UPDATE SET owner=excluded.owner,generation=excluded.generation,expires_at=excluded.expires_at",
                (owner,generation,iso(now+timedelta(seconds=30))))
            return {'owner':owner,'generation':generation}

    def _owns(self, db, lease, now):
        row=db.one("SELECT * FROM observed_paper_lease WHERE name='worker'")
        return bool(isinstance(lease,dict) and row and lease=={'owner':row['owner'],'generation':row['generation']} and stamp(row['expires_at'])>now)

    def release(self, lease, *, mark_stopped=False):
        with self.repo.transaction() as db:
            row=db.one("SELECT * FROM observed_paper_lease WHERE name='worker'")
            # An expired owner may invalidate its old heartbeat, but never a
            # successor's generation (even if the owner label was reused).
            if not (isinstance(lease,dict) and row and lease=={'owner':row['owner'],'generation':row['generation']}):
                return False
            at=iso(self.now())
            db.execute("UPDATE observed_paper_lease SET expires_at=? WHERE name='worker'",(at,))
            if mark_stopped:
                db.execute("INSERT INTO runtime_health VALUES('observed_paper',?,?) ON CONFLICT(name) DO UPDATE SET updated_at=excluded.updated_at,payload=excluded.payload",
                    (at,canonical({'state':'STOPPED','externalOrder':False})))
            return True
