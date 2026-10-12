"""Disposable two-connection PostgreSQL runtime acceptance, no market network."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import timedelta
import json
import os
from pathlib import Path
import sys
import threading
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from app import market_data_journal as journal, market_runtime as rt
from app.market_data import DataResponse, MarketDataError
from app.repository import Repository
from app.service import TradingService
from market_data_journal_check import fixture as journal_fixture


def check(repositories):
    services = [TradingService(r) for r in repositories]
    sample, initial = journal_fixture()
    clock = [initial]
    for service in services:
        service.now = lambda: clock[0]
    calls = []
    def snapshot(ticker):
        calls.append(ticker)
        return sample.stock_snapshot(ticker)
    provider = SimpleNamespace(status=lambda: {'connection_enabled': True, 'connection_state': 'MOCK'},
                               stock_snapshot=snapshot)
    accounts = []
    for name in ('runtime-disposable-A', 'runtime-disposable-B'):
        account = services[0].create_account(name)['id']
        accounts.append(account)
        with repositories[0].transaction() as db:
            db.execute("DELETE FROM watchlist WHERE account_id=? AND symbol<>'AAPL'", (account,))
        rt.configure(services[0], account, expected_version=0, enabled=True,
                     strategies={'breakout': name.endswith('A'), 'pullback': False})
    services[0].reconcile(accounts[0])
    with repositories[0].transaction() as db:
        original = db.one('SELECT * FROM accounts WHERE id=?', (accounts[0],))
        for kind in rt.INTERVALS:
            due = clock[0] if kind == 'stock_snapshot' else clock[0]+timedelta(hours=1)
            db.execute('INSERT INTO market_runtime_tasks VALUES(?,?,?) ON CONFLICT(symbol,kind) DO UPDATE SET next_due=excluded.next_due',
                       ('AAPL', kind, journal.utc(due)))
        # Only fixture runtime rows exist in this disposable CI database. No
        # user/server database is accepted by run().
        state = rt.coordinator_in(db)
        state.update(owner=None, lease_until=None)
        rt.save_coordinator(db, state)
    collectors = [rt.MarketCollector(s, provider, owner='pg-worker-' + str(i)) for i, s in enumerate(services)]
    checks = []
    with patch.object(journal, 'utc_now', lambda: clock[0]):
        barrier = threading.Barrier(2)
        def attempt(index):
            barrier.wait(timeout=10)
            return collectors[index].tick()['state']
        with ThreadPoolExecutor(max_workers=2) as pool:
            states = list(pool.map(attempt, range(2)))
        assert sorted(states) == ['COLLECTING_ANALYSIS_ONLY', 'STANDBY']
        assert calls == ['AAPL']
        assert all(len(journal.list_records(services[0], a)['items']) == 1 for a in accounts)
        checks.append('postgres_two_worker_lease_and_shared_symbol_single_fetch')
        with repositories[1].transaction() as db:
            assert db.one('SELECT * FROM accounts WHERE id=?', (accounts[0],)) == original
            assert not db.all('SELECT * FROM orders WHERE account_id=?', (accounts[0],))
        checks.append('demo_account_trust_and_ledger_unchanged')
        one = rt.events(services[0], accounts[0])['items'][0]
        for statement in ('UPDATE market_runtime_events SET payload=payload WHERE id=?',
                          'DELETE FROM market_runtime_events WHERE id=?'):
            try:
                with repositories[1].transaction() as db:
                    db.execute(statement, (one['id'],))
            except Exception as error:
                assert 'immutable' in str(error)
            else:
                raise AssertionError('Immutable event mutation accepted')
        checks.append('native_postgres_event_update_delete_guards')
        try:
            rt.acknowledge(services[1], accounts[1], one['id'])
        except journal.JournalError as error:
            assert error.code == 'RUNTIME_EVENT_NOT_FOUND'
        else:
            raise AssertionError('Cross-account notification acknowledged')
        rt.acknowledge(services[1], accounts[0], one['id'])
        rt.acknowledge(services[1], accounts[0], one['id'])
        with repositories[0].transaction() as db:
            assert db.one('SELECT COUNT(*) AS n FROM market_runtime_ack WHERE event_id=?', (one['id'],))['n'] == 1
        checks.append('account_scoped_idempotent_notification_ack')
        foreign = journal.list_records(services[0], accounts[0])['items'][0]['id']
        try:
            with repositories[1].transaction() as db:
                db.execute('UPDATE market_runtime_latest SET observation_id=? WHERE account_id=?', (foreign, accounts[1]))
        except Exception as error:
            assert 'foreign key' in str(error).lower()
        else:
            raise AssertionError('Cross-account original-observation link accepted')
        checks.append('native_account_observation_composite_foreign_key')
        winner = collectors[states.index('COLLECTING_ANALYSIS_ONLY')]
        loser = collectors[states.index('STANDBY')]
        clock[0] += timedelta(seconds=121)
        assert loser.tick()['state'] == 'COLLECTING_ANALYSIS_ONLY'
        assert winner.tick()['state'] == 'STANDBY'
        checks.append('expired_lease_takeover_without_duplicate_orders')
        # Same DB budget observed by a second connection, including Retry-After.
        network_calls = []
        def throttled(path, params):
            network_calls.append(path)
            return DataResponse(429, {'Retry-After': '180'}, {})
        wrapped = rt.CoordinatedTransport(repositories[0], loser.owner,
                                         SimpleNamespace(get=throttled), lambda: clock[0], 2)
        wrapped.get('/v2/stocks/trades/latest', {'symbols': 'AAPL', 'feed': 'iex'})
        after_restart = rt.CoordinatedTransport(repositories[1], loser.owner,
                                               SimpleNamespace(get=throttled), lambda: clock[0], 2)
        try:
            after_restart.get('/v2/stocks/trades/latest', {'symbols': 'AAPL', 'feed': 'iex'})
        except MarketDataError as error:
            assert error.code == 'COLLECTOR_BACKOFF'
        else:
            raise AssertionError('Restart lost Retry-After')
        assert len(network_calls) == 1
        checks.append('postgres_shared_budget_and_retry_after_survive_connection_change')
        loser.release()
        fresh_process = rt.MarketCollector(services[0], provider, owner='pg-restarted')
        assert fresh_process.tick()['state'] == 'BACKOFF'
        assert not rt.status(services[0], accounts[0])['stop_loss_execution_assumed']
        clock[0] += timedelta(seconds=181)
        assert fresh_process.tick()['state'] == 'COLLECTING_ANALYSIS_ONLY'
        assert all(not services[0].rows(a, 'orders') for a in accounts)
        checks.append('restart_backoff_recovery_and_no_fabricated_stop_fills')
        fresh_process.release()
    return checks


def run():
    url = os.environ.get('TEST_DATABASE_URL', '')
    if os.environ.get('TEST_DATABASE_ALLOW_DISPOSABLE') != '1':
        raise SystemExit('Explicit disposable database acknowledgement required')
    if not url.startswith(('postgresql://', 'postgres://')) or urlparse(url).hostname not in {'localhost', '127.0.0.1', '::1', 'postgres'}:
        raise SystemExit('Only a local/container disposable PostgreSQL database is permitted')
    repositories = []
    try:
        for _ in range(2):
            repositories.append(Repository(url, invalidate_accounts=False))
        checks = check(repositories)
        print(json.dumps({'status': 'passed', 'database': 'PostgreSQL', 'checks_passed': len(checks),
                          'checks_failed': 0, 'checks': checks, 'external_market_connection': False,
                          'provider': 'explicit_mock_contract'}, indent=2))
    finally:
        for repo in repositories:
            repo.close()


if __name__ == '__main__':
    run()
