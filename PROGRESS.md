# Progress — recovery/v1.0-20261011

## Independent market runtime batch 2 — process and Compose

- Batch 1 published/read back at `ea7f9e4cd26f2c4c5a52753753bd6254e6263aef`. GitHub backend/Compose `38267289325` and security `38267289373` succeeded on that source.
- Added a long-lived collector CLI with SIGTERM handling, safe DB reconnect, heartbeat healthcheck and explicit audited maintenance to reset a stopped collector's authentication lock. Its default performs no credential read or provider connection. Secrets require separate approval and an explicit private regular file; other-app/legacy key variables are ignored.
- Opt-in `infra/compose.market-runtime.yaml` adds a fourth non-root, read-only service. Only that service mounts the data secret; API becomes persisted-cache-only even if manual provider approval variables were inherited. Existing Synthetic worker remains separate. The profile is disabled by default.
- Targeted process/runtime/Compose guard tests: **44 passed**. Includes two real independent Python process starts against persisted SQLite, unchanged Demo account state, strict secret-file rejection and no API provider construction. Actual new Compose container stop/restart/PostgreSQL-outage scenarios are added to CI; not yet claimed run here. Existing base Compose acceptance is retained.
- No mobile source or user account connection. Persisted API inbox is implemented; mobile rendering/push delivery, qualified option simulation, long-running archival retention and actual independent server acceptance remain incomplete.

## Independent market runtime batch 1 — 2026-10-12

- Inspected current branch/reports at `119f0b3805392f8f090fcbb330b3f135894e3a15`; tracked source was clean. Reused the accepted Alpaca adapter, immutable journal, causal analysis pipeline and US calendar. No earlier work rebuilt.
- Additive migration 7: independent per-account collection/strategy settings, persisted collector lease/request budget/backoff, fair deduplicated symbol tasks, original-observation links, immutable analysis/error events and a durable API notification inbox with account-scoped acknowledgements. Controls require the existing operator bearer token and optimistic config version.
- Collection never invokes synthetic or external execution. Basic indicative option prices remain non-executable; no SL/TP/reversal fill is assumed during outage. No real-price virtual option ledger claimed. Credentials/production entrypoint and Compose wiring follow in a separate saved batch.
- A collector repository can opt out of the existing Demo reconciliation invalidation; default trading-process restart behavior is unchanged. Tests verify account/risk/watchlist/positions/orders/fills/marks stay unchanged.
- Local targeted runtime/journal/migration **69 passed**; full Python **982 passed**, zero failures/errors/skips, one existing Starlette deprecation warning. New cases exercise two SQLite connections, lease takeover/fencing, restart-persistent request/429/auth gates, failed connection/recovery, account isolation, stale/future/gapped bars, immutable events, config races and strict API inputs. Initial 68/1 targeted failure was a new test using an unsupported generic fills reader; corrected to an explicit DB assertion. No production failure hidden.
- No real Alpaca connection, other-app access, market orders, paid services, deployment or native build. Actual PostgreSQL/Compose acceptance for this batch is pending CI. This is a collector/analysis foundation, not operational 24/7 trading.

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

## Continuation batch 1: retain unresolved US expiration exposure

- Resumed from verified clean Recovery head `3a72226143944dd8985f14d82cc14afc45acbb8f`. No uncommitted changes or empty recovery commit; all earlier source, history and build 13 artifacts retained.
- Reproduced **22 failures** against an isolated export of that saved backend. Current implementation passes all **22** regressions: CALL/PUT final-session closes, DST/early/holiday cutoffs, partial close fees/basis, lost-response receipts, restart, review dedupe, reversal lock, missed ticks, unknown calendars, policy-change bypass and unaffected valid owned closes.
- US accounts now reject final-session BUY exposure, allow owned reductions until the modeled close, and retain unresolved quantity/basis/policy after cutoff without invented settlement or premium writeoff. Expiration facts are saved with decisions; review state is visible and blocks incomplete new-risk valuation even with fresh synthetic marks. Legacy synthetic fixtures and phone Demo remain unchanged.
- Pure policy: **46 passes**; combined targeted execution gate: **214 passes** before two final regressions were added; full local gate: **850 passes**, zero failure/error/skip, one existing Starlette warning. Real HTTP/independent-worker/process-restart smoke passed. Evidence in `docs/evidence/expiry-20261011/`.
- Initial compatibility run had one diagnostic-text failure (147 passed); existing market-session error ordering was restored without relaxing risk or expiry gates. Baseline logs are separated from the authoritative current acceptance.
- Expanded actual PostgreSQL acceptance harness from 14 to **22 checks** with two connections and concurrent review. Script dry run used SQLite only and is labeled accordingly; PostgreSQL/Compose and security CI remain pending publication.
- Official OCC/OIC/IBKR public documentation reviewed; modeled close-only protection does not implement real exercise, assignment, adjusted contracts or settlement. No IBKR/Paper connection, financial order, paid service, Live enablement, key or secret.
- This is a backend-only batch. No needless Android/iOS rebuild; build 13 does not gain local US-policy parity. Do not begin another feature batch before this checkpoint is pushed and its remote SHA verified.

### Continuation batch 1: cloud acceptance verified

