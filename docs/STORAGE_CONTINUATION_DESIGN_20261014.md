# Storage continuation — original observed source references

Accepted baseline43c0c01 (code432222b) remains intact. This is a routine internal storage improvement, not authority to change financial receipts, discard history or relax acceptance. No APK is built.

The present journal repeats up to1000 OHLCV rows in each account's decision, even when several accounts observed the identical provider window. First remove that duplication with an append-only source archive in the same atomic book; the next step can move immutable segments outside the live file. This first step alone does not close full-file rewrite or unbounded-storage work.

Requirements for implementation:

* Existing inline source evidence and original journal entries remain byte/structurally unchanged. New decisions may reference an immutable source epoch/range only after full OHLCV, chronology, completedness and window matching validation.
* Source identity includes fixture/alpaca, IEX/SIP, regular/extended and symbol. A changed or revised source starts a new immutable epoch. Identical overlapping windows share original observations; no synthetic gap filling or retrospective revision.
* Captures preserve when each appended observation became available, separately from bar timestamps. Resolving a decision reference must reject any source first known after that decision's recordedAt. No reference can silently resolve to another symbol/source/epoch.
* Financial receipt validation does not depend on optional chart history. A missing/corrupt/capacity-exhausted archive retains originals and makes chart replay explicitly unavailable; it cannot veto qualified owned protection. New capture failures fall back to the original inline evidence only where that source was actually available, never to reconstructed prices.
* Replay preserves original event JSON and resolves bars separately. A source reference is a resource pointer, not an authenticated signature or a new interpretation of the decision.
* Backup exports both sources and references, validates their relationship and restores only into an empty stopped ledger. Standalone original events without their referenced archive explicitly lack replay data.
* Acceptance covers window overlap, all-account deduplication, source revisions, capture chronology, missing/tampered references, restart/backup/CAS failures, preserved original receipts and actual saved-decision cursor rendering. Measure serialized size reduction against the same observed history; do not claim phone performance or unbounded capacity from synthetic tests.

Implemented in `observed_bar_archive.dart`, MarketPaper atomic persistence, backup join validation and offline Replay. Reference v2 adds a SHA-256 digest of canonical compact OHLCV rows, so a valid-looking changed middle candle cannot satisfy the original decision reference. `crypto`3.0.7 is pinned with the archive digest returned by the official Pub API (`https://pub.dev/api/packages/crypto/versions/3.0.7`); no secret or signing key is involved. A digest does not authenticate imported history. Draft v1 pointers are explicitly unavailable, never silently upgraded; none was shipped in an APK.

Capacity remains50000 bars/8MiB, alongside existing wave/option limits. A four-account synthetic1000-bar source/reference payload is less than one quarter of four inline copies. This measures serialization of source evidence only, not total-book/phone latency or indefinite storage. Journal reads no longer clone unrelated source archives; writes still serialize the atomic whole book. Preserved originals and actual inline fallback can still reach the existing export/native limits. External immutable segments, incremental validation, bounded retention with verified export, long soak and native storage-pressure acceptance remain open.

The first integrated source79a5a1ba passed Flutter/analyze/JVM, chart/Golden and security. Subsequent content-binding and divergence source9cf4b4ab has acceptance in progress; see the newest continuation report/log for the completed source-specific evidence. Keep earlier raw evidence rather than overwriting it with pending results.
