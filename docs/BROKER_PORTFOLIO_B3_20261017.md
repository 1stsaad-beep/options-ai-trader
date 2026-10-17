# Batch B3: Paper balances and positions screen per broker account (2026-10-17)

Base: `work/android-build-b2` @ `11a6f5fbcdf8656bdc313c507d336d203370e89f`. Branch `work/positions-b3`.

## Implemented (mobile, read-only, Paper only)

| File | Purpose |
|---|---|
| `mobile/lib/brokers/broker_portfolio.dart` | `BrokerPortfolio`: one observation (balances plus positions) with local receipt time and source. `loadPortfolio()` fetches balances first (authenticating and verifying the Paper account), then positions. Any failure returns no partial portfolio. It refuses an unverified Paper snapshot before fetching positions. Data is stale after 60 s. |
| `mobile/lib/brokers/broker_portfolio_screen.dart` | Per-account screen: Paper/broker badge and source host; cash, equity, buying power, currency, broker account id and status exactly as reported (decimal strings, no float rounding); positions with quantity, average price, market value and signed unrealized P/L; receipt time; stale warning; refresh button and pull-to-refresh. A failed refresh shows the coded error and keeps the previous values visible but marked stale, and never merges them. TradeStation token rotation is saved. There are no order controls. |
| `mobile/lib/brokers/broker_accounts_screen.dart` | Tapping an account opens its portfolio screen. |
| `mobile/test/broker_portfolio_test.dart` | 6 tests with `MockClient` (no network): Paper verification gate, stale boundary, exact Alpaca rendering plus refresh, failed-refresh stale/error behaviour, IBKR and TradeStation portfolios plus token rotation, navigation from settings. |

## Results (box: Flutter 3.47.7, JDK 17, SDK 36)

- `flutter analyze`: no issues. `flutter test`: **1046 passed** (B2 had 1040, plus 6), 0 failed.
- `flutter build apk --debug`: built (see `apk-debug-sha256-size.txt`). The APK is not committed. Local copy: `/workspace/tools/apk/options-ai-trader-b3-debug.apk`.
- `scripts/security_scan.py`: 1216 tracked files, 0 findings. No dependency change since B2.
- Evidence: `docs/evidence/positions-b3-20261017/`.

## Limits

No real Paper account was queried. Values are broker-reported, with no portfolio totals or local recomputation. History is not kept (each refresh replaces the in-memory view). Order entry still goes through B4 and the existing admission/risk path.
