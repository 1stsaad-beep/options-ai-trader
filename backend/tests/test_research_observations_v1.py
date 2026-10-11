"""Counterfactual outcomes require durable, later, prospectively captured inputs."""
from datetime import timedelta, timezone
from hashlib import sha256
import json
import sqlite3

from fastapi.testclient import TestClient
import pytest

from app.main import create_app
from app.repository import Repository
from app.research_workbench import capture_workbench_observation, replay_workbench, snapshot_workbench
from app.service import Rejected, TradingService
from test_research_workbench_v1 import world, NOW  # noqa: F401


def test_advancing_clock_never_creates_missing_outcomes(world, monkeypatch):
    service, account, _, clock = world
    saved = snapshot_workbench(service, account, 'NVDA')
    clock[0] += timedelta(days=300)
    monkeypatch.setattr('app.research_workbench.fixture_quote', lambda *a: pytest.fail('Replay generated a price'))
    result = replay_workbench(service, account, 'NVDA', saved['snapshot_id'])
    assert result['counterfactual']['status'] == 'INSUFFICIENT_OBSERVED_OUTCOME'
    assert result['counterfactual']['pnl'] is None
    assert result['original_workbench'] == saved['workbench']


def test_capture_is_prospective_idempotent_and_survives_restart(world, monkeypatch):
    service, account, _, clock = world
    saved = snapshot_workbench(service, account, 'NVDA')
    key = saved['snapshot_id']
    with pytest.raises(Rejected, match='later unexpired'):
        capture_workbench_observation(service, account, 'NVDA', key)
    clock[0] += timedelta(minutes=1)
    first = capture_workbench_observation(service, account, 'NVDA', key)
    clock[0] += timedelta(seconds=2)
    assert capture_workbench_observation(service, account, 'NVDA', key) == first
    assert replay_workbench(service, account, 'NVDA', key)['counterfactual']['pnl'] is None
    clock[0] += timedelta(minutes=1)
    second = capture_workbench_observation(service, account, 'NVDA', key)
    assert first['observed_at'] < second['observed_at']
    with service.repo.transaction() as db:
        assert db.one('SELECT COUNT(*) AS n FROM research_observations')['n'] == 2
    assert len([a for a in service.rows(account, 'audit') if a['event'] == 'RESEARCH_OBSERVATION']) == 2
    result = replay_workbench(service, account, 'NVDA', key)
    assert result['counterfactual']['status'] == 'REPLAYED'
    assert result['counterfactual']['commissions'] == pytest.approx(1.3)
    clock[0] += timedelta(days=300)
    monkeypatch.setattr('app.research_workbench.fixture_quote', lambda *a: pytest.fail('Replay regenerated evidence'))
    restarted = TradingService(service.repo, now=lambda: clock[0], today=lambda: clock[0].date())
    assert replay_workbench(restarted, account, 'NVDA', key) == result
    assert not service.rows(account, 'orders')


def test_future_capture_not_available_to_earlier_replay(world):
    service, account, _, clock = world
    key = snapshot_workbench(service, account, 'NVDA')['snapshot_id']
    clock[0] += timedelta(minutes=1)
    capture_workbench_observation(service, account, 'NVDA', key)
    clock[0] += timedelta(minutes=1)
    capture_workbench_observation(service, account, 'NVDA', key)
    clock[0] = NOW + timedelta(minutes=1)
    assert replay_workbench(service, account, 'NVDA', key)['counterfactual']['pnl'] is None
    # Equivalent time zones do not shift observation availability.
    clock[0] = (NOW + timedelta(minutes=2)).astimezone(timezone(timedelta(hours=3)))
    assert replay_workbench(service, account, 'NVDA', key)['counterfactual']['status'] == 'REPLAYED'


