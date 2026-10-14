# Continuation after Build23 audit — 2026-10-14

Baseline actual HEAD:3f72b29a1116da099f7a01a86991ddff243c1df5 on recovery/v1.0-20261011. All work remains in this repository. No new APK, phone test, service purchase, secret use, external order or deployment. Every code checkpoint uses [chart-check].

## Active sequence

1. Virtual equity-option exercise/expiry/delivery ledger with explicit immutable idempotent receipts, cash/share ownership checks, restart/readback and cross-language arithmetic fixtures.
2. Explicit option cost/Greeks/liquidity policies and qualified-observation replay; no unobserved price substitution.
3. Shared causal analysis contract, persistent wave history, source revision/gap boundaries and archived decisions.
4. Durable continuous virtual worker and recovery/heartbeat/outbox with safe opt-in and no provider credentials in fixtures. No promise of operation with the phone powered off; deployment evidence remains separate.
5. Final applicable gates and distinct review. No independent reviewer is currently available in this session; another implementer pass will not be called independent.

## Batch 1 — settlement arithmetic

Added pure Python/Dart standard-long-equity settlement projections: partial/full Call exercise transfers strike cash and capitalizes premium/fees into delivered shares; Put exercise needs owned shares and removes their basis; explicit worthless expiry requires a non-ITM at-cutoff observation; disposal consumes only owned delivered shares. All deltas require whole-cent OCC terms, explicit chronology/reference and available cash. Long-position assignment and fabricated cash settlement of physical equity contracts are rejected. Sources are explicitly manual_paper/fixture; this is not broker settlement confirmation or automatic exercise.

Primary references checked: OIC https://www.optionseducation.org/advancedconcepts/equity-vs-index-options and https://www.optionseducation.org/optionsoverview/exercising-options (equity share delivery; holder exercise versus writer assignment). These do not provide account-specific authority or settlement receipts. No broker network action occurred.

Local arithmetic tests:22 passed including the 27 checked-in cross-language positive/negative cases. Initial checkpoint2275be6 passed backend/security but Flutter analysis stopped on one missing brace; corrected by0cc1c31. Its Flutter test step and chart/golden gate passed; native gate/artifact verification remain to collect.

## Batch 2 — durable device settlement integration

MarketPaper.settle now applies explicit paper receipts only to stopped receipt-v2 accounts, records request/result atomically, reconciles the full original journal at load, deduplicates retry identity and rejects changed identity. Delivery shares and basis survive export/recovery; a dropped/ambiguous write never silently consumes another receipt. Historical exercise predating the latest acquisition is conservatively rejected pending lot reconstruction. Full and partial conversions/disposals and worthless expiry have independent numeric expectations plus corruption/recovery tests. Manual receipt UI previews cash/shares/P&L, invalidates preview on edits and has no network/order path.

Delivered shares have no invented mark: current equity is unknown and new option exposure is blocked until disposal. Mixed delivery/option aggregate win rate is unknown; ordinary option close counts and settlement event/P&L totals are separate. This is a limited paper model, not proof of actual exercise, OPRA data or broker settlement. Put exercise requires already owned shares. Legacy ledgers without complete quantity receipts cannot be upgraded silently.

Source1cb5ae66: Flutter analysis/tests and41-JVM job passed in38539607661; chart/golden38539607650, security38539607609 and backend/Compose38539607632 passed. Original artifacts/counts still need archival. Cross-language cases increased from27 to35 for invalid timestamps, padded references and exact large-integer arithmetic. No Android/iOS package was built.

## Batch 3 — server transactional receipts

Added migration9: immutable settlement receipts and fill clocks plus delivered-share inventory. Authenticated paper-settlements/paper-deliveries routes never call a broker. Reconciliation interleaves receipts with fill sequence, reconstructs stock basis/cash/realized/day totals, checks digest/identity and locks on corruption. Exact retries return original results; transaction failures roll back all effects. Receipt sources remain manual_paper/fixture; account policy must be US-equity paper/mock, automation stopped, snapshot reconciled, and no unresolved orders/intents. Old synthetic writeoff accounts require explicit historical reconstruction; no silent conversion. New fills have original times; old day-only receipts do not fabricate intraday ownership. Delivered stock without a valuation blocks new risk, including global risk admission where open loss is unknown.

Local full backend suite:1098 passed. One migration fixture initially failed because it invoked the newest trading validator on an intentionally V4-only database; fixed by explicitly seeding the original research decision without weakening current validation. Added PostgreSQL two-connection concurrency/immutability/mixed fill checks and delivery backup/restore coverage; these require CI and are not yet claimed passed.

