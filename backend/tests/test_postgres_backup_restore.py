"""PostgreSQL archive safety tests; server round trip is a separate CI check."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
from types import SimpleNamespace

import psycopg
import pytest


ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("postgres_snapshots", ROOT / "scripts/postgres_backup_restore.py")
snapshots = importlib.util.module_from_spec(spec)
spec.loader.exec_module(snapshots)


@pytest.fixture
def connection():
    return snapshots.Connection("localhost", 5432, "fixture_role", "fixture:password\\only", "fixture_db", "disable")


@pytest.fixture
def archive(tmp_path):
    target = tmp_path / "fixture.dump"
    target.write_bytes(b"PGDMP" + b"synthetic custom format stand-in" * 20)
    metadata = {"format": snapshots.FORMAT, "version": 1, "created_utc": datetime.now(timezone.utc).isoformat(),
                "sha256": hashlib.sha256(target.read_bytes()).hexdigest(), "size_bytes": target.stat().st_size}
    snapshots.manifest_path(target).write_text(json.dumps(metadata))
    return target


@pytest.fixture
def client(monkeypatch):
    calls = []
    monkeypatch.setattr(snapshots, "_executable", lambda name: name)
    def run(arguments, **kwargs):
        calls.append((arguments, kwargs))
        if arguments[0] == "pg_dump":
            path = Path(next(value.removeprefix("--file=") for value in arguments if value.startswith("--file=")))
            path.write_bytes(b"PGDMP" + b"synthetic pg_dump result" * 20)
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(snapshots.subprocess, "run", run)
    return calls


class Database:
    def __init__(self, *, role=(False, False, False, False, True), exists=False, nonempty=False, fail_create=False):
        self.role, self.exists, self.nonempty, self.fail_create = role, exists, nonempty, fail_create
        self.statements = []
        self.row = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, statement, parameters=None):
        rendered = statement.as_string() if hasattr(statement, "as_string") else statement
        self.statements.append((rendered, parameters))
        if rendered.startswith("SELECT rolsuper"):
            self.row = self.role
        elif rendered.startswith("SELECT 1 FROM pg_database"):
            self.row = (1,) if self.exists else None
        elif rendered.startswith("SELECT 1 FROM pg_class"):
            self.row = (1,) if self.nonempty else None
        elif rendered.startswith("CREATE DATABASE"):
            if self.fail_create:
                raise psycopg.errors.DuplicateDatabase("private database data")
            self.exists = True
        return self

    def fetchone(self):
        return self.row


@pytest.fixture
def database(monkeypatch):
    db = Database()
    monkeypatch.setattr(snapshots, "_connect", lambda *args, **kwargs: db)
    return db


def test_credentials_are_private_escaped_removed_and_never_forwarded(connection, tmp_path, monkeypatch):
    monkeypatch.setenv("PGPASSWORD", "inherited secret")
    monkeypatch.setenv("PGOPTIONS", "hostile inherited configuration")
    monkeypatch.setenv("EXTERNAL_API_TOKEN", "unrelated inherited secret")
    with snapshots._credentials(connection, tmp_path, "oat_restore_test") as environment:
        password_file = Path(environment["PGPASSFILE"])
        assert stat.S_IMODE(password_file.stat().st_mode) == 0o600
        assert password_file.read_text() == "localhost:5432:oat_restore_test:fixture_role:fixture\\:password\\\\only\n"
        assert "PGPASSWORD" not in environment and "EXTERNAL_API_TOKEN" not in environment
        assert "hostile" not in environment["PGOPTIONS"]
        assert connection.password not in repr(connection)
    assert not password_file.exists()


@pytest.mark.parametrize("value", [
    "", "file:///tmp/database", "postgresql://user@localhost/db", "postgresql://user:p@localhost/db?options=-c_bad",
    "postgresql://user:p@localhost/db?sslmode=disable&sslmode=verify-full", "postgresql://user:p@remote.invalid/db?sslmode=disable",
    "postgresql://user:p@remote.invalid/db?sslmode=require", "postgresql://user:p@localhost:99999/db",
    "postgresql://user:p@localhost/db?service=other", "postgresql://user:p%0Ax@localhost/db",
    "postgresql://user:p@localhost/db/name", "postgresql://user:p@localhost/db#fragment",
], ids=["missing", "wrong_scheme", "missing_password", "options_injection", "duplicate_query", "remote_plaintext", "remote_unverified_tls", "bad_port", "service_override", "password_newline", "dbname_path", "fragment"])
def test_invalid_or_ambiguous_connection_configuration_refused(value):
    with pytest.raises(snapshots.BackupError):
        snapshots.Connection.from_env(environ={"OAT_POSTGRES_URL": value})


def test_remote_connection_defaults_to_certificate_and_hostname_verification():
    connection = snapshots.Connection.from_env(environ={"OAT_POSTGRES_URL": "postgresql://fixture_role:p@remote.invalid/fixture"})
    assert connection.sslmode == "verify-full"
    assert connection.kwargs()["sslmode"] == "verify-full"


def test_backup_publishes_private_checksums_and_verify_is_offline(connection, tmp_path, client):
    path = tmp_path / "snapshot.dump"
    metadata = snapshots.backup(connection, path)
    assert metadata["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert snapshots.verify(path) == metadata
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(snapshots.manifest_path(path).stat().st_mode) == 0o600
    assert not list(tmp_path.glob(".oat-pg-backup-*"))
    for arguments, options in client:
        assert connection.password not in repr(arguments)
        assert options["stdin"] is subprocess.DEVNULL and options["shell"] is False
        assert options["stderr"] is subprocess.DEVNULL
    assert all("--dbname=" not in " ".join(args) for args, _ in client if args[0] == "pg_restore")


@pytest.mark.parametrize("companion", ["", ".manifest.json"])
def test_existing_archive_or_manifest_preserved(connection, tmp_path, client, companion):
    target = tmp_path / "existing.dump"
    occupied = Path(str(target) + companion)
    occupied.write_bytes(b"preserve existing")
    with pytest.raises(snapshots.BackupError, match="already exists"):
        snapshots.backup(connection, target)
    assert occupied.read_bytes() == b"preserve existing" and not client


def test_nonprivate_archive_directory_refused(connection, tmp_path, client):
    directory = tmp_path / "public"
    directory.mkdir(mode=0o755)
    with pytest.raises(snapshots.BackupError, match="private"):
        snapshots.backup(connection, directory / "new.dump")
    assert not client


def test_concurrent_backup_preserves_one_complete_archive_pair(connection, tmp_path, client):
    target = tmp_path / "shared.dump"
    def attempt(_):
        try:
            snapshots.backup(connection, target)
            return True
        except snapshots.BackupError:
            return False
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(attempt, range(2))).count(True) == 1
    snapshots.verify(target)


@pytest.mark.parametrize("change", ["bytes", "sha", "boolean_size", "boolean_version", "unknown_field", "naive_time", "symlink_manifest", "symlink_archive", "oversized_manifest", "not_custom"])
def test_tampered_or_untrusted_manifest_refused_before_any_database_access(archive, connection, client, database, change):
    manifest = snapshots.manifest_path(archive)
    value = json.loads(manifest.read_text())
    if change == "bytes":
        archive.write_bytes(archive.read_bytes() + b"changed")
    elif change == "sha":
        value["sha256"] = "a" * 64
    elif change == "boolean_size":
        value["size_bytes"] = True
    elif change == "boolean_version":
        value["version"] = True
    elif change == "unknown_field":
        value["command"] = "untrusted instruction"
    elif change == "naive_time":
        value["created_utc"] = "2026-10-10T00:00:00"
    elif change.startswith("symlink"):
        selected = manifest if change == "symlink_manifest" else archive
        held = selected.with_suffix(".held")
        selected.rename(held)
        selected.symlink_to(held)
    elif change == "oversized_manifest":
        manifest.write_bytes(b" " * 17000)
    elif change == "not_custom":
        archive.write_bytes(b"plain SQL that must never be executed")
        value["sha256"] = hashlib.sha256(archive.read_bytes()).hexdigest()
        value["size_bytes"] = archive.stat().st_size
    if change not in {"symlink_manifest", "symlink_archive", "oversized_manifest"}:
        manifest.write_text(json.dumps(value))
    with pytest.raises(snapshots.BackupError):
        snapshots.restore(connection, archive, "oat_restore_rejected", trusted_archive=True)
    assert not database.statements and not client


def test_restore_requires_trusted_archive_acknowledgement(archive, connection, database, client):
    with pytest.raises(snapshots.BackupError, match="trusted"):
        snapshots.restore(connection, archive, "oat_restore_test")
    assert not database.statements and not client


def test_duplicate_manifest_keys_are_rejected(archive, connection, database, client):
    path = snapshots.manifest_path(archive)
    path.write_text(path.read_text().replace('"version": 1', '"version": 0, "version": 1'))
    with pytest.raises(snapshots.BackupError):
        snapshots.restore(connection, archive, "oat_restore_duplicate", trusted_archive=True)
    assert not database.statements and not client


@pytest.mark.parametrize("timeout", [0, -1, 3601, True])
def test_invalid_timeout_cannot_create_database(archive, connection, database, client, timeout):
    with pytest.raises(snapshots.BackupError):
        snapshots.restore(connection, archive, "oat_restore_timeout", trusted_archive=True, timeout=timeout)
    assert not database.statements and not client


@pytest.mark.parametrize("target", ["fixture_db", "postgres", "template1", "oat_restore_", "oat_restore_a;DROP DATABASE", "oat_restore_" + "a" * 51])
def test_target_must_be_a_new_isolated_name(archive, connection, database, client, target):
    with pytest.raises(snapshots.BackupError):
        snapshots.restore(connection, archive, target, trusted_archive=True)
    assert not database.statements and not client


@pytest.mark.parametrize("role", [(True, False, False, False, True), (False, True, False, False, True),
                                  (False, False, True, False, True), (False, False, False, True, True),
                                  (False, False, False, False, False), None],
                         ids=["superuser", "create_role", "replication", "bypass_rls", "no_create_db", "missing_role"])
def test_elevated_or_unsuitable_restore_role_refused(archive, connection, database, client, role):
    database.role = role
    with pytest.raises(snapshots.BackupError, match="non-superuser"):
        snapshots.restore(connection, archive, "oat_restore_test", trusted_archive=True)
    assert not any(statement.startswith("CREATE") for statement, _ in database.statements)
    assert not any("--single-transaction" in args for args, _ in client)


def test_existing_target_database_is_never_modified(archive, connection, database, client):
    database.exists = True
    with pytest.raises(snapshots.BackupError, match="already exists"):
        snapshots.restore(connection, archive, "oat_restore_existing", trusted_archive=True)
    assert all(statement.startswith("SELECT") for statement, _ in database.statements)
    assert not any("--single-transaction" in args for args, _ in client)


def test_creation_race_does_not_drop_database_or_execute_restore(archive, connection, database, client):
    database.fail_create = True
    with pytest.raises(snapshots.BackupError, match="preserved"):
        snapshots.restore(connection, archive, "oat_restore_race", trusted_archive=True)
    assert not any("DROP" in statement for statement, _ in database.statements)
    assert not any("--single-transaction" in args for args, _ in client)


def test_nonempty_new_target_stops_before_restore(archive, connection, database, client):
    database.nonempty = True
    with pytest.raises(snapshots.BackupError, match="not empty"):
        snapshots.restore(connection, archive, "oat_restore_changed", trusted_archive=True)
    assert not any("--single-transaction" in args for args, _ in client)
    assert not any("DROP" in statement for statement, _ in database.statements)


def test_restore_uses_private_verified_copy_single_transaction_and_no_public_connections(archive, connection, database, client, monkeypatch):
    original_create = snapshots._create_new_database
    def mutate_input_then_create(*args):
        archive.write_bytes(b"untrusted changes after verification")
        original_create(*args)
    monkeypatch.setattr(snapshots, "_create_new_database", mutate_input_then_create)
    result = snapshots.restore(connection, archive, "oat_restore_isolated", trusted_archive=True)
    arguments = next(args for args, _ in client if "--single-transaction" in args)
    assert arguments[-1] != str(archive)
    assert "--clean" not in arguments and "--create" not in arguments
    assert "--dbname=oat_restore_isolated" in arguments
    assert result["requires_application_reconciliation"] is True
    statements = [value for value, _ in database.statements]
    create_index = next(i for i, value in enumerate(statements) if value.startswith("CREATE"))
    assert "ALLOW_CONNECTIONS false" in statements[create_index]
    assert "REVOKE ALL" in statements[create_index + 1]
    assert "ALLOW_CONNECTIONS true" in statements[create_index + 2]


def test_restore_client_failure_never_drops_created_database(archive, connection, database, client, monkeypatch):
    original = snapshots._run
    def fail_restore(arguments, **kwargs):
        if "--single-transaction" in arguments:
            raise snapshots.BackupError("restore failed")
        return original(arguments, **kwargs)
    monkeypatch.setattr(snapshots, "_run", fail_restore)
    with pytest.raises(snapshots.BackupError):
        snapshots.restore(connection, archive, "oat_restore_failed", trusted_archive=True)
    assert database.exists
    assert not any("DROP" in statement for statement, _ in database.statements)


def test_client_timeout_and_cli_errors_are_redacted(connection, archive, client, monkeypatch, capsys):
    marker = "private-password-account-and-sql"
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(marker, 5, output=marker, stderr=marker)
    monkeypatch.setattr(snapshots.subprocess, "run", timeout)
    with pytest.raises(snapshots.BackupError) as error:
        snapshots._run(["pg_restore", marker])
    assert marker not in str(error.value)
    assert snapshots.main(["verify", str(archive)]) == 2
    output = capsys.readouterr().out
    assert marker not in output and str(archive) not in output
    assert json.loads(output)["ok"] is False
