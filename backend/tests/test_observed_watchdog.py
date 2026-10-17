from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import pytest

from app.observed_paper_watchdog import observe, stop_health
from app.observed_paper_alerts import page
from app.observed_paper_runtime import ObservedPaperRuntime
from app.repository import Session
from app.runtime_health import probe_heartbeat
from test_observed_paper import stored, iso


def url(tmp_path):return 'sqlite:///'+str(tmp_path/'observed.db')


def tables(repo):
    with repo.transaction() as db:
        return {table:db.all('SELECT * FROM '+table) for table in ['accounts','orders',
            'observed_paper_accounts','observed_paper_events','observed_paper_segments',
            'observed_paper_lease','observed_paper_data_state']}


def test_dead_worker_detected_without_restart_then_recovers_without_financial_effect(tmp_path):
    repo,store,clock=stored(tmp_path);runtime=ObservedPaperRuntime(store);runtime.tick()
    before=tables(repo);clock.step(61)
    result=observe(url(tmp_path),clock())
    assert not result['workerAvailable'] and result['alerts']==['WORKER_UNAVAILABLE']
    event=page(store)['events'][-1]
    assert event['detectedAt']==iso(clock()) and event['raised']==['WORKER_UNAVAILABLE']
    assert tables(repo)==before
    for _ in range(3):observe(url(tmp_path),clock())
    assert page(store)['through']==event['sequence']
    runtime.tick();observe(url(tmp_path),clock())
    assert page(store)['events'][-1]['resolved']==['WORKER_UNAVAILABLE']
    runtime.close();repo.close()


def test_concurrent_watchdogs_deduplicate_in_same_locked_snapshot(tmp_path):
    repo,store,clock=stored(tmp_path);before=tables(repo)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda _:observe(url(tmp_path),clock()),range(2)))
    assert all(x['alerts']==['WORKER_UNAVAILABLE'] for x in results)
    assert page(store)['through']==1 and tables(repo)==before
    repo.close()


def test_monitor_cannot_create_or_migrate_database(tmp_path):
    missing=tmp_path/'absent.db'
    with pytest.raises(sqlite3.OperationalError):observe('sqlite:///'+str(missing),datetime.now(timezone.utc))
    assert not missing.exists()
    legacy=tmp_path/'legacy.db';db=sqlite3.connect(legacy);db.execute('CREATE TABLE sentinel(x)');db.commit();db.close()
    with pytest.raises(sqlite3.OperationalError):observe('sqlite:///'+str(legacy),datetime.now(timezone.utc))
    db=sqlite3.connect(legacy)
    assert db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()==[('sentinel',)]
    db.close()


def test_clock_regression_fails_closed_without_rewriting_worker_health(tmp_path):
    repo,store,clock=stored(tmp_path);ObservedPaperRuntime(store).tick()
    with repo.transaction() as db:before=db.one("SELECT * FROM runtime_health WHERE name='observed_paper'")
    clock.step(-1);assert observe(url(tmp_path),clock())['alerts']==['WORKER_UNAVAILABLE']
    with repo.transaction() as db:assert db.one("SELECT * FROM runtime_health WHERE name='observed_paper'")==before
    repo.close()


def test_alert_failure_rolls_back_monitor_heartbeat_and_preserves_accounts(tmp_path,monkeypatch):
    repo,store,clock=stored(tmp_path);before=tables(repo);original=Session.execute
    def fail(self,sql,parameters=()):
        if sql.startswith('INSERT INTO observed_alert_events'):raise sqlite3.OperationalError('private details')
        return original(self,sql,parameters)
    monkeypatch.setattr(Session,'execute',fail)
    with pytest.raises(sqlite3.OperationalError):observe(url(tmp_path),clock())
    with repo.transaction() as db:assert db.one("SELECT * FROM runtime_health WHERE name='observed_watchdog'") is None
    assert page(store)['through']==0 and tables(repo)==before
    repo.close()


def test_old_monitor_shutdown_cannot_invalidate_successor(tmp_path):
    repo,store,clock=stored(tmp_path)
    observe(url(tmp_path),clock(),'old');observe(url(tmp_path),clock(),'new')
    stop_health(url(tmp_path),'old')
    assert probe_heartbeat(url(tmp_path),'observed_watchdog',clock())
    stop_health(url(tmp_path),'new')
    assert not probe_heartbeat(url(tmp_path),'observed_watchdog',clock())
    repo.close()


def process(tmp_path,approved=True):
    env={k:v for k,v in os.environ.items() if not k.startswith(('OAT_','APCA_','ALPACA_','ENABLE_LIVE','TRADING_MODE','DATABASE_URL'))}
    env.update(DATABASE_URL=url(tmp_path),TRADING_MODE='paper',ENABLE_LIVE='false')
    if approved:env['OAT_OBSERVED_MONITOR_APPROVAL']='monitor_only_approved'
    return subprocess.run([sys.executable,'-m','app.observed_paper_watchdog','--once'],
        cwd=Path(__file__).parents[1],env=env,text=True,capture_output=True,timeout=10)


def test_actual_independent_process_records_outage_without_worker_or_keys(tmp_path):
    repo,store,_=stored(tmp_path);before=tables(repo)
    result=process(tmp_path)
    assert result.returncode==0 and json.loads(result.stdout)['alerts']==['WORKER_UNAVAILABLE']
    assert page(store)['events'][-1]['raised']==['WORKER_UNAVAILABLE'] and tables(repo)==before
    assert not probe_heartbeat(url(tmp_path),'observed_watchdog',datetime.now(timezone.utc))
    repo.close()


def test_actual_disabled_and_failed_process_cannot_bootstrap_or_leak_path(tmp_path):
    result=process(tmp_path,False)
    assert result.returncode==0 and json.loads(result.stdout)['state']=='DISABLED'
    assert not (tmp_path/'observed.db').exists()
    result=process(tmp_path)
    assert result.returncode==1 and json.loads(result.stdout)['state']=='MONITOR_UNAVAILABLE'
    assert str(tmp_path) not in result.stdout+result.stderr and not (tmp_path/'observed.db').exists()


def test_naive_clock_rejected_before_database_access(tmp_path):
    with pytest.raises(ValueError,match='Explicit monitor time'):observe(url(tmp_path),datetime(2026,10,12))
    assert not (tmp_path/'observed.db').exists()
