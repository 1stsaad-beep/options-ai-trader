# Round 5 — IV/RV filter and multi-timeframe strategies

Branch: `rebuild/strategies-ivrv-20261018` (made from `rebuild/hybrid-engines-20261018`;
merge back optional, plain merge only). Live trading stays compiled out.

Status: **Batch 5.1 (IV/RV filter) done — versionCode 6.** Batch 5.2 (strategies A/B,
backtests, validation protocol, results) is next; this file will be extended.

## 0. The "round-4 report" — found

It is in the repo: `rebuild/research/report4/10_main.md` (+ PDF/HTML) with the
IV data in `rebuild/research/results/r4/IV_FILTER.md`. What it says about IV:

* The weekly contracts the signals bought were priced with real implied vol well
  above the underlying's realised vol (e.g. strategy A 31% IV vs 24% RV; C 49% vs 24%),
  so the premium ate the predicted move.
* Recommendation: log the real IV and bid/ask of every order, and add an
  **optional** IV/RV cap "to be tuned later".
* Caveat from the same data (real option prints, dev vs test periods): IV/RV did
  **not** separate winners from losers consistently. Pooled, the lowest IV/RV bucket
  (0–0.9) was −13.3% expectancy in dev and +9.4% in test; for strategy A the
  below-median half was *worse* in dev (−16.5% vs +3.3%). Median IV/RV of the
  weeklies bought was 1.28–2.14 depending on the strategy.

Hence the design: measure and log always; block only if the user turns it on per
account; default off.

## 1. Filter design (trader_core `lib/src/analysis/volatility.dart`)

For every entry candidate that reaches contract selection (every new entry; scale-ins
are unchanged):

| quantity | definition |
|---|---|
| IV | broker IV of the selected contract (Alpaca snapshot `impliedVolatility`, IBKR field 7633, simulator model IV). Fallback: solved from the mid (ask if one-sided) by bisection on Black-Scholes, r = 4%; source recorded as `broker` / `solved` / `none`. |
| RV (daily) | sample stdev of the last N daily close-to-close log returns × √252, N = `rvLookbackDays` (default 20), completed daily bars only. |
| RV (intraday, option) | same on the analysis-timeframe bars (last N sessions × bars/session; m5 = 78, m15 = 26, h1 = 7) × √(252 × bars/session). Used when `rvUseIntraday`. |
| IV/RV | IV ÷ chosen RV. |
| break-even move | Call: max(0, K + premium − S); Put: max(0, S − (K − premium)); shown as % of S. |
| expected move | S × RV × √T, T = time to 16:00 ET on expiry day (≥ 1 h). |
| spread % | (ask − bid) / mid × 100. |

Blocking rules (only when `ivRvFilterEnabled`):
1. IV/RV > `maxIvRvRatio` (default 1.5) → blocked.
2. break-even / expected move > `maxBreakevenToExpectedMove` (default 1.0; 0 = off) → blocked.
3. IV or RV not measurable → blocked (fail closed: "no entry without a measurement").

Journal: the entry (or the `blocked` entry) carries `details.vol` =
`{iv, ivSource, rvDaily, rvIntraday, ivRv, breakevenMovePct, expectedMovePct, blocked}`
plus `bid`, `ask`, `spreadPct`, `contract`, and a one-line Arabic summary in the reason
(visible in the decision log). The cycle log's per-symbol reason shows the block.

### AccountSettings (per account)

| key | default | range | meaning |
|---|---|---|---|
| `ivRvFilterEnabled` | false | — | turn blocking on |
| `maxIvRvRatio` | 1.5 | 0.5–5 | IV/RV cap |
| `rvLookbackDays` | 20 | 5–120 | RV window |
| `rvUseIntraday` | false | — | RV from analysis bars |
| `maxBreakevenToExpectedMove` | 1.0 | 0–5 | break-even ÷ expected move cap (0 = off) |

Settings screen: new section "فلتر التقلب IV/RV (اختياري)" with Arabic explanations,
allowed and suggested ranges.

Notes / limits:
* With the round-4 medians (1.3–2.1), a 1.5 cap blocks roughly half or more of
  weekly entries; that is expected, not a bug. Start on Paper and compare the logged
  IV/RV of winners vs losers in the report before trusting it.
* The **simulator's** synthetic daily bars are far more volatile (daily RV ≈ 100%)
  than its model IV (35%), so on simulator accounts daily IV/RV is ~0.3 and never
  blocks; use `rvUseIntraday` or a Paper account to see the filter act.
* The break-even rule with a 1.0 cap is strict for weeklies bought ATM/slightly OTM;
  it is skipped when disabled (0).

### Tests
`trader_core/test/volatility_test.dart` (11): RV formula, IV solver inverts BS, time
to expiry, disabled = measure only, IV/RV cap, break-even cap, solved-IV fallback and
fail-closed, intraday RV, engine: default off logs IV/RV/bid/ask/spread on the entry,
enabled blocks with reason in journal + cycle log and no position, JSON round trip and
validation. App: `test/ivrv_app_test.dart` (every ranged setting has Arabic help; the
filter is enabled per account from the settings screen and the other account is untouched).

### Build 5.1
`rebuild-v2-debug-6` (private builds repo), versionCode 6 / 2.0.0-dev.6, 164,876,346 bytes,
SHA-256 `430871e1959b2baed61a6f0d76541a1a0a2c87a02363098669bc1a65face379c`, same app id
(`.rebuildv2`) and debug cert → updates debug-5 in place.

### Not done in 5.1 (moved to 5.2)
* Re-running the default strategy with vs without the filter on real bars: in the
  real-bar replay the option IV is itself a realised-vol proxy, so the comparison is
  only meaningful for the break-even rule / intraday-vs-daily RV, and will be
  reported with the strategy backtests, clearly labelled as modeled.
