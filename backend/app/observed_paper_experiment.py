"""Atomic USD1,000 experiment and snapshot-consistent receipt comparison."""
import re

from .observed_option_replay import iso
from .observed_paper import apply, canonical, create
from .observed_paper_performance import summarize
from .observed_paper_store import LedgerConflict, ZERO

VERSION = 'observed-paper-experiment-v1'
STRATEGIES = ('trend', 'breakout', 'pullback', 'divergence')
INITIAL_CASH = 100000


def bootstrap(store, source):
    if source not in ('alpaca', 'fixture'):
        raise ValueError('Explicit observed source required')
    ids = [f'experiment_{source}_{strategy}' for strategy in STRATEGIES]
    at = iso(store.now())
    with store.repo.transaction() as db:
        existing = [db.one('SELECT id FROM observed_paper_accounts WHERE id=?', (account,)) for account in ids]
        if any(existing) and not all(existing):
            raise LedgerConflict('Partial or colliding experiment requires review')
        if not any(existing):
            count = db.one('SELECT COUNT(*) AS n FROM observed_paper_accounts')['n']
            if count + len(ids) > 100:
                raise LedgerConflict('Observed-paper account limit reached')
            for account, strategy in zip(ids, STRATEGIES):
                state = create(account, 'Experiment / ' + strategy, INITIAL_CASH, source)
                db.execute('INSERT INTO observed_paper_accounts VALUES(?,?,?,?)', (account, canonical(state), -1, ZERO))
                genesis = store._append(db, account, -1, ZERO, VERSION + ':' + strategy,
                    {'kind': 'CREATE', 'state': state}, state, {'kind': 'CREATE', 'externalOrder': False}, at)
                command = {'kind': 'CONFIGURE', 'config': state['config'] | {'strategy': strategy}}
                state, facts = apply(state, command, at)
                store._append(db, account, 0, genesis['digest'], 'experiment-config', command, state, facts, at)
        result = []
        for account, strategy in zip(ids, STRATEGIES):
            genesis = db.one('SELECT request_key FROM observed_paper_events WHERE account_id=? AND sequence=0', (account,))
            if not genesis or genesis['request_key'] != VERSION + ':' + strategy:
                raise LedgerConflict('Account identity belongs to another operation')
            # A retry after configuration, fills, restart or settlement returns
            # current verified state; it cannot restore the starting balance.
            row, state = store._read(db, account, full=True)
            if state['source'] != source or state['initialCash'] != INITIAL_CASH:
                raise LedgerConflict('Experiment identity mismatch')
            result.append({'version': row['version'], 'eventHash': row['event_hash'], 'state': state})
        return {'contract': VERSION, 'source': source, 'externalOrder': False,
                'created': not any(existing), 'accounts': result}


def compare(store, accounts):
    if (not isinstance(accounts, list) or not 1 <= len(accounts) <= 4
            or any(not isinstance(a, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', a) for a in accounts)
            or len(set(accounts)) != len(accounts)):
        raise ValueError('One to four distinct account identifiers required')
    reports = []
    with store.repo.transaction() as db:
        for account in accounts:
            row, state = store._read(db, account)
            report = summarize(db.stream('SELECT payload FROM observed_paper_events WHERE account_id=? ORDER BY sequence', (account,)), state)
            reports.append({'name': state['name'], 'strategy': state['config']['strategy'],
                'enabled': state['enabled'], 'initialCashCents': state['initialCash'],
                'risk': {key: state['config'][key] for key in ('riskPercent', 'allocationPercent', 'dailyLossPercent', 'maxPositions', 'maxContracts')},
                'performance': report | {'version': row['version'], 'eventHash': row['event_hash']}})
        sources = {r['performance']['source'] for r in reports}
        if len(sources) != 1:
            raise ValueError('Fixture and market evidence cannot be combined')
    return {'contract': 'observed-paper-comparison-v1', 'source': sources.pop(),
            'externalOrder': False, 'accounts': reports, 'valuationStatus': 'UNMARKED',
            'threeSessionAcceptance': 'NOT_RUN'}
