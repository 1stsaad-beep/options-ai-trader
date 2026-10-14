# Known gaps and closed defects

The engineering candidate is not a claim that every V1.0 requirement is complete. Do not use a fixture result as real-market or physical-phone acceptance.

## Post-Build23 audit — 2026-10-14

No final-phone request or new APK. All three assignments remain partial overall. Independent second review has NOT occurred; earlier same-agent review does not satisfy it. Full status and code/test evidence: docs/POST_BUILD23_AUDIT_20261014_AR.md.

Newly repaired source defects (not present in the old APK): stopped-account manual close was silently ignored; owned symbols removed from watchlists lacked direct close/selection controls; decision evidence clipped1000-bar analysis to120 bars; Direct wave rendering bypassed causal invalidation and omitted main/alternate selection. Regression evidence is tied to the new source, not Build23. Old incomplete decision sources cannot be recovered retroactively.

Remaining programming work is not all an external-access blocker: settlement/delivery receipt accounting, phone/server analysis parity, persistent cross-window wave history, real-option replay integration, continuous virtual execution/reliable alerting and capacity improvements need implementation. OPRA entitlement, three observed sessions, secure stable signing and deployment evidence are separate external/operational gates.

## Corrected in source, subject to final-source gates

- Optional stock analysis formerly blocked independent protective option exits. It is now separated from qualified owned-option protection; no option price still means no fill.
- Lost write acknowledgements, mutable nested data and weak saved-state validation could corrupt/reuse uncertain ownership. Exact preimage/readback, uncertainty latch, strict receipt reconciliation and deep copies now apply. Android adds synced AtomicFile and native expected-byte CAS, with retained legacy migration.
- Empty-position manual close formerly fell through into an entry; it is explicitly rejected.
- Direct paper lacked an explicit four-account experiment, account strategy/watchlist, aggregate/day caps, complete receipts/performance, partial close intent and close/restart reconciliation. These are implemented with regressions.
- Original chart decisions, complete higher-frame aggregation, manual backup and narrow RTL account controls are now implemented. Missing/unobserved data is not fabricated.

## Remaining material limits

| Priority | Gap / boundary | Required evidence or work |
|---|---|---|
| High functional | Exercise, assignment, stock delivery and cash settlement accounting are not implemented. | Expired holdings are retained, entries blocked and review required; never assume a settlement or erase inventory. A future complete implementation needs a separately specified stock/cash ledger and verified receipts. |
| High execution realism | Direct Market Paper is a standard-100-multiplier bid/ask research ledger with fixed USD0.65 commission/side. | No adjusted/mini contracts, queue model, market-calibrated slippage or Greeks-based live execution admission. Server Option Twin/Replay models are explicitly hypothetical and cannot qualify Direct fills. |
| High external evidence | Real OPRA permission/data, user device behavior and three full sessions have not been observed by the agent. | Keep account experiment NOT_RUN/partially observed until real evidence exists. No request for intermediate APK testing. Do not request phone acceptance while software prerequisites remain open. |
| Platform durability | Android atomic disk store is stronger than non-Android preference fallback. | iOS native durability/signing/device distribution acceptance remains open; no unsupported equivalence claim. |
| Distribution | Stable signing secrets were unavailable in prior runs; old private key cannot be recovered from its public certificate. | Verified Build23 uses an ephemeral Android Debug signer, not a stable key. Build23 uses a separate package, retains old applications/data, and cannot read another package's private ledger or Keystore. Never uninstall old builds as an upgrade shortcut. |
| Research continuity | Live analysis uses bounded observed source windows; broad classical pattern catalog and phone/server parity are incomplete. | Original decision snapshots are retained, but no unlimited live wave archive or predictive calibration is claimed. |
| Capacity | Paper keeps original event segments in its local ledger; JSON rewrite and validation cost grow with history. | Manual backup is bounded to16MiB and native disk bytes to64MiB; storage failure stops mutation. Not a high-volume or multi-process trading system. |
| Operations | Oracle has not been deployed or soak-tested; Android monitor is time-bounded and only collects data. | Independent server/Compose tests demonstrate portability only. Direct paper pauses outside foreground; no continuous protection promise. |
| Prohibited scope | Live/external broker orders, connected IBKR Paper, paid data purchases, public deployment and other repositories. | Remain locked/unperformed under user authorization boundaries. |

No confirmed market profitability, realistic execution guarantee, calibrated signal probability, completed three-session study, or iOS distribution readiness is claimed. Existing source/reports remain available as historical evidence; current acceptance is tied to exact workflow/source hashes.
