"""Actual process shutdown and lease-fenced health, without market credentials."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import pytest

from app.observed_paper_runtime import ObservedPaperRuntime
from app.repository import Repository
from app.runtime_health import probe_heartbeat
from test_observed_paper import stored
from test_worker_recovery import read_status

BACKEND = Path(__file__).resolve().parents[1]


def row(repo):
    with repo.transaction() as db:
        return db.one("SELECT * FROM runtime_health WHERE name='observed_paper'")


def test_close_invalidates_health_without_touching_original_ledger(tmp_path):
    repo, store, clock = stored(tmp_path)
    runtime = ObservedPaperRuntime(store, owner='first')
    saved = store.snapshot('a', full=True)
    runtime.tick()
    assert probe_heartbeat('sqlite:///' + str(tmp_path/'observed.db'), 'observed_paper', clock())
    runtime.close()
    stopped = row(repo)
    assert json.loads(stopped['payload'])['state'] == 'STOPPED'
    assert not probe_heartbeat('sqlite:///' + str(tmp_path/'observed.db'), 'observed_paper', clock())
    runtime.close()
    assert row(repo) == stopped and runtime.lease is None
    assert store.snapshot('a', full=True) == saved
    repo.close()


def test_expired_owner_can_stop_only_its_own_generation(tmp_path):
    repo, store, clock = stored(tmp_path)
    old = ObservedPaperRuntime(store, owner='reused-id')
    old.tick(); clock.step(31)
    old.close()
    assert json.loads(row(repo)['payload'])['state'] == 'STOPPED'
    old.tick(); clock.step(31)
    successor = ObservedPaperRuntime(store, owner='reused-id')
    successor.tick()
    healthy = row(repo)
    old.close()
    assert row(repo) == healthy
    assert probe_heartbeat('sqlite:///' + str(tmp_path/'observed.db'), 'observed_paper', clock())
    successor.close(); repo.close()


def test_health_failure_rolls_back_release_and_allows_safe_retry(tmp_path):
    repo, store, clock = stored(tmp_path)
    runtime = ObservedPaperRuntime(store, owner='atomic')
    runtime.tick(); before = row(repo)
    with repo.transaction() as db:
        db.execute("CREATE TRIGGER fail_health BEFORE INSERT ON runtime_health BEGIN SELECT RAISE(ABORT,'fixture failure'); END")
    with pytest.raises(Exception, match='fixture failure'):
        runtime.close()
    with repo.transaction() as db:
        assert store._owns(db, runtime.lease, clock())
        db.execute('DROP TRIGGER fail_health')
    assert row(repo) == before
    runtime.close()
    assert json.loads(row(repo)['payload'])['state'] == 'STOPPED'
    repo.close()


def test_recoverable_exception_invalidates_previous_health(tmp_path, monkeypatch, capsys):
    from app.observed_paper_worker import main
    path = tmp_path/'failure.db'
    monkeypatch.setenv('DATABASE_URL', 'sqlite:///' + str(path))
    monkeypatch.setenv('TRADING_MODE', 'paper'); monkeypatch.setenv('ENABLE_LIVE', 'false')
    monkeypatch.delenv('OAT_OBSERVED_PAPER_APPROVAL', raising=False)
    tick = ObservedPaperRuntime.tick
    def fail_after_tick(runtime):
        tick(runtime)
        raise ValueError('private provider text')
    monkeypatch.setattr(ObservedPaperRuntime, 'tick', fail_after_tick)
    assert main(['--once']) == 1
    output = capsys.readouterr()
    assert 'private provider text' not in output.out + output.err
    assert json.loads(output.out)['state'] == 'WORKER_UNAVAILABLE'
    assert not probe_heartbeat('sqlite:///' + str(path), 'observed_paper', datetime.now(timezone.utc))


def test_actual_once_and_sigterm_do_not_leave_a_healthy_stopped_worker(tmp_path):
    path = tmp_path/'actual.db'
    env = {**os.environ, 'DATABASE_URL':'sqlite:///' + str(path), 'TRADING_MODE':'paper',
        'ENABLE_LIVE':'false', 'OAT_OBSERVED_PAPER_APPROVAL':'', 'OAT_ALPACA_DATA_APPROVAL':''}
    command = [sys.executable, '-m', 'app.observed_paper_worker']
    once = subprocess.run(command + ['--once'], cwd=BACKEND, env=env, capture_output=True, text=True, timeout=10)
    assert once.returncode == 0 and not once.stderr and json.loads(once.stdout)['state'] == 'DISABLED'
    assert not probe_heartbeat(env['DATABASE_URL'], 'observed_paper', datetime.now(timezone.utc))
    process = subprocess.Popen(command, cwd=BACKEND, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        assert read_status(process)['state'] == 'DISABLED'
        assert probe_heartbeat(env['DATABASE_URL'], 'observed_paper', datetime.now(timezone.utc))
        process.terminate(); _, errors = process.communicate(timeout=5)
        assert process.returncode == 0 and not errors
        health = subprocess.run(command + ['--healthcheck'], cwd=BACKEND, env=env, capture_output=True, text=True, timeout=10)
        assert health.returncode == 1 and not health.stdout and not health.stderr
        repo = Repository(env['DATABASE_URL'], invalidate_accounts=False)
        assert json.loads(row(repo)['payload'])['state'] == 'STOPPED'
        repo.close()
    finally:
        if process.poll() is None:
            process.kill(); process.communicate(timeout=5)
