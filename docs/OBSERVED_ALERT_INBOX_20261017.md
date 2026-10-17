# Observed runtime alert inbox v1

Worker-generated operational evidence, independent of immutable financial ledger-v1/v2. Schema11 is additive; no old ledger rewriting or deletion. All routes require the existing owner token. No provider key, raw error body or network notification destination is stored.

- GET /api/observed-paper/alerts: default after=owner ACK, limit=25 (1–100). Optional after and through pin a snapshot. Sequence, previousHash and eventHash bind each original event. One indexed page is loaded. Old acknowledged originals remain available with explicit after=0.
- POST /api/observed-paper/alerts/ack: strict sequence, event_hash, expected_ack. Monotonic owner-wide watermark; exact retries after lost responses succeed without moving it backward. A conflicting newer ACK requires rereading. ACK means reviewed, not resolved.
- Events store sorted active/raised/resolved allowlisted codes and detectedAt. The sequence is ordering authority across clock regression. No inferred historical timestamp or claim of uninterrupted monitoring.
- A live worker writes transitions in its fenced heartbeat transaction. Expired capture and old owner shutdown cannot publish. Stale heartbeat is observed at the next successful owned tick; read-only status still reports current staleness immediately without writing. A dead process cannot deliver its own outage; an external observer/deployment remains required for unattended outage delivery.
- No automatic pruning or retention loss. Hashes detect accidental corruption, not a hostile database administrator. Native SQL triggers reject event UPDATE/DELETE. ACK storage is separate. SQLite whole-database snapshots and PostgreSQL custom archives preserve both.
- This is authenticated pull delivery with at-least-once presentation until explicit ACK, not external push, a market entitlement or execution eligibility.

Tests: test_observed_paper_alerts.py; observed_paper_check.py; postgres_backup_check.py. The latter two run on a disposable PostgreSQL service in the existing workflow. No new automation or APK workflow is introduced.