- Pushed/read back and synchronized exact local/remote commit `381eec3cf2ed1454764d75ab51683dcf3634e453` before any next feature work.
- Backend/Compose run **38126076027** and security run **38126076071** succeeded. Downloaded artifact CRC and raw JUnit/JSON verify **850 Python**, **22 actual PostgreSQL V1**, **10 backup/restore**, **12 Compose** checks, plus real HTTP/worker/restart. Zero final failure/skip.
- Raw cloud evidence and source/run mapping saved in `docs/evidence/expiry-20261011/`. Security patterns: zero findings; existing dependency audits show no known advisories for 24 Python dependencies and 43 Pub packages at run time.
- Next bounded batch is phone-only manual Demo backup/restore; no backend or external broker feature is being added.

## Continuation batch 2: manual mobile Demo portability — awaiting cloud gate

- Previous expiry checkpoint `381eec3cf2ed1454764d75ab51683dcf3634e453` is saved and all backend/Compose/security gates passed before this independent phone batch.
- Added explicit clipboard JSON export, strict bounded/versioned import, immutable preview counts, and confirmation before replacing all local Demo accounts. Original order decisions/receipts remain intact. Current imported connection/trust/entry/automation permissions are reset conservatively; owned closes can execute only after local reconciliation and existing gates.
- Import serializes with saves, refuses stale target state, verifies persisted bytes before switching memory, and verifies rollback after save failure. Unverifiable rollback blocks ordinary writes/play while preserving export and explicit reload; missing/corrupt recovery reads preserve original memory.
- Read-only safety review found the same write-then-throw defect in ordinary `change()` saves. Applied the same verified persistence/rollback and uncertainty latch there, with two dedicated fault-injection regressions.
- Added **12 engine/store and 3 widget tests**, including actual Demo ledger roundtrip/reopen, pending permissions, invalid/future/cross-account/credential payloads, size limit, cancellation/clipboard/confirmation, storage failure and overlap. These are **authored, not locally executed**: Flutter is unavailable. Static diff check passed; CI analyze/tests/build must pass before acceptance. No Python runtime change, so no redundant backend/mobile-history retest is claimed.
- Build number is 14 in pubspec and both mobile workflows. Existing key provisioning remains unchanged; stable signing/device upgrades are still not available. Clipboard portability is manual, not a file writer/cloud sync or proof of physical-device durability. Initial corrupt-store recovery import remains a documented gap.
- Full instructions/limits: `docs/DEMO_BACKUP_V1.md`. Publish this tested-backend/pending-mobile checkpoint, then inspect CI and fix failures before delivery; do not start another feature.

### Continuation final acceptance — build 14

- Mobile checkpoint pushed, read back and synchronized at `c6345ceeb5a94642385aa6eacaaaca322554f29d`; no new feature began after it. Android **38126818937**, iOS **38126818914**, security **38126818920** all completed successfully.
- Parsed both downloaded Flutter JSONL artifacts: **186 successful visible tests on each platform**, zero failure/error/skip, final success=true; analyze passed. The 15 new tests include ordinary write-then-throw and failed rollback. Backend remains the accepted **850 Python /22 PostgreSQL /10 backup /12 Compose** at 381eec3.
- APK build 14 downloaded, ZIP CRC passed, checksum matched CI, CI apksigner v2 proof retained. SHA-256 `b567ae38c0e8df58a48b8799cd6dbb3fe746a8a9aa5ea3ff3d52333369dc2ef6`; 154973056 bytes; ephemeral runner development signature, no stable-key or install/upgrade acceptance.
- iOS archive downloaded/CRC checked, Info.plist confirms 1.0.0 build 14/minimum 15.0. SHA-256 `96a5c3589ee8b5ef6c82ef582dfcc86366fb940d9ee3df58a6772a45621c5e30`. Root Runner.app has no distribution signature; embedded framework CodeResources are separately recorded and do not establish IPA/TestFlight readiness.
- Latest security evidence: zero pattern findings across 485 tracked files /31 commits /666 history blobs; no known advisories at check time for 24 Python dependencies and 43 Pub packages. No new dependency or key.
- A fresh persistent conversation-file upload attempt failed before transfer because helper authentication was unavailable. No successful upload is claimed. Local downloads and private GitHub artifacts (expire 2026-10-25) are available; source/reports/evidence remain in Git.
- Updated delivery, test, safety, requirements, phone/backup/run guides and resume reports. This final batch is documentation/evidence only; mobile/backend runtime remains at the accepted commits above. No unnecessary rebuild or full retest.
- V1.0 remains incomplete: settlement/exercise/assignment, full server/chart parity, long-term wave archive, stable signing and device upgrades, initial corrupt-store import, reliable production alerts, actual broker transport and real-market OOS evidence remain explicit gaps.
# Phone repair checkpoint — baseline inspected

- Recovered and verified the exact Build 14 Recovery head `615576768612c1c7cbd008632b325be05c57c774`; no unavailable prior-session edits are claimed. Preserved the full remote tree and history.
- Inspected chart analysis, wave journal, painter, Demo engine, existing tests, build/signing and previous delivery reports. User phone findings are now recorded separately from CI evidence in `docs/PHONE_BUILD15_REPAIR.md`.
- Identified missing MACD/divergence drawing, unlabeled/off-screen chart geometry, mutable-engine follow cursor issue, and strict plateau pivot suppression. Monotonic baseline data can legitimately have no wave/harmonic result.
- Documentation-only checkpoint: exact recovered blob SHA verification and whitespace review; no runtime changes or new test counts. Next batch adds targeted regressions and bounded chart repairs. New preview must use a separate application identity and preserve Demo schema.
# Phone chart repair — implementation checkpoint, CI pending

