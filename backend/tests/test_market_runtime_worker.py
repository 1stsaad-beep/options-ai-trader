"""Worker entrypoint and secret boundary: no credentials or remote requests."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import Mock
import pytest
from app import market_runtime as rt, market_runtime_worker as worker
from app.market_data import DisabledMarketData, MarketDataError
from app.main import create_app
from app.repository import Repository
from app.service import TradingService
from fastapi.testclient import TestClient
from test_alpaca_market_api import TOKEN, HEADERS


def test_unapproved_worker_ignores_other_app_and_never_reads_file(monkeypatch):
    monkeypatch.delenv('OAT_ALPACA_DATA_APPROVAL', raising=False)
    monkeypatch.setenv('APCA_API_KEY_ID', 'other-app-do-not-use')
    monkeypatch.setenv('OAT_ALPACA_DATA_CREDENTIALS_FILE', '/not/authorized/to/read')
    monkeypatch.setattr(worker, 'credentials_from_file', Mock(side_effect=AssertionError('Must not read')))
    assert isinstance(worker.build_provider(None, 'worker', lambda: None), DisabledMarketData)


@pytest.mark.parametrize('kind', ['missing', 'symlink', 'world_readable', 'extra_field', 'invalid_json', 'directory', 'oversize'])
def test_secret_file_strict_safe_failure(tmp_path, kind):
    path = tmp_path/'private.json'
    value = {'key_id': 'fixture-id', 'secret_key': 'fixture-value-not-real'}
    path.write_text(json.dumps(value))
    path.chmod(0o600)
    if kind == 'missing':
        path = tmp_path/'absent'
    elif kind == 'symlink':
        link = tmp_path/'link'
        link.symlink_to(path)
        path = link
    elif kind == 'world_readable':
        path.chmod(0o644)
    elif kind == 'extra_field':
        path.write_text(json.dumps({**value, 'trading_endpoint': 'forbidden'}))
    elif kind == 'invalid_json':
        path.write_text('fixture-secret-must-not-appear-in-error')
    elif kind == 'directory':
        path = tmp_path
    elif kind == 'oversize':
        path.write_text('x'*5000)
    with pytest.raises(MarketDataError) as result:
        worker.credentials_from_file(str(path))
    assert str(result.value) == 'INVALID_COLLECTOR_SECRET_FILE'


def test_private_explicit_credentials_do_not_leak_in_repr(tmp_path):
    path = tmp_path/'private.json'
    path.write_text(json.dumps({'key_id': 'fixture-id', 'secret_key': 'fixture-value-not-real'}))
    path.chmod(0o400)
    value = worker.credentials_from_file(str(path))
    assert value.key_id == 'fixture-id' and 'fixture' not in repr(value)


def test_cache_only_api_cannot_construct_second_provider(monkeypatch):
    monkeypatch.setenv('OAT_MARKET_RUNTIME_ROLE', 'api_cache_only')
    monkeypatch.setenv('OAT_ALPACA_DATA_APPROVAL', 'read_only_approved')
    monkeypatch.setattr('app.market_data.from_environment', Mock(side_effect=AssertionError('No API credential reads')))
    repo = Repository()
    try:
        s = TradingService(repo)
        a = s.create_account('isolated')['id']
        with TestClient(create_app(repo, TOKEN)) as client:
            status = client.get(f'/api/accounts/{a}/market-data/status', headers=HEADERS).json()
            assert status['connection_enabled'] is False
    finally:
        repo.close()


def test_actual_process_restart_and_heartbeat_without_phone_or_network(tmp_path):
    path = tmp_path/'persisted.db'
    url = 'sqlite:///' + str(path)
    repo = Repository(url)
    try:
        s = TradingService(repo)
        account = s.create_account('kept')['id']
        s.reconcile(account)
        with repo.transaction() as db:
            before = db.one('SELECT * FROM accounts WHERE id=?', (account,))
        env = {**os.environ, 'DATABASE_URL': url, 'OAT_ALPACA_DATA_APPROVAL': '',
               'OAT_ALPACA_DATA_CREDENTIALS_FILE': '/must/not/be/read', 'ENABLE_LIVE': 'false', 'TRADING_MODE': 'paper'}
        backend = Path(__file__).resolve().parents[1]
        for _ in range(2):
            run = subprocess.run([sys.executable, '-m', 'app.market_runtime_worker', '--once'],
                cwd=backend, env=env, capture_output=True, text=True, timeout=10)
            assert run.returncode == 0, run.stderr
            assert json.loads(run.stdout)['state'] == 'DISABLED'
        check = subprocess.run([sys.executable, '-m', 'app.market_runtime_worker', '--healthcheck'],
            cwd=backend, env=env, capture_output=True, text=True, timeout=10)
        assert check.returncode == 0
        assert worker.heartbeat_ok(repo, datetime.now(timezone.utc))
        with repo.transaction() as db:
            assert db.one('SELECT * FROM accounts WHERE id=?', (account,)) == before
            assert db.all('SELECT * FROM orders') == []
    finally:
        repo.close()


def test_explicit_auth_reset_requires_collector_stopped_and_audits(tmp_path):
    repo = Repository()
    try:
        s = TradingService(repo)
        account = s.create_account('auth-reset')['id']
        rt.configure(s, account, expected_version=0, enabled=False, strategies={'breakout': False, 'pullback': False})
        with repo.transaction() as db:
            state = rt.coordinator_in(db)
            state.update(auth_blocked=True)
            rt.save_coordinator(db, state)
        worker.reset_auth_lock(s)
        assert rt.events(s, account)['items'][0]['kind'] == 'OPERATOR_AUTH_LOCK_RESET'
        c = rt.MarketCollector(s, DisabledMarketData())
        c.tick()
        with pytest.raises(MarketDataError, match='STOP_COLLECTOR'):
            worker.reset_auth_lock(s)
    finally:
        repo.close()
