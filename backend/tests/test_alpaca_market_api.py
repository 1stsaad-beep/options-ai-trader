"""Offline FastAPI+SQLite integration: scope, persistence and execution isolation."""
from datetime import timedelta
import json
from unittest.mock import patch
import pytest
from fastapi.testclient import TestClient
from app.main import create_app
from app.repository import Repository
from app.market_data import AlpacaBasicData, DisabledMarketData
from test_alpaca_market_data import Clock, Responses, NOW, CONTRACT, stock_responses, chain, ok, bar

TOKEN = 'test-token-at-least-32-characters-long'
HEADERS = {'Authorization': 'Bearer ' + TOKEN}


@pytest.fixture
def api():
    repo, clock = Repository(), Clock()
    transport = Responses(*stock_responses(), chain())
    provider = AlpacaBasicData(transport, now=clock.now, monotonic=clock.mono, sleep=clock.advance)
    with patch('socket.create_connection', side_effect=AssertionError('Unexpected external connection')):
        with TestClient(create_app(repo, TOKEN, provider)) as client:
            first = client.post('/api/accounts', headers=HEADERS, json={'name': 'First'}).json()['id']
            second = client.post('/api/accounts', headers=HEADERS, json={'name': 'Second'}).json()['id']
            yield client, repo, transport, first, second
    repo.close()


def base(account):
    return f'/api/accounts/{account}/market-data'


def test_data_routes_require_existing_auth_before_provider(api):
    client, _, transport, first, _ = api
    for path in ['/status', '/stocks/AAPL/snapshot', '/options/AAPL/chain']:
        assert client.get(base(first)+path).status_code == 401
    assert client.post(base(first)+'/virtual-orders', json={}).status_code == 401
    assert not transport.calls


def test_unknown_account_and_other_account_symbol_rejected_before_provider(api):
    client, _, transport, first, second = api
    assert client.get(base('missing')+'/status', headers=HEADERS).status_code == 409
    client.post(f'/api/accounts/{first}/watchlist', headers=HEADERS, json={'symbol': 'MSFT'})
    assert client.get(base(second)+'/stocks/MSFT/snapshot', headers=HEADERS).status_code == 409
    assert not transport.calls
    assert 'MSFT' in client.get(base(first)+'/status', headers=HEADERS).json()['symbols']
    assert 'MSFT' not in client.get(base(second)+'/status', headers=HEADERS).json()['symbols']


def test_user_added_non_fixture_symbols_do_not_require_synthetic_enable(api):
    client, _, transport, first, _ = api
    response = client.post(f'/api/accounts/{first}/watchlist', headers=HEADERS, json={'symbol': 'MSFT'})
    assert response.status_code == 200 and not response.json()['enabled']
    transport.responses = [ok({'quotes': {}}), ok({'trades': {}})]
    response = client.get(base(first)+'/stocks/MSFT/snapshot', headers=HEADERS)
    assert response.status_code == 200 and response.json()['data']['symbol'] == 'MSFT'
    assert transport.calls[0][1]['symbols'] == 'MSFT'


def test_shared_provider_cache_keeps_account_identity_separate(api):
    client, _, transport, first, second = api
    a = client.get(base(first)+'/stocks/AAPL/snapshot', headers=HEADERS).json()
    b = client.get(base(second)+'/stocks/AAPL/snapshot', headers=HEADERS).json()
    assert a['account_id'] == first and b['account_id'] == second
    assert a['mode'] == b['mode'] == 'real_market_virtual'
    assert b['cached'] and len(transport.calls) == 2
    assert b['data']['price'] == 200


def test_real_data_read_does_not_change_demo_ledger_risk_or_entitlement(api):
    client, repo, _, first, _ = api
    def state():
        with repo.transaction() as db:
            return {table: db.all('SELECT * FROM '+table) for table in (
                'accounts', 'watchlist', 'positions', 'orders', 'fills', 'option_marks', 'market_snapshots', 'decision_snapshots')}
    before = state()
    assert client.get(base(first)+'/stocks/AAPL/snapshot', headers=HEADERS).status_code == 200
    assert client.get(base(first)+'/options/AAPL/chain', headers=HEADERS).status_code == 200
    assert state() == before


