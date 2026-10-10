# Database V0.4 compatibility — mock only

V0.4 changes no table schema. Its new automation settings are backward-compatible defaults in account configuration; existing accounts remain automation-disabled until explicitly opted in.

Repository initialization runs additive schema migrations in a transaction under the same SQLite write lock/PostgreSQL advisory lock used for risk admission. The `schema_migrations` ledger records versions 1 (V0.2 baseline) 2 (V0.3 market observations and relational guards), and 3 (an explicitly unverified imported balance baseline). Existing account, order, fill, position and audit rows are retained. Startup invalidates account trust until a new Mock reconciliation succeeds. This also applies when the worker starts; refresh account state after restarting services.

Migration 2 adds per-account `market_snapshots` and indices for account queries. PostgreSQL receives native foreign keys; existing SQLite tables receive insert/update/delete relationship triggers rather than a destructive table rebuild. The new market availability flag has a CHECK constraint. Missing parent rows in an old database abort and roll back migration; the system never silently removes orphan ledgers. Unknown migration histories fail closed. A migration failure closes the connection.

Before upgrading an existing database, stop API/worker and back it up (SQLite backup API or PostgreSQL `pg_dump`). Never migrate a live or unrelated database with these tools. Restore a backup to roll back; migration downgrades are intentionally unsupported. Accounts cannot be deleted while ledgers refer to them. This supports audit preservation, not a general retention policy.

Migration 3 writes `MIGRATION_BALANCE_BASELINE` only for imported accounts without an integer `ACCOUNT_CREATED.initial_equity_cents`. It freezes the existing local `accounts.equity` value with source `local_v02_import_unverified`, retaining original audit rows. It does not validate whether that value was correct before import and does not consult a broker. Subsequent balance changes are rejected during reconciliation. Accounts with V0.3 creation provenance receive no import baseline. The migration transaction and version ledger prevent duplicate baseline events after restart. This is corruption detection within a local synthetic ledger, not a tamper-proof audit or a broker balance certification.

## Disposable PostgreSQL integration check

Only local/container PostgreSQL is accepted by the check script. It writes synthetic accounts/ledgers and is not a read-only command. Run against an empty, disposable database:

```sh
export TEST_DATABASE_URL='postgresql://local_user:local_password@127.0.0.1:5432/options_disposable'
export TEST_DATABASE_ALLOW_DISPOSABLE=1
python scripts/postgres_check.py
```

Credentials are entered only locally; do not send them in chat or commit them. The script checks the migration ledger and native foreign keys, account isolation, duplicate requests, partial fills, disconnection, reconciliation and stop behavior. It does not delete records afterward: destroy the disposable database separately once you have inspected the evidence.

## Historical V0.3 environment evidence (not a new V0.4 PostgreSQL run)

Seven SQLite migration tests were executed successfully, zero failures/skips; JUnit is `docs/archive/v0.3/evidence/v03-database-tests.xml`. They cover preserving V0.2 rows/repeated startup, transaction rollback for orphans, missing account/order references, unknown schema versions and parent deletion restriction, imported equity tamper detection/repeated migration, and preserving existing creation provenance.

PostgreSQL 16.2 `initdb --version` ran after configuring its bundled shared-library path. Server initialization could not run: the process is root, `initdb` rejects root, workspace `chown` and a subprocess selecting the non-root UID each return `OSError(22, Invalid argument)`. No PostgreSQL server or integration check passed. Running `postgres_check.py` without a configured disposable URL exited with the expected safety instruction; this is not integration success. Docker is absent (`command -v docker` produced no executable), so neither images nor Compose were executed. YAML parse and tests cannot prove runtime PostgreSQL/Compose compatibility.

Compose exposes API only at `127.0.0.1:8000`; PostgreSQL has no published port and no database admin UI. API requires a locally generated token. API/worker are non-root, read-only containers with dropped capabilities; mock is required and `ENABLE_LIVE=false` is explicit. Secrets are generated into excluded `infra/.env` with mode 0600. Docker images require network access during the later local build. No production deployment occurred.

Remaining work: execute disposable PostgreSQL and Compose integration on a supported host, run multi-process PostgreSQL contention tests, backup/restore drills and production DB privilege design. The current development DB role is a bootstrap-owned role, not a hardened production role. No profitability or live-readiness conclusion follows from these checks.