Sourcee579947c passed backend/PostgreSQL/backup/Compose run38540705745, including the new two-connection and stock-delivery restore gates. Security run38540705519 flagged the literal injected TestClient fixture token in the new test. It is an authored local fixture, not an external credential. The next checkpoint adds that exact value to the existing test-path-only fixture classification, preserving detection elsewhere and the full Git history; no scanner gate is disabled.

## Batch 4 — reachable cash-funded Put delivery (acceptance pending)

Added BUY_FOR_PUT: an explicit manual/fixture receipt may acquire only the missing number of shares needed for an already owned, unexpired Put, using available virtual cash and capitalizing the purchase fee. It is not an unrestricted stock entry or automatic purchase. The next explicit exercise consumes those shares and realizes the full option/share/fee result. The phone UI exposes this action only for Put holdings.43 shared arithmetic cases and one new end-to-end ledger test per runtime cover this path, including restart, excess-quantity, already-owned, insufficient-cash and invalid chronology rejection.

Source7dd7f5b: backend/PostgreSQL/Compose38541301569, security38541301573 and chart/golden38541301588 passed. Flutter analysis/tests passed; native JVM gate was still running at the next checkpoint. The exact test-token exception is regression-tested to remain flagged outside test paths.

## Batch 5 — Direct/server indicator contract (acceptance pending)

Introduced completed-bar-indicators-v1: SMA-seeded EMA, Wilder RSI/ATR, 12/26/9 MACD with null warmup, population Bollinger bands, and UTC-calendar-day VWAP with null zero-volume availability. Six checked-in cases compare every Python/Dart series value with1e-9 tolerance and every observed prefix; Direct strategy input, divergence input, displayed plots and saved research v3 now use this contract. Original v2 decisions remain unchanged. Existing synthetic Demo uses its explicitly labeled legacy rolling/first-close indicator convention; its reviewed Golden images are not silently regenerated. This closes the identified Direct arithmetic mismatch, not full engine/strategy/Demo parity.

Source343b23ac first stopped at one test-format lint; corrected in3b51b9dc. Flutter analysis/tests/JVM steps in38542520798 passed, chart/golden38542520856 and security38542520600 passed. Backend arithmetic suite in38542248567 passed. Original artifacts still need the final source-linked archival checkpoint.

## Batch 6 — durable Direct wave observation epochs (acceptance pending)

Added source-specific wave history to the atomic device ledger/backup, separate from account execution authority. Matching overlapping provider windows extend a fixed origin beyond1000 bars; original detected/invalidated events survive. A changed feed/session/source, a revised overlapping candle or an unexplained gap creates a new epoch without rewriting the old one. Complete known regular-session overnight/weekend closures connect without invented candles. Original capture boundaries distinguish a historical bar timestamp from when the app first learned it. Direct snapshots record archive origin and the one-minute chart maps archived geometry onto the visible provider window. Source epochs can be copied for offline inspection.

The initial capacity is explicit:10000 observations/8MiB, no silent eviction or auto-reset. This does not close unbounded archive/soak/performance work; segmentation outside the live ledger and incremental checkpoint optimization remain open. The archive is optional research: corrupted research is retained and unavailable, but cannot veto qualified owned protection. Failed CAS/readback never claims a new archived observation. Tests cover rolling windows, restore, revision/source/gap boundaries, corruption, capacity and original events.

Sourceb2d1d651 stopped at two redundant null-assertion analyzer warnings; corrected inc2e2793d. Chart/golden38544279560 and security38544279376 passed. Full Direct38544279503 found a runtime generic cast when appending milliseconds to a newly created typed integer list; explicitly typed map<int> fixes the actual append, retaining all failure/restore tests. Batch6 acceptance remains pending that correction's CI; earlier chart success did not establish archive correctness.

## Batch 7 — observed option counterfactual contract (integration pending)

Added a shared Python/Dart read-only model with34 hand-authored expected cases: original ask/quantity/entry fee, latest qualified OPRA bid received by a fixed horizon, explicit adverse cents and exit commission, observed size and source/account/contract isolation. Missing/stale/future/indicative/revised-ambiguous observations never acquire a fabricated price. Original decisions are not recomputed or changed; results have executionAllowed=false and cannot become fills. Session/expiry checks and exact bounded integer arithmetic apply. A late-arriving quote cannot become information known at the horizon. Fixture/alpaca provenance is retained but not authenticated by this arithmetic.

Python targeted tests:37 passed. One initially mis-timed closure fixture was corrected to place asOf after its target; production policy was not weakened. Device durable observation capture/UI and server exposure remain the next integration step. No actual OPRA access occurred; queue/Greeks valuation are explicitly not modeled by this counterfactual.

