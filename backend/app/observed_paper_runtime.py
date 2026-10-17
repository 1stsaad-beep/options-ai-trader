"""One fenced worker; network capture never holds the ledger transaction lock."""
import uuid

from .market_data import MarketDataError
from .market_sessions import evaluate_session, US_EQUITY_OPTIONS_POLICY
from .observed_paper import canonical
from .observed_option_replay import iso
from .observed_paper_store import LedgerConflict
from .observed_paper_status import safe_diagnostic


class ObservedPaperRuntime:
    def __init__(self,store,provider=None,owner=None):
        self.store=store; self.provider=provider; self.owner=owner or str(uuid.uuid4()); self.lease=None

    def tick(self):
        self.lease=self.store.acquire(self.owner)
        if self.lease is None: return {'state':'STANDBY','externalOrder':False}
        result=self._tick_owned()
        with self.store.repo.transaction() as db:
            if self.store._owns(db,self.lease,self.store.now()):
                db.execute("INSERT INTO runtime_health VALUES('observed_paper',?,?) ON CONFLICT(name) DO UPDATE SET updated_at=excluded.updated_at,payload=excluded.payload",
                    (iso(self.store.now()),canonical(result)))
        return result

    def _tick_owned(self):
        result={'state':'DISABLED','externalOrder':False,'processed':0,'blocked':0}
        if self.provider is None: return result
        snapshots=[]
        for account in self.store.accounts():
            try:
                snapshot=self.store.snapshot(account)
                state=snapshot['state']
                if state['source']!=self.provider.source: continue
                if state['enabled'] or any(p.get('closeIntent') for p in state['positions'].values()):
                    snapshots.append(snapshot)
            except LedgerConflict:
                result['blocked']+=1
        if not snapshots: return result|{'state':'LEDGER_BLOCKED' if result['blocked'] else 'NO_ACTIVE_DEMAND'}
        if not evaluate_session(self.store.now(),US_EQUITY_OPTIONS_POLICY).fill_allowed:
            # No provider requests off-session. A new session rebuilds a fresh
            # signal and prior-session positions receive protective exits.
            return result|{'state':'SESSION_CLOSED'}
        try:
            observation=self.provider.capture([s['state'] for s in snapshots],self.lease)
        except MarketDataError as exc:
            return result|{'state':'DATA_UNAVAILABLE','diagnosticCode':safe_diagnostic(exc.code)}
        for snapshot in snapshots:
            state=snapshot['state']; account=state['id']
            # Bound each account's original evidence to its own current demand.
            symbols=set(state['config']['contracts'])|set(state['positions'])
            contracts={p['contract'] for p in state['positions'].values()}|{c for choices in state['config']['contracts'].values() for c in choices.values()}
            scoped=observation|{'bars':{s:b for s,b in observation['bars'].items() if s in symbols},
                'quotes':[q for q in observation['quotes'] if q.get('contract') in contracts]}
            try:
                self.store.command(account,'cycle:'+str(uuid.uuid4()),{'kind':'CYCLE','observation':scoped},
                    expected_version=snapshot['version'],lease=self.lease)
                result['processed']+=1
            except (LedgerConflict,ValueError):
                result['blocked']+=1
        return result|{'state':'RUNNING_VIRTUAL' if not result['blocked'] else 'PARTIALLY_BLOCKED'}

    def close(self):
        if self.lease:
            self.store.release(self.lease,mark_stopped=True)
            self.lease=None
