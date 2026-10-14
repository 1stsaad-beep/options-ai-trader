"""Real isolated processes: no provider, credentials, deployment or external order."""
import json
import os
from pathlib import Path
import selectors
import subprocess
import sys
from datetime import datetime, timezone

from app.repository import Repository
from app.service import TradingService
from app.worker import heartbeat_ok

BACKEND = Path(__file__).resolve().parents[1]


def environment(path):
    return {**os.environ, 'DATABASE_URL':'sqlite:///' + str(path),
            'TRADING_MODE':'paper', 'ENABLE_LIVE':'false'}


def read_status(process):
    with selectors.DefaultSelector() as selector:
        selector.register(process.stdout, selectors.EVENT_READ)
        assert selector.select(5), 'Worker did not report within five seconds'
        value = process.stdout.readline()
        assert value, 'Worker exited without status'
        return json.loads(value)


def test_actual_db_unavailability_recovers_then_sigterm_interrupts_wait(tmp_path):
    path = tmp_path/'late-mounted-directory'/'local.db'
    process = subprocess.Popen([sys.executable,'-m','app.worker','--interval','1'],
        cwd=BACKEND, env=environment(path), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        first = read_status(process)
        assert first['status'] == 'WORKER_UNAVAILABLE' and first['external_orders_enabled'] is False
        assert 'late-mounted-directory' not in json.dumps(first)
        path.parent.mkdir()
        recovered = None
        for _ in range(3):
            recovered = read_status(process)
            if recovered['status'] == 'OK':
                break
        assert recovered['status'] == 'OK' and recovered['orders_submitted'] == 0
        assert recovered['execute_mock'] is False
        process.terminate()
        _, errors = process.communicate(timeout=5)
        assert process.returncode == 0 and not errors
        repo = Repository('sqlite:///' + str(path), invalidate_accounts=False)
        try:
            assert not heartbeat_ok(repo, datetime.now(timezone.utc))
            with repo.transaction() as db:
                value = json.loads(db.one("SELECT payload FROM runtime_health WHERE name='worker'")['payload'])
                assert value['status'] == 'STOPPED'
                assert db.one('SELECT COUNT(*) AS n FROM orders')['n'] == 0
        finally:
            repo.close()
    finally:
        if process.poll() is None:
            process.kill();process.communicate(timeout=5)


def test_process_restart_preserves_ledger_and_readonly_healthcheck_does_not_disarm(tmp_path):
    path = tmp_path/'ledger.db'; url='sqlite:///' + str(path)
    repo = Repository(url)
    try:
        service = TradingService(repo); account = service.create_account('kept',1234567)['id']
        service.reconcile(account)
        for _ in range(2):
            run = subprocess.run([sys.executable,'-m','app.worker','--once'],cwd=BACKEND,
                env=environment(path),capture_output=True,text=True,timeout=10)
            assert run.returncode == 0 and not run.stderr
            assert json.loads(run.stdout)['orders_submitted'] == 0
            with repo.transaction() as db:
                saved = db.one('SELECT * FROM accounts WHERE id=?',(account,))
                assert saved['equity'] == 1234567 and not saved['state_known']
            service.reconcile(account)
            with repo.transaction() as db:
                before = db.one('SELECT * FROM accounts WHERE id=?',(account,))
            health = subprocess.run([sys.executable,'-m','app.worker','--healthcheck'],cwd=BACKEND,
                env=environment(path),capture_output=True,text=True,timeout=10)
            assert health.returncode == 0 and not health.stdout and not health.stderr
            with repo.transaction() as db:
                assert db.one('SELECT * FROM accounts WHERE id=?',(account,)) == before
    finally:
        repo.close()


def test_once_failure_is_nonzero_sanitized_and_live_mode_never_starts(tmp_path):
    path = tmp_path/'absent'/'must-not-appear.db'
    for extra in ({}, {'ENABLE_LIVE':'true'}):
        run = subprocess.run([sys.executable,'-m','app.worker','--once'],cwd=BACKEND,
            env=environment(path)|extra,capture_output=True,text=True,timeout=10)
        assert run.returncode != 0 and not path.exists()
        assert 'must-not-appear' not in run.stdout + run.stderr


def test_sigterm_does_not_wait_for_sixty_second_poll(tmp_path):
    process = subprocess.Popen([sys.executable,'-m','app.worker','--interval','60'],cwd=BACKEND,
        env=environment(tmp_path/'long-poll.db'),stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    try:
        assert read_status(process)['status'] == 'OK'
        process.terminate();_, errors=process.communicate(timeout=5)
        assert process.returncode == 0 and not errors
    finally:
        if process.poll() is None:
            process.kill();process.communicate(timeout=5)