- Previous documentation checkpoint `a3b8439212a57393d3f4332d665c9a4099260e11` was pushed and read back before runtime edits.
- Added rightmost equal-extremum confirmation, calculated MACD/signal/histogram with warmup, typed causal divergence endpoints and ratio-based harmonic PRZ distinct from invalidation. Controlled continuous-OHLC wave/ABC/Bat/divergence samples are explicitly display-only.
- Chart now follows a mutable engine only in follow mode; historical decision replay remains pinned. Added visible empty states, primary/alternate labels, fitted 360-pixel canvas, shared observation axis, completed 1/5/15-observation aggregation, zoom/reset, separate RSI/MACD scales and divergence connectors.
- Authored nine semantic/data/widget regressions and six light/dark canvas golden cases. No local Flutter SDK: actual execution is pending the targeted CI workflow. Initial goldens are DRAFT images for inspection, not accepted comparisons. Android/iOS packaging is skipped for `[chart-check]` checkpoints; existing non-golden Flutter tests still run in the targeted job.
- No Demo storage schema, account risk, execution engine, broker, market data feed or existing signing key was changed. `git diff --check` passes. Publish this bounded checkpoint, inspect CI, repair failures, then commit reviewed golden baselines before further features.
### Chart gate correction 1

- Targeted run `38178300373` stopped in analyze on two required brace-style findings in the new painter; compilation reported no type/syntax errors. Semantic and golden tests did not run and are not counted as passing.
- Added explicit braces around both conditional drawing loops. No behavioral change. Re-run the same gate; packaging remains disabled for this checkpoint.
### Chart gate correction 2

- Run `38178458939`: analyze passed; **194 visible tests passed, one new timeframe widget test failed**. Raw evidence retained. The new 5× selector exposed the wave journal's original 1×-only fixed-origin validation.
- Added an explicit journal observation factor, saved/restored with causal events, while retaining exact fixed-origin spacing and rejecting missing groups. MTF summaries still aggregate the original prefix once. Added a direct journal restore/gap regression; re-run required before chart acceptance.
### Chart acceptance and isolated safety exercise checkpoint

- Chart run `38178794977` at `bd65ec573f056a212618b4c651db93577bca6c1f` passed analyze and **196 visible Flutter tests**, zero final failure/skip. Downloaded/CRC-checked and parsed the raw machine results. All ten new chart regressions and the prior 186 tests passed.
- Six light/dark draft golden renders succeeded and were visually inspected. Geometry shows primary/alternate, Bat PRZ, RSI and MACD divergence. Default test Ahem glyphs are squares; the next run loads the pinned SDK's Roboto font to review readable labels before committing strict comparison baselines. Draft generation is not a golden comparison pass.
- Added a phone-accessible isolated safety exercise screen. It calls the actual local engine for SL/TP/trailing and both reversal directions, including actual quantitative signals, partial closes, loss of response, repeat keys, disconnect, serialized restart, reconciliation-before-entry and receipt ordering. It never receives the user's engine or store. Fixture risk settings are stated explicitly; user settings are not changed.
- Seven new safety tests are authored and await CI, including a disabled-execution negative control and phone-route/no-network/byte-for-byte persistence isolation. Chart layer toggles now have semantic integration assertions. No broker, financial data, Live or storage schema change.
### Safety/golden gate correction

- Run `38179057559` stopped on one redundant import in the readable-font golden test; no safety tests were executed in that run. Removed the import without disabling analysis rules.
- Initial visual review showed D/PRZ label bands were too close. Moved the PRZ caption below its shaded band; the next draft golden will show readable text. Runtime safety exercise code has not changed since the saved checkpoint.
### Safety accepted; readable golden review and isolated packaging preparation

- Run `38179195664` at `0307ec5ba262f2f05884ad43c5557bcc0cd16012` passed analyze and **203 visible Flutter tests**, zero failures/errors/skips. Raw JSON downloaded and CRC checked. Five actual isolated engine exercises pass, as do the negative control and phone-route network/storage isolation checks.
- Six readable Roboto golden drafts generated and were inspected. The review identified overlapping RSI/MACD price captions; deduplicated the shared price segment and moved each indicator caption into its own pane. This painter-only change uses the affected chart/wave tests; all Flutter tests will run again at the final Android/iOS acceptance gate.
- Prepared Build 15 as a separate `com.optionsaitrader.options_ai_trader.v1previewrc2b15` app, launcher label `Options AI Trader Lab 15`. Added a fail-closed check of actual APK badging and retained cryptographic signature verification. Build once per final gate, with the available private development key or an explicitly identified ephemeral SDK development key. No key enters Git/artifacts.
- Added Arabic coexistence/backup/import/phone exercise instructions. No native build or phone installation of Build 15 has run yet. Golden comparison remains pending readable baseline approval; `[chart-check]` still prevents premature Android/iOS packaging.
### Reviewed golden baseline checkpoint

