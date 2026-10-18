# Strategy B — Multi-timeframe RSI re-entry (both directions)

Code: `trader_core/lib/src/strategies/mtf_rsi.dart`. Tests: `trader_core/test/strategies_test.dart`.
Research only — **not selectable in the app** (failed the holdout, see `rebuild/ROUND5.md`).

## Rules (symmetric)

* **PUT**: slow RSI (spec: hourly) ≥ overbought (70; also 65 and 75 tested). The fast RSI
  (spec: 15 min) is in overbought, **drops out** (crosses below the threshold) and **comes
  back** (crosses above it again) within `window` fast bars, while the slow RSI is still
  overbought (checked both when the fast RSI left the zone and when it returned) → buy a
  weekly Put at the next fast bar's open.
* **CALL** (mirror): slow RSI ≤ oversold (30; 35/25); fast RSI rises out of oversold and
  returns into it within the window while the slow RSI is still oversold → weekly Call.
* Slow RSI is read from the last slow bar **completed** at the fast bar's close (no
  forming bar). Signals fire at the fast bar's close; fill next bar open.
* Invalidation (for logging): the extreme of the fast bars between leaving and returning.

## Grid tested (per direction and combined)

Threshold 65/70/75 (oversold 35/30/25), RSI length 14 and 9 (both timeframes), window 4/8/16
fast bars, exits: fixed time (spec: 8 × 15 min = 2 h; 1h/daily: 7 bars; daily/weekly: 3
sessions), option TP +50% / SL −50%, fast RSI back through 50 (or 3× the time limit).
Timeframe pairs: 15m/1h (spec, 60 days of data), 1h/daily (~2 years), daily/weekly (since 1998).
