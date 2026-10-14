"""Process health probes must never create/migrate/lock the financial database."""
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import time
import pytest

BACKEND = Path(__file__).resolve().parents[1]
MODULES = ['app.worker', 'app.market_runtime_worker']

def probe(module, path):
    env = {**os.environ, 'DATABASE_URL': 'sqlite:///' + str(path), 'ENABLE_LIVE': 'false',
           'TRADING_MODE': 'paper', 'OAT_ALPACA_DATA_APPROVAL': '',
           'OAT_ALPACA_DATA_CREDENTIALS_FILE': '/must-not-read-for-health'}
    return subprocess.run([sys.executable, '-m', module, '--healthcheck'], cwd=BACKEND,
                          env=env, capture_output=True, text=True, timeout=4)

def minimal(path, module, *, offset=0, payload=None):
    name = 'worker' if module == 'app.worker' else 'market_collector'
    payload = payload if payload is not None else {'status': 'OK', 'state': 'DISABLED'}
    c = sqlite3.connect(path)
    c.execute('CREATE TABLE runtime_health(name TEXT PRIMARY KEY,updated_at TEXT,payload TEXT)')
    at = (datetime.now(timezone.utc) + timedelta(seconds=offset)).isoformat()
    c.execute('INSERT INTO runtime_health VALUES(?,?,?)', (name, at, json.dumps(payload)))
    c.commit(); c.close()

@pytest.mark.parametrize('module', MODULES)
def test_missing_database_probe_is_nonzero_and_does_not_create_file(tmp_path, module):
    path = tmp_path/'missing.db'; result = probe(module, path)
    assert result.returncode == 1
    assert not path.exists(), 'Health probe must not initialize a missing ledger'
    assert not result.stdout and not result.stderr

@pytest.mark.parametrize('module', MODULES)
def test_probe_reads_only_existing_heartbeat_without_schema_migration(tmp_path, module):
    path = tmp_path/'existing.db'; minimal(path, module); before = path.read_bytes()
    result = probe(module, path)
    assert result.returncode == 0 and not result.stdout and not result.stderr
    assert path.read_bytes() == before, 'Read probe must not migrate or change journal mode'
    with sqlite3.connect(path) as c:
        assert c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall() == [('runtime_health',)]

@pytest.mark.parametrize('module', MODULES)
def test_health_read_does_not_wait_for_financial_writer_lock(tmp_path, module):
    path = tmp_path/'locked.db'; minimal(path, module)
    c = sqlite3.connect(path); c.execute('BEGIN IMMEDIATE')
    try:
        started = time.monotonic(); result = probe(module, path)
        assert result.returncode == 0 and time.monotonic() - started < 3
    finally:
        c.rollback(); c.close()

@pytest.mark.parametrize('module', MODULES)
@pytest.mark.parametrize('payload,offset', [({'status':'STOPPED','state':'STOPPED'},0),
    ({'status':'OK','state':'DISABLED'},-121), ({'status':'OK','state':'DISABLED'},60),
    ({'status':'OK','state':'unrecognized'},0), (None,0)])
def test_stale_future_stopped_and_malformed_probes_fail_closed(tmp_path, module, payload, offset):
    if payload == {'status':'OK','state':'unrecognized'} and module == 'app.worker':
        payload = {'status':'unrecognized'}
    path = tmp_path/'bad.db'; minimal(path, module, offset=offset, payload=payload)
    if payload is None:
        with sqlite3.connect(path) as c:c.execute("UPDATE runtime_health SET payload='[invalid-json'")
    before = path.read_bytes(); result = probe(module, path)
    assert result.returncode == 1 and not result.stdout and not result.stderr
    assert path.read_bytes() == before


def test_collector_sigterm_marks_stopped_and_preserves_account(tmp_path):
    from app.repository import Repository
    from app.service import TradingService
    from test_worker_recovery import environment, read_status
    path = tmp_path/'collector.db'
    repo = Repository('sqlite:///' + str(path))
    service = TradingService(repo); account = service.create_account('preserved')['id']; service.reconcile(account)
    with repo.transaction() as db:
        before = db.one('SELECT * FROM accounts WHERE id=?', (account,))
    process = subprocess.Popen([sys.executable,'-m','app.market_runtime_worker'], cwd=BACKEND,
        env=environment(path)|{'OAT_ALPACA_DATA_APPROVAL':''}, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        assert read_status(process)['state'] == 'DISABLED'
        assert probe('app.market_runtime_worker',path).returncode == 0
        process.terminate(); _, errors = process.communicate(timeout=4)
        assert process.returncode == 0 and not errors
        assert probe('app.market_runtime_worker',path).returncode == 1
        with repo.transaction() as db:
            row = db.one("SELECT payload FROM runtime_health WHERE name='market_collector'")
            assert json.loads(row['payload'])['state'] == 'STOPPED'
            assert db.one('SELECT * FROM accounts WHERE id=?', (account,)) == before
            assert db.all('SELECT * FROM orders') == []
    finally:
        if process.poll() is None:process.kill();process.communicate(timeout=4)
        repo.close()


def test_stale_owner_shutdown_cannot_replace_successor_heartbeat(tmp_path):
    from app.repository import Repository
    from app.service import TradingService
    from app.market_runtime import MarketCollector, coordinator_in
    from app.market_data import DisabledMarketData
    repo = Repository('sqlite:///' + str(tmp_path/'lease.db'))
    clock = [datetime.now(timezone.utc)]; service = TradingService(repo)
    old = MarketCollector(service,DisabledMarketData(),owner='old',now=lambda:clock[0])
    new = MarketCollector(service,DisabledMarketData(),owner='new',now=lambda:clock[0])
    try:
        old.tick();clock[0]+=timedelta(seconds=121);new.tick()
        old.release(mark_stopped=True)
        with repo.transaction() as db:
            assert coordinator_in(db)['owner'] == 'new'
            saved = json.loads(db.one("SELECT payload FROM runtime_health WHERE name='market_collector'")['payload'])
            assert saved['owner']=='new' and saved['state']=='DISABLED'
    finally:repo.close()


def test_collector_database_outage_recovers_without_phone_or_orders(tmp_path):
    import selectors
    from app.repository import Repository
    from test_worker_recovery import environment
    path=tmp_path/'late-volume'/'collector.db'
    process=subprocess.Popen([sys.executable,'-m','app.market_runtime_worker'],cwd=BACKEND,
        env=environment(path)|{'OAT_ALPACA_DATA_APPROVAL':''},stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    def status():
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout,selectors.EVENT_READ)
            assert selector.select(7), 'No bounded recovery status'
            return json.loads(process.stdout.readline())
    try:
        first=status();assert first['state']=='WORKER_UNAVAILABLE'
        assert 'late-volume' not in json.dumps(first)
        path.parent.mkdir();assert status()['state']=='DISABLED'
        process.terminate();_,errors=process.communicate(timeout=4)
        assert process.returncode==0 and not errors
        repo=Repository('sqlite:///'+str(path),invalidate_accounts=False)
        try:
            with repo.transaction() as db:assert db.all('SELECT * FROM orders')==[]
        finally:repo.close()
    finally:
        if process.poll() is None:process.kill();process.communicate(timeout=4)