- Final painter-caption run `38179500439`: analyze and **23 affected chart/wave tests** passed. Six readable light/dark drafts generated successfully; all reviewed. ABC/Bat image bytes exactly match the earlier reviewed drafts; both divergence images now separate RSI and MACD captions by pane.
- Committed all six PNG references with a review README and raw targeted evidence. Changed CI from explicit draft generation to strict comparison with **no `--update-goldens`**. Android packaging now also requires that strict six-case comparison on its own source commit.
- Documentation distinguishes fixed bugs, legitimately absent results, incomplete features and tests not run. Full source and phone instructions are saved; the next gate must pass strict comparison before starting native packaging. No claim of a built/installed Build 15 yet.
### Strict chart acceptance; final native gate started next

- Saved/read-back golden checkpoint `49a485d6395dbf40bd5869ea84918d45133f4d77`. Run `38179859625` passed analyze, **23 affected tests and six strict golden comparisons**, with no baseline regeneration. Downloaded/CRC-checked and parsed both machine reports.
- Existing backend workflow was triggered by the signing-script diagnostic update: run `38179500360` passed **850 Python**, **22 actual PostgreSQL V1**, **10 backup/restore**, **12 Compose** checks and HTTP/worker/restart smoke. The backend runtime was not edited. Saved actual current artifacts instead of assuming earlier counts.
- Security `38179859622` passed: zero pattern findings across 519 tracked text files /40 commits /744 historical blobs; no known advisories among 24 pinned Python dependencies and 43 Pub packages at the check. Scanner limitations remain explicit.
- Updated the stale mobile README from its old V0.4 title to the actual RC2 Lab 15 operation and installation paths. This documentation-only mobile change opens the final native gate after all runtime/strict chart checks passed. Android must pass all 203 semantic tests, six strict goldens and actual APK identity/signature checks. iOS must pass all semantic tests and its unsigned macOS build. Binaries remain pending until those runs finish.
### Native delivery checkpoint — iOS complete, Android packaging pending

- Final native source is `c5033ab2e108b18de1b873652d911b226b7770a8`; subsequent report commits do not change runtime or require rebuilds.
- iOS run `38180059417` passed analyze, **203 Flutter tests**, and the actual macOS unsigned release build. Downloaded/CRC-checked artifact `11716364660`; archive SHA-256 matches GitHub: `8e8ed878943b274cb2d5fc224eefd046284eb1e4babae1fa6779ec5aa45f065d`. Inspected plist: version 1.0.0/build 15, minimum iOS 15.0; root app distribution signature resources absent. No IPA/TestFlight/device claim.
- Final chart run `38180059538`: **23 targeted tests and six strict comparisons** passed. Final security `38180059442`: zero findings /531 tracked text files /41 commits /758 historical blobs; 24 Python and 43 Pub packages without known advisories at check time. Exact reports and run mapping saved.
- Android `38180059532` has passed analyze, semantic Flutter tests and strict golden comparisons, and is currently assembling the APK. Do not claim artifact acceptance until package/version/signature verification and local SHA-256 comparison finish.
- One temporary local execution transport interruption occurred during evidence download; retried successfully. All source was already pushed; no feature work or source was lost. Continue from this report checkpoint without rebuilding passed jobs unless the remaining Android gate fails.
### Final Lab 15 delivery — all software gates passed

- Android **38180059532** completed successfully on native source **`c5033ab2e108b18de1b873652d911b226b7770a8`**: analyze, **203 Flutter**, **six strict golden comparisons**, build, actual APK identity and apksigner v2 verification. Parsed final JSON: zero failure/error/skip. No source change after the accepted build.
- Downloaded artifact **11717805640**; archive SHA matches GitHub and CRC passes. Extracted APK is **155006308 bytes**; local SHA-256 matches CI: **`ae1f4db787fe19aefaba3dd2382c9caf7e0a368503c66e53c84749b8bd31a3ee`**. Inspected 1.0.0/build 15, API 24, three ABIs, separate `.v1previewrc2b15` identifier and `Options AI Trader Lab 15` label. Development signing is ephemeral, not stable upgrade certification.
- iOS build/203-test acceptance and archive inspection were already saved in `790b8e685de9accc92eff67efed834bd5120b662`. Final strict chart and security evidence are on the same native source. Backend/real PostgreSQL/Compose acceptance is mapped separately to its unchanged runtime.
- Finished the four-category diagnosis, requirement limits, test/security reports, install guide and source/run/hash manifest. Original user phone passes remain Build 14 observations. Build 15 physical-device install/coexistence/gestures/import/restart and TestFlight remain **not run**. V1.0 completeness/profitability is not claimed.
- Source/reports and every bounded repair checkpoint are on Recovery. Artifact downloads expire **2026-10-25**. A fresh additional permanent-file save attempt failed before upload because authentication was unavailable; no successful extra upload is claimed. Local download copies and private GitHub artifacts are available. No secret, broker connection, Live activation or paid service was introduced.
- Stop adding features in this session. Resume with the user's Lab 15 device results and the ordered gaps in `PHONE_BUILD15_REPAIR.md` / `RECOVERY_REQUIREMENTS_V1.md`; do not rebuild or repeat passed gates without a code change or a concrete failure.

### 2026-10-12 continuation — initial unreadable Demo recovery checkpoint

