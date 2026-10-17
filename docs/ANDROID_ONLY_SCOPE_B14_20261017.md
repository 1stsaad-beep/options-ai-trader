# B14: This phase is Android only. iOS and the server are paused, not deleted (2026-10-17)

Branch `work/android-scope-b14`, stacked on `work/nav-b13`. This batch adds documentation and a guard test only; no product code changed.

## Decision (D35)
This phase delivers **one Flutter Android app** with no persistent server. iOS and the server (FastAPI/worker/PostgreSQL/Compose) are **out of scope for this phase**.
- **Kept:** every file, its history and its old reports stay as they are. Nothing was deleted, renamed or disabled.
- **Not requirements:** they are not acceptance criteria for this phase's batches. A batch is accepted on the Android gates: analyze, tests, debug APK, secret scan, and JVM/policy checks where native code changed.
- **No new work:** their divergences are documented, not fixed. Examples are server trailing-stop arming (B10) and the server having no extended patterns (B11).
- **Resuming later** requires an explicit user decision. The Android-side contracts that keep sharing possible (strict 3/1 pivots, daily report rules, fixtures) are kept.

## Paused components (inventory at 50966b5 plus B1–B13)
| Component | Path | Files | Status this phase |
|---|---|---|---|
| iOS runner | `mobile/ios/` | 40 | Kept. Not built locally. `ios.yaml` CI still runs only on its existing branches (main, develop/*, recovery/v1.0-20261011); the work/* branches don't trigger it |
| Server | `backend/` | 158 | Kept and unchanged. Not deployed. Not required by any Android feature |
| Infra | `infra/` (Caddy, Docker, Compose profiles) | 15 | Kept, not deployed |
| Old archive | `repository/` | 4 | Kept as history |
| Server CI | `.github/workflows/checks.yaml` | — | Kept. Runs only on backend/scripts/infra paths |
| Phone server-observer screens | `mobile/lib/api.dart`, `mobile/lib/observed_server*.dart` (one entry point in `main.dart`) | — | Kept as an **optional** read-only viewer. They need a server URL, which this phase doesn't provide |

## Android core (in scope), with no server dependency
Demo (`lib/demo/`), Direct/Market Paper (`lib/direct*.dart`, `lib/market_paper*.dart`), Broker Paper with Alpaca/IBKR/TradeStation (`lib/brokers/`), and the shared calculations (`daily_nav`, `protective_exit`, `option_pricing`, `extended_patterns`).

`test/android_scope_test.dart` enforces two things:
1. None of these modules imports `api.dart` or `observed_server*`.
2. The iOS and server sources still exist, so a later cleanup cannot delete them silently.

Live trading remains hard-disabled behind an approval flag that defaults off.

## Evidence
`docs/evidence/android-scope-b14-20261017/`: analyze, full test run, debug APK and secret scan.

## Still open
- Server-only features (24/7 automation, alert delivery, the observed paper runtime) have no Android equivalent. On the phone, sampling happens only while the app is open; see B13.
- iOS has no signed build or acceptance.
