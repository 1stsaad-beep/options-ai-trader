"""Explicitly disposable local PostgreSQL acceptance, no financial transport."""
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
from app import market_data_journal as journal
from app.market_data import timestamp
from app.repository import Repository
from app.service import TradingService


def fixture():
    """Shared, explicitly mocked contract; no actual account data."""
    path = Path(__file__).resolve().parents[1] / 'mobile/test/fixtures/market_data_v1.json'
    data = json.loads(path.read_text())
    assert data['fixture_source'] == 'mock_transport_for_contract_tests_not_live_prices'
    observation = data['snapshot']
    now = timestamp(observation['served_at']) + timedelta(seconds=2)
    return SimpleNamespace(stock_snapshot=lambda _: deepcopy(observation)), now


def check(repositories):
    services = [TradingService(repo) for repo in repositories]
    a = services[0].create_account('journal-disposable-A')['id']
    b = services[0].create_account('journal-disposable-B')['id']
    provider, now = fixture()
    request = {'kind': 'stock_snapshot', 'symbol': 'AAPL', 'request_key': 'concurrent'}
    checks = []
    with patch.object(journal, 'utc_now', lambda: now):
        gate = threading.Barrier(2)
        def attempt(index):
            gate.wait(timeout=10)
            return journal.capture(services[index], a, request, provider)
        with ThreadPoolExecutor(max_workers=2) as pool:
            receipts = list(pool.map(attempt, range(2)))
        assert receipts[0] == receipts[1]
        saved = receipts[0]
        with repositories[0].transaction() as db:
            assert db.one('SELECT COUNT(*) AS n FROM market_data_journal WHERE account_id=?', (a,))['n'] == 1
            assert db.one("SELECT COUNT(*) AS n FROM audit WHERE account_id=? AND event='MARKET_DATA_OBSERVATION_SAVED'", (a,))['n'] == 1
        checks.append('two_connection_duplicate_capture_has_one_receipt_and_audit')
        for operation in ('UPDATE market_data_journal SET payload=payload WHERE id=?',
                          'DELETE FROM market_data_journal WHERE id=?'):
            try:
                with repositories[1].transaction() as db:
                    db.execute(operation, (saved['id'],))
            except Exception as exc:
                assert 'immutable' in str(exc)
            else:
                raise AssertionError('Journal mutation unexpectedly accepted')
        assert journal.replay(services[1], a, saved['id']) == saved
        checks.append('native_update_delete_guards_and_cross_connection_exact_replay')
        try:
            journal.replay(services[1], b, saved['id'])
        except journal.JournalError as exc:
            assert exc.code == 'JOURNAL_OBSERVATION_NOT_AVAILABLE'
        else:
            raise AssertionError('Cross-account replay unexpectedly accepted')
        assert journal.list_records(services[1], b)['items'] == []
        checks.append('account_isolation')
        try:
            with repositories[1].transaction() as db:
                db.execute('INSERT INTO market_data_journal SELECT ?,?,sequence,request_key,fingerprint,kind,symbol,recorded_at,payload,digest,size_bytes FROM market_data_journal WHERE id=?',
                    ('orphan-'+saved['id'], 'missing-'+a, saved['id']))
        except Exception as exc:
            assert 'foreign key' in str(exc).lower()
        else:
            raise AssertionError('Orphan observation unexpectedly accepted')
        checks.append('native_account_foreign_key')
        assert journal.list_records(services[1], a, as_of=now-timedelta(seconds=1))['items'] == []
        try:
            journal.replay(services[1], a, saved['id'], as_of=now-timedelta(seconds=1))
        except journal.JournalError as exc:
            assert exc.code == 'JOURNAL_OBSERVATION_NOT_AVAILABLE'
        else:
            raise AssertionError('Future observation leaked into prior decision time')
        checks.append('as_of_cannot_backdate_provider_history')
        with patch.object(services[1], 'audit', side_effect=RuntimeError('injected audit failure')):
            try:
                journal.capture(services[1], a, {**request, 'request_key': 'rollback'}, provider)
            except RuntimeError as exc:
                assert str(exc) == 'injected audit failure'
            else:
                raise AssertionError('Capture unexpectedly committed despite audit failure')
        assert len(journal.list_records(services[0], a)['items']) == 1
        checks.append('capture_and_audit_atomic_rollback')
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
            repositories.append(Repository(url))
        checks = check(repositories)
        print(json.dumps({'status': 'passed', 'database': 'PostgreSQL', 'checks_passed': len(checks),
                          'checks_failed': 0, 'checks': checks, 'provider': 'mock_contract_fixture',
                          'external_market_connection': False}, indent=2))
    finally:
        for repo in repositories:
            repo.close()


if __name__ == '__main__':
    run()
