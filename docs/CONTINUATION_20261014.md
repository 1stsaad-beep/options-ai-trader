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

## Batch 3 — server transactional receipts (acceptance pending)

Added migration9: immutable settlement receipts and fill clocks plus delivered-share inventory. Authenticated paper-settlements/paper-deliveries routes never call a broker. Reconciliation interleaves receipts with fill sequence, reconstructs stock basis/cash/realized/day totals, checks digest/identity and locks on corruption. Exact retries return original results; transaction failures roll back all effects. Receipt sources remain manual_paper/fixture; account policy must be US-equity paper/mock, automation stopped, snapshot reconciled, and no unresolved orders/intents. Old synthetic writeoff accounts require explicit historical reconstruction; no silent conversion. New fills have original times; old day-only receipts do not fabricate intraday ownership. Delivered stock without a valuation blocks new risk, including global risk admission where open loss is unknown.

Local full backend suite:1098 passed. One migration fixture initially failed because it invoked the newest trading validator on an intentionally V4-only database; fixed by explicitly seeding the original research decision without weakening current validation. Added PostgreSQL two-connection concurrency/immutability/mixed fill checks and delivery backup/restore coverage; these require CI and are not yet claimed passed.

NEXT: collect/fix batch3 CI and archive source-linked evidence. Add the explicit cash-funded purchase of only the shares needed for an already owned Put (currently Put math requires shares but no reachable acquisition path in the options-only workflow); qualify delivery marks/risk and option cost/liquidity model. Then continue analysis parity, persistent wave archive, observed Replay and runtime recovery above. R09 remains partial; the rest of the software backlog remains open. No final readiness or independent review claim.

Open software work remains distinct from external evidence: actual OPRA entitlement and three recorded sessions, secure stable signing material, independently deployed uptime, signed iOS/device acceptance cannot be manufactured. The software gaps above remain authorized work, not requests for user testing.
