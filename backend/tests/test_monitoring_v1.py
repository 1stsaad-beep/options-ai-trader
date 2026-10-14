from datetime import datetime, timedelta, timezone
from fastapi.testclient import TestClient
from app.main import create_app
from app.monitoring import readiness
from app.repository import Repository
from app.service import TradingService
from app.worker import tick


def test_readiness_observation_never_repairs_account_and_heartbeat_expires():
    repo = Repository()
    clock = [datetime(2026, 10, 5, 15, tzinfo=timezone.utc)]
    service = TradingService(repo, now=lambda: clock[0], today=lambda: clock[0].date())
    try:
        account = service.create_account('readiness')['id']
        service.watch(account, 'NVDA', True)
        service.configure(account, {'automation_enabled': True})
        before = readiness(service)
        assert before['api_ready'] and not before['trading_ready']
        tick(service)
        assert readiness(service)['worker']['fresh']
        service.reconcile(account)
        assert readiness(service)['accounts'][0]['new_entries_allowed']
        assert readiness(service)['worker']['execute_mock'] is False
        assert readiness(service)['trading_ready'] is False  # Analysis-only process is not execution readiness.
        with repo.transaction() as db:
            import json
            payload = json.loads(db.one("SELECT payload FROM runtime_health WHERE name='worker'")['payload'])
            payload['execute_mock'] = True
            db.execute("UPDATE runtime_health SET payload=? WHERE name='worker'", (json.dumps(payload),))
        assert readiness(service)['trading_ready'] is True
        service.disconnect(account)
        result = readiness(service)
        assert not result['trading_ready']
        assert not result['accounts'][0]['state_known']
        clock[0] += timedelta(seconds=121)
        assert not readiness(service)['worker']['fresh']
    finally:
        repo.close()


def test_readiness_protected_and_database_failure_not_liveness_success():
    repo = Repository()
    token = 'test-token-at-least-32-characters-long'
    with TestClient(create_app(repo, token)) as client:
        assert client.get('/api/readiness').status_code == 401
        headers = {'Authorization': 'Bearer ' + token}
        assert client.get('/api/readiness', headers=headers).json()['api_ready']
        repo.close()
        result = client.get('/api/readiness', headers=headers)
        assert result.status_code == 503
        assert not result.json()['api_ready']
        assert client.get('/health').json()['live_enabled'] is False
