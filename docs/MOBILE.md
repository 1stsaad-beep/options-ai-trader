# Flutter V0.4 — client behavior and build status

The existing V0.3 client was incrementally extended. Version `0.4.0+4` has ten Arabic RTL destinations: home, accounts, opportunities, orders/positions, account risks, independent watchlists, reports, decisions, notifications/emergency, and separate strategy settings. Dark is the startup default; an explicit menu also offers Light and System appearance. Theme and access token remain in memory, not persisted.

Home loads each account's performance from the server and totals its realized P&L only when all returned values are valid. Missing/unreachable server data is never displayed as simulated success or a fabricated balance. Unrealized P&L has no mark-to-market implementation and remains unavailable. Opportunities are sorted by the server's quantitative score; the screen does not submit trades.

Each watchlist supports add, remove, pause and resume without a three-symbol limit. NVDA/AAPL/TSLA defaults are created by the backend. Symbol validation is explicitly **MockBroker fixture validation**, not IBKR verification. A newly added symbol starts disabled; enabling it asks the server to check mock entitlements. An explicit row refresh records a new synthetic market observation (60-second validity); account reconciliation is separate (120-second snapshot validity). No fabricated automatic freshness refresh runs in the background. No real market data or brokerage account is connected.

Account risks and strategies have separate screens. Strategy settings allow paper/shadow/analysis and intraday/swing; Live has no option. Risk settings include an optional related-account risk group and group exposure/loss ceilings. Account and global emergency stop show the server status and its emergency policy. Opening new positions stops; owned-position closes still require trusted reconciliation. Emergency stop never promises automatic liquidation. Notifications are refresh-time status messages; OS Push notifications are not implemented.

Manual orders, cancellation, mock partial fills, reconciliation and performance remain from V0.2. Order retry keys are retained independently per account in memory, and saved order details display the server request key for manual review after an app restart; partial-fill retry identifiers are retained per order. Dialog actions capture the intended account before awaiting user input and reject the action if selection changes. Server validation remains authoritative. No client mutation is retried automatically after timeout/disconnection. The client rejects redirect responses, remote plaintext URLs, credential/query-bearing server URLs and malformed collection payloads.

## Automatic Mock trading

Automation is disabled by default and configured independently for every account from the strategy screen. The client offers a separate on/off switch, stop-loss percent (1–95; default 20), take-profit percent (1–500; default 30), entry quantity (1–100 and no greater than the account maximum; default 1), partial-fill chunk (1–100; default 1), and maximum bid/ask spread percent (1–50; default 10). The server validates all values and remains the authority for risk limits, data trust, reconciliation and order execution. The client does not calculate signals or create automatic orders directly.

The automation switch and run button are available only in the Mock paper mode. Shadow and analysis remain non-executing. Enabling automation also permits the server to manage existing owned Mock positions, including manual positions; this is stated visibly before enabling. Rules use synthetic fixture quotes, with at most one automatic new entry per symbol per UTC day and one partial-fill step per unique quote observation. No real quote stream or broker is connected. A configured stop-loss is a trigger, not a guaranteed fill price.

“تشغيل دورة محاكاة واحدة” sends exactly one `POST /api/accounts/{id}/automation/run` request with `{}`. It does not retry on timeout or failure. Returned results are displayed only when the server's `account_id` matches the captured target and `source` is `synthetic_mock`; another account's result is rejected. Each account keeps its own last visible cycle result. Server refusal is surfaced without claiming an execution. Account reconciliation and enabled, validated watchlist symbols are required before execution. Continuing cycles while the phone app is closed requires the separate backend worker to be running.

## Build and install

Install Flutter >=3.35 / Dart >=3.9 (delivered CI pins Flutter 3.47.7), Android SDK and Java on a supported host; iOS requires Xcode/macOS. Run from `mobile/`:

```bash
./scripts/bootstrap.sh
flutter analyze
flutter test
flutter build apk --debug --dart-define=API_URL=http://10.0.2.2:8000
```

Android debug output: `build/app/outputs/flutter-apk/app-debug.apk`. See `.github/workflows/checks.yaml` for automated APK building and `.github/workflows/ios.yaml` for a macOS unsigned build (actual names follow the delivered workflows). A configured CI workflow is not evidence of successful compilation.

Run the backend and use the generated local API token according to the root setup guide. The connection settings dialog accepts that token locally; never enter broker credentials. Android emulator host: `http://10.0.2.2:8000`. A physical Android phone can use `adb reverse tcp:8000 tcp:8000` and `http://127.0.0.1:8000`, or an authenticated HTTPS endpoint. Remote plaintext LAN URLs are rejected.

## Termux and iPhone

The mock backend can run inside Termux using the documented SQLite development fallback. Use `http://127.0.0.1:8000` in the debug app on the same phone. Android may terminate background Termux; this development setup cannot guarantee continuously running execution. Build the APK on CI or a compatible workstation, not inside Termux.

iPhone distribution requires a configurable unique Bundle Identifier, an Apple Developer membership, certificates/provisioning and App Store Connect/TestFlight authorization. No signing account, credentials or certificates are requested or configured here. Shared Flutter tests and `flutter build ios --no-codesign` run on the provided macOS workflow; an unsigned build does not establish an installable TestFlight app.

## Actual validation

The V0.3 baseline contained 15 Flutter tests (7 API and 8 widget). V0.4 adds 9 tests: explicit account and empty-body cycle transport, wrong-account/source refusal, no cycle retry, empty account rejection, default-off and locked cycle UI, isolated automation switch, isolated exit settings, account maximum enforcement and account-specific cycle result rendering. The suite now contains 24 tests (11 API and 13 widget).

Formatting of the four source/test files was executed successfully during V0.4 development. Actual final Flutter tests, analyzer and Android build results are recorded in the V0.4 test/build reports and evidence logs; source or workflow configuration is not evidence of a completed build. V0.3's historical successful test/build logs are retained as historical evidence. No iOS build has run in this Linux workspace.

Remaining mobile work: physical Android device acceptance, iPhone build/signing/device acceptance, secure persisted session storage if requested, Push notifications, richer analytics charts, broker connection UX only after separately approved integration, and accessibility/localization refinement of backend decision reason strings.
