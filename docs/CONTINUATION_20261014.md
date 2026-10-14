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

Open software work remains distinct from external evidence: actual OPRA entitlement and three recorded sessions, secure stable signing material, independently deployed uptime, signed iOS/device acceptance cannot be manufactured. The software gaps above remain authorized work, not requests for user testing.
