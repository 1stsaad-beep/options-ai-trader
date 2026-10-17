from datetime import timedelta
import json
import sqlite3
from pathlib import Path
import sys

import pytest
from fastapi.testclient import TestClient

from app import health_exporter as module
from app.health_exporter import PATH, create_app, main, snapshot, token_file
from app.observed_option_replay import iso
from app.observed_paper import canonical
from test_observed_paper import stored

TOKEN = 'fixture-only-token-not-a-secret'
NONCE = 'a' * 32


def setup(tmp_path):
    repo, store, clock = stored(tmp_path)
    url = 'sqlite:///' + str(tmp_path / 'observed.db')
    # stored() names the fixture database; get its actual existing file.
    with repo.transaction() as db:
        file = db.one('PRAGMA database_list')['file']
    url = 'sqlite:///' + file
    return repo, store, clock, url


def seed(repo, now, worker='RUNNING_VIRTUAL', delivery='AUTH_BLOCKED'):
    with repo.transaction() as db:
        for name, state in [('observed_paper', worker), ('observed_watchdog','MONITORING'), ('observed_alert_delivery',delivery)]:
            db.execute('INSERT INTO runtime_health VALUES(?,?,?) ON CONFLICT(name) DO UPDATE SET updated_at=excluded.updated_at,payload=excluded.payload',
                       (name, iso(now), canonical({'state': state, 'externalOrder': False, 'owner': 'private-owner-not-exported'})))
        db.execute("INSERT INTO observed_paper_data_state VALUES('budget',?) ON CONFLICT(name) DO UPDATE SET payload=excluded.payload",
            (canonical({'calls': [iso(now)], 'authBlocked': True, 'retryAt': iso(now + timedelta(seconds=60)), 'failures': 1}),))


def test_same_snapshot_distinguishes_liveness_from_delivery_or_trading_health(tmp_path):
    repo, store, clock, url = setup(tmp_path); seed(repo, clock())
    before = store.snapshot('a', full=True)
    value, status = snapshot(url, clock(), NONCE)
    assert status == 200 and value['databaseReadable'] is True
    assert value['components'] == {'worker': {'fresh': True, 'state': 'RUNNING_VIRTUAL'},
        'watchdog': {'fresh': True, 'state': 'MONITORING'}, 'delivery': {'fresh': True, 'state': 'AUTH_BLOCKED'}}
    assert value['dataAccess'] == {'verified': True, 'authBlocked': True, 'backoff': True}
    assert value['nonce'] == NONCE and value['serverTime'] == iso(clock())
    assert value['executionAllowed'] is value['newEntryAllowed'] is value['externalOrder'] is False
    assert 'private-owner' not in canonical(value) and 'a' not in value
    assert store.snapshot('a', full=True) == before
    repo.close()


@pytest.mark.parametrize('seconds', [-1, 31, 61])
def test_future_or_stale_health_never_reuses_old_success(tmp_path, seconds):
    repo, store, clock, url = setup(tmp_path); seed(repo, clock())
    value, status = snapshot(url, clock() + timedelta(seconds=seconds), NONCE)
    assert status == 200
    assert value['components']['delivery'] == {'fresh': False, 'state': 'UNAVAILABLE'}
    assert value['components']['worker']['fresh'] == (seconds == 31)
    repo.close()


@pytest.mark.parametrize('state', ['DISABLED', 'NO_ACTIVE_DEMAND', 'SESSION_CLOSED', 'DATA_UNAVAILABLE', 'LEDGER_BLOCKED'])
def test_fresh_blocked_or_disabled_worker_is_live_with_explicit_state(tmp_path, state):
    repo, store, clock, url = setup(tmp_path); seed(repo, clock(), worker=state)
    value, _ = snapshot(url, clock(), NONCE)
    assert value['components']['worker'] == {'fresh': True, 'state': state}
    assert value['newEntryAllowed'] is False
    repo.close()


def test_missing_database_is_unknown_and_is_not_created(tmp_path):
    path = tmp_path / 'missing.sqlite'
    from datetime import datetime, timezone
    value, status = snapshot('sqlite:///' + str(path), datetime.now(timezone.utc), NONCE)
    assert status == 503 and value['databaseReadable'] is False and not path.exists()
    assert all(v == {'fresh': False, 'state': 'UNKNOWN'} for v in value['components'].values())
    assert str(path) not in canonical(value)


