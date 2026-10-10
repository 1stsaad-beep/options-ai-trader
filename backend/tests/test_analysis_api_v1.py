import json
from datetime import datetime, timedelta, timezone
from fastapi.testclient import TestClient
from app.main import create_app
from app.repository import Repository


def test_shadow_facades_and_durable_history_have_no_order_authority(tmp_path):
    path = str(tmp_path / 'history.db')
    repo = Repository('sqlite:///' + path)
    token = 'test-token-at-least-32-characters-long'
    headers = {'Authorization': 'Bearer ' + token}
    clock = [datetime(2026, 10, 5, 15, tzinfo=timezone.utc)]
    app = create_app(repo, token)
    try:
        with TestClient(app) as client:
            app.state.service.now = lambda: clock[0]
            a = client.post('/api/accounts', json={'name': 'A'}, headers=headers).json()['id']
            b = client.post('/api/accounts', json={'name': 'B'}, headers=headers).json()['id']
            prefix = '/api/accounts/' + a
            assert client.get('/api/research/demo').status_code == 401
            research = client.get('/api/research/demo', headers=headers).json()
            assert research['mode'] == 'SHADOW' and not research['external_connections']
            assert client.get(prefix + '/analysis/NVDA', headers=headers).status_code == 409
            client.patch(prefix + '/watchlist/NVDA', json={'enabled': True}, headers=headers)
            analysis = client.get(prefix + '/analysis/NVDA', headers=headers).json()
            assert not analysis['executable'] and analysis['source'] == 'synthetic_fixture'
            first = client.post(prefix + '/analysis/NVDA/snapshot', json={}, headers=headers)
            assert first.status_code == 200, first.text
            initial = client.get(prefix + '/decisions', headers=headers).json()
            clock[0] += timedelta(minutes=1)
            second = client.post(prefix + '/analysis/NVDA/snapshot', json={}, headers=headers)
            assert second.status_code == 200, second.text
            decisions = client.get(prefix + '/decisions', headers=headers).json()
            assert len(decisions) == 2
            assert next(x for x in decisions if x['id'] == initial[0]['id']) == initial[0]
            assert client.get('/api/accounts/' + b + '/decisions', headers=headers).json() == []
            assert client.get(prefix + '/orders', headers=headers).json() == []
            assert client.post(prefix + '/analysis/NVDA/snapshot', json={'execute': True}, headers=headers).status_code == 422
        repo.close()
        reopened = Repository('sqlite:///' + path)
        from app.analysis_service import snapshot_analysis
        from app.service import TradingService
        service = TradingService(reopened, now=lambda: clock[0] + timedelta(minutes=1))
        snapshot_analysis(service, a, 'NVDA')
        assert len(service.rows(a, 'decision_snapshots')) == 3
        assert service.rows(a, 'orders') == []
        assert not service.list_accounts()[0]['state_known']
        reopened.close()
    finally:
        try:
            repo.close()
        except Exception:
            pass