def test_capture_identity_expiry_and_immutable_database_boundary(world):
    service, account, other, clock = world
    key = snapshot_workbench(service, account, 'NVDA')['snapshot_id']
    clock[0] += timedelta(minutes=1)
    for a, symbol in ((other, 'NVDA'), (account, 'AAPL')):
        with pytest.raises(Rejected):
            capture_workbench_observation(service, a, symbol, key)
    capture_workbench_observation(service, account, 'NVDA', key)
    for sql in ('UPDATE research_observations SET digest=digest', 'DELETE FROM research_observations'):
        with pytest.raises(sqlite3.IntegrityError, match='immutable'):
            with service.repo.transaction() as db:
                db.execute(sql)
    with pytest.raises(sqlite3.IntegrityError, match='FOREIGN KEY'):
        with service.repo.transaction() as db:
            db.execute('INSERT INTO research_observations VALUES(?,?,?,?,?,?)',
                       (other, key, 'other-time', 'other-time', '{}', 'bad'))
    clock[0] += timedelta(days=31)
    with pytest.raises(Rejected, match='later unexpired'):
        capture_workbench_observation(service, account, 'NVDA', key)


@pytest.mark.parametrize('mutation', ['digest', 'account', 'contract', 'model', 'bid'])
def test_corrupt_observation_never_produces_pnl(world, mutation):
    service, account, _, clock = world
    key = snapshot_workbench(service, account, 'NVDA')['snapshot_id']
    clock[0] += timedelta(minutes=1)
    value = capture_workbench_observation(service, account, 'NVDA', key)
    clock[0] += timedelta(minutes=1)
    value['observed_at'] = clock[0].replace(second=0, microsecond=0).isoformat()
    value['captured_at'] = clock[0].isoformat()
    if mutation == 'account': value['account_id'] = 'other'
    if mutation == 'contract': value['contract_id'] = 'other'
    if mutation == 'model': value['quote_model_version'] = 'unreviewed-v2'
    if mutation == 'bid': value['bid'] = True
    payload = json.dumps(value, sort_keys=True)
    digest = '0'*64 if mutation == 'digest' else sha256(payload.encode()).hexdigest()
    with service.repo.transaction() as db:
        db.execute('INSERT INTO research_observations VALUES(?,?,?,?,?,?)',
                   (account, key, value['observed_at'], value['captured_at'], payload, digest))
    with pytest.raises(Rejected, match='failed validation'):
        replay_workbench(service, account, 'NVDA', key)


def test_observation_api_cannot_accept_client_prices_or_times(world):
    service, account, _, clock = world
    key = snapshot_workbench(service, account, 'NVDA')['snapshot_id']
    clock[0] += timedelta(minutes=1)
    token = 'research-observation-test-token-000'
    with TestClient(create_app(service.repo, token)) as client:
        client.app.state.service = service
        path = f'/api/accounts/{account}/research/NVDA/snapshots/{key}/observations'
        headers = {'Authorization': 'Bearer ' + token}
        assert client.post(path, json={}).status_code == 401
        assert client.post(path, json={'bid': 100}, headers=headers).status_code == 422
        assert client.post(path, json={'observed_at': NOW.isoformat()}, headers=headers).status_code == 422
        assert client.post(path, json={}, headers=headers).status_code == 200


def test_upgrade_from_v4_preserves_decision_and_allows_new_observations(tmp_path, monkeypatch):
    import app.migrations as migrations
    all_migrations = migrations.MIGRATIONS
    monkeypatch.setattr(migrations, 'MIGRATIONS', all_migrations[:4])
    url = 'sqlite:///' + str(tmp_path / 'v4.db')
    repo = Repository(url)
    service = TradingService(repo, now=lambda: NOW, today=lambda: NOW.date())
    account = service.create_account('existing')['id']
    service.watch(account, 'NVDA', True)
    saved = snapshot_workbench(service, account, 'NVDA')
    before = service.rows(account, 'decision_snapshots')
    repo.close()
    monkeypatch.setattr(migrations, 'MIGRATIONS', all_migrations)
    repo = Repository(url)
    try:
        service = TradingService(repo, now=lambda: NOW+timedelta(minutes=1), today=lambda: NOW.date())
        assert service.rows(account, 'decision_snapshots') == before
        capture_workbench_observation(service, account, 'NVDA', saved['snapshot_id'])
        assert replay_workbench(service, account, 'NVDA', saved['snapshot_id'])['original_workbench'] == saved['workbench']
    finally:
        repo.close()