def test_basic_virtual_attempts_never_reach_synthetic_submit_fill_or_orders(api):
    client, repo, transport, first, _ = api
    request = {'symbol': 'AAPL', 'contract': CONTRACT, 'request_key': 'same-attempt'}
    service = client.app.state.service
    with (patch.object(service, 'submit', side_effect=AssertionError('Cross-mode submit')),
          patch.object(service, 'fill', side_effect=AssertionError('Cross-mode fill'))):
        for _ in range(2):
            response = client.post(base(first)+'/virtual-orders', headers=HEADERS, json=request)
            assert response.status_code == 409
            assert response.json()['detail'] == 'INDICATIVE_OPTIONS_NOT_EXECUTABLE'
            assert response.json()['accepted'] is False
    assert not transport.calls
    with repo.transaction() as db:
        assert not db.all('SELECT * FROM orders') and not db.all('SELECT * FROM fills')
        audits = db.all("SELECT detail FROM audit WHERE event='REAL_MARKET_VIRTUAL_ORDER_BLOCKED'")
        assert len(audits) == 2 and json.loads(audits[0]['detail'])['mode'] == 'real_market_virtual'


@pytest.mark.parametrize('extra', [{'price_cents': 100}, {'broker': 'alpaca'}, {'live': True}, {'mode': 'paper'}, {'feed': 'opra'}])
def test_caller_cannot_supply_prices_or_broker_overrides(api, extra):
    client, _, transport, first, _ = api
    response = client.post(base(first)+'/virtual-orders', headers=HEADERS,
        json={'symbol': 'AAPL', 'contract': CONTRACT, 'request_key': 'x', **extra})
    assert response.status_code == 422 and not transport.calls


def test_option_history_and_contract_scope(api):
    client, _, transport, first, _ = api
    transport.responses = [ok({'bars': {CONTRACT: [bar()]}})]
    params = {'contract': CONTRACT, 'start': (NOW-timedelta(hours=2)).isoformat(),
              'end': (NOW-timedelta(minutes=15)).isoformat(), 'timeframe': '1Min'}
    response = client.get(base(first)+'/options/AAPL/bars', headers=HEADERS, params=params)
    assert response.status_code == 200 and len(response.json()['data']['bars']) == 1
    assert response.json()['account_id'] == first
    params['contract'] = 'TSLA261016C00200000'
    assert client.get(base(first)+'/options/AAPL/bars', headers=HEADERS, params=params).status_code == 422
    assert len(transport.calls) == 1


def test_disabled_data_has_clear_no_fallback_state(api):
    client, _, transport, first, _ = api
    client.app.state.market_data = DisabledMarketData()
    status = client.get(base(first)+'/status', headers=HEADERS).json()
    assert status['virtual_execution_state'] == 'ANALYSIS_ONLY'
    assert status['connection_enabled'] is False
    response = client.get(base(first)+'/stocks/AAPL/snapshot', headers=HEADERS)
    assert response.status_code == 503 and response.json()['synthetic_fallback'] is False
    assert not transport.calls


def test_restart_preserves_watchlist_and_demo_without_enabling_connection(tmp_path, monkeypatch):
    monkeypatch.delenv('OAT_ALPACA_DATA_APPROVAL', raising=False)
    url = 'sqlite:///' + str(tmp_path/'restart.sqlite')
    repo = Repository(url)
    with TestClient(create_app(repo, TOKEN)) as client:
        account = client.post('/api/accounts', headers=HEADERS, json={'name': 'Saved'}).json()['id']
        client.post(f'/api/accounts/{account}/watchlist', headers=HEADERS, json={'symbol': 'MSFT'})
        risk = client.get(f'/api/accounts/{account}/risk', headers=HEADERS).json()
    repo.close()
    repo = Repository(url)
    with TestClient(create_app(repo, TOKEN)) as client:
        result = client.get(base(account)+'/status', headers=HEADERS).json()
        assert 'MSFT' in result['symbols'] and not result['connection_enabled']
        assert client.get(f'/api/accounts/{account}/risk', headers=HEADERS).json() == risk
    repo.close()
