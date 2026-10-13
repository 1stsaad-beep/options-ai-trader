# Direct Alpaca Lab20 — recovery and staged implementation

Recovered on 2026-10-13 from `67995126bd095e3e3bbbae2d74e9d19e0e2c8207`, branch `recovery/v1.0-20261011`. All 944 tree entries preserved. Source text verified against Git blob IDs. Local workspace had been removed by maintenance; no unsaved earlier-session work can be claimed recovered. Lab19 remains the accepted prior Android release.

## Batch 1: native read-only boundary (acceptance pending)

- AES-GCM AndroidKeyStore vault, randomized IV and authentication tag, atomic ciphertext in `noBackupFilesDir`. No reveal method. Android memory/runtime compromise can still expose credentials; background access intentionally has no per-read biometric prompt.
- Fixed HTTPS GET stock bars endpoints and stock WebSocket endpoints only. No broker SDK, configurable host, trading verb, order/cancel/replace API or credentials sent to project servers. Redirects and automatic HTTP retries disabled. No request/response logging.
- IEX/SIP selection explicit; SIP authentication/entitlement failures are not silently downgraded. REST maximum six calls/minute across symbols, conservative 5-minute cooldown after 429, bounded retry and cache. One optional process-wide stream, disabled by default, connection-limit 406 stops reconnect attempts and retains REST. Other apps/account usage is not observable or controllable.
- Validated complete minute OHLCV only; duplicate/revised timestamps replace cache rows. Original decision persistence is a separate forthcoming UI layer. Rolling 600 bars per symbol is a chart cache, not a permanent archive.
- Native mocked policy/transport tests added; CI will establish actual result. No Android SDK/Flutter/JDK is available in the recovered local environment. No actual provider request was made.
- UI, native vault device verification, background service, charts, APK and Market Paper account controls are not yet accepted.

## Official references checked 2026-10-13

- https://docs.alpaca.markets/us/docs/about-market-data-api — Basic: IEX equity coverage, 30 stock symbols, 200 historical requests/minute; indicative options rather than OPRA. Historical entitlement limits apply. This client uses a smaller local budget, not a reservation on a shared account.
- https://docs.alpaca.markets/us/docs/streaming-market-data — authentication, subscription acknowledgements, connection-limit 406, entitlement 409.
- https://docs.alpaca.markets/us/docs/real-time-stock-pricing-data — closed one-minute bars and late updatedBars, extended-session bars.
- https://docs.alpaca.markets/us/reference/stockbars — historical OHLCV endpoint.
- https://developer.android.com/reference/android/security/keystore/KeyGenParameterSpec.Builder — GCM randomized encryption and authentication settings.
- https://github.com/square/okhttp/blob/master/CHANGELOG.md — OkHttp changelog; initial 5.5.0 pin corrected to 5.3.2 for compileSdk 36 compatibility.

No OPRA entitlement, true provider connectivity, profitable backtest, actual phone service survival or realistic option fills is established by mocks.

Concurrent checkpoint 3bc4345d574f2be16340c214ca595bd68d730af1 was detected and preserved. Its Java policy/tests and original vault format remain intact; additional bounded cache/transport tests extend that work. Our checkpoint 2c4350f051488a586f66d79c1ffaa8ca8b439c11 is also preserved on recovery/direct-alpaca-lab20-20261013.

## Concurrent writer detected; isolated acceptance

The target branch advanced again to `157b91ccf21cd35b1a722d1a54ceca13abe54d19` during the second lease check, with another transport/service implementation. Neither attempted lease replaced that work. Our merged checkpoint is `a96d35f47a989271d0ee9d5839f3e881e65a17f3` on `recovery/direct-alpaca-lab20-20261013`, preserving the earlier concurrent checkpoint and our source. This branch is experimental and must not be blindly merged: AlpacaEngine and the independently added AlpacaSession overlap. Native mock CI on this isolated branch will verify its checkpoint; no new APK or UI is claimed. Reconcile against the actual target head after the concurrent writer stops.

## Actual failed acceptance retained

Run 38403905558 at b9c09da6fe9ceb39ff147ca81c10bbaed825fef1 passed Flutter analysis but failed Android AAR metadata: OkHttp 5.5.0 requires compileSdk 37 while the established Flutter/AGP toolchain compiles SDK 36. Unit tests did not run. Corrected the dependency to 5.3.2 (the documented timeout-fix release), preserving the existing toolchain; next targeted native run must pass. This is not a provider authentication failure.

## Final isolated acceptance receipt — 2026-10-13

Accepted native source: `2c698c697ecb60195ff32935f81530b0814518b0`, isolated branch `recovery/direct-alpaca-lab20-20261013`. GitHub Actions run **38404976275** succeeded: **11 native JUnit Mock tests**, 0 failures, 0 errors, 0 skipped; `flutter analyze` passed. The conditional Flutter direct-test step found no `test/alpaca_direct_test.dart` on this isolated branch, so **no new Flutter widget test execution is claimed**. These native tests compile the Android Kotlin/Java application code but are not Keystore instrumentation or physical-phone tests. No APK packaging was run.

Downloaded artifact **11818487146**, verified ZIP CRC and SHA-256 `3369a1729ab1213ed6168ac2a4f79cd2cbf4ef646c2597bf563945fdf11865b2`, and read all three JUnit suites. Exact XML and receipt are saved under `docs/evidence/direct-alpaca-isolated-20261013/`. The earlier SDK compatibility failure is retained above. The subsequent receipt commit changes documentation/evidence only.

Read `docs/DIRECT_ALPACA_RECONCILIATION_20261013.md` before resuming. The requested recovery branch advanced independently again to **7935c01c56a4df22101d16495dcb0689b5a867ca**, adding Flutter labs and Market Paper while this session tested its isolated checkpoint. This branch is therefore deliberately not merged wholesale. No new accepted APK, signature, live connectivity, OPRA entitlement or phone/background acceptance is claimed. Lab19/Demo/backend data were not changed or migrated.
