"""V0.4 authenticated, account-scoped automation boundary regression tests."""
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.adapters import GenericAnalysisAdapter
from app.main import create_app
from app.repository import Repository


@pytest.fixture
def api():
    repo = Repository()
    app = create_app(repo, token='test-automation-token-never-production')
    with TestClient(app) as client:
        app.state.service.now = lambda: datetime(2026, 10, 12, 14, 30, tzinfo=timezone.utc)
        app.state.service.today = lambda: app.state.service.now().date()
        client.headers['Authorization'] = 'Bearer test-automation-token-never-production'
        yield client, app.state.service
    repo.close()


def test_generic_analysis_always_disabled_without_network():
    adapter = GenericAnalysisAdapter()
    assert adapter.enabled is False
    assert adapter.capabilities() == {'enabled': False, 'read_only': True,
        'execution_authority': False, 'source': 'external_disabled'}
    with pytest.raises(AttributeError):
        adapter.enabled = True
    with patch('socket.create_connection', side_effect=AssertionError('Network attempted')):
        with pytest.raises(PermissionError):
            adapter.analyze('NVDA', enabled=True, endpoint='https://invalid.example')


def test_automation_run_requires_auth_and_rejects_execution_injection(api):
    client, service = api
    account = service.create_account('A')['id']
    path = f'/api/accounts/{account}/automation/run'
    assert client.post(path, json={}, headers={'Authorization': ''}).status_code == 401
    for extra in ({'force': True}, {'account_id': 'other'}, {'price_cents': 1},
                  {'signal': 'BUY'}, {'ai_approved': True}, {'live': True}):
        assert client.post(path, json=extra).status_code == 422
    assert service.rows(account, 'orders') == []


def test_account_opt_in_and_cycle_identity(api):
    client, service = api
    a, b = [service.create_account(name)['id'] for name in ('A', 'B')]
    for account in (a, b):
        service.watch(account, 'NVDA', True)
    path = f'/api/accounts/{a}/automation/run'
    default = client.post(path, json={})
    assert default.status_code == 200
    assert service.rows(a, 'orders') == []
    response = client.put(f'/api/accounts/{a}/risk', json={'automation_enabled': True})
    assert response.status_code == 200
    result = client.post(path, json={})
    assert result.status_code == 200, result.text
    assert result.json()['account_id'] == a
    assert result.json()['source'] == 'synthetic_mock'
    orders = service.rows(a, 'orders')
    assert len(orders) == 1 and orders[0]['side'] == 'BUY'
    positions = service.rows(a, 'positions')
    assert positions
    assert client.post(path, json={}).status_code == 200
    assert service.rows(a, 'orders') == orders
    assert service.rows(a, 'positions') == positions
    assert service.rows(b, 'orders') == []


def test_automation_config_strict_and_live_stays_locked(api):
    client, service = api
    account = service.create_account('A')['id']
    path = f'/api/accounts/{account}/risk'
    for payload in ({'automation_enabled': 'true'}, {'auto_quantity': True},
                    {'auto_fill_chunk': 0}, {'stop_loss_pct': 0},
                    {'take_profit_pct': 501}, {'max_spread_pct': 51},
                    {'mode': 'live'}, {'broker': 'ibkr'}, {'external_analysis_enabled': True}):
        assert client.put(path, json=payload).status_code == 409, payload
    health = client.get('/health').json()
    assert health['version'] == '0.5.0'
    assert not health['live_enabled'] and not health['external_analysis_enabled']


def test_unknown_automation_account_rejected(api):
    client, _ = api
    assert client.post('/api/accounts/not-an-account/automation/run', json={}).status_code == 409
