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

### Batch 1 CI correction

- Batch 1 pushed and read back at `9eba22278054a771a44c4a0e1c8bff9dff29a8b1`.
- Backend/Compose CI `38117173190` and security CI `38117173235` succeeded. Android CI `38117173242` stopped at Flutter analyze: one missing brace lint in the replay response guard (`main.dart:329`). Tests/build were not reached and are not counted as passed.
- Added the required braces without changing behavior; this checkpoint reruns the mobile gate while the separate critical safety batch is being prepared. No source reset or history deletion.

## Engineering mission batch 2: partial exits and current fill authority

- Previous CI correction pushed and verified at `6897522becda2db00b1cf6bd58c5867babb5617b`.
- Real SQLite regressions reproduced 19 failures / 3 passes before the safety fix. Partial-profit resumption now preserves the accepted close quantity, including partial execution, repricing and restart; a new validated full-exit trigger can still close the rest.
- A failed optional scenario feed cannot veto a justified partial reduction. A valid scenario invalidation retains full-close priority. New quantitative BUY fills verify original immutable decision evidence and currently enabled strategy/automation/reversal permissions. Automatic/manual origin is recorded explicitly; ambiguous legacy scaling is conservative. Recorded fill receipts and owned closing sells remain supported.
- Added 31 Python regressions; targeted gate **164 passed**. Full local Python acceptance **669 passed**, zero failures/skips; one existing Starlette deprecation warning. Raw before/after and acceptance evidence retained in `docs/evidence/engineering-20261011`.
- Real local HTTP+worker smoke passed, now including research snapshot/list/original replay across an actual server process restart, authentication and cross-account rejection. No external broker connections or orders.
- Mobile Demo received corresponding current-permission checks for pending/partial automated entry and reversal, preserving explicit manual behavior. Added 17 Dart regression cases; these are authored, not locally executed (Flutter absent).
- CI at `6897522` passed analyze, but one newly added widget race test missed the drawer while its animation had not started. The saved failure log is retained; test navigation now starts/finishes the animation and checks hit testing before switching accounts. Mobile tests/build must pass on this checkpoint before acceptance.

## Engineering mission batch 3: bounded US market sessions

- Safety batch pushed and verified at `f896ed324dc1d900c347beb307a6d591c4f92191`. Its backend/Compose CI `38117633869` and security CI `38117633887` passed. Mobile analyze exposed an ambiguous Dart ternary/null-aware index at engine.dart:547; this batch uses an explicit nested conditional. No mobile acceptance is claimed until CI reruns successfully.
- Added opt-in per-account `us_equity_options_2026_2027` session policy with official NYSE holiday/early-close snapshot and New York IANA DST. Default synthetic fixtures retain their existing policy. Current session facts are saved with accepted decisions and exposed in status/cycle audit.
- BUY acceptance and every new fill recheck session policy inside the ledger transaction. Previous-session BUY decisions cannot execute at the next open; automation cancels their remaining quantity. Intraday carries close when execution is permitted. Protective owned close intents remain durable outside hours, while fill admission refuses to invent an off-session execution.
- Calendar pure suite: **70 passed**. Calendar+execution+related safety targeted suite: **120 passed**. Full local Python gate: **758 passed**, zero failed/skipped. Real HTTP/worker/journal restart smoke passed. Initial test fixture errors (missing open-loss mark and incorrect expected reason label) are retained separately, then corrected without loosening production checks.
- Sources, opt-in settings and limits: `docs/MARKET_SESSION_POLICY_V1.md`. Unscheduled halts and local mobile calendar parity remain unimplemented. Same-day contract rejection and conservative UTC-date expiry writeoff remain synthetic; real exercise/assignment is not implemented or claimed.

## Engineering mission batch 4: prospective replay evidence and wave integrity

