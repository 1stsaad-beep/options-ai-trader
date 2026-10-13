# Known gaps — completion mission

V1.0 is not complete. Baseline: `9ff7b6084c5a874dd3621748346bf0692f5bc962`. Prior green Lab22 checks do not close the requirements below.

| Priority | Gap | Evidence / closure condition |
|---|---|---|
| Critical | Direct Market Paper stock-analysis gate can veto independently justified protective option exits. | `market_paper.dart:evaluate`; reproduce with valid option quote and unavailable stock signal, preserve no-price/no-fill. |
| Critical | Paper write failure is treated as proof of no disk commit; uncertain state can be reused. | `commit` does no readback or uncertainty latch; inject write-then-throw/lost-read/changed-state and prove no double close/open. |
| High | Paper saved ledger validation is shallow and exposed maps are shallow copies. | Validate account identities/numeric balances/positions/evidence; preserve malformed original; reject mutation aliasing. |
| High | Direct paper daily/aggregate exposure, pending lifecycle, complete protective policies and persistent reversal revalidation are incomplete. | Add independent admission, lifecycle and replay regressions; do not infer server safety applies to phone ledger. |
| High | Four-account USD1,000 experiment and three-session comparison absent. | Explicit idempotent setup, distinct rules, independent watchlists/risk, event-based reports; sessions unobserved until actual collection. |
| High | Option expiry exercise/assignment/settlement remains unresolved; holdings must never be silently erased. | Server US guard retains review exposure; require explicit qualified synthetic receipts and isolated accounting tests. |
| High | Direct trade evidence/chart markers and full performance accounting absent. | Persist quantity/cost/fee/price/source/time/reason on each event, report unavailable marks honestly. |
| Medium | Long-term causal wave/source rollover and phone/server analysis parity incomplete. | Preserve old immutable evidence and show explicit source/version; no retrospective rewritten counts. |
| Medium | Stable Android signer and compatible upgrade path not established. | Use existing secure CI secrets only if present; inspect actual signer. Preserve old installations; no key reconstruction from public certificate. |
| External evidence | No current agent real-provider/physical-phone/three-real-session/Oracle-soak test. | Do not fabricate; no intermediate APK request. Oracle deployment/IBKR connection remain outside authority. |
| Distribution | iOS signing/device testing unavailable. | Unsigned build is build evidence, not distribution readiness. |

No confirmed market profitability, calibrated probabilities, realistic execution guarantee, or completed three-session study is claimed. Paid data is not purchased to eliminate a gap. User account keys remain on device.