- User requested continuation. Verified clean local/remote Recovery head `2260e5baa7ec7c4cd3579bff07dec277a399dd9a`. Build 15 phone acceptance is still not reported; its accepted binary/source remain preserved. No unsaved changes needed recovery.
- Confirmed a documented gap: a decode failure on initial load disables the existing import menu. Added a separate initial recovery path using the existing strict backup validator and permission-pausing import. No engine, risk limits, account schema or original ledger evidence changes.
- Before replacement, retain and read back the exact unreadable original under a separate immutable preference key. Refuse a different pre-existing recovery copy, unsupported archive storage, failed reads, changed disk state or archive mismatch. Verify replacement, roll back exact original on failure, and latch writes if rollback is uncertain. Preserve/export valid memory if an ordinary later reload fails. Preference reads now refresh the plugin cache before verification.
- UI offers explicit raw-original copy, backup inspection/cancel/confirmation and archive export after recovery. No automatic clipboard read or network call. A single immutable archive slot intentionally blocks another different damaged original; no destructive reset/delete bypass is offered. SharedPreferences is not an atomic multi-process or power-loss transaction guarantee.
- Authored controller/adapter/widget failure-injection regressions plus existing persistence regressions in `.github/workflows/demo-recovery.yaml`. No local Flutter/Dart SDK: only whitespace review executed locally; CI tests are **pending**, not claimed as passes. Publish this bounded checkpoint with `[chart-check]` to avoid premature native packaging, inspect actual CI, repair any failures before the acceptance gate.

### Recovery gate correction and missing-snapshot guard

- Checkpoint `7165cca807c4a7d0e99f92f37f1df8a08260094a` pushed/read back. Recovery run `38205010875` stopped at analyze: missing explicit archive-interface cast and one required brace. Tests did not execute. Corrected both; no analyzer rule disabled.
- Review also found that a missing disk snapshot after an earlier load could bootstrap replacement accounts. Now only first-ever empty storage bootstraps defaults; a previously read original or valid memory is retained. Initial bootstrap also verifies readback before enabling simulation. Added three regressions for both missing-state paths and incomplete first write.
- Re-run the targeted gate on this saved correction before packaging. No runtime outside the Demo storage/UI path changed.

### Initial recovery accepted — checkpoint before native packaging

- Correction `3ae10f85fe472f3a887761b354751c63d3c4ba53` pushed/read back. Targeted run **38205166729** passed analyze and **102 visible Flutter tests**, zero failures/errors/skips. Artifact **11726728614** downloaded, SHA-256/CRC verified, raw JSONL parsed and preserved. Chart **38205166732** and security **38205166880** gates also succeeded.
- Saved `docs/DEMO_RECOVERY_V1.md`: explicit recovery steps, immutable original copy, fail-closed cases, single archive-slot limitation, no device/power-loss/multi-process guarantee. No engine/financial logic or Demo ledger schema change.
- The next bounded batch prepares a separately identified Build 16 and runs the complete mobile acceptance gate once. Build 14/15 binaries and app data remain independent; no in-place upgrade under an ephemeral key is promised. Native build and physical-device tests for Build 16 are not yet executed.

### Build 16 packaging gate prepared

- Accepted evidence/report checkpoint `863148cd1a92592f0ee09b57aff888742e17d731` pushed and read back before this batch. Changed only native preview identity/version and related delivery instructions: `.v1previewrc2b16`, `Options AI Trader Lab 16`, build 16. No further Demo runtime change since the passing targeted source.
- The identity verifier locally accepted synthetic Build 16 badging and rejected Build 14, Build 15, and a wrong-package candidate with a matching label/version. Actual binary verification remains required in CI; these checks do not prove installation.
- Added `PHONE_BUILD16_INSTALL_AR.md`: preserve both prior apps/data, compare checksum, manual backup/preview/cancel/import, never damage real data to test recovery. Stable signing remains unconfigured unless existing CI Secrets supply the private key; no key or secret is added to Git.
- Publish to start the full Android/iOS mobile gate. No new feature will begin while packaging/acceptance is unresolved. Recovery targeted proof remains 102 passes; full Flutter count and APK/iOS hashes are pending the actual runs.

### Native gate in progress — security evidence saved

- Packaging source `b38b03daab15c70f9a076b1def27b55eae4347b2` pushed/read back. Android **38205487162** passed analyze/full semantic tests/strict goldens and is building; iOS **38205487135** is running its full tests/build gate. No artifact or physical install acceptance claimed yet.
- Final-source chart **38205487142** succeeded. Security **38205487148** artifact **11726559425** downloaded with SHA-256/CRC verification: zero pattern findings across 552 tracked text files /47 commits /806 historical blobs; no known advisories for 24 Python and 43 Pub dependencies at check time. Saved actual JSON reports, security explanation and updated requirement gap.
- Backend runtime has not changed and was not re-tested in this batch; previous accepted 850 Python/22 PostgreSQL/10 backup/12 Compose evidence remains separately mapped to run 38179500360. Do not present these as new executions.
- This checkpoint is documentation/evidence only. Continue awaiting existing native runs; do not rebuild them or add features while delivery is pending.

### Build 16 iOS accepted; Android still building

