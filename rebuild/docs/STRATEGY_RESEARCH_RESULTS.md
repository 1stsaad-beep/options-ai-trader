# Strategy research results — round 5 (honest summary)

Details, tables and method: [`rebuild/ROUND5.md`](../ROUND5.md) §2. Raw tables:
`rebuild/research/results/r5/`. All option results are **modeled** (Black-Scholes on real
underlying bars, IV proxy, spreads/fees/slippage); no real option fills were available.

| strategy | spec timeframes | best evidence | recommendation |
|---|---|---|---|
| A — MTF Elliott, CALL at end of wave 2 + RSI divergence | 15m/5m entry under 1h/daily | spec: 4–9 trades in 60 days (untestable); shifted to **daily entry**: selected variant passed validation and holdout — disc +25.0% (73), val +23.6% (37), **holdout +16.5% (39)**, PF 1.42, vs control −3.4%; without AAPL +13.6% (128) | **add as experimental, off by default, Paper only** (`elliottDaily`); fragile to zig-zag size (k 1.5 peak, k 2.0 negative) |
| A — PUT at end of wave C | same | −30% / −57% / −52% per split | don't add |
| A — confluences (MA, wave vs MA, S/R, double bottom, Fib price, Fib time, MACD) | — | samples 5–36, indistinguishable from noise; weekly impulse context did not help | don't use as filters (yet) |
| B — MTF RSI, PUT (overbought) | 15m/1h | 23 trades in 60 days, +0.7%; 1h/daily −11.3% (72); daily/weekly +9.9% (220) but decays to +2.4% in holdout; selected variant −13.6% in holdout | don't add |
| B — MTF RSI, CALL (oversold) | 15m/1h | 8 trades, −5.7%; 1h/daily 18 trades; daily/weekly 7 trades | don't add (too rare to judge) |
| B — threshold 75 | — | fewer trades, holdout negative in every pair | don't add |
| Default composite ± IV/RV filter | 1h / 15m | −10.3% per trade (1,157 trades); filter on SPY/QQQ −11.0% → −6.2% | keep filter optional; the default strategy itself remains unproven/negative in this model |
