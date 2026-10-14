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

Local arithmetic tests:21 passed after correcting one expected-value arithmetic typo (Put P&L78835, not78735 cents). Added27 checked-in cross-language positive/negative cases, plus Python fixture consistency test. Source integration into durable ledgers/UI remains next, so R09 is not closed by this pure module. CI is pending for the first checkpoint.

Open software work remains distinct from external evidence: actual OPRA entitlement and three recorded sessions, secure stable signing material, independently deployed uptime, signed iOS/device acceptance cannot be manufactured. The software gaps above remain authorized work, not requests for user testing.