- iOS **38205487135** passed analyze, **222 visible Flutter tests** (the prior 203 plus 19 new recovery/controller/widget regressions), zero failure/error/skip, and its actual macOS unsigned build. Downloaded artifact **11727431974**; CRC and SHA-256 match: `bc97aed102bf8f828e4d9d667eb61606728306087c60af23c5499cb1909d640b`, 7899317 bytes.
- Inspected actual plist: 1.0.0/build 16, minimum iOS 15.0, bundle `com.optionsaitrader.optionsAiTrader`; root distribution signature resources absent. No signed IPA, TestFlight or iPhone installation is claimed. Saved raw machine tests, plist inspection and source/run manifest.
- Downloaded final-source chart artifact **11727127014** and parsed **23 targeted passes +6 strict golden passes**, zero errors/skips. Source remains `b38b03daab15c70f9a076b1def27b55eae4347b2`; following report commits do not require rebuilds.
- Android **38205487162** has passed test gates but is still building. Continue artifact identity/signature/hash inspection when it completes; do not infer the APK result from iOS success.

### Final Build 16 delivery — software gates accepted

- Android **38205487162** completed successfully on source **`b38b03daab15c70f9a076b1def27b55eae4347b2`**: analyze, **222 Flutter**, **six strict Golden comparisons**, build, actual APK identity and v2 signature checks. Raw results parsed: zero failure/error/skip. No runtime edit followed this accepted build.
- Downloaded artifact **11727516320**; ZIP SHA-256 matches GitHub and ZIP/APK CRC pass. APK **155014268 bytes**, local SHA-256 matches CI **`387511db63af45e435a72be681f80158588d3b83e8c4cc4e95ef8ffa75b07247`**. Rechecked actual aapt data with the identity verifier: `.v1previewrc2b16`, label Lab 16, version 1.0.0/code 16, API 24/target 36, three ABIs. Development signing is ephemeral; no in-place upgrade claim.
- iOS **38205487135** and its 222 tests/unsigned macOS build were accepted and saved in `07fb3f6936971edc687917d2f7d43efe1e675cbd`. Both native artifacts, checksums, provenance, signing/plist inspection and source/run mapping are recorded. Android/iOS artifacts expire **2026-10-26**.
- A current Library prepared-upload helper attempted the ordered APK/iOS/checksum save and failed before transfer because authentication was unavailable. No files were claimed saved there; no direct-write bypass or credential probing. Local downloads and private GitHub artifacts remain available; source/reports/evidence are in Git.
- Updated final delivery, recovery/resume guide, four-category report, requirements, test and safety reports. The initial recovery gap is closed within the explicit single-original-slot scope. Backend/Backtesting were unchanged and not re-run. Device installation/coexistence/upgrade/power-loss, stable signing and TestFlight remain not run/unavailable; V1.0 is still incomplete.
- All source batches were pushed and read back before the next batch. This final checkpoint is documentation/evidence only. Resume from the actual Recovery head using `docs/BUILD16_RESUME.md`; preserve earlier apps and reports. No broker, Live, financial data, paid service, secret key or unrelated project was introduced.

## Alpaca batch 0 — source checkpoint

- Baseline `8161c458a4734eeb26839e95dd7b16379acaf1ac`, recovery branch preserved. Exact source/tree hashes verified; no local edits existed to rescue.
- Reviewed official Alpaca US documentation: Basic IEX versus consolidated SIP; indicative option quotes are modified and trades delayed, not executable OPRA. Will use bounded shared REST cache/polling and no stream connection to avoid competing with the other app.
- Documentation-only checkpoint: no new runtime code, account connection, credentials, market-data fetch, or tests claimed. Next batch: provider protocol, fixed data-only transport, mock/documented fixture tests and safe API integration.

## Alpaca batch 1 — isolated Basic data adapter

- Batch 0 published/read back at `9b72e0caa3c44d71000ccb74ae0fc754108ca0f5`.
- Added a provider protocol and fixed HTTPS GET-only transport for Alpaca Market Data. No trading adapter dependency, orders, account endpoint, streams, redirect following or external app configuration discovery. Activation remains disabled without a separate operator approval setting.
- Explicit IEX quotes/trades/OHLCV; Basic indicative chain snapshots with nullable provider Greeks; delayed historical option bars. Per-result provenance, timestamps, age, completeness and usage notice. No feed auto-upgrade or synthetic price fallback; all option fills remain blocked.
- Shared bounded REST cache (128 entries), concurrent request deduplication, default 30 requests/minute, provider headers/429 cooldown, bounded read retries and terminal auth/entitlement circuit. Budget is local to one provider process; cannot see the other app's usage. No streaming implementation is claimed.
- Local offline targeted test: **55 passed**, zero failed/skipped. Includes fixed-host transport mocks, no-network guard, documented AAPL IEX historical example, no future/unclosed bars, DST completion, missing/modified options, concurrency, reconnect and rate limits. Evidence: `docs/evidence/alpaca-20261012/adapter-targeted.*`.
- Not yet connected to the API or mobile at this checkpoint. No actual account credentials/connection, OPRA entitlement, out-of-sample study or profitability claim.

## Alpaca batch 2 — account-scoped API and virtual execution lock

