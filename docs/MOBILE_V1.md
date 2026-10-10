# Flutter V1 implementation notes

This extends the V0.5 Flutter application. It does not replace the backend dashboard or connect the local simulator to a broker.

## Implemented in local Demo

- Four named, independent first-install fixture accounts; additional accounts remain unlimited. Existing saved accounts are retained, and extra fixture accounts are not injected into existing installations.
- Version 2 local ledger serialization with version 1 migration. Existing balances, ownership and order IDs persist. Old orders without a decision snapshot remain explicitly unrecorded; reasons are not fabricated retrospectively.
- Allocation, open exposure, trade premium budget, daily loss and group limits are distinct settings accepting 0–100%. Elevated settings require an explicit acknowledgement. Budget checks include commissions and outstanding entry reservations. Limits are rechecked at fill.
- Account/symbol opposite-direction lock covers owned Calls/Puts and unresolved entry orders, across strikes and expirations. Rechecked at submission, execution and saved-state validation.
- Opt-in intelligent reversal uses persisted intents: cancel old entries, close owned contracts, wait for complete closing executions, validate and reconcile the ledger, re-evaluate a fresh quantitative signal, then submit the opposite entry. Expired, cancelled, disconnected and ambiguous states do not permit replacement entry. Automatic reversal is off by default.
- Optional trailing and staged-profit exits, Intraday and Swing time exits, near-expiry protection, expiry cost write-off without exercise. Staged profit requires at least two owned contracts. Market-data outage freezes execution; it does not fabricate prices or guarantee liquidation.
- Profitable scaling is off by default, configurable per account with max count, quantity, decreasing sizing and cooldown. It checks aggregate position premium risk, pending orders, cash and global linked limits. Acceptance reserves the scale count even if the response is lost.
- Decision-time snapshots are stored as immutable JSON text on each new order. Completed trades retain entry and scaling snapshots, exit decision, cost basis, execution price and fee. Replay shows recorded evidence only. This is application immutability, not cryptographic tamper-proof storage.
- Entry profile and method controls are independent from risk sizing. Confirmed entry requires the same directional qualifying rule on the prior completed observation; conservative mode requires the higher breakout score; pullback mode restricts the eligible rule.
- All existing ten Arabic pages retained, plus Advanced Chart Lab and Trade Decision Replay. Dark/light/system themes and RTL remain. Local account state never transfers automatically to backend or future Paper/Live modes.

## Five chart labs

Wave, Classic, Harmonic, Indicator and AI Confluence labs use a shared candlestick canvas with horizontal pan, pinch zoom, overlay toggles and a causal replay cursor. Inputs are synthetic local data through the selected cursor, never future observations. Confirmed pivots require two later *already observed* candles; historical labels are not shown before confirmation.

Local indicator calculations include SMA, EMA, simple-window RSI (not Wilder smoothing), MACD line, ATR, VWAP, Bollinger bands, support/resistance and Fibonacci levels. Divergence candidates use confirmed same-type pivots and bounded spacing. Harmonic candidates validate alternating XABCD geometry and ratio ranges for Gartley, Bat, Butterfly, Crab and Cypher. Impulse candidates enforce basic Elliott 1–5 geometry.

The local chart engines are intentionally limited research candidates, clearly labelled synthetic/Shadow. They are not a full expert Elliott count system: nested degrees, persistent primary/alternate scenario tracking, 3-of-3 identification, ABC, multi-timeframe confluence and a complete classical-pattern library are not implemented in this local canvas. Backend research modules are independent and are not silently represented as Flutter features. The AI Confluence tab is a deterministic rules summary with no model/API call. There are no profitability claims.

The simple synthetic OHLC fixtures often produce no confirmed strict pivots or pattern candidates. Empty candidate results are displayed honestly; the canvas does not fabricate a wave or harmonic model to fill the screen.

## Safety and persistence limits

- No HTTP, socket, API or broker dependency is imported by the local engine or chart analytics. Live/Paper/IBKR modes are rejected in local account configuration.
- An invalid save is retained and the controller stays locked. A failed write rolls back the cycle and stops the local timer.
- Existing V0.5 saves with opposing positions or an opposing unresolved order fail closed rather than being silently rewritten.
- Local time pauses when the application backgrounds. This is expected for offline Demo; the separate backend worker owns server operation.
- Synthetic session and option quotes are fixtures, not exchange calendars or realistic option pricing. Broker qualification, real liquidity, exercise/assignment management and operating-system install tests remain separate verification tasks.

## Tests and evidence

Added engine regressions for all new safety policies, first-install/migration persistence, reversal partial fill/disconnection/emergency/cancellation, lost scaling response, fixed decision evidence, indicator and harmonic geometry, causal pivot timing and replay. The widget suite traverses the added Arabic screens, and includes a narrow RTL chart-lab test; the existing default-app HTTP-blocking test remains.

Actual execution counts and analyze/build results belong in the release test report after the tools have run. Writing this file is not evidence of a successful Flutter test or build.

## Verified cloud checkpoint

At commit `32531f772200cbb798a98a744323f007bbb2d210`, GitHub Actions completed the following on 2026-10-10:

- Android run [38067549917](https://github.com/1stsaad-beep/options-ai-trader/actions/runs/38067549917): analyze, shared Flutter tests, APK compilation, preview signature verification and artifact upload succeeded.
- macOS/iOS run [38067549913](https://github.com/1stsaad-beep/options-ai-trader/actions/runs/38067549913): analyze, **114 passed / 0 failed / 0 skipped** shared Flutter tests, and `flutter build ios --release --no-codesign` succeeded. Six hidden test-suite loaders are excluded from the test count. The downloaded artifact passed ZIP CRC verification and contains the compiled `Runner.app/Runner` executable.

The iOS result is an unsigned device build, not an installable signed IPA or a TestFlight upload. Android signature identity and final downloadable APK hashes are recorded in the release report. These results do not establish a successful installation on a physical phone, live-market qualification, or strategy profitability. Local scratch Dart execution remained blocked by its runtime stack-bounds limitation; these successful runs used actual GitHub-hosted runners.