def test_corrupt_budget_is_unverified_and_oversized_state_is_unavailable(tmp_path):
    repo, store, clock, url = setup(tmp_path); seed(repo, clock())
    with repo.transaction() as db:
        db.execute("UPDATE observed_paper_data_state SET payload='{}' WHERE name='budget'")
    value, status = snapshot(url, clock(), NONCE)
    assert status == 200 and value['dataAccess'] == {'verified': False, 'authBlocked': None, 'backoff': None}
    assert 'DATA_STATE_REVIEW_REQUIRED' in value['workerAlerts']
    with repo.transaction() as db:
        db.execute("UPDATE runtime_health SET payload=? WHERE name='observed_paper'", ('x' * 4097,))
    value, status = snapshot(url, clock(), NONCE)
    assert status == 503 and value['components']['worker']['state'] == 'UNKNOWN'
    repo.close()


def test_endpoint_has_separate_auth_nonce_and_no_write_routes(tmp_path, monkeypatch):
    repo, store, clock, url = setup(tmp_path); seed(repo, clock())
    client = TestClient(create_app(url, TOKEN, clock)); headers = {'Authorization': 'Bearer ' + TOKEN, 'X-OAT-Probe': NONCE}
    original = module.snapshot
    monkeypatch.setattr(module, 'snapshot', lambda *a: (_ for _ in ()).throw(AssertionError('No DB before authentication')))
    assert client.get(PATH).status_code == 401
    assert client.get(PATH, headers={'Authorization': 'Bearer other-owner-token'}).status_code == 401
    monkeypatch.setattr(module, 'snapshot', original)
    first = client.get(PATH, headers=headers)
    assert first.status_code == 200 and first.headers['cache-control'] == 'no-store'
    second = client.get(PATH, headers=headers | {'X-OAT-Probe': 'b' * 32})
    assert first.json()['nonce'] != second.json()['nonce']
    assert client.get(PATH + '?private=query', headers=headers).status_code == 400
    assert client.get(PATH, headers={'Authorization': 'Bearer ' + TOKEN}).status_code == 400
    assert client.get(PATH, headers=list(headers.items()) + [('X-OAT-Probe', NONCE)]).status_code == 400
    assert client.get(PATH, headers=list(headers.items()) + [('Authorization', 'Bearer ' + TOKEN)]).status_code == 401
    assert client.post(PATH, headers=headers).status_code == 405
    assert client.get('/api/observed-paper/accounts', headers=headers).status_code == 404
    assert client.get('/openapi.json', headers=headers).status_code == 404
    repo.close()


def test_database_enforces_read_only_even_if_projection_regresses(tmp_path, monkeypatch):
    repo, store, clock, url = setup(tmp_path); before = store.snapshot('a', full=True)
    def attempt(db, now):
        with pytest.raises(sqlite3.OperationalError, match='readonly'):
            db.execute('DELETE FROM observed_paper_accounts')
        raise RuntimeError('private driver diagnostic')
    monkeypatch.setattr(module, 'read_status', attempt)
    value, status = snapshot(url, clock(), NONCE)
    assert status == 503 and 'private driver' not in canonical(value)
    assert store.snapshot('a', full=True) == before
    repo.close()


def test_token_file_strict_private_regular_and_no_follow(tmp_path):
    path = tmp_path / 'health.json'; path.write_text(json.dumps({'token': TOKEN})); path.chmod(0o600)
    assert token_file(path) == TOKEN
    link = tmp_path / 'health-link.json'; link.symlink_to(path)
    with pytest.raises(ValueError): token_file(link)
    path.chmod(0o644)
    with pytest.raises(ValueError): token_file(path)
    path.chmod(0o600); path.write_text('{"token":"a","token":"b"}')
    with pytest.raises(ValueError): token_file(path)
    path.write_text(json.dumps({'token': TOKEN, 'extra': True}))
    with pytest.raises(ValueError): token_file(path)


def test_disabled_cli_does_not_open_database_or_secret(monkeypatch, capsys):
    monkeypatch.setenv('TRADING_MODE', 'paper'); monkeypatch.setenv('ENABLE_LIVE', 'false')
    monkeypatch.delenv('OAT_HEALTH_EXPORT_APPROVAL', raising=False)
    def forbidden(*args): raise AssertionError('No IO')
    monkeypatch.setattr(module, 'token_file', forbidden); monkeypatch.setattr(module, 'snapshot', forbidden)
    assert main(['--check']) == 0
    assert json.loads(capsys.readouterr().out)['state'] == 'DISABLED'
    monkeypatch.setenv('ENABLE_LIVE', 'true')
    assert main(['--check']) == 1


def test_shared_postgresql_export_contract_on_disposable_sqlite(tmp_path):
    sys.path.insert(0, str(Path(__file__).parents[2] / 'scripts'))
    from health_export_check import check
    from app.repository import Repository
    repo, store, clock, url = setup(tmp_path)
    second = Repository(url, invalidate_accounts=False)
    try:
        assert len(check(url, [repo, second])) == 3
    finally:
        second.close(); repo.close()
