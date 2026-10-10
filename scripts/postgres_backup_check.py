"""Opt-in local disposable PostgreSQL backup/restore round trip.

Creates a unique least-privilege fixture role and two fixture databases, then
removes only those fixtures. Never use against a production database/server.
"""
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import tempfile
from urllib.parse import quote
import uuid

import psycopg
from psycopg import sql

import postgres_backup_restore as snapshots

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.repository import Repository
from app.service import TradingService


def _url(connection, database):
    host = f"[{connection.host}]" if ":" in connection.host else connection.host
    return (f"postgresql://{quote(connection.user, safe='')}:{quote(connection.password, safe='')}@"
            f"{host}:{connection.port}/{database}?sslmode={connection.sslmode}")


def _client_major(tool):
    result = subprocess.run([snapshots._executable(tool), "--version"], stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=15,
                            env=snapshots._offline_environment(), check=True, text=True)
    matched = re.search(r"PostgreSQL\) (\d+)\.", result.stdout)
    if not matched:
        raise snapshots.BackupError("Could not identify PostgreSQL client version")
    return int(matched.group(1))


def run():
    if os.environ.get("TEST_DATABASE_ALLOW_DISPOSABLE") != "1":
        raise snapshots.BackupError("Explicit disposable database acknowledgement required")
    admin = snapshots.Connection.from_env("TEST_DATABASE_URL")
    if admin.host not in snapshots.LOCAL_HOSTS:
        raise snapshots.BackupError("Only a local/container disposable PostgreSQL server is allowed")
    nonce = uuid.uuid4().hex[:16]
    role, source_name, restored_name = "oat_backup_" + nonce, "oat_backup_fixture_" + nonce, "oat_restore_" + nonce
    role_created, created_databases, repository = False, [], None
    checks = []
    password = secrets.token_urlsafe(36)
    fixture = snapshots.Connection(admin.host, admin.port, role, password, source_name, admin.sslmode, admin.sslrootcert)
    now = datetime.now(timezone.utc)
    expiry = now.date() + timedelta(days=14)
    expiry += timedelta(days=(4 - expiry.weekday()) % 7)
    accounts, orders = [], []
    with psycopg.connect(**admin.kwargs(), autocommit=True) as manager:
        try:
            major = int(manager.execute("SHOW server_version_num").fetchone()[0]) // 10000
            if any(_client_major(tool) != major for tool in ("pg_dump", "pg_restore")):
                raise snapshots.BackupError("Use pg_dump and pg_restore with the same major version as the CI server")
            checks.append("matching_postgresql_client_and_server_versions")
            manager.execute(sql.SQL("CREATE ROLE {} LOGIN CREATEDB NOSUPERUSER NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD {}")
                            .format(sql.Identifier(role), sql.Literal(password)))
            role_created = True
            manager.execute(sql.SQL("CREATE DATABASE {} OWNER {} TEMPLATE template0")
                            .format(sql.Identifier(source_name), sql.Identifier(role)))
            created_databases.append(source_name)
            repository = Repository(_url(fixture, source_name))
            service = TradingService(repository, today=lambda: now.date(), now=lambda: now)
            for index in range(4):
                account = service.create_account("restore-fixture-" + str(index))["id"]
                service.watch(account, "NVDA", True)
                with repository.transaction() as db:
                    service.record_option_mark(db, account, "NVDA", "CALL", expiry.isoformat(), 15000, 50, 55, now)
                order = service.submit(account, {"request_key": "restore-order-" + str(index), "symbol": "NVDA",
                                                "right": "CALL", "side": "BUY", "expiry": expiry.isoformat(),
                                                "strike_cents": 15000, "quantity": 1, "limit_cents": 55})
                service.fill(account, order["id"], "restore-fill-" + str(index), 1, 50)
                accounts.append(account)
                orders.append(order["id"])
            with tempfile.TemporaryDirectory(prefix="oat-postgres-roundtrip-") as temporary:
                archive = Path(temporary) / "ledger.dump"
                metadata = snapshots.backup(fixture, archive)
                assert snapshots.verify(archive)["sha256"] == metadata["sha256"]
                checks.append("custom_dump_checksum_and_offline_verification")
                service.create_account("after-snapshot-account")
                assert len(service.list_accounts()) == 5
                checks.append("source_changes_after_snapshot_are_independent")
                try:
                    snapshots.restore(fixture, archive, restored_name, trusted_archive=True)
                finally:
                    # Register only this run's never-before-existing target if
                    # creation succeeded but restore subsequently failed.
                    exists = manager.execute("SELECT 1 FROM pg_database WHERE datname=%s", (restored_name,)).fetchone()
                    if exists:
                        created_databases.append(restored_name)
                checks.append("non_superuser_restore_to_new_database_only")
                try:
                    snapshots.restore(fixture, archive, restored_name, trusted_archive=True)
                except snapshots.BackupError:
                    pass
                else:
                    raise AssertionError("Existing restore database was overwritten")
                checks.append("second_restore_refuses_existing_target")
                with psycopg.connect(**fixture.kwargs(restored_name)) as restored:
                    assert {row[0] for row in restored.execute("SELECT id FROM accounts")} == set(accounts)
                    assert {row[0] for row in restored.execute("SELECT id FROM orders")} == set(orders)
                    assert restored.execute("SELECT COUNT(*) FROM positions WHERE quantity=1").fetchone()[0] == 4
                    assert restored.execute("SELECT COUNT(*) FROM fills").fetchone()[0] == 4
                    assert restored.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0] >= 4
                    assert restored.execute("SELECT COUNT(*) FROM pg_constraint WHERE contype='f' AND NOT convalidated").fetchone()[0] == 0
                    checks.append("four_account_ledger_fills_positions_migrations_and_validated_constraints_restored")
                    snapshot_id = restored.execute("SELECT id FROM decision_snapshots LIMIT 1").fetchone()[0]
                    try:
                        restored.execute("UPDATE decision_snapshots SET payload=payload WHERE id=%s", (snapshot_id,))
                    except psycopg.Error as error:
                        assert "immutable" in str(error)
                        restored.rollback()
                    else:
                        raise AssertionError("Immutable decision guard missing after restore")
                    try:
                        restored.execute("DELETE FROM accounts WHERE id=%s", (accounts[0],))
                    except psycopg.errors.ForeignKeyViolation:
                        restored.rollback()
                    else:
                        raise AssertionError("Restored account ownership foreign keys not enforced")
                    checks.append("restored_immutable_decisions_and_account_foreign_keys_enforced")
                recovered_repository = Repository(_url(fixture, restored_name))
                try:
                    recovered = TradingService(recovered_repository, today=lambda: now.date(), now=lambda: now)
                    assert all(not row["state_known"] for row in recovered.list_accounts())
                    for account in accounts:
                        assert recovered.reconcile(account)["resubmitted"] == 0
                        assert len(recovered.rows(account, "orders")) == 1
                    checks.append("application_invalidates_account_trust_and_reconciles_without_resubmission")
                finally:
                    recovered_repository.close()
                archive.write_bytes(archive.read_bytes() + b"tampered")
                try:
                    snapshots.restore(fixture, archive, "oat_restore_corrupt_" + nonce, trusted_archive=True)
                except snapshots.BackupError:
                    assert not manager.execute("SELECT 1 FROM pg_database WHERE datname=%s", ("oat_restore_corrupt_" + nonce,)).fetchone()
                else:
                    raise AssertionError("Corrupt archive accepted")
                checks.append("tampered_archive_rejected_before_database_creation")
        finally:
            if repository:
                repository.close()
            # Fixtures are created above with this run's random names. No
            # database from TEST_DATABASE_URL or pre-existing name is dropped.
            for name in reversed(created_databases):
                manager.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(name)))
            if role_created:
                manager.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role)))
    checks.append("only_owned_disposable_fixtures_cleaned_up")
    return {"status": "passed", "checks_passed": len(checks), "checks_failed": 0, "checks": checks,
            "database": "PostgreSQL", "postgresql_major": major, "broker": "none", "data": "synthetic"}


if __name__ == "__main__":
    try:
        print(json.dumps(run(), indent=2))
    except (snapshots.BackupError, psycopg.Error, OSError, AssertionError, subprocess.SubprocessError):
        print(json.dumps({"status": "failed", "error": "Disposable PostgreSQL backup/restore check failed; database details and credentials redacted"}))
        raise SystemExit(1)