NEXT: collect/fix batch7 CI and archive source-linked evidence. Integrate durable option observations and read-only Replay. Qualify delivery marks/risk and option cost/liquidity model; complete remaining analysis parity, scalable wave archival and runtime recovery above. R09 and overall assignments remain partial. No final readiness or independent review claim.

## Batch 8 — durable observed option Replay integration (acceptance pending)

Added an append-only segmented option observation archive to device CAS/readback and backup. Entry/hold/close observations share the financial commit; repeated exact quotes retain their first capture. Optional archive corruption/capacity cannot veto owned protective closure. Read-only foreground capture follows original BUY contracts for at most5m30s (20 distinct contracts/cycle), including already closed/stopped accounts, without rearming them. Five-minute outcomes still require a qualified quote received by the horizon; a later poll never fills the gap. Native request limits remain unchanged; no background or phone-off claim. Capacity is explicitly20000 observations/8MiB with no eviction; full-file rewrite scalability remains open.

The original decision view offers a separate optional1/5-minute hold comparison and0/5/10-cent adverse-price sensitivity, after exposing the original decision cursor. It shows fees, source, unknown outcomes and non-execution authority, never modifies original balances/receipts. A protected server POST `/api/research/observed-option-replay` exposes the identical portable calculation, labels client-supplied evidence unverified, writes nothing and makes no provider call. The existing128KiB request cap applies; callers submit only the relevant contract/time window. It is not a provider-connected server collector or device/server account synchronization.

35 cross-language fixture cases now include equivalent timezone representations without false ambiguity. Added device segment/hold/closed-receipt/restart/backup/dropped-write/corrupt-protection/capacity/UI tests and server authenticated no-write/no-network tests. Await full CI; independent review and continuous virtual runtime remain open.

Source6d95fa9d passed backend/PostgreSQL/Compose38546065017, chart/golden38546065007 and security38546065031. Full Flutter38546065000 reached all tests with one UI-test failure: its generic scroll helper matched both the outer list and selectable-text scrollables. Correctionee7517e3 explicitly targets the outer list; the financial result assertion remains unchanged. Archive and counterfactual arithmetic tests passed in that run; do not call the whole gate passed until the rerun completes.

## Batch 9 — worker recovery and truthful readiness (acceptance pending)

Fixed readiness incorrectly allowing trading_ready with a fresh analysis-only worker: the observed heartbeat must explicitly report execute_mock=true in addition to trusted opted-in accounts and all previous admission checks. Added SIGTERM/SIGINT handling, bounded DB outage retries, sanitized process status, a healthcheck that never invalidates accounts, immediate STOPPED state on graceful shutdown and Compose health/grace settings. Actual recovery still invalidates stale account knowledge and never silently reconciles or resumes financial execution; explicit ledger reconciliation remains required. This preserves the original safety boundary and is not unattended Market Paper execution.

Four new real-process local tests cover DB initially unavailable then recovering, restart preserving balances/disarming stale knowledge, read-only healthchecks, fast graceful shutdown during a60-second wait and sanitized one-shot/live-lock failure. The complete local backend suite passed1144 tests after these changes. PostgreSQL/Compose and final-source security remain pending publication; no deployed uptime or independent reviewer claim.

Source2a297436 passed backend/PostgreSQL/Compose38546730107 and security38546730336. Flutter reruns on ee7517e3 were cancelled while later checkpoints were published; those are not accepted final-source gates. A complete final mobile/JVM run is still required after the next code checkpoint.

## Batch 10 — Direct/server harmonic and classic geometry (acceptance pending)

Direct now uses the server facade's strict three-left/three-right confirmed pivots for XABCD and classic geometry. Canonical Gartley/Bat/Butterfly/Crab/Cypher ratios,0.03 tolerance, XA/BC PRZ intersection (XC for Cypher), direction, activation, invalidation and both targets are matched, including Butterfly's1.272–1.618 extension range. Double top/bottom, head-and-shoulders/inverse and converging-triangle detection/confirmation are displayed as research and saved. The Direct research schema is v4; original v2/v3 decisions and Demo Golden images are unchanged. Wave journals retain their original plateau convention; this is deliberately not full wave/Demo/divergence/strategy parity.

18 harmonic/mirror/negative cases,10 classic cases and3 strict-pivot source/prefix fixtures compare Python and Dart with1e-9 tolerance. Local Python geometry plus existing intelligence tests:74 passed. Await Flutter integration/gates before claiming acceptance. Broad classic pattern drawing and independent visual review remain open.

