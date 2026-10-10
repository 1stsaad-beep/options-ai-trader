"""A small DB-API repository; all safety changes occur in one transaction.

SQLite is the isolated demo/test backend. PostgreSQL is selected by DATABASE_URL.
PostgreSQL advisory transaction locking serializes risk admission across workers.
"""
import json
import sqlite3
import threading
from contextlib import contextmanager

from .migrations import SCHEMA, migrate

class Repository:
    def __init__(self, url='sqlite:///:memory:'):
        self.lock = threading.RLock()
        self.postgres = url.startswith(('postgresql://', 'postgres://'))
        if self.postgres:
            import psycopg
            from psycopg.rows import dict_row
            self.connection = psycopg.connect(url, row_factory=dict_row)
        else:
            path = url.removeprefix('sqlite:///')
            self.connection = sqlite3.connect(path, check_same_thread=False)
            self.connection.row_factory = sqlite3.Row
            self.connection.execute('PRAGMA foreign_keys=ON')
            self.connection.execute('PRAGMA busy_timeout=5000')
            self.connection.execute('PRAGMA journal_mode=WAL')
        try:
            with self.transaction() as db:
                migrate(db, self.postgres)
                db.execute('UPDATE accounts SET state_known=0')
        except BaseException:
            self.connection.close()
            raise

    @contextmanager
    def transaction(self):
        with self.lock:
            try:
                if self.postgres:
                    self.connection.execute('SELECT pg_advisory_xact_lock(82741639)')
                else:
                    self.connection.execute('BEGIN IMMEDIATE')
                yield Session(self.connection, self.postgres)
                self.connection.commit()
            except BaseException:
                self.connection.rollback()
                raise

    def close(self):
        self.connection.close()

class Session:
    def __init__(self, connection, postgres):
        self.connection, self.postgres = connection, postgres
    def execute(self, sql, parameters=()):
        return self.connection.execute(sql.replace('?', '%s') if self.postgres else sql, parameters)
    def one(self, sql, parameters=()):
        row = self.execute(sql, parameters).fetchone()
        return dict(row) if row is not None else None
    def all(self, sql, parameters=()):
        return [dict(row) for row in self.execute(sql, parameters).fetchall()]
