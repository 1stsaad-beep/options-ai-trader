"""Migration/ledger preservation and database-level isolation guards."""
import sqlite3
import pytest
from app.repository import Repository
from app.migrations import SCHEMA


def seed_v02(path, orphan=False):
    con = sqlite3.connect(path)
    for sql in SCHEMA:
        con.execute(sql)
    con.execute("INSERT INTO accounts VALUES('kept','old','{}',1000000,0,1,0,'2026-10-09T00:00:00+00:00')")
    con.execute("INSERT INTO watchlist VALUES(?, 'NVDA',1,1)", ('missing' if orphan else 'kept',))
    con.commit()
    con.close()


def test_legacy_migration_preserves_ledger_and_locks_state(tmp_path):
    path = tmp_path / 'v02.db'
    seed_v02(path)
    repo = Repository(f'sqlite:///{path}')
    with repo.transaction() as db:
        assert db.one('SELECT * FROM accounts')['name'] == 'old'
        assert db.one('SELECT * FROM accounts')['state_known'] == 0
        assert db.one('SELECT * FROM watchlist')['enabled'] == 1
        assert [r['version'] for r in db.all('SELECT * FROM schema_migrations ORDER BY version')] == [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]
    repo.close()
    repo = Repository(f'sqlite:///{path}')
    with repo.transaction() as db:
        assert len(db.all('SELECT * FROM schema_migrations')) == 11
    repo.close()


def test_migration_rollback_for_unsafe_legacy_relationship(tmp_path):
    path = tmp_path / 'orphan.db'
    seed_v02(path, orphan=True)
    with pytest.raises(ValueError, match='orphan'):
        Repository(f'sqlite:///{path}')
    con = sqlite3.connect(path)
    assert con.execute('SELECT COUNT(*) FROM accounts').fetchone()[0] == 1
    assert con.execute("SELECT name FROM sqlite_master WHERE name='schema_migrations'").fetchone() is None
    con.close()


def test_database_prevents_orphan_market_and_ledger_rows():
    repo = Repository()
    for sql in ["INSERT INTO watchlist VALUES('other','NVDA',1,1)", "INSERT INTO market_snapshots VALUES('other','NVDA','now',1)", "INSERT INTO fills VALUES('f','missing',1,100,1,'2026-10-09')"]:
        with pytest.raises(sqlite3.IntegrityError):
            with repo.transaction() as db:
                db.execute(sql)
    repo.close()


def test_unknown_database_version_fails_closed(tmp_path):
    path = tmp_path / 'future.db'
    repo = Repository(f'sqlite:///{path}')
    with repo.transaction() as db:
        db.execute("INSERT INTO schema_migrations VALUES(999,'future','now')")
    repo.close()
    with pytest.raises(ValueError, match='incompatible'):
        Repository(f'sqlite:///{path}')


def test_account_delete_restricted_with_ledger_and_market():
    repo = Repository()
    with repo.transaction() as db:
        db.execute("INSERT INTO accounts VALUES('a','mock','{}',1000000,0,1,0,'now')")
        db.execute("INSERT INTO market_snapshots VALUES('a','NVDA','now',1)")
    with pytest.raises(sqlite3.IntegrityError):
        with repo.transaction() as db:
            db.execute("DELETE FROM accounts WHERE id='a'")
    repo.close()


def test_legacy_balance_baseline_once_and_balance_tamper_rejected(tmp_path):
    import json
    from app.service import TradingService, Rejected, DEFAULT_CONFIG
    path = tmp_path / 'legacy-balance.db'
    seed_v02(path)
    con = sqlite3.connect(path)
    con.execute('UPDATE accounts SET config=?', (json.dumps(DEFAULT_CONFIG),))
    con.execute("INSERT INTO audit VALUES('old-create','kept','ACCOUNT_CREATED','{\"broker\":\"mock\"}','2026-10-09T00:00:00+00:00')")
    con.commit()
    con.close()
    repo = Repository(f'sqlite:///{path}')
    service = TradingService(repo)
    assert service.reconcile('kept')['state_known']
    with repo.transaction() as db:
        events = db.all("SELECT detail FROM audit WHERE event='MIGRATION_BALANCE_BASELINE'")
        assert len(events) == 1
        assert json.loads(events[0]['detail']) == {'initial_equity_cents': 1000000, 'source': 'local_v02_import_unverified'}
        assert db.one("SELECT id FROM audit WHERE id='old-create'") is not None
        db.execute("UPDATE accounts SET equity=2000000 WHERE id='kept'")
    with pytest.raises(Rejected, match='provenance'):
        service.reconcile('kept')
    repo.close()
    repo = Repository(f'sqlite:///{path}')
    with repo.transaction() as db:
        assert len(db.all("SELECT * FROM audit WHERE event='MIGRATION_BALANCE_BASELINE'")) == 1
    with pytest.raises(Rejected, match='provenance'):
        TradingService(repo).reconcile('kept')
    repo.close()


def test_migration_keeps_existing_v03_creation_provenance(tmp_path):
    import json
    path = tmp_path / 'already-provenance.db'
    seed_v02(path)
    con = sqlite3.connect(path)
    detail = json.dumps({'initial_equity_cents': 1000000, 'broker': 'mock'})
    con.execute("INSERT INTO audit VALUES('create','kept','ACCOUNT_CREATED',?,'now')", (detail,))
    con.commit()
    con.close()
    repo = Repository(f'sqlite:///{path}')
    with repo.transaction() as db:
        assert db.all("SELECT * FROM audit WHERE event='MIGRATION_BALANCE_BASELINE'") == []
        assert db.one("SELECT detail FROM audit WHERE id='create'")['detail'] == detail
    repo.close()
