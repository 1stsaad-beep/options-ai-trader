"""Bounded read-only heartbeat probes, independent of repository migrations.

Liveness only: a healthy disabled/blocked collector never grants data or order
readiness. Opening a probe cannot create a database, disarm an account, take the
application writer/advisory lock, read provider credentials or issue an order.
"""
from contextlib import contextmanager
from datetime import datetime
import json
from pathlib import Path
import sqlite3

COLLECTOR_STATES = frozenset({'DISABLED', 'NO_ACTIVE_DEMAND', 'DEMAND_LIMIT_REACHED',
    'AUTH_BLOCKED', 'BACKOFF', 'SESSION_CLOSED', 'WAITING', 'COLLECTING_ANALYSIS_ONLY',
    'DATA_UNAVAILABLE'})


def heartbeat_valid(row, name, now):
    try:
        if row is None or now.tzinfo is None or now.utcoffset() is None:
            return False
        value = json.loads(row['payload'])
        at = datetime.fromisoformat(row['updated_at'])
        if not isinstance(value, dict) or at.tzinfo is None or at.utcoffset() is None:
            return False
        if name == 'worker':
            state_ok, seconds = value.get('status') == 'OK', 120
        elif name == 'market_collector':
            state_ok, seconds = value.get('state') in COLLECTOR_STATES, 30
        else:
            return False
        return state_ok and 0 <= (now - at).total_seconds() <= seconds
    except (KeyError, TypeError, ValueError, OverflowError):
        return False


@contextmanager
def readonly_connection(url):
    if url.startswith(('postgresql://', 'postgres://')):
        import psycopg
        from psycopg.rows import dict_row
        # Explicit keyword settings supersede URL options. Queries are bounded
        # even when another process holds DDL locks; no advisory lock is taken.
        connection = psycopg.connect(url, row_factory=dict_row, autocommit=True,
            connect_timeout=3, options='-c default_transaction_read_only=on -c statement_timeout=2000 -c lock_timeout=1000')
    elif url.startswith('sqlite:///') and url != 'sqlite:///:memory:':
        uri = Path(url.removeprefix('sqlite:///')).resolve().as_uri() + '?mode=ro'
        connection = sqlite3.connect(uri, uri=True, timeout=1)
        connection.row_factory = sqlite3.Row
        connection.execute('PRAGMA query_only=ON')
    else:
        raise ValueError('Unsupported health probe database')
    try:
        yield connection
    finally:
        connection.close()


def probe_heartbeat(url, name, now):
    if name not in {'worker', 'market_collector'}:
        return False
    try:
        with readonly_connection(url) as connection:
            placeholder = '%s' if url.startswith(('postgresql://', 'postgres://')) else '?'
            row = connection.execute('SELECT updated_at,payload FROM runtime_health WHERE name=' + placeholder,
                                     (name,)).fetchone()
            return heartbeat_valid(row, name, now)
    except Exception:
        # Health command returns only its exit status: no URL, credential,
        # database path or driver error is emitted or stored.
        return False
