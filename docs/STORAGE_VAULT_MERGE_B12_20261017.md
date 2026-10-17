# Batch B12 — order-journal storage capacity, and merging the old Direct vault into broker accounts (2026-10-17)

Branch: `work/storage-b12` (stacked on B11). Paper only; the Live lock is unchanged.

## 1. Broker Paper journal capacity (`broker_order_journal.dart`)
- Before (v1): one secure-storage value for all events, rewritten in full on every append, max 2000 events.
- Now (v2):
  - Segments of 250 events (`oat.brokers.orders.v2.<id>.seg.<n>`) plus a small head (`...head`).
  - An append writes only the last segment, then the head, each verified by read-back.
  - Capacity is 50,000 events. When full, new orders are refused; nothing is deleted.
- Migration from v1: happens on the first append. Every segment is written, then the head, with `migratedFrom` holding the event count, the SHA-256 of the v1 text, and the time. **The v1 value is never modified or deleted** (byte-identical test).
- A corrupt v1 journal is never migrated (fails with `JOURNAL_CORRUPT` and stays as it was).
- Crash between segment and head: an extra event beyond the head is ignored. That append never returned, so the order was never sent, because the send only happens after the INTENT is confirmed.
- `stats()` returns the format, count, segments and migration details without any event content.

## 2. Merging the old Direct vault (Alpaca) into broker accounts
- Native: `AlpacaAccess.exportForMigration(confirmed)` requires explicit consent and readable keys, and does not modify the vault. The `exportKeysForMigration` channel requires the app to be in the foreground.
- Dart: `VaultMigration`, triggered from the «نقل مفاتيح Direct» button in the accounts screen with a confirmation dialog. It:
  - creates an Alpaca Paper account labeled «Alpaca (من خزنة Direct)», or
  - links an existing account that has the same key (no duplicate), or
  - returns `ALREADY_MIGRATED`.
- Migration record: `oat.brokers.migration.v1`, append-only, storing only a 16-character fingerprint of the key id. No key material is stored there (tested).
- **The Direct vault stays as it was**, so the market data session (OPRA/stock quotes) keeps using it. Nothing old is deleted.
- If the vault holds Live keys, `paper-api` rejects them in the connection test, and the migrated account stays unusable until Paper keys are entered.

## Evidence (`docs/evidence/storage-b12-20261017/`)
- analyze clean; **1113** Flutter tests (B11: 1105, +8 in `test/storage_migration_test.dart`).
- **62 JVM tests** (B2: 61, +1 `migrationExportNeedsConsentAndReadableKeysAndLeavesVaultUnchanged`), plus the result XML files.
- Native policy checks 30 + 44 pass.
- Debug APK built, secret scan 0, SHA256SUMS.

## Not covered / OPEN
- The Market Paper ledger and its native archive (64 MiB whole-JSON, 16 MiB export) are not changed in this batch; they remain documented gaps.
- Reading the full v2 journal still loads all segments into memory (bounded at 50k events).
- The protective-state record (B10) stays a single value bounded at 500 lots.
- The vault migration has not been run on a real device or Keystore.
