"""Opt-in independent outage observer; no provider, execution or repository init.

Opens only an EXISTING database. It shares the short alert/heartbeat transaction
lock with the worker, but never acquires a worker lease, migrates a schema or
writes a financial table. Database failure emits a fixed local diagnostic: it
cannot truthfully claim to persist an alert into an unavailable database.
"""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import signal
import sqlite3
import threading
import uuid

from .observed_option_replay import iso
from .observed_paper import canonical
from .observed_paper_alerts import record
from .observed_paper_status import read_status
from .repository import Session


@contextmanager
def connection(url):
    db = None
    try:
        if url.startswith(('postgresql://', 'postgres://')):
            import psycopg
            from psycopg.rows import dict_row
            db = psycopg.connect(url, row_factory=dict_row, connect_timeout=3,
                options='-c statement_timeout=2000 -c lock_timeout=1000')
            db.execute('SELECT pg_advisory_xact_lock(82741639)')
            postgres = True
        elif url.startswith('sqlite:///') and url != 'sqlite:///:memory:':
            uri = Path(url.removeprefix('sqlite:///')).resolve().as_uri() + '?mode=rw'
            db = sqlite3.connect(uri, uri=True, timeout=1)
            db.row_factory = sqlite3.Row
            db.execute('BEGIN IMMEDIATE')
            postgres = False
        else:
            raise ValueError('Unsupported monitor database')
        yield Session(db, postgres)
        db.commit()
    except BaseException:
        if db is not None: db.rollback()
        raise
    finally:
        if db is not None: db.close()


def observe(url, now, owner=None):
    """Capture current status and deduplicated alert atomically, at detection time.

    Fresh worker state can recover the alert on the next monitor sample. It does
    not enable/restart a worker or clear authentication/budget/financial locks.
    """
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError('Explicit monitor time required')
    owner = owner or str(uuid.uuid4())
    with connection(url) as db:
        status = read_status(db, now)
        record(db, now)
        db.execute("INSERT INTO runtime_health VALUES('observed_watchdog',?,?) "
            "ON CONFLICT(name) DO UPDATE SET updated_at=excluded.updated_at,payload=excluded.payload",
            (iso(now), canonical({'state':'MONITORING','externalOrder':False,'owner':owner})))
    return {'component':'observed_watchdog','state':'MONITORING','detectedAt':iso(now),
        'workerAvailable':status['heartbeatFresh'],'alerts':status['alerts'],
        'externalOrder':False,'executionAllowed':False}


def stop_health(url, owner):
    # A retiring process cannot invalidate the most recent sample of a successor.
    with connection(url) as db:
        row=db.one("SELECT payload FROM runtime_health WHERE name='observed_watchdog'")
        if row and json.loads(row['payload']).get('owner')==owner:
            db.execute("UPDATE runtime_health SET payload=? WHERE name='observed_watchdog' AND payload=?",
                (canonical({'state':'STOPPED','externalOrder':False,'owner':owner}),row['payload']))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--once', action='store_true')
    group.add_argument('--healthcheck', action='store_true')
    args = parser.parse_args(argv)
    if os.getenv('TRADING_MODE','paper') != 'paper' or os.getenv('ENABLE_LIVE','false').lower() != 'false':
        return 1
    now = lambda: datetime.now(timezone.utc)
    url = os.getenv('DATABASE_URL','sqlite:///options_demo.db')
    if args.healthcheck:
        from .runtime_health import probe_heartbeat
        return 0 if probe_heartbeat(url,'observed_watchdog',now()) else 1
    if os.getenv('OAT_OBSERVED_MONITOR_APPROVAL') != 'monitor_only_approved':
        print(json.dumps({'component':'observed_watchdog','state':'DISABLED','externalOrder':False}),flush=True)
        return 0
    owner = str(uuid.uuid4())
    stop = threading.Event()
    previous = {name:signal.signal(name,lambda *_:stop.set()) for name in (signal.SIGTERM,signal.SIGINT)}
    try:
        while not stop.is_set():
            try:
                result = observe(url,now(),owner); ok = True
            except Exception:
                result = {'component':'observed_watchdog','state':'MONITOR_UNAVAILABLE',
                    'externalOrder':False,'executionAllowed':False}; ok = False
            print(json.dumps(result),flush=True)
            if args.once: return 0 if ok else 1
            stop.wait(15)
    finally:
        try: stop_health(url,owner)
        except Exception: pass
        # No worker health, lease or account cleanup is owned by this process.
        for name,handler in previous.items(): signal.signal(name,handler)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
