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
from types import SimpleNamespace
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
    now = datetime(2026,10,13,15,5,tzinfo=timezone.utc)  # Deterministic US option session fixture.
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
                account = service.create_account("restore-fixture-" + str(index),3000000 if index==3 else 1000000)["id"]
                if index==3:
                    service.configure(account,{'session_policy':'us_equity_options_2026_2027'})
                service.watch(account, "NVDA", True)
                with repository.transaction() as db:
                    service.record_option_mark(db, account, "NVDA", "CALL", expiry.isoformat(), 15000, 50, 55, now)
                order = service.submit(account, {"request_key": "restore-order-" + str(index), "symbol": "NVDA",
                                                "right": "CALL", "side": "BUY", "expiry": expiry.isoformat(),
                                                "strike_cents": 15000, "quantity": 1, "limit_cents": 55})
                service.fill(account, order["id"], "restore-fill-" + str(index), 1, 50)
                accounts.append(account)
                orders.append(order["id"])
            settlement_request=dict(id='backup-exercise',action='EXERCISE',
                contract='NVDA'+expiry.strftime('%y%m%d')+'C00150000',quantity=1,feeCents=0,underlyingCents=15500,
                effectiveAt=now.isoformat(),recordedAt=now.isoformat(),source='fixture',reference='backup-fixture')
            settlement_result=service.settle_paper(accounts[3],settlement_request)
            from market_data_journal_check import fixture as market_journal_fixture
            from app import market_data_journal as journal
            from unittest.mock import patch
            provider, journal_time = market_journal_fixture()
            with patch.object(journal, 'utc_now', lambda: journal_time):
                saved_market = journal.capture(service, accounts[0], {
                    'kind': 'stock_snapshot', 'symbol': 'AAPL', 'request_key': 'backup-journal'}, provider)
            from app import market_runtime as runtime
            runtime_config = runtime.configure(service, accounts[0], expected_version=0, enabled=True,
                                               strategies={'breakout': True, 'pullback': False})
            runtime_event = runtime.events(service, accounts[0])['items'][0]
            runtime.acknowledge(service, accounts[0], runtime_event['id'])
            with repository.transaction() as db:
                db.execute('INSERT INTO market_runtime_latest VALUES(?,?,?,?,?)',
                    (accounts[0], 'AAPL', 'stock_snapshot', saved_market['id'], 'FRESH_IEX_TRADE'))
                coordinator = runtime.coordinator_in(db)
                coordinator.update(auth_blocked=True, requests=[journal.utc(journal_time)],
                                   retry_at=journal.utc(journal_time+timedelta(seconds=180)))
                runtime.save_coordinator(db, coordinator)
            saved_runtime_events = runtime.events(service, accounts[0])
            from app.observed_paper_store import ObservedPaperStore
            from observed_paper_check import seed as seed_observed, observation as observed_input
            observed=ObservedPaperStore(repository,lambda:now)
            seed_observed(observed,'backup-observed')
            observed_lease=observed.acquire('backup-observed-worker')
            observed.command('backup-observed','entry',{'kind':'CYCLE','observation':observed_input(now)},expected_version=2,lease=observed_lease)
            observed.command('backup-observed','close',{'kind':'REQUEST_CLOSE','symbol':'NVDA'})
            observed.command('backup-observed','stop',{'kind':'ENABLE','enabled':False})
            saved_observed=observed.snapshot('backup-observed',full=True)
            saved_observed_events=observed.events('backup-observed')
            from app.observed_paper_data import ObservedPaperData
            from app.market_data import DataResponse
            coverage=ObservedPaperData(observed,SimpleNamespace(get=lambda *_:DataResponse(200,{}, {'quotes':{}})))
            assert coverage.capture([saved_observed['state']],observed_lease)['quotes']==[]
            with repository.transaction() as db: saved_capture_cursor=ObservedPaperData._cursor(db)
            observed.release(observed_lease)
            from app.observed_paper_runtime import ObservedPaperRuntime
            from app.observed_paper_alerts import page as alert_page, acknowledge as alert_ack
            alert_worker=ObservedPaperRuntime(observed)
            alert_worker.tick(); alert_worker.close()
            first_alert=alert_page(observed)['events'][0]
            alert_ack(observed,first_alert['sequence'],first_alert['eventHash'],0)
            saved_alerts=alert_page(observed,after=0)
            with tempfile.TemporaryDirectory(prefix="oat-postgres-roundtrip-") as temporary:
                archive = Path(temporary) / "ledger.dump"
                metadata = snapshots.backup(fixture, archive)
                assert snapshots.verify(archive)["sha256"] == metadata["sha256"]
                checks.append("custom_dump_checksum_and_offline_verification")
                service.create_account("after-snapshot-account")
                assert len(service.list_accounts()) == 5
                checks.append("source_changes_after_snapshot_are_independent")
                from app import market_archive as market_archiver
                with patch.object(journal, 'utc_now', lambda: journal_time):
                    late_market = journal.capture(service, accounts[0], {
                        'kind': 'stock_snapshot', 'symbol': 'AAPL', 'request_key': 'post-backup-market'}, provider)
                with repository.transaction() as db:
                    runtime.event_in(db, accounts[0], 'post-backup-event', now, 'OBSERVATION_ANALYZED',
                        {'observation_id': late_market['id'], 'source': 'synthetic_fixture'})
                market_export = Path(temporary) / 'market-observations.jsonl'
                # Use the real export clock; original event/capture times remain untouched.
                market_manifest = market_archiver.export(service, accounts[0], market_export)
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
                    assert restored.execute("SELECT COUNT(*) FROM positions WHERE quantity=1").fetchone()[0] == 3
                    assert restored.execute("SELECT COUNT(*) FROM fills").fetchone()[0] == 4
                    assert restored.execute("SELECT COUNT(*) FROM fill_receipt_times").fetchone()[0] == 4
                    assert restored.execute("SELECT quantity,cost FROM paper_delivery_positions").fetchone() == (100,1505000)
                    assert restored.execute("SELECT COUNT(*) FROM paper_settlement_receipts").fetchone()[0] == 1
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
                    recovered_observed=ObservedPaperStore(recovered_repository,lambda:now)
                    assert recovered_observed.snapshot('backup-observed',full=True)==saved_observed
                    assert recovered_observed.events('backup-observed')==saved_observed_events
                    with recovered_repository.transaction() as db: assert ObservedPaperData._cursor(db)==saved_capture_cursor
                    checks.append('bounded_capture_rotation_cursor_restored_without_invented_quotes')
                    assert alert_page(recovered_observed,after=0)==saved_alerts
                    assert alert_page(recovered_observed)['after']==first_alert['sequence']
                    for statement in ('UPDATE observed_alert_events SET payload=payload','DELETE FROM observed_alert_events'):
                        try:
                            with recovered_repository.transaction() as db: db.execute(statement)
                        except psycopg.Error as error: assert 'immutable' in str(error)
                        else: raise AssertionError('Restored alert guard missing')
                    checks.append('observed_alert_original_chain_ack_unread_and_immutable_guards_restored')
                    assert saved_observed['state']['positions']['NVDA']['closeIntent']['quantity']==3
                    checks.append('observed_virtual_balance_original_inputs_pending_close_segments_and_replay_restored')
                    try:
                        with recovered_repository.transaction() as db:
                            db.execute("UPDATE observed_paper_events SET payload=payload WHERE account_id='backup-observed'")
                    except psycopg.Error as error:
                        assert 'immutable' in str(error)
                    else:
                        raise AssertionError('Observed event guard missing after restore')
                    with patch.object(journal, 'utc_now', lambda: journal_time):
                        assert journal.replay(recovered, accounts[0], saved_market['id']) == saved_market
                    checks.append('market_journal_exact_payload_hash_and_receipt_restored')
                    for statement in ('UPDATE market_data_journal SET payload=payload WHERE id=?',
                                      'DELETE FROM market_data_journal WHERE id=?'):
                        try:
                            with recovered_repository.transaction() as db:
                                db.execute(statement, (saved_market['id'],))
                        except psycopg.Error as error:
                            assert 'immutable' in str(error)
                        else:
                            raise AssertionError('Restored market journal immutable guard missing')
                    checks.append('restored_market_journal_update_delete_guards')
                    assert runtime.events(recovered, accounts[0]) == saved_runtime_events
                    with recovered_repository.transaction() as db:
                        config = runtime.config_in(db, accounts[0])
                        assert config['version'] == runtime_config['version']
                        assert config['enabled'] is True
                        assert runtime.coordinator_in(db) == coordinator
                        assert db.one('SELECT observation_id FROM market_runtime_latest WHERE account_id=?', (accounts[0],))['observation_id'] == saved_market['id']
                    checks.append('runtime_config_inbox_ack_cache_link_budget_backoff_restored')
                    try:
                        with recovered_repository.transaction() as db:
                            db.execute('UPDATE market_runtime_events SET payload=payload WHERE id=?', (runtime_event['id'],))
                    except psycopg.Error as error:
                        assert 'immutable' in str(error)
                    else:
                        raise AssertionError('Restored runtime event guard missing')
                    checks.append('restored_runtime_event_immutable_guard')
                    runtime.configure(recovered, accounts[0], expected_version=1, enabled=False,
                                      strategies={'breakout': True, 'pullback': False})
                    imported = market_archiver.restore(recovered, accounts[0], market_export,
                        expected_sha256=market_manifest['sha256'], trusted_archive=True)
                    assert imported['added']['market_data_journal'] == 1
                    with patch.object(journal, 'utc_now', lambda: journal_time):
                        assert journal.replay(recovered, accounts[0], late_market['id']) == late_market
                        assert journal.replay(recovered, accounts[0], saved_market['id']) == saved_market
                    checks.append('streaming_market_archive_restores_post_backup_original_without_overwriting_prior_rows')
                    repeated = market_archiver.restore(recovered, accounts[0], market_export,
                        expected_sha256=market_manifest['sha256'], trusted_archive=True)
                    assert all(n == 0 for n in repeated['added'].values())
                    checks.append('market_archive_idempotent_restore_preserves_disabled_runtime_and_orders')
                    assert all(not row["state_known"] for row in recovered.list_accounts())
                    for account in accounts:
                        assert recovered.reconcile(account)["resubmitted"] == 0
                        assert len(recovered.rows(account, "orders")) == 1
                    checks.append("application_invalidates_account_trust_and_reconciles_without_resubmission")
                    assert recovered.settle_paper(accounts[3],settlement_request)==settlement_result
                    assert recovered.performance(accounts[3])['simulated_cash_cents']==1495000
                    checks.append('settlement_receipt_clock_delivery_and_exact_retry_survive_backup_restore')
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
