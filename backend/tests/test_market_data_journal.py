"""SQLite/API archive integration with an isolated Alpaca transport."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import json
from pathlib import Path
import sqlite3
from unittest.mock import Mock, patch
import pytest
from fastapi.testclient import TestClient
from app import market_data_journal as journal
from app.main import create_app
from app.market_data import DisabledMarketData
from app.repository import Repository
from app.service import TradingService
from test_alpaca_market_api import TOKEN, HEADERS, base
from test_alpaca_market_data import adapter, stock_responses, chain, ok, bar, NOW, CONTRACT


def intent(key='capture-one', **changes):
    return {'kind': 'stock_snapshot', 'symbol': 'AAPL', 'request_key': key, **changes}


@pytest.fixture
def setup(monkeypatch):
    monkeypatch.setattr(journal, 'utc_now', lambda: NOW + timedelta(seconds=2))
    monkeypatch.setattr('socket.create_connection', Mock(side_effect=AssertionError('No external network')))
    repo = Repository()
    service = TradingService(repo)
    first = service.create_account('first')['id']
    second = service.create_account('second')['id']
    provider, transport, clock = adapter(*stock_responses(), chain())
    yield service, first, second, provider, transport, clock
    repo.close()


def test_archive_replays_exact_bytes_without_provider_even_when_stale(setup, monkeypatch):
    s, a, _, p, transport, clock = setup
    saved = journal.capture(s, a, intent(), p)
    with s.repo.transaction() as db:
        original = db.one('SELECT payload FROM market_data_journal')['payload']
    clock.advance(86400)
    monkeypatch.setattr(journal, 'utc_now', clock.now)
    p.stock_snapshot = Mock(side_effect=AssertionError('Replay must not query provider'))
    replay = journal.replay(s, a, saved['id'])
    assert replay == saved
    assert replay['freshness_fields_are_as_recorded'] and replay['replay']
    assert not replay['virtual_fills_enabled'] and not replay['point_in_time_backtest_verified']
    assert replay['observation']['data']['trade']['fresh']  # Historical flag, not current eligibility.
    assert replay['observation']['captured_at'] == NOW.isoformat()
    with s.repo.transaction() as db:
        assert db.one('SELECT payload FROM market_data_journal')['payload'] == original
    assert len(transport.calls) == 2


def test_lost_reply_same_key_returns_first_snapshot_without_new_read_or_audit(setup):
    s, a, _, p, transport, _ = setup
    saved = journal.capture(s, a, intent(), p)
    assert journal.capture(s, a, intent(), DisabledMarketData()) == saved
    with s.repo.transaction() as db:
        assert db.one('SELECT COUNT(*) AS n FROM market_data_journal')['n'] == 1
        assert len(db.all("SELECT * FROM audit WHERE event='MARKET_DATA_OBSERVATION_SAVED'")) == 1
    assert len(transport.calls) == 2


def test_request_key_conflict_is_checked_before_provider(setup):
    s, a, _, p, transport, _ = setup
    journal.capture(s, a, intent(), p)
    with pytest.raises(journal.JournalError, match='REQUEST_KEY_CONFLICT'):
        journal.capture(s, a, intent(kind='option_chain'), DisabledMarketData())
    assert len(transport.calls) == 2


def test_concurrent_retries_have_one_immutable_receipt(setup):
    s, a, _, p, _, _ = setup
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: journal.capture(s, a, intent(), p), range(8)))
    assert len({r['id'] for r in results}) == 1
    with s.repo.transaction() as db:
        assert db.one('SELECT COUNT(*) AS n FROM market_data_journal')['n'] == 1


def test_account_isolation_same_request_key_and_removed_watchlist(setup):
    s, a, b, p, _, _ = setup
    first, second = journal.capture(s, a, intent(), p), journal.capture(s, b, intent(), p)
    assert first['id'] != second['id']
    assert second['observation']['account_id'] == b
    with pytest.raises(journal.JournalError, match='NOT_AVAILABLE'):
        journal.replay(s, b, first['id'])
    with s.repo.transaction() as db:
        db.execute('DELETE FROM watchlist WHERE account_id=?', (a,))
    assert journal.replay(s, a, first['id']) == first
    assert journal.capture(s, a, intent(), DisabledMarketData()) == first
    with pytest.raises(journal.JournalError, match='SYMBOL_NOT_WATCHED'):
        journal.capture(s, a, intent('new'), p)


@pytest.mark.parametrize('kind', ['stock_bars', 'option_bars'])
def test_historical_bars_not_available_before_server_recording(setup, kind):
    s, a, _, p, transport, _ = setup
    key = CONTRACT if kind == 'option_bars' else 'AAPL'
    transport.responses = [ok({'bars': {key: [bar()]}})]
    request = intent(kind=kind, start=NOW-timedelta(hours=2), end=NOW-timedelta(minutes=15), timeframe='1Min')
    if kind == 'option_bars':
        request['contract'] = CONTRACT
    saved = journal.capture(s, a, request, p)
    assert saved['observation']['data']['bars'][0]['timestamp'].startswith('2026-10-12T14:00')
    with pytest.raises(journal.JournalError, match='NOT_AVAILABLE'):
        journal.replay(s, a, saved['id'], as_of=NOW)
    assert not journal.list_records(s, a, as_of=NOW)['items']
    assert journal.replay(s, a, saved['id'], as_of=NOW+timedelta(seconds=2)) == saved


def test_documented_history_sample_preserved_without_historical_availability_claim(setup):
    s, a, _, p, transport, _ = setup
    fixture = json.loads((Path(__file__).parent/'fixtures/alpaca_iex_aapl_20230929.json').read_text())
    transport.responses = [ok({'bars': {'AAPL': fixture['response']['bars']}})]
    request = intent(kind='stock_bars', start='2023-09-29T00:00:00Z', end='2023-09-30T12:00:00Z', timeframe='1Day')
    saved = journal.capture(s, a, request, p)
    assert saved['observation']['data']['bars'][0]['c'] == 171.29
    assert journal.list_records(s, a, as_of='2023-10-01T00:00:00Z')['items'] == []


def test_option_missing_greeks_partial_and_delay_preserved(setup):
    s, a, _, p, transport, _ = setup
    p._max_pages = 1
    transport.responses = [chain(token='more')]
    saved = journal.capture(s, a, intent(kind='option_chain'), p)
    observation = saved['observation']
    assert observation['feed'] == 'indicative' and not observation['complete']
    assert observation['data']['contracts'][0]['greeks'] is None
    assert observation['data']['quote_delay_seconds'] is None
    assert observation['data']['trade_delay_seconds'] == 900
    assert observation['usage'] and observation['usage_url']


def test_empty_data_stays_empty_not_fabricated(setup):
    s, a, _, p, transport, _ = setup
    transport.responses = [ok({'quotes': {}}), ok({'trades': {}})]
    saved = journal.capture(s, a, intent(), p)
    assert saved['observation']['data']['price'] is None
    assert saved['observation']['data']['availability'] == 'NO_DATA'


def test_capture_does_not_modify_demo_ledger_or_risk(setup):
    s, a, _, p, _, _ = setup
    tables = ('accounts', 'orders', 'fills', 'positions', 'watchlist', 'option_marks',
              'market_snapshots', 'decision_snapshots', 'research_observations', 'lifecycle_intents')
    def state():
        with s.repo.transaction() as db:
            return {t: db.all('SELECT * FROM ' + t) for t in tables}
    before = state()
    with patch.object(s, 'submit', side_effect=AssertionError('No submit')), patch.object(s, 'fill', side_effect=AssertionError('No fill')):
        journal.capture(s, a, intent(), p)
    assert state() == before


def test_audit_failure_rolls_back_capture_without_receipt(setup):
    s, a, _, p, _, _ = setup
    with patch.object(s, 'audit', side_effect=RuntimeError('injected storage error')):
        with pytest.raises(RuntimeError):
            journal.capture(s, a, intent(), p)
    assert not journal.list_records(s, a)['items']
    assert journal.capture(s, a, intent(), p)['sequence'] == 1


@pytest.mark.parametrize('operation', ['UPDATE market_data_journal SET payload=payload', 'DELETE FROM market_data_journal'])
def test_database_rejects_update_and_delete(setup, operation):
    s, a, _, p, _, _ = setup
    saved = journal.capture(s, a, intent(), p)
    with pytest.raises(sqlite3.IntegrityError, match='immutable'):
        with s.repo.transaction() as db:
            db.execute(operation)
    assert journal.replay(s, a, saved['id']) == saved


def test_corrupt_payload_detected_after_bypassing_trigger_in_disposable_fixture(setup):
    s, a, _, p, _, _ = setup
    saved = journal.capture(s, a, intent(), p)
    # Disposable test only: simulate damaged storage, never repair user data.
    with s.repo.transaction() as db:
        db.execute('DROP TRIGGER immutable_market_journal_v1_update')
        db.execute("UPDATE market_data_journal SET payload='{}'")
    with pytest.raises(journal.JournalError, match='INTEGRITY_FAILED'):
        journal.replay(s, a, saved['id'])
    with pytest.raises(journal.JournalError, match='INTEGRITY_FAILED'):
        journal.capture(s, a, intent(), p)


@pytest.mark.parametrize('limit', ['MAX_ACCOUNT_RECORDS', 'MAX_ACCOUNT_BYTES', 'MAX_RECORD_BYTES'])
def test_capacity_failure_never_evicts_existing_snapshots(setup, monkeypatch, limit):
    s, a, _, p, _, _ = setup
    saved = journal.capture(s, a, intent(), p)
    monkeypatch.setattr(journal, limit, 1)
    with pytest.raises(journal.JournalError, match='CAPACITY_REACHED|RECORD_TOO_LARGE'):
        journal.capture(s, a, intent('second'), p)
    assert journal.replay(s, a, saved['id']) == saved


def test_clock_rollback_cannot_backdate_an_observation(setup, monkeypatch):
    s, a, _, p, _, _ = setup
    saved = journal.capture(s, a, intent(), p)
    monkeypatch.setattr(journal, 'utc_now', lambda: NOW+timedelta(seconds=1))
    with pytest.raises(journal.JournalError, match='CLOCK_MOVED_BACKWARDS'):
        journal.capture(s, a, intent('second'), p)
    assert not journal.list_records(s, a)['items']
    monkeypatch.setattr(journal, 'utc_now', lambda: NOW+timedelta(seconds=2))
    assert journal.replay(s, a, saved['id']) == saved


@pytest.mark.parametrize('field,value', [('virtual_fills_enabled', True), ('external_orders_enabled', True),
    ('point_in_time_backtest_verified', True), ('feed', 'opra'), ('served_at', (NOW+timedelta(hours=1)).isoformat())])
def test_provider_contract_cannot_grant_authority_or_backdate(setup, field, value):
    s, a, _, p, _, _ = setup
    observation = p.stock_snapshot('AAPL')
    observation[field] = value
    p.stock_snapshot = lambda _: observation
    with pytest.raises(journal.JournalError, match='PROVIDER_CONTRACT_INVALID'):
        journal.capture(s, a, intent(), p)
    assert not journal.list_records(s, a)['items']


def test_pagination_is_account_scoped_stable_across_same_time_inserts(setup):
    s, a, b, p, _, _ = setup
    saved = [journal.capture(s, a, intent(str(n)), p) for n in range(3)]
    journal.capture(s, b, intent('other'), p)
    first = journal.list_records(s, a, limit=2)
    journal.capture(s, a, intent('later'), p)
    second = journal.list_records(s, a, limit=2, before_sequence=first['next_before_sequence'])
    assert [r['id'] for r in first['items'] + second['items']] == [r['id'] for r in reversed(saved)]
    assert second['next_before_sequence'] is None


def test_restart_and_sqlite_backup_restore_keep_original_receipt(setup, tmp_path):
    from test_operations_v1 import module
    snapshots = module('backup_restore')
    _, _, _, p, _, _ = setup
    path = tmp_path/'source.db'
    repo = Repository('sqlite:///'+str(path))
    service = TradingService(repo)
    a = service.create_account('durable')['id']
    saved = journal.capture(service, a, intent(), p)
    snapshots.backup(path, tmp_path/'snapshot.db')
    repo.close()
    snapshots.restore(tmp_path/'snapshot.db', tmp_path/'restored.db')
    for name in ('source.db', 'restored.db'):
        repo = Repository('sqlite:///'+str(tmp_path/name))
        try:
            assert journal.replay(TradingService(repo), a, saved['id']) == saved
        finally:
            repo.close()


def test_migration_from_v5_preserves_existing_records_and_is_additive(setup, monkeypatch, tmp_path):
    import app.migrations as migrations
    old = migrations.MIGRATIONS
    monkeypatch.setattr(migrations, 'MIGRATIONS', old[:5])
    url = 'sqlite:///'+str(tmp_path/'upgrade.db')
    repo = Repository(url)
    s = TradingService(repo)
    a = s.create_account('keep-risk')['id']
    s.watch(a, 'MSFT', False)
    with repo.transaction() as db:
        before = db.all('SELECT * FROM watchlist')
        config = db.one('SELECT config FROM accounts WHERE id=?', (a,))
    repo.close()
    monkeypatch.setattr(migrations, 'MIGRATIONS', old)
    repo = Repository(url)
    try:
        with repo.transaction() as db:
            assert db.all('SELECT * FROM watchlist') == before
            assert db.one('SELECT config FROM accounts WHERE id=?', (a,)) == config
            assert db.all('SELECT * FROM market_data_journal') == []
    finally:
        repo.close()


def test_api_auth_account_scope_replay_and_disabled_capture(setup):
    s, a, b, p, transport, _ = setup
    with TestClient(create_app(s.repo, TOKEN, p)) as client:
        for method, path, args in [('post', '/observations', {'json': intent()}), ('get', '/observations', {}), ('get', '/observations/x', {})]:
            assert getattr(client, method)(base(a)+path, **args).status_code == 401
        assert not transport.calls
        response = client.post(base(a)+'/observations', json=intent(), headers=HEADERS)
        assert response.status_code == 200
        saved = response.json()
        client.app.state.market_data = DisabledMarketData()
        assert client.get(base(a)+'/observations/'+saved['id'], headers=HEADERS).json() == saved
        assert client.get(base(b)+'/observations/'+saved['id'], headers=HEADERS).status_code == 404
        assert client.get(base('missing')+'/observations', headers=HEADERS).status_code == 409
        assert client.post(base(a)+'/observations', json=intent(), headers=HEADERS).json() == saved
        assert client.post(base(a)+'/observations', json=intent('new'), headers=HEADERS).status_code == 503
        assert len(transport.calls) == 2


@pytest.mark.parametrize('changes', [{'price': 1}, {'payload': {}}, {'account_id': 'other'}, {'feed': 'opra'},
    {'key': 'not-an-alpaca-field'}, {'kind': 'live_order'}, {'request_key': ''}, {'start': '2023-01-01T00:00:00Z'},
    {'kind': 'option_bars', 'contract': 'TSLA261016C00200000', 'start': '2026-10-10T00:00:00Z', 'end': NOW.isoformat()},
    {'kind': 'stock_bars', 'start': '2026-10-10T00:00:00', 'end': NOW.isoformat()}])
def test_api_rejects_client_prices_credentials_overrides_and_invalid_queries(setup, changes):
    s, a, _, p, transport, _ = setup
    with TestClient(create_app(s.repo, TOKEN, p)) as client:
        response = client.post(base(a)+'/observations', json={**intent(), **changes}, headers=HEADERS)
        assert response.status_code == 422
        assert not transport.calls


@pytest.mark.parametrize('query', [{'as_of': (NOW+timedelta(days=1)).isoformat()}, {'as_of': '2026-10-12T15:00:00'},
    {'limit': 0}, {'limit': 51}, {'before_sequence': 0}])
def test_api_rejects_future_naive_or_unbounded_replay_queries(setup, query):
    s, a, _, p, transport, _ = setup
    with TestClient(create_app(s.repo, TOKEN, p)) as client:
        assert client.get(base(a)+'/observations', headers=HEADERS, params=query).status_code == 422
        assert not transport.calls

