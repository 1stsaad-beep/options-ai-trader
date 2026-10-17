"""Durable at-least-once notification delivery, isolated from financial state.

The immutable inbox is the outbox source. A receiver must deduplicate the stable
idempotency key and acknowledge the exact event hash; HTTP200 alone is not ACK.
No request is made until a lease and retry reservation have committed.
"""
from contextlib import closing
from datetime import timedelta
import json
import uuid

from .observed_paper import canonical, digest
from .observed_option_replay import iso
from .observed_paper_alerts import decode, ZERO, fingerprint
from .observed_paper_store import LedgerConflict
from .paper_settlement import stamp

VERSION = 'observed-alert-delivery-v1'
ACK = 'observed-alert-ack-v1'


class AlertDelivery:
    def __init__(self, transaction, now, transport, target_hash, owner=None):
        self.transaction, self.now, self.transport = transaction, now, transport
        self.target = fingerprint(target_hash)
        self.owner = owner or uuid.uuid4().hex

    def _state(self, db):
        row = db.one('SELECT payload FROM observed_alert_delivery_state WHERE target_hash=?', (self.target,))
        if row is None:
            return {'version':1,'owner':None,'generation':0,'leaseUntil':None,'retryAt':None,'failures':0,'authBlocked':False}
        try:
            state = json.loads(row['payload'])
            if (set(state) != {'version','owner','generation','leaseUntil','retryAt','failures','authBlocked'} or
                    type(state['version']) is not int or state['version'] != 1 or type(state['authBlocked']) is not bool or
                    type(state['failures']) is not int or not 0 <= state['failures'] <= 16 or
                    type(state['generation']) is not int or state['generation'] < 0 or
                    state['owner'] is not None and (not isinstance(state['owner'],str) or len(state['owner']) > 120)):
                raise ValueError()
            for key in ('leaseUntil','retryAt'):
                if state[key] is not None: stamp(state[key])
            return state
        except (ValueError,TypeError,KeyError,AttributeError):
            raise LedgerConflict('Alert delivery state requires review') from None

    def _save(self, db, state):
        db.execute('INSERT INTO observed_alert_delivery_state VALUES(?,?) ON CONFLICT(target_hash) DO UPDATE SET payload=excluded.payload',
                   (self.target,canonical(state)))

    def _acknowledged(self, db):
        sequence=0;event_hash=ZERO
        try:
            with closing(db.stream('SELECT * FROM observed_alert_delivery_receipts WHERE target_hash=? ORDER BY sequence',(self.target,))) as rows:
                for row in rows:
                    sequence+=1
                    if row['sequence']!=sequence: raise ValueError()
                    fingerprint(row['event_hash'])
                    value=json.loads(row['payload'])
                    if (value!={'contract':ACK,'sequence':sequence,'eventHash':row['event_hash'],'acknowledgedAt':value['acknowledgedAt']} or
                            type(value['sequence']) is not int):
                        raise ValueError()
                    if stamp(value['acknowledgedAt'])>self.now(): raise ValueError()
                    original=db.one('SELECT * FROM observed_alert_events WHERE sequence=?',(sequence,))
                    if original is None or decode(original)['eventHash']!=row['event_hash']: raise ValueError()
                    event_hash=row['event_hash']
            return sequence,event_hash
        except (ValueError,TypeError,KeyError,AttributeError):
            raise LedgerConflict('Alert delivery receipt requires review') from None

    def tick(self):
        now=self.now()
        # Validate the full inbox before publishing any unacknowledged event.
        # Verification is streamed; this makes no constant-time history claim.
        with self.transaction() as db:
            state=self._state(db)
            if state['authBlocked']: return {'state':'AUTH_BLOCKED','externalOrder':False}
            if state['leaseUntil'] and stamp(state['leaseUntil']) > now: return {'state':'STANDBY','externalOrder':False}
            if state['retryAt'] and stamp(state['retryAt']) > now: return {'state':'BACKOFF','externalOrder':False}
            acknowledged, previous = self._acknowledged(db)
            sequence=0; chain=ZERO; next_event=None; active=[]
            with closing(db.stream('SELECT * FROM observed_alert_events ORDER BY sequence')) as rows:
                for row in rows:
                    event=decode(row);sequence+=1
                    if (event['sequence']!=sequence or event['previousHash']!=chain or
                            stamp(event['detectedAt'])>now or
                            event['raised']!=sorted(set(event['active'])-set(active)) or
                            event['resolved']!=sorted(set(active)-set(event['active']))):
                        raise LedgerConflict('Alert journal requires review')
                    if sequence==acknowledged and event['eventHash']!=previous:
                        raise LedgerConflict('Alert delivery receipt requires review')
                    if sequence==acknowledged+1: next_event=event
                    chain=event['eventHash'];active=event['active']
            if sequence<acknowledged: raise LedgerConflict('Alert journal requires review')
            if next_event is None: return {'state':'IDLE','externalOrder':False}
            generation=state['generation']+1
            # Conservative crash retry: the reservation remains durable even if
            # the process disappears after sending or before saving the ACK.
            state.update(owner=self.owner,generation=generation,leaseUntil=iso(now+timedelta(seconds=30)),
                         retryAt=iso(now+timedelta(seconds=30)),failures=min(16,state['failures']+1))
            self._save(db,state)
        key=digest([VERSION,self.target,next_event['sequence'],next_event['eventHash']])
        body={'contract':VERSION,'idempotencyKey':key,'event':next_event,'externalOrder':False}
        try:
            response=self.transport.send(body,key)
            status=response.status
            acknowledged_body=response.body
            ack_ok=(type(status) is int and status==200 and isinstance(acknowledged_body,dict) and
                acknowledged_body=={'contract':ACK,'sequence':next_event['sequence'],'eventHash':next_event['eventHash']} and
                type(acknowledged_body['sequence']) is int)
        except Exception:
            status,ack_ok=0,False
        completed=self.now()
        with self.transaction() as db:
            state=self._state(db)
            if (state['owner']!=self.owner or state['generation']!=generation or
                    not now <= completed < stamp(state['leaseUntil'])):
                return {'state':'OWNERSHIP_LOST','externalOrder':False}
            if ack_ok:
                # Recheck the original at commit; a changed source cannot gain ACK.
                original=db.one('SELECT * FROM observed_alert_events WHERE sequence=?',(next_event['sequence'],))
                if original is None or decode(original)!=next_event:
                    raise LedgerConflict('Alert journal requires review')
                receipt={'contract':ACK,'sequence':next_event['sequence'],'eventHash':next_event['eventHash'],'acknowledgedAt':iso(completed)}
                db.execute('INSERT INTO observed_alert_delivery_receipts VALUES(?,?,?,?)',
                    (self.target,next_event['sequence'],next_event['eventHash'],canonical(receipt)))
                state.update(owner=None,leaseUntil=None,retryAt=None,failures=0)
                result='DELIVERED'
            else:
                delay=min(300,5*2**(state['failures']-1))
                if status==429: delay=max(60,delay)
                state.update(owner=None,leaseUntil=None,retryAt=iso(completed+timedelta(seconds=delay)),
                             authBlocked=status in (401,403))
                result='AUTH_BLOCKED' if state['authBlocked'] else 'RETRY_PENDING'
            self._save(db,state)
        return {'state':result,'sequence':next_event['sequence'],'externalOrder':False}

    def reset_auth(self):
        with self.transaction() as db:
            state=self._state(db)
            if state['leaseUntil'] and stamp(state['leaseUntil'])>self.now():
                raise LedgerConflict('Stop active notification delivery before reset')
            state.update(authBlocked=False,retryAt=None,failures=0)
            self._save(db,state)
