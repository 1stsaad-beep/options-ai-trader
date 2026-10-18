# Strategy A — Multi-timeframe Elliott (deterministic)

Code: `trader_core/lib/src/strategies/mtf_elliott.dart` (+ `common.dart`). Tests:
`trader_core/test/strategies_test.dart`, `elliott_engine_test.dart`. Research: `rebuild/ROUND5.md`.

## Building blocks (all causal)

* **ATR zig-zag** (`atrZigZag`, k × ATR14). A swing high is *confirmed* at the first later
  bar whose low is ≥ k·ATR below the running high (ATR of the confirming bar); mirror for
  lows. Every pivot stores `confirmedIndex`; nothing may use it earlier. Pivots alternate.
* **Degrees.** One zig-zag per timeframe: *top* (e.g. daily or weekly), *mid* (hourly or
  daily/weekly) and *entry* (5m/15m/1h/daily) plus a *fine* zig-zag (k_fine < k) on the
  entry timeframe for the sub-waves a-b-c. Higher timeframes are read only through bars
  **completed** at the entry bar's close (`TfSeries.completedAt`; daily bars end 16:00 NY,
  weekly bars at the last session's close).
* **Impulse context** (`impulseContext`) of a degree: bullish when the last confirmed low is
  above the previous low (wave 2/4 did not go beyond the start of the prior up-leg), the
  last confirmed high is above the previous high, and price is above the last low; bearish
  mirror. `strict` additionally enforces, when a full 0-1-2-3-4 is visible, "wave 4 does
  not overlap wave 1" and "wave 3 is not shorter than wave 1".

## Entry rules

CALL — end of wave 2 (sub-sub wave 2 on the entry degree):
1. Entry-degree pivots L0 < H1 > L2 with **L2 > L0** (wave 2 not beyond the start of wave 1),
   retracement (H1 − L2)/(H1 − L0) in [0.236, 0.999].
2. Inside wave 2, the fine zig-zag shows a-b-c: a fine low **a**, a fine high **b**, then
   **c = L2** below a, with **RSI14(c) > RSI14(a)** (bullish divergence).
3. Context: top degree bullish (if required), mid degree bullish (if required).
4. The signal fires at the bar that **confirms L2** (zig-zag reversal), never at L2 itself;
   fill no earlier than the next bar's open. Invalidation = L2; target = L2 + 1.618 × wave 1.

PUT — end of wave C: exact mirror (H0 > L1 < H2 with H2 < H0, wave C high above wave A
high with a lower RSI = bearish divergence, bearish context).

## Optional confluences (tested one by one and in pairs)

| flag | rule |
|---|---|
| `maTrend` | on daily bars: close > SMA50 and SMA20 > SMA50 > SMA200 (mirror for puts) |
| `waveMa` | wave behaviour vs MA: wave-1 extreme beyond SMA50, wave-2 end within 1 ATR of SMA50, close back beyond SMA50 |
| `sr` | wave-2 end within 0.5 ATR of one of the last 12 mid-degree pivot levels |
| `classical` | double bottom / top: \|a − c\| ≤ 0.5 ATR |
| `fibPrice` | retracement 0.5–0.786 (±0.03) and C/A ≈ 1.0 or 1.618 (±15%) |
| `fibTime` | duration(wave 2)/duration(wave 1) within 10% of 0.382, 0.618, 1, 1.618, 2.618 |
| `macd` | MACD(12,26,9) histogram divergence a→c and histogram turning in trade direction |

## What ships

Only the variant that survived validation and holdout is in the app, as the experimental
per-account strategy **"إليوت اليومي — تجريبية"** (`StrategyKind.elliottDaily`, off by default):
daily entry bars, k = 1.5, k_fine = 0.6, no higher-degree requirement (optional weekly
context switch), **Calls only** (puts optional, not recommended), signal on the last
completed daily bar → entry next session, each signal used once. Preset
(`AccountSettings.withElliottDailyPreset`): weekly contracts 2–9 DTE, delta 0.5, hold ≤ 7
calendar days (≈ 5 sessions), out 1 day before expiry, emergency stop −90%, no profit
target / trailing / partial / scale-in, no opposite-signal or invalidation exits.
