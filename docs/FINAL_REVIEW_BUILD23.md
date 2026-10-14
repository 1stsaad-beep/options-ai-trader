> 2026-10-14 correction: this is the implementer's historical adversarial pass, not completion of the independent-review assignment. Additional defects were found and fixed after Build23. Current status: [post-Build23 audit](POST_BUILD23_AUDIT_20261014_AR.md). No new APK or phone test now.

# Build23 engineering review

Review boundary: completion changes from recovery baseline `9ff7b6084c5a874dd3621748346bf0692f5bc962`. This is a separate adversarial review pass by the same engineering agent, not a second human review or external certification. Acceptance uses original failing regressions, immutable-source CI artifacts, independently executed server calendar fixtures and real Android framework instrumentation with mock provider data.

## Invariants reviewed

| Boundary | Evidence and result |
|---|---|
| Ownership and cash | Receipt-v2 replays all fills and reconciles cash, residual cost, fees, closed round trips and realized P&L. Deep copies prevent external map aliases. Legacy unrecorded totals remain unknown. |
| Persistence | A thrown write is not presumed absent. Durable preimage and readback distinguish committed/unchanged/uncertain outcomes. Unknown outcomes disable every mutation. Android adds AtomicFile/fsync/CAS on a background channel and retains legacy preference data. A native initialization marker prevents silently reviving stale legacy data after disk loss. |
| Optional research | Stale/throwing stock analysis cannot veto independently priced stop/take/trailing/manual/expiry protection. WAIT is not a structural invalidation. Scenario boundary is frozen at entry and checked against fresh stock prices; research snapshots carry no execution permission. |
| Partial close and reversal | Partial cost/fee allocation preserves the remaining ledger. Original partial target survives quote loss. Same/older quote observations cannot consume more liquidity. Pending ownership blocks opposite exposure; full close must be durably reconciled before fresh signal/contract/risk admission. Restart disarms execution. |
| Risk | Independent per-account cost/allocation/day/position/contract constraints; pending close blocks new exposure. All owned option marks must be qualified to admit additional risk. Profit does not offset negative marked loss. No gap-loss guarantee or measured actual-violation claim. |
| Timing and expiry | Only conservative supported US sessions permit fills. Full/early close, DST, holidays, last trading date and unsupported-year fixtures are checked against the server policy. Expired positions remain review exposure; exercise/settlement is never fabricated. |
| Evidence and charts | Original rule/quote/bar/research/receipt snapshots are frozen at decision time. Complete UTC-anchored higher frames reject missing minutes. Trade markers refer to the stock observation, while option fill prices are separate. No retrospective reason generation. |
| Backups and isolation | Mode-specific bounded backup, ledger validation, prohibited credential fields and empty-ledger-only restore. Imported accounts start stopped. API authentication and independent account/process boundaries are covered by existing backend suites and real disposable PostgreSQL. |
| Platform/network | Native data allowlist, single socket, stop/retry lifecycle and Keystore secure-screen behavior remain unchanged. Added native storage tests do not contact Alpaca. No external broker or IBKR connection; only approved private-repository CI runs. |

## Defects found during this mission

Original baseline regression run had14 failures among332 results, all in newly specified safety cases. Repairs eliminated these failures. A newly found empty-position manual-close fall-through was also fixed. Subsequent review corrected native disk durability, optional scenario authority, partial-target growth during outage and old quote reuse. One final preflight failed solely on a multiline-if lint; the exact failure is retained and the condition was not weakened. No failed/cancelled workflow is relabeled as a successful full run.

## Gate evidence available before release packaging

- Backend run38469775315 on4bad1a00: **1055 Python passed**, no skips/failures; HTTP/API lifecycle checks; PostgreSQL22 execution/concurrency,6 journal,8 runtime,16 backup/restore checks; disposable Compose17 checks. These source directories are unchanged since that run.
- Android framework run38469775290 on4bad1a00: **13 tests passed on API28 emulator**, including disk CAS/recovery, Keystore and actual Activity sleep/wake with one mock socket. Native source remains unchanged since that run.
- Chart run38470254193 on e5559f0b: **23 semantic tests and6 reviewed Golden comparisons passed**; no baseline regeneration.
- Security run38470254048 on e5559f0b: zero findings across919 tracked text files and1536 historical blobs/130 commits; no known advisories among24 Python and43 hosted Pub packages. These are bounded scans, not proof of zero vulnerabilities. Expanded new evidence archives were separately scanned with the same redacted rules.
- Direct run38470254079 on e5559f0b passed384 Flutter and41 JVM tests; raw JSON/XML and ZIP digest were verified. Final report correction adds one truthful-risk-metric regression. The packaging pipeline reruns the complete gate before generating the release artifact; final provenance is recorded separately.

## Remaining limits

See `../KNOWN_GAPS.md` and `../REQUIREMENTS_TRACEABILITY.md`. Exercise/stock delivery/settlement, realistic option queue/slippage, adjusted contracts, unlimited live wave continuity, iOS distribution and actual provider/phone/three-session evidence remain incomplete. The release candidate is for acceptance of the documented engineering scope; it must not be described as complete V1.0 or validated real-market profitability.

Final packaged source `63a6d646d86f75c322751b3e791c66a204e75f2b` passed385 Flutter,6 Golden,41 JVM and90-package Android dependency audit. APK/public signer/hash and raw outputs are recorded in FINAL_DELIVERY; no third-party/provider/physical-phone approval is inferred.