- Adapter batch published/read back at `e7f179a5306b69654224b56d55e21ae479419af4`; GitHub backend/Compose run `38222631771` and security run `38222631809` succeeded. Exact result counts will be checked at the final gate.
- Added authenticated `/market-data` endpoints under each account for status, IEX snapshots/history, indicative chains and delayed option history. Existing per-account watchlist symbols, including disabled synthetic symbols, can be read without granting synthetic execution permission. Unknown accounts/symbols are rejected before provider calls.
- Separate `real_market_virtual` namespace is explicitly `ANALYSIS_ONLY` for Basic options. Its virtual-order gate always rejects; it cannot call the existing synthetic submit/fill path or any external order endpoint. It audits the reason and refuses caller-supplied prices/broker overrides. No new trading ledger or migration, no modification of user risk settings.
- Offline API/adapter/critical regression gate: **86 passed**, zero failures/skips; existing Starlette TestClient deprecation warning. SQLite integration checks authentication, account scope, unchanged Demo ledger/risk, restart persistence and blocked duplicate attempts. Evidence in `docs/evidence/alpaca-20261012/api-targeted.*`.
- No real Alpaca connection, keys or account entitlements validated. Mobile integration and final gates are next.

## Alpaca batch 3 — mobile integration checkpoint for runner validation

- API batch published/read back at `a4fde3de96775128d51eaaa5add925611b9fba4d`. Full local Python gate on that source: **919 passed**. Initial attempt was 917 passed/2 missing-file failures because DATABASE.md and HTTPS Compose had not yet been materialized; recovered exact originals, then all passed. No runtime fix was needed for those environment failures.
- Added a separate real-market screen reachable from the server dashboard. It uses GET-only account-scoped observations, explicit source/delay/missing-data notices, nullable Greeks and OHLCV candles with zoom/pan. No Demo store/engine writes, Alpaca credentials field, fill button or broker client. Changing accounts invalidates late responses.
- Added a shared Python-produced mock-transport contract fixture and Flutter parser/widget tests. Python fixture/API integration: **15 passed**. These are mock observations, not actual account market data.
- Flutter SDK is absent locally and the official SDK/archive metadata download returned HTTP 404 in this environment. Saving this small checkpoint to run the dedicated Flutter analyze/targeted-test CI; mobile acceptance is **pending**, not claimed passed. Native APK/iOS builds are intentionally skipped until that gate succeeds.

### Mobile preflight correction and private connection guide

- Mobile checkpoint `b5cad48e39cbeaab0729c68e8749983f8b69df23` saved/read back. Runner `38224122195` stopped in analyze on three const-constructor lints in the same static notice; tests were not executed and are not counted. Added the outer const without changing behavior and rerunning the focused runner.
- Added `docs/ALPACA_DATA_V1.md`: Basic capability/source limitations, account namespace, option-fill block, shared-account request budget limits, explicit no-redistribution grant, point-in-time history limitation and private connection procedure requiring separate approval.
- Added an opt-in Compose overlay passing dedicated credentials only to API. Default Compose and worker stay unchanged; the overlay has not been used to connect to any account.

### Mobile test viewport correction

- Checkpoint `7dc4f00bef78dbe149af8dbed1a714b17ba60c70`: analyze now passes. Focused runner `38224616335` reached tests; one widget expectation queried a lazily rendered result below the visible scroll viewport. Parser, account-race, disabled connection, history rendering and error cases passed.
- Updated that test to scroll to the actual price/Greeks rows before asserting. No production data or risk logic changed. Preserved the failing machine log in `mobile-preflight2/market-data-tests.json`; native builds remain gated until success.

## Alpaca batch 4 — native acceptance gate

- Widget correction published/read back at `03dc0d1fbecb18e25178d696c8c3c4a9675a7e86`; focused Flutter runner **38225000099 succeeded** (analyze + market-data/API tests). No more production mobile changes after the const notice correction.
- Preparing Lab 17 with distinct Android identity `.v1previewrc2b17`, launcher name `Options AI Trader Lab 17` and version code 17. Prior Build 14/15/16 apps and storage are not replaced. Signing remains the existing private-development-key path, or explicitly reported ephemeral runner development key; no key is added to Git.
- Requesting the full existing Flutter/strict chart Golden + Android APK gates and macOS unsigned iOS build on this source. Their results remain pending until checked. No device installation or real Alpaca connection is claimed.

## Alpaca final delivery — verified Lab 17

- Native checkpoint published/read back at `55b4940cc6cbd237a1ea93478bef768c9c0380db`. Android `38225336664` and macOS/iOS `38225336649` succeeded: **242 Flutter each**, 6 strict Android Golden, analyze and build passed; no failures/skips. Downloaded and CRC-verified both artifacts.
- Android 155041108 bytes, `.v1previewrc2b17`, code 17, ephemeral development signature; APK SHA-256 `1c88d97a88714bdd81fcd8b284fd20a06f4a81b03dc5ae5a6b092f367acee071` matches CI. iOS Runner.app 1.0.0/17 (iOS 15+) is unsigned for distribution; archive SHA-256 `332e874e7877641b5845f494af233d88d4a09a7e37b64e14ab7b34028d688ec6`. No physical installation claimed.
- Final Python: **920 passed** locally and in CI; 70 Alpaca cases are included. Actual PostgreSQL 22, backup/restore 10, Compose 12 and HTTP/worker/restart passed on backend run `38224616312`. Shared contract tests and viewport correction: focused Flutter 31 passed.
- Security run `38225336652`: zero pattern findings (589 tracked text files /57 commits /873 historical blobs); 24 Python and 43 Pub dependencies with no known advisories at query time. Not a comprehensive vulnerability assessment.
- Reports, requirement statuses, connection procedure, phone guide, backtest limits, failure history and raw text evidence saved in Git. Android/iOS artifacts expire 2026-10-26. Latest delivery commit only documents the verified source; no additional feature or rebuild is needed.
- Real account connection, other-app access, financial orders, Live/Paper/IBKR, paid services and key handling were not performed. Basic indicative options remain monitoring-only; local virtual execution over qualified real option quotes and full V1.0 completion remain unclaimed.