## Batch 11 — exact option quote boundaries (acceptance pending)

Parser now rejects sub-cent/oversize prices instead of rounding a provider quote into a different fill. Qualification uses exact integer spread comparison, microsecond freshness/future boundaries, explicit exact-money product bounds and whole-cent strikes consistent with the settlement model. Added regression tests for fractional cents, one-microsecond future/stale quotes, oversized sizes/prices and overflowing quantity products. Unsupported adjusted/fractional-strike contracts remain unavailable; these checks do not authenticate the actual multiplier/deliverable. Replay view normalizes its supplied asOf to UTC.

NEXT: finish final applicable CI without interrupting native JVM jobs; inspect raw artifact counts/digests and save evidence. Update requirements with accepted source scopes. Remaining code includes full wave/divergence/strategy/Demo parity, scalable storage outside the rewritten live ledger, richer Direct execution/Greeks and adjusted-deliverable modeling, legacy lot reconstruction, delivered-stock qualified marks and a durable actual-market virtual execution worker. Read-only collector and synthetic recovery are not that worker. Independent review is still unavailable; no APK or phone request.

## Batch 12 — exact financial receipt products and proportional basis (acceptance pending)

Self-review found ordinary partial closes multiplying cost*quantity in a64-bit Dart integer before division, unlike the already-exact settlement path. Added BigInt intermediate product/sum/allocation helpers bounded to the portable ledger range and applied them to closure and receipt reconstruction. A regression exercises a valid million-contract historical fixture with8e15-cent basis, an exact500000-contract partial reduction and restart. A separate forged receipt whose gross product is2^64+48384 must be rejected, never accepted as48384; original unreadable storage is retained. These extreme local fixtures are arithmetic adversaries, not supported trading recommendations or real positions.

Added3 additional complete OHLCV geometry fixtures (Gartley, extended Butterfly, bearish Cypher), comparing actual detected pivots and nonempty saved harmonic results with Python. A Direct widget assertion verifies the painter receives the five observed XABCD points and enclosing PRZ; this complements geometry unit checks but is not an independent visual-design acceptance.

Verified original c96447e backend artifacts by SHA-256+ZIP CRC:1146 Python tests, zero failures/errors/skips;22 execution +6 journal +8 runtime +5 settlement PostgreSQL checks,17 backup/restore checks and17 Compose checks passed. Files are downloaded for the forthcoming source-linked evidence archive. Final Dart/JVM/security results remain pending this correction's publication.

Open software work remains distinct from external evidence: actual OPRA entitlement and three recorded sessions, secure stable signing material, independently deployed uptime, signed iOS/device acceptance cannot be manufactured. The software gaps above remain authorized work, not requests for user testing.


## Accepted code checkpoint and exact resume

Tested source432222b8f6274ec047ce607ce5ecb69e443f1cf1: all applicable gates completed successfully. Direct38548953555:591 Flutter,41 JVM; chart38548953574:23 semantic+6 unchanged Golden; backend38548953575:1146 Python,22+6+8+5 PostgreSQL,17 restore,17 Compose; security38548953545:0 findings967 files/1700blobs/154commits and0 known advisories24 Python/43 Pub at scan time. Android38548953552 and iOS38548953554 skipped. Original ZIPs, JSON/XML recounts, SHA-256/CRC and source receipts are stored in docs/evidence/continuation-20261014/. Bundle SHA-256:d8120678d58e014074fc5903e1d2e818b3438abd803667efcf920598ba894bec. The evidence/report commit after this source changes documentation only.

The initial failures/cancellations above remain historical facts; this checkpoint supersedes their pending acceptance. No independent reviewer, real OPRA connection, order submission, external deployment, purchase or new APK occurred. All assignment-level statuses remain PARTIAL. See CONTINUATION_ACCEPTANCE_20261014_AR.md for precise open software work versus external evidence. Do not restart from Build23 or repeat a successful package build; resume latest HEAD and preserve existing source/artifacts/history. Next substantial work is scalable ledger/archive storage and qualified delivered-stock/market-option modeling, then full causal engine parity and durable market-priced virtual execution. Current source is a verified continuation checkpoint, not completed V1.0.


## Batches13–15 — shared source archive, canonical divergence and classical rendering

Starting from accepted documentation43c0c01/code432222b, f8a19659/727b1f4a/79a5a1ba add immutable shared OHLCV epochs with exact source/session/symbol/window identity and first-capture causality. Original inline receipts are unchanged; references and source share one atomic financial commit. Backup validates joins, including journalArchive; optional archive corruption cannot veto owned protective closure. Bounds50000 bars/8MiB and whole-file rewrite remain open. Initial4 analyzer style findings and one test-map type were corrected in727b1f4a. Integrated79a5a1ba passed Direct38552190139, chart38552190054 and security38552190116.

