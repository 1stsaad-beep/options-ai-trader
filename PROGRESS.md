# Progress — recovery/v1.0-20261011

## Batch 0: recovery checkpoint

- Base: 3d35475cd92058f8470d6f81826aaa4a16f587b1 (latest saved RC2).
- Verified five original branch heads, RC2 ancestry (17 commits), 33 workflow runs and current deliverable artifact metadata.
- Preserved existing RECOVERY_STATUS.md and appended this session's limitations.
- No code changes or test reruns in this documentation-only batch.
- Remote branch created successfully; checkpoint commit `cd990434a2f3e0066953ae1df418140d544bfcbe` was read back from GitHub successfully before the next batch.

## Next batch

Restore exact saved source, verify artifact logs/counts/signatures and inspect requirements and critical safety tests. Fix evidenced gaps in small tested commits. Completion remains unclaimed.

## Batch 1: recovered evidence and critical baseline

- Reconstructed exact RC2 source tree and remote commit identities from verified Git objects and existing history bundles; Git fsck reported no missing or corrupt reachable objects. Old checkout and all recovered objects retained.
- Inventoried all 33 workflow runs and all artifacts returned by their run endpoints. No releases exist.
- Downloaded and CRC-checked RC2 Android/iOS and backend/Compose/security artifacts. APK SHA-256 matches CI; CI apksigner verifies v2 signature with temporary development key.
- Verified historical RC1 Python 537, current RC2 Python 625, Flutter 142 on each platform; zero failures/skips. PostgreSQL backup/restore 10 checks and Compose 12 checks passed.
- Re-ran the existing 51 critical selected Python cases locally: all passed. Exact command, JUnit and output retained.
- No application code changed in this batch. Evidence is in docs/evidence/recovery-20261011.
- Next: failure-injection review of optional analysis versus protective exits; then current delivery reports.

## Batch 2: protective exits survive optional research failure

- Previous batch published and read back at `7dbf350a406f36339709ab3848110f78c11a2b7a`.
- Reproduced a real safety defect: when scenario_exit_enabled was true, an optional bar/analysis failure stranded five independently justified exits (SL, TP, trailing, intraday, swing). Corrected-fixture reproduction: 5 failed, 1 passed.
- The fix gives validated protective triggers and accepted automatic close receipts priority over optional scenario research. Account, inventory, quote freshness/spread, order/fill risk admission and idempotency checks remain mandatory. No failed scenario is treated as a signal.
- Added six regression cases. Targeted lifecycle/automation/RC2 suite: 78 passed, zero failed/skipped. A no-trigger analysis outage leaves the owned position untouched. Repeated ticks do not duplicate orders or P&L.
- Test development initially exposed fixture defects (rolled synthetic expiry and an unintended nested transaction); these fixtures were corrected before the definitive reproduction. All attempt logs are retained; `protective-reproduced.*` and `protective-acceptance.*` are the authoritative before/after pair.
- No Flutter source changed, so existing verified RC2 APK/iOS artifacts remain applicable to mobile source. Backend final acceptance and current reports are next.

## Batch 3: acceptance harness correction

- Batch 2 published and verified at `bb95d170460b3d99c3a2bcf1011bb4f55a2af3f3`. Full local Python gate: 631 passed, zero failed/skipped (one existing Starlette deprecation warning).
- The real HTTP smoke failed at the one-order assertion when executed after the configured UTC intraday cutoff. This also failed CI run 38089561046; Python itself passed. The newly opened account legitimately attempted a timed exit, so the test scenario was time-dependent.
- Isolated this partial-entry/explicit-stop scenario with `holding=swing`; production intraday policy is unchanged and its existing deterministic tests remain in the critical suite. The actual HTTP smoke now passes.
- Aligned Python package and lifecycle evidence metadata with RC2. Added the recovery branch to existing security CI; no new service or deployment.
- Initial direct lifecycle/research script invocations lacked installed editable package; installed the documented backend package, then reran successfully. This was environment setup, not application failure.
- Secret-pattern scan: zero findings in tracked source and reachable history; this is not a penetration test. Unchanged dependency locks retain the verified cloud audit.
- Acceptance artifacts include the full Python gate, successful HTTP/worker run, deterministic lifecycle, synthetic backtest and walk-forward. CI is rerun by this script fix before delivery.

## Batch 4: current delivery and resumable gaps

- Batch 3 published and verified at `b39b164f6869305b1e71586ef2d6978a7612fcf1`.
- CI 38089730231 completed successfully: Python 631, real HTTP/worker smoke, PostgreSQL integration and V1 checks, backup/restore 10 checks, Compose 12 checks. Security CI 38089730298 completed successfully. Raw artifacts and job logs copied into versioned evidence.
- No mobile source changed from verified build `3d35475cd92058f8470d6f81826aaa4a16f587b1`; 142 Flutter tests per platform and both builds retained without unnecessary rebuild.
- New current reports cover tests, security, backtesting, every requested requirement, remaining work and operation/resumption. README points to FINAL_DELIVERY.md; previous reports remain historical.
- APK and iOS bytes downloaded, ZIP CRC and SHA-256 checked. Persistent conversation-file saving failed before upload because helper authentication was unavailable; no successful save is claimed. GitHub artifact links and downloadable local copies are provided, with 14-day retention clearly stated.
- This documentation/evidence-only batch requires link/content and diff checks, not another mobile build or full test run.
- V1.0 completeness is explicitly unclaimed. Next work is listed in docs/RECOVERY_REQUIREMENTS_V1.md. Start from this branch, retain all prior history, keep external brokers and Live disabled.

## Engineering mission batch 1: connected research journal

- Started from verified clean local/remote Recovery head `72abca1c637fbabf55ecf5d30dcb276c9798170c`; no unsaved work was present at mission start.
- Added a versioned server/mobile research boundary, account/symbol-scoped snapshot list, and exact original workbench in replay. The phone can explicitly save, list and replay server snapshots, and drops responses after identity/page changes.
- Added a shared real-service JSON fixture consumed by Python and Flutter, rather than relying only on handwritten mock payloads. Python targeted research/contract gate: **34 passed**, zero failed/skipped; raw output/JUnit in `docs/evidence/engineering-20261011`.
- Mobile tests and builds require GitHub runners; no local Flutter execution is claimed. Recovery branch now triggers the existing Android/iOS gates. Build number raised to 12, without changing the preview app identity or adding keys.
- List history is explicitly bounded; counterfactual results remain synthetic fixture outcomes, not actual option observations. All external execution remains locked. Full contract and limits: `docs/RESEARCH_CONTRACT_V1.md`.
- Independent safety review reproduced partial-profit over-closing, optional-analysis blocking partial exits, and pending reversal fills after permissions changed. These are next-batch safety fixes; no acceptance completion is claimed while they remain.