- Session batch pushed and read back at `b52af9efcfbd83a61cea3145ebfc4a0bbad1cbb2`. Backend/Compose CI `38118049131`, security CI `38118049133`, and unsigned iOS CI `38118049104` succeeded; Android result checked at delivery. These builds predate this new observation UI.
- Counterfactual GET no longer generates missing future quotes. Migration 5 adds immutable, account-linked research observations captured prospectively by an authenticated empty-body POST. Two distinct later observations are required; advancing the clock alone keeps P&L unavailable. Original costs/reasons/contracts stay fixed; same-minute duplicate capture returns one receipt.
- Added Python→Dart real observation fixture and explicit phone capture action. Prices/timestamps cannot come from API callers. Quote model version is pinned; unversioned legacy snapshots remain viewable without inventing a historical model version. These remain synthetic observations, not market evidence.
- Added 11 observation/migration/isolation/tamper/causality cases; targeted research/database gate **52 passed**. PostgreSQL CI harness now exercises concurrent capture, immutable guards, cross-connection replay and account isolation, and retains its report artifact.
- Wave snapshots now verify persisted digest, scope, schema/source version, complete retained source hashes and audit linkage before restoring the tracker. Missing/corrupt history refuses reset. Added 13 tests, including real restart and preservation of nonempty wave-event history while new bars append.
- Full local Python gate **782 passed**, zero failed/skipped (one existing Starlette warning). Real HTTP/worker/journal restart smoke passed. Flutter tests/build require CI; build number 13 distinguishes the new observation UI. No signing secret or external trading connection was added.
- Remaining: local offline Demo Counterfactual and unified five-lab server analysis are partial; actual market OOS evidence, real expiry/exercise, stable signing/device upgrade and broker transport remain unproven.
## بوابة تسليم الدفعة الرابعة — تصحيح اختبار واجهة 2026-10-11

- المصدر `055f42c4aed2d1baaef199a4e38b6873ab1e63b2`: نجحت بوابة الخادم (Python/PostgreSQL/Compose) والأمان. فشل اختبار Flutter واحد على المنصتين عند البحث عن إشعار الحفظ الواقع خارج نافذة ListView الكسولة بعد التمرير لزر الالتقاط؛ طلب الالتقاط نفسه نجح.
- حُفظ سجل الفشل في `docs/evidence/engineering-20261011/flutter-observation-first-failure.jsonl`. صار الاختبار يعيد التمرير إلى الإشعار قبل فحص نصه، مع إبقاء فحص طلب POST الوحيد وغياب P&L المختلق كما هو.
- لا تغيير في منطق التطبيق أو الخادم. إعادة Flutter/Analyze والبناء في CI مطلوبة قبل قبول build 13؛ Flutter غير متاح محليًا. فحص diff ناجح.

## Engineering final acceptance and delivery checkpoint

- Widget correction published and read back at `67ddb6e7cf58cd59604ab7187a6864d527a69aac`. Android `38118890108`, iOS `38118890095`, and security `38118890093` all completed successfully. Runtime remains identical to `055f42c`, whose backend/Compose `38118532583` passed.
- Actual artifact parsing: **782 Python** local/cloud; **171 Flutter** on Linux and macOS each; zero final failures/errors/skips. Analyze passed on both platforms. PostgreSQL V1 **14** checks plus basic integration; backup/restore **10**; Compose **12**, migrations 1–5. No physical-device/emulator-install or upgrade test was run.
- Downloaded build 13 APK and unsigned iOS archive; CRC checked, APK hash matched CI, apksigner v2 proof retained, iOS plist/version/signature absence inspected. Android SHA-256 `07bb0061172e0cd8de62a03b5e05faf9639d3541f56fdccd2430e5b5b6c700f3`; iOS archive `00533a0a6b17350ee52aeed53cbc05562afd41fcd67cc9b6e6d5015f3e6c92a4`.
- Current security CI: zero pattern findings in 423 tracked files / 28 commits / 570 historical blobs; 24 Python dependencies and 43 Pub packages without known advisories at the check. Limits retained in the report.
- Fresh synthetic accounting and nine-fold walk-forward evidence saved; results do not prove real-market profitability. Counterfactual requires actually saved synthetic observations.
- Updated all delivery/recovery/test/security/backtest/requirements reports and added phone acceptance, IBKR readiness and engineering resume guides. Independent read-only safety review corrected manual Mock close freshness wording. Local links and diff checks passed. No new runtime edits in this documentation/evidence batch; no unnecessary rebuild or full retest.
- Additional persistent conversation-file upload failed before upload because helper authentication was unavailable. GitHub private artifacts (14-day retention) and local downloadable files remain available; no permanent file-service save is claimed. No private key or external account connection was introduced.
- Source and reports are saved on Recovery; completeness remains explicitly unclaimed. Resume from the actual remote head and the ordered gaps in `RECOVERY_REQUIREMENTS_V1.md`.
