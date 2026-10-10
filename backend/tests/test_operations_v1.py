"""Operations safeguards use temporary local fixtures, never external databases."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import stat
import subprocess
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import pytest


ROOT = Path(__file__).resolve().parents[2]


def module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


snapshots = module("backup_restore")
scanner = module("security_scan")


@pytest.fixture
def ledger(tmp_path):
    source = tmp_path / "source.db"
    connection = sqlite3.connect(source)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("CREATE TABLE balances(account TEXT PRIMARY KEY, cents INTEGER NOT NULL)")
    connection.executemany("INSERT INTO balances VALUES(?,?)", [("demo-a", 10000), ("demo-b", 20000)])
    connection.commit()
    yield source, connection
    connection.close()


def contents(path):
    with sqlite3.connect(path) as db:
        return db.execute("SELECT * FROM balances ORDER BY account").fetchall()


def test_online_backup_includes_committed_wal_and_restore_is_independent(ledger, tmp_path):
    source, connection = ledger
    assert Path(str(source) + "-wal").exists()
    snapshot, restored = tmp_path / "snapshot.db", tmp_path / "restored.db"
    manifest = snapshots.backup(source, snapshot)
    assert manifest["sha256"] == hashlib.sha256(snapshot.read_bytes()).hexdigest()
    assert stat.S_IMODE(snapshot.stat().st_mode) == 0o600
    assert stat.S_IMODE(snapshots.manifest_path(snapshot).stat().st_mode) == 0o600
    assert snapshots.verify(snapshot)["sha256"] == manifest["sha256"]
    connection.execute("UPDATE balances SET cents=999 WHERE account='demo-a'")
    connection.commit()
    result = snapshots.restore(snapshot, restored)
    assert result["restored_from_sha256"] == manifest["sha256"]
    assert contents(restored) == [("demo-a", 10000), ("demo-b", 20000)]
    assert contents(source)[0][1] == 999
    assert not list(tmp_path.glob(".oat-snapshot-*"))


def test_backup_does_not_include_uncommitted_write(ledger, tmp_path):
    source, connection = ledger
    connection.execute("UPDATE balances SET cents=123 WHERE account='demo-a'")
    snapshots.backup(source, tmp_path / "committed.db")
    assert contents(tmp_path / "committed.db")[0][1] == 10000
    connection.rollback()


@pytest.mark.parametrize("companion", ["", ".manifest.json", "-wal", "-shm", "-journal"])
def test_backup_refuses_existing_destination_or_sidecar(ledger, tmp_path, companion):
    source, _ = ledger
    destination = tmp_path / "occupied.db"
    occupied = Path(str(destination) + companion)
    occupied.write_bytes(b"preserve this exact existing file")
    before = occupied.read_bytes()
    with pytest.raises(snapshots.BackupError, match="already exists"):
        snapshots.backup(source, destination)
    assert occupied.read_bytes() == before


def test_restore_never_replaces_existing_database(ledger, tmp_path):
    source, _ = ledger
    snapshot = tmp_path / "snapshot.db"
    snapshots.backup(source, snapshot)
    before = source.read_bytes()
    with pytest.raises(snapshots.BackupError):
        snapshots.restore(snapshot, source)
    assert source.read_bytes() == before


def test_concurrent_backups_publish_one_complete_pair(ledger, tmp_path):
    source, _ = ledger
    target = tmp_path / "race.db"
    def operation():
        try:
            snapshots.backup(source, target)
            return True
        except snapshots.BackupError:
            return False
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: operation(), range(2)))
    assert results.count(True) == 1
    snapshots.verify(target)


@pytest.mark.parametrize("kind", ["bytes", "manifest", "missing", "symlink", "forged_integrity"])
def test_restore_refuses_tampering_without_creating_destination(ledger, tmp_path, kind):
    source, _ = ledger
    snapshot, restored = tmp_path / "snapshot.db", tmp_path / "new.db"
    snapshots.backup(source, snapshot)
    manifest_path = snapshots.manifest_path(snapshot)
    if kind == "bytes":
        snapshot.write_bytes(snapshot.read_bytes() + b"modified")
    elif kind == "manifest":
        manifest_path.write_text('{"version": true}')
    elif kind == "missing":
        manifest_path.unlink()
    elif kind == "symlink":
        manifest_path.unlink()
        manifest_path.symlink_to(source)
    else:
        snapshot.write_bytes(b"invalid database" * 500)
        manifest = json.loads(manifest_path.read_text())
        manifest.update(sha256=hashlib.sha256(snapshot.read_bytes()).hexdigest(), size_bytes=snapshot.stat().st_size)
        manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(snapshots.BackupError):
        snapshots.restore(snapshot, restored)
    assert not restored.exists()
    assert not snapshots.manifest_path(restored).exists()
    assert not list(tmp_path.glob(".oat-snapshot-*"))


def test_symlink_source_and_destination_are_refused(ledger, tmp_path):
    source, _ = ledger
    link = tmp_path / "source-link.db"
    link.symlink_to(source)
    with pytest.raises(snapshots.BackupError):
        snapshots.backup(link, tmp_path / "refused.db")
    destination = tmp_path / "destination.db"
    destination.symlink_to(tmp_path / "missing.db")
    with pytest.raises(snapshots.BackupError):
        snapshots.backup(source, destination)
    assert destination.is_symlink()


def test_foreign_key_violation_refuses_backup(tmp_path):
    source = tmp_path / "invalid.db"
    with sqlite3.connect(source) as db:
        db.execute("CREATE TABLE parent(id INTEGER PRIMARY KEY)")
        db.execute("CREATE TABLE child(parent_id INTEGER REFERENCES parent(id))")
        db.execute("INSERT INTO child VALUES(42)")
    with pytest.raises(snapshots.BackupError, match="foreign key"):
        snapshots.backup(source, tmp_path / "bad.db")
    assert not (tmp_path / "bad.db").exists()


def test_backup_cli_error_never_prints_data_or_paths(tmp_path, capsys):
    marker = "private-account-data"
    assert snapshots.main(["backup", str(tmp_path / marker), str(tmp_path / "output.db")]) == 2
    output = capsys.readouterr().out
    assert marker not in output
    assert json.loads(output)["ok"] is False


def test_restore_real_mock_ledger_keeps_four_accounts_and_requires_reconciliation(tmp_path):
    from app.repository import Repository
    from app.service import TradingService

    source, snapshot, restored = (tmp_path / name for name in ("app.db", "app-snapshot.db", "app-restored.db"))
    now = datetime(2026, 10, 10, 12, tzinfo=timezone.utc)
    request = dict(request_key="restore-fixture", symbol="NVDA", right="CALL", expiry="2026-10-23",
                   strike_cents=10000, side="BUY", quantity=1, limit_cents=105)
    repository = Repository("sqlite:///" + str(source))
    account_ids, order_ids = [], []
    try:
        service = TradingService(repository, today=lambda: now.date(), now=lambda: now)
        for index in range(4):
            account_id = service.create_account(f"backup-demo-{index}")["id"]
            service.watch(account_id, "NVDA", True)
            # Global risk needs explicit fresh quotes for each owned account.
            with repository.transaction() as db:
                service.record_option_mark(db,account_id,"NVDA","CALL","2026-10-23",10000,100,105,now)
            order = service.submit(account_id, request)
            service.fill(account_id, order["id"], f"restore-fill-{index}", 1, 100)
            account_ids.append(account_id)
            order_ids.append(order["id"])
        snapshots.backup(source, snapshot)
    finally:
        repository.close()
    snapshots.restore(snapshot, restored)
    recovered = Repository("sqlite:///" + str(restored))
    try:
        service = TradingService(recovered, today=lambda: now.date(), now=lambda: now)
        accounts = service.list_accounts()
        assert {account["id"] for account in accounts} == set(account_ids)
        assert all(not account["state_known"] for account in accounts)
        for account_id, order_id in zip(account_ids, order_ids):
            assert service.submit(account_id, request)["id"] == order_id
            assert len(service.rows(account_id, "orders")) == 1
            assert service.rows(account_id, "positions")[0]["quantity"] == 1
            assert service.reconcile(account_id)["resubmitted"] == 0
    finally:
        recovered.close()


def fake_github():
    return "gh" + "p_" + "A1b2C3d4" * 5


@pytest.mark.parametrize("name,value,rule", [
    ("github", fake_github(), "github_token"),
    ("aws", "AK" + "IA" + "A1" * 8, "aws_access_key"),
    ("pem", "-----BEGIN " + "PRIVATE KEY-----", "private_key"),
    ("openai", "sk-" + "proj-" + "Ab0_" * 15, "openai_key"),
    ("slack", "xox" + "b-" + "0123456789-" * 4, "slack_token"),
    ("db", "postgresql://demo:" + "strongPass123" + "@localhost/db", "credential_url"),
], ids=["github_fixture", "aws_fixture", "private_key_fixture", "openai_fixture", "slack_fixture", "database_fixture"])
def test_secret_patterns_are_redacted_even_in_test_files(name, value, rule):
    findings = scanner.scan_text("backend/tests/new_test.py", "one line\n" + value)
    assert any(row["rule"] == rule and row["line"] == 2 for row in findings)
    serialized = json.dumps(findings)
    assert value not in serialized
    assert name != serialized


def test_exact_fixture_exception_is_scoped_not_blanket():
    fixture = "test-token-at-least-32-characters-long"
    content = "TOKEN = '" + fixture + "'"
    assert scanner.scan_text("backend/tests/test_api.py", content) == []
    assert scanner.scan_text("app/config.py", content)
    assert scanner.scan_text("backend/tests/test_api.py", fake_github())


def test_secret_assignment_and_environment_placeholders():
    actual = "aB3!cD4_eF5-gH6IjK7LmN8OpQ9"
    assert scanner.scan_text("app/config.py", 'API_KEY="' + actual + '"')[0]["rule"] == "high_entropy_secret_assignment"
    assert scanner.scan_text("infra/.env.example", 'API_KEY="REPLACE_WITH_LOCALLY_GENERATED_TOKEN"') == []
    assert scanner.scan_text("infra/compose.yaml", "postgresql://trader:${POSTGRES_PASSWORD}@postgres/db") == []


def test_reviewed_documentation_fixture_exception_is_value_and_path_specific():
    content = (ROOT / "docs" / "DATABASE.md").read_text()
    assert scanner.scan_text("docs/DATABASE.md", content) == []
    assert scanner.scan_text("app/runtime-config.py", content)
    changed = "postgresql://demo:" + "aDifferentValue123" + "@localhost/db"
    assert scanner.scan_text("docs/DATABASE.md", changed)


@pytest.mark.parametrize("path", [".env", "infra/.env.local", "android/key.properties", "keys/signing.jks", "id_ed25519", "certs/server.pem"])
def test_sensitive_paths_flagged(path):
    assert scanner.path_findings(path, "HEAD")[0]["rule"] == "sensitive_file_path"
    assert not scanner.path_findings("infra/.env.example", "HEAD")


def git(repository, *args):
    return subprocess.run(["git", "-C", str(repository), *args], check=True, capture_output=True)


@pytest.fixture
def git_fixture(tmp_path):
    git(tmp_path, "init", "-q")
    git(tmp_path, "config", "user.name", "Offline Fixture")
    git(tmp_path, "config", "user.email", "fixture@example.invalid")
    return tmp_path


def test_current_scan_ignores_untracked_and_history_finds_removed_secret(git_fixture):
    root = git_fixture
    (root / "config.txt").write_text(fake_github())
    git(root, "add", "config.txt")
    git(root, "commit", "-qm", "synthetic scanner test")
    (root / "config.txt").write_text("no credential here")
    git(root, "commit", "-qam", "removed synthetic scanner fixture")
    (root / "untracked.txt").write_text(fake_github())
    current = scanner.scan_repository(root)
    assert not current["findings"]
    history = scanner.scan_repository(root, all_history=True)
    assert history["history_commits"] == 2
    assert any(row["path"] == "config.txt" and row["rule"] == "github_token" for row in history["findings"])
    assert fake_github() not in json.dumps(history)


def test_scanner_reports_opaque_and_oversized_content_and_refuses_symlink(git_fixture):
    root = git_fixture
    (root / "archive.bundle").write_bytes(b"opaque history")
    (root / "large.txt").write_bytes(b"A" * 500)
    (root / "link.txt").symlink_to(root / "large.txt")
    git(root, "add", "archive.bundle", "large.txt", "link.txt")
    report = scanner.scan_repository(root, max_bytes=100)
    assert {x["reason"] for x in report["skipped"]} == {"opaque_archive", "size_limit"}
    assert report["findings"][0]["rule"] == "unscanned_symlink"


def test_scanner_cli_failure_is_redacted(tmp_path, capsys):
    assert scanner.main(["--repository", str(tmp_path)]) == 2
    assert str(tmp_path) not in capsys.readouterr().out


def test_opt_in_https_has_loopback_only_binding_and_internal_ca():
    compose = (ROOT / "infra" / "compose.https.yaml").read_text()
    caddy = (ROOT / "infra" / "Caddyfile").read_text()
    assert '127.0.0.1:8443:8443' in compose
    assert 'profiles: ["local-https"]' in compose
    assert "tls internal" in caddy and "admin off" in caddy
    assert "skip_install_trust" in caddy
    assert "tls_insecure_skip_verify" not in caddy
    assert "acme" not in caddy.lower()