### Delivery receipt verification

- Delivery reports and raw acceptance evidence published/read back at `7520fb848776c277005ce6837f9b37a9b0b66981`. Added the exact CI APK checksum file to the source evidence manifest and a machine summary of the initial missing-prerequisite failures. Manifest SHA-256 values rechecked; no runtime changes or extra rebuild.
- All source/report edits are committed; remaining local untracked files are intermediate logs/download ZIPs, not uncommitted application changes. No previous files or Git history deleted.

## Market data journal batch 1 — 2026-10-12

- Recovered latest remote `cfff75b71f3400160156a1647d36d00e57bcf695` and exact tree from GitHub. No previous workspace checkout or uncommitted source survived; no unavailable session edits are claimed recovered. Recovery branch/history and unmaterialized files are preserved.
- Added an explicit account-scoped capture/list/replay API and additive migration 6. Immutable original observations, SHA-256 integrity, original source/missing values, server-recorded availability, idempotent requests and transactional audit. No automatic GET persistence, no trading or analysis coupling.
- Before changes: 70 existing Alpaca tests passed. Targeted archive/migration/Alpaca: 120 passed. Full local Python on corrected code: **963 passed**, zero failures/errors/skips, including 43 new journal cases.
- Initial targeted test: 49 passed/1 failed because a test helper consumed an intended forbidden field; corrected the request construction. First full gate: 959 passed/4 failed (one new test import relative to wrong cwd; three missing original mobile fixture/signing-script prerequisites). Corrected import, recovered exact missing originals, reran full gate successfully.
- PostgreSQL/Compose and source/dependency CI for this commit are pending publication, not claimed rerun. Next batch extends actual PostgreSQL race and backup/restore acceptance for the new journal.
- Flutter/APK/iOS sources unchanged; Lab 17 remains the latest accepted phone build. Journal UI, actual provider connection, point-in-time market backtesting and qualified real-option virtual execution remain incomplete/unperformed. No other app access, credentials read, Alpaca/IBKR connection or financial order.

## Market data journal batch 2 — storage acceptance

- First feature batch published and verified at `3fc090a9d24a9dc69289fd140d6a965ba63c88e8`. Existing backend/Compose workflow `38260160654` and security workflow `38260160771` succeeded on that source.
- Added six disposable two-connection database acceptance scenarios for journal idempotency, native immutable guards, account foreign keys/isolation, causal availability and atomic audit rollback. Local execution against two SQLite connections passed; PostgreSQL execution is gated in CI, not conflated with that local run.
- Extended actual PostgreSQL backup/restore fixture to include the original market receipt and verify restored UPDATE/DELETE protection. Checks run only against an explicitly acknowledged disposable local/container database; no market transport.
- Targeted journal + backup tool tests: **97 passed**, zero failures/errors/skips, including one new multi-connection acceptance test. Python compile and whitespace checks pass. Full Python count is expected to increase by one, pending the CI result.
- No runtime/API behavior changed in this batch; no native build requested. Source and evidence are saved before subsequent work.

### PostgreSQL backup acceptance correction

- Storage checkpoint `a42021b718a5510978570983cc30d36ee6c1958d` published/read back. CI `38260543598` passed Python, existing PostgreSQL checks, all six new journal PostgreSQL scenarios and Compose. The backup step **failed**, so its expanded acceptance remains unpassed.
- The failure was a name collision in the test harness: importing the journal fixture function replaced the existing database connection variable named fixture. Corrected to an explicit market_journal_fixture alias; production archive/backup APIs are unchanged.
- Retained the actual traceback in docs/evidence/market-journal-20261012/preflight/backup-failure.txt. Targeted journal and backup-tool tests rerun: **97 passed**. Publishing correction to repeat actual PostgreSQL backup/restore CI; no new feature started.

## Market data journal — accepted delivery

- Correction published/read back at `54cdf16952a9253fb5c4abbd795fa85ba60720e1`. Full CI `38260912057` now **succeeded**: 964 Python / zero failures/errors/skips; 22 existing PostgreSQL +6 new actual two-connection journal checks; 12 actual PostgreSQL backup/restore; 12 Compose. HTTP/worker/restart and synthetic lifecycle scripts passed.
- Downloaded final backend and Compose artifacts; checked ZIP CRC and exact API SHA-256, read JUnit and JSON results. Final security `38260911861` passed (622 tracked text files /62 commits /928 historical blobs, zero pattern findings; 24 Python +43 Pub dependencies with no known advisories at query time). Scope/limitations and the failed backup run are retained.
- Complete report/API guide, remaining gaps, safe database-upgrade note and raw evidence saved under docs/MARKET_DATA_JOURNAL_V1.md and docs/evidence/market-journal-20261012/. Latest receipt commit changes documentation/evidence only, not tested runtime.
- Native source is unchanged: no extra Flutter, Android, iOS or device testing claimed. Lab 17 remains latest APK with its prior checksum/signature limitations. New journal UI, actual account connection, qualified option execution and full V1.0 remain incomplete. No secrets, account access, trading commands, paid services or changes to the other application.