Self-review found that structural checks alone allowed a valid-looking modified candle:2630171e adds reference v2 SHA-256 content binding, an independent Python hash vector and corrupted-source/journal-segment tests. Draft v1 pointers stay unavailable, never silently upgraded; no APK shipped them. crypto3.0.7 is pinned with the official Pub archive digest. Integrity is not provider authenticity or signing.

9cf4b4ab aligns Direct divergence with server strict3-bar pivots, every adjacent same-kind pair, distance3..60 and epsilon filters.41 shared pivot cases and3 full OHLCV sources cover all causal prefixes and actual painter segments. New research v5 preserves previous original snapshots. All source9cf4b4ab gates passed: Direct38553233660, chart38553233961, backend/PostgreSQL/Compose38553233708, security38553233733. Demo/wave/complete strategy parity remains open.

2f295734 adds actual canonical classical drawings (vertices, neckline, triangle boundaries) without invented targets/stops,7 full-source fixtures, real Widget assertions and6 light/dark preview PNGs. It fixes Direct's Models toggle incorrectly controlling oscillator panels by separating levels/models/indicators. Existing reviewed Golden baselines remain unchanged. Its Flutter preview test stalled;6a71afff moves font-file I/O outside the widget fake clock to setUpAll and independently asserts named classic patterns/break states. The superseded pending run was cancelled, not reported passed.

Latest code6a71afff6109c15a9d193ab67a0f1c136a7cb147: analyze/Flutter stages pass; chart38554751668, backend38554751899 and security38554751764 pass; Direct38554751700 JVM gate still running at this checkpoint. Backend log says1192 passed; Pub audit44 packages reports no known advisories. No raw artifact recount or visual inspection is claimed. The local exec-server disconnected and repeated execution/write recovery attempts did not respond. Code is safely on GitHub; final reports/metadata are preserved directly with expected-SHA/non-force commits and may not yet be synchronized to local scratch.

Resume from docs/RESUME_POST_BUILD23_20261014_AR.md. First finish CI, download raw artifacts before expiry2026-10-28, verify SHA/CRC and JSON/XML, inspect all6 preview images and preserve a separate evidence bundle. Earlier432222b bundle remains intact. Then continue software gaps: scalable external storage, realistic market-option/Greeks/deliverable modeling, delivery marks/legacy lots, full wave/strategy/Demo parity, broader/server Replay and durable market-priced virtual execution. Independent reviewer unavailable. No real OPRA, key use, external trade, purchase, deployment, other-project change, APK or phone request.


## Final remote checkpoint after runtime outage

All applicable gates for code6a71afff6109c15a9d193ab67a0f1c136a7cb147 completed successfully: Direct38554751700 (analyze, Flutter and native JVM), chart38554751668, backend/PostgreSQL/backup/Compose38554751899, security38554751764. Android38554751894 and iOS38554751917 skipped. This supersedes the pending CI status above. Five source-matched artifact metadata records and all job/step receipts are preserved in docs/evidence/storage-parity-20261014/metadata-only.json. Python log1192 passed; Pub44 packages no known advisories. The local runtime still did not recover on a final bounded attempt. Raw ZIP SHA/CRC/recounts, visual inspection of6 classic PNGs, a new offline evidence bundle and local synchronization remain explicitly incomplete. The reports and metadata are committed directly on GitHub; application code is unchanged after6a71afff. No independent reviewer, new APK or phone-test request. Resume the outstanding software and acceptance work, not a release build.


## Batch16 — recovered artifacts and visual defect correction

See FINAL_COMPLETION_PROGRESS.md and docs/evidence/storage-parity-20261014/index.json. Existing6a71afff results are now verified from original bytes, not metadata alone. Visual inspection found real annotation/neckline issues; the source fix preserves detector confirmation policy, source pivots and historical snapshots. Await new CI and review of corrected previews; old Golden images remain unchanged.


## Batch17 — read-only health probes and collector shutdown recovery

Reproduced2 failures: both health commands created an absent database. Replaced repository initialization with bounded read-only probes, no financial/advisory writer lock or migrations. Collector SIGTERM now records STOPPED only for its current lease owner; stale-owner shutdown cannot overwrite the successor. Actual process outage/recovery and account preservation verified.56 targeted Python checks passed; PostgreSQL adds2 acceptance checks and awaits CI. See docs/RUNTIME_HEALTH_RECOVERY_20261014.md. This does not close durable market-priced execution or long soak.
