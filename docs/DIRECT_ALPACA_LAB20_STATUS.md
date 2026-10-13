# Direct Alpaca Lab20 — recovery and staged implementation

Recovered on 2026-10-13 from `67995126bd095e3e3bbbae2d74e9d19e0e2c8207`, branch `recovery/v1.0-20261011`. All 944 tree entries preserved. Source text verified against Git blob IDs. Local workspace had been removed by maintenance; no unsaved earlier-session work can be claimed recovered. Lab19 remains the accepted prior Android release.

## Batch 1: native read-only boundary (acceptance pending)

- AES-256-GCM AndroidKeyStore vault, randomized IV and authenticated version context, atomic ciphertext in `noBackupFilesDir`. No reveal method. Android memory/runtime compromise can still expose credentials; background access intentionally has no per-read biometric prompt.
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
- https://github.com/square/okhttp/blob/master/CHANGELOG.md — pinned OkHttp 5.5.0.

No OPRA entitlement, true provider connectivity, profitable backtest, actual phone service survival or realistic option fills is established by mocks.
