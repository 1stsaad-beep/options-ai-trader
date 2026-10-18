# Round 5 — IV/RV filter and multi-timeframe strategies

Branch: `rebuild/strategies-ivrv-20261018` (made from `rebuild/hybrid-engines-20261018`;
merge back optional, plain merge only). Live trading stays compiled out.

Status: **5.1 (IV/RV filter) — versionCode 6. 5.2 (strategies A/B, backtests, validation,
results, experimental daily-Elliott strategy in the app) — versionCode 7.**

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

(The default strategy with/without the filter is in §2.6.)

---

# 5.2 — Strategies A (MTF Elliott) and B (MTF RSI), backtests, validation

Rules: [`docs/STRATEGY_MTF_ELLIOTT.md`](docs/STRATEGY_MTF_ELLIOTT.md),
[`docs/STRATEGY_MTF_RSI.md`](docs/STRATEGY_MTF_RSI.md). Conclusions:
[`docs/STRATEGY_RESEARCH_RESULTS.md`](docs/STRATEGY_RESEARCH_RESULTS.md). Full tables:
`research/results/r5/R5_BACKTESTS.md` (+ `r5_variants.csv`), `A4_CALL_ROBUSTNESS.md`,
`COMPOSITE_IVRV.md`. Reproduce: `cd trader_core && dart run tool/r5_run.dart`,
`dart run tool/r5_robust.dart`, `dart run tool/r5_composite.dart` (needs
`research/fetch_yahoo.py SPY QQQ AAPL MSFT NVDA TSLA AMZN ^VIX ^VXN` with `OAT_SKIP_M1=1`;
the data folder is git-ignored).

## 2.1 Data (public, no keys) and its limits

Yahoo chart API, 7 symbols (SPY QQQ AAPL MSFT NVDA TSLA AMZN) + ^VIX/^VXN:
daily since 1998 (TSLA 2010; adjusted), hourly RTH 2023-11-17 → 2026-10-16 (Yahoo max
730 days), **15-min and 5-min only the last 60 days** (2026-07-24 → 2026-10-16).
Consequence: the *literal* specs (15m/5m entries under 1h/daily) can only be measured on 60
days → a handful of trades. We therefore also ran the **same rules shifted one or two
degrees up** (1h entry / daily / weekly; daily entry / weekly) where samples are large.
That is a different (slower) strategy, labelled "shifted" everywhere.

## 2.2 Option model (MODELED — not real fills)

No public options history without keys, so every option result is modeled: ATM strike,
**next Friday** expiry (≥ 2 calendar days, i.e. Thu/Fri entries roll to next week),
Black-Scholes with an IV proxy (SPY: previous VIX close, QQQ: previous VXN close, stocks:
1.3 × RV20 — round 4's median IV/RV), re-priced at every bar close with the then-current
proxy. Fill at the next bar's open at mid + half spread (5% of mid, min $0.01) + 1%
slippage + $0.65/contract; exit symmetric. One open trade per symbol. Prices normalised to
spot = 100 at the fill (scale invariant). Intraday trades are forced out 1 h before the
Friday close, daily ones at Thursday's close. "dir. hit %" (underlying moved the right way
between fill and exit) is model-independent. Sizing for "total" and "max DD": premium = 2%
of starting equity per trade, simple sum, overlaps across symbols ignored.

## 2.3 Validation protocol

Per configuration, chronological split of the entry-timeframe span: **discovery 50% /
validation 25% / holdout 25%**. Pre-registered selection in code: rank variants by
discovery expectancy among those with n ≥ 30 → take the top 5 → the first with validation
n ≥ 20, expectancy > 0 and PF > 1.1 is "selected"; only the selected variant's holdout is
computed (if none passes, the discovery #1's holdout is shown, flagged FAILED). Warnings:
⚠ n < 30, ⚠⚠ n < 10. Controls with the same exits: an entry every 5th bar (drift +
option-decay baseline) and every 5th bar only when the higher-degree context agrees.

Variants: B — 3 thresholds (65/70/75) × 2 RSI lengths × 3 windows × 3 exits = 54 per
timeframe pair; A — 17 parameter/confluence variants × 3 exits = 51 per configuration.

## 2.4 Strategy B (MTF RSI) results

Spec rule (threshold 70, RSI 14, window 8, time exit), all splits:

| config | dir | n | win % | expectancy | PF | dir. hit % | holdout n / exp |
|---|---|---|---|---|---|---|---|
| B1 15m/1h (60 d) | Put | 23 ⚠ | 35 | +0.7% | 1.07 | 57 | 2 ⚠⚠ / +27.0% |
| B1 15m/1h | Call | 8 ⚠⚠ | 25 | −5.7% | 0.21 | 50 | 4 ⚠⚠ / −1.5% |
| B1 15m/1h | both | 31 | 32 | −1.0% | 0.90 | 55 | 6 ⚠⚠ / +8.0% |
| B2 1h/daily (2 y) | Put | 72 | 29 | −11.3% | 0.60 | 44 | 14 ⚠ / −13.3% |
| B2 1h/daily | Call | 18 ⚠ | 50 | +34.1% | 2.42 | 56 | 5 ⚠⚠ / −37.7% |
| B2 1h/daily | both | 90 | 33 | −2.2% | 0.92 | 47 | 19 ⚠ / −19.7% |
| B3 daily/weekly (1998+) | Put | 220 | 39 | +9.9% | 1.24 | 52 | 85 / +2.4% |
| B3 daily/weekly | Call | 7 ⚠⚠ | 57 | +37.4% | 2.38 | 57 | 0 |
| B3 daily/weekly | both | 227 | 39 | +10.8% | 1.27 | 52 | 85 / +2.4% |

Threshold 75 (same rule), holdout: B1 both 3 ⚠⚠ −10.3%; B2 both 4 ⚠⚠ −26.8%; B3 Put 29 ⚠
−16.3% (Calls: no holdout signals). Threshold 75 cuts the sample without improving results.

Pre-registered selections (holdout):

| config | dir | selected | validation | holdout n | win % | exp | PF |
|---|---|---|---|---|---|---|---|
| B1 | Put | ob65 L14 W16 time8 | fail | 15 ⚠ | 33 | −5.3% | 0.62 |
| B1 | Call | ob65 L9 W16 time8 | fail | 25 ⚠ | 48 | +2.4% | 1.23 |
| B2 | Put | ob70 L14 W4 time7 | fail | 10 ⚠ | 30 | −19.1% | 0.31 |
| B2 | Call | ob70 L9 W16 rsi50 | fail | 9 ⚠⚠ | 56 | −20.8% | 0.32 |
| B3 | Put | ob70 L14 W4 rsi50 | **pass** | 61 | 26 | −13.6% | 0.77 |
| B3 | Call | ob65 L14 W8 rsi50 | fail | 10 ⚠ | 60 | +13.6% | 1.57 |

Reading: on the spec timeframes the sample is too small to say anything (31 trades in 60
days for 7 symbols). On 1h/daily it loses. On daily/weekly the Put side beat its control
(every-5th-bar Puts −13.4%) clearly in discovery (+18.8%) and validation (+10.4%), but the
edge decays to +2.4% (PF 1.06) in the holdout, and the selected variant lost −13.6% in the
holdout. Calls are rare (the slow RSI is seldom oversold in these up-trending names).
**Verdict B: do not ship.** Kept in trader_core for research only.

## 2.5 Strategy A (MTF Elliott) results

Spec configuration (base rule, top + mid context required), all splits:

| config | dir | n | win % | expectancy | PF |
|---|---|---|---|---|---|
| A1 15m / 1h / daily (60 d), tp50/sl50 | both | 4 ⚠⚠ | 50 | −5.8% | 0.85 |
| A2 5m / 1h / daily (60 d), tp50/sl50 | both | 9 ⚠⚠ | 33 | −22.9% | 0.38 |
| A3 1h / daily / weekly (2 y), tp50/sl50 | both | 15 ⚠ | 47 | −10.9% | 0.70 |
| A4 daily / weekly (1998+), time5 | Call | 59 | 41 | −8.7% | 0.80 |
| A4 daily / weekly, time5 | Put | 27 ⚠ | 19 | −42.3% | 0.29 |

The full rule (divergence at the end of an a-b-c wave 2 inside a higher-degree impulse on
two degrees) is **rare**: ~1–2 signals per symbol per year on hourly bars, a few on
15-minute bars in 60 days. Every confluence filter only reduces it further. No intraday
configuration reached n ≥ 30 in discovery, so nothing could be selected there.

Pre-registered selections (holdout):

| config | dir | selected | validation | holdout n | win % | exp | PF | max DD | dir. hit |
|---|---|---|---|---|---|---|---|---|---|
| A3 | both | top base, wave exit | fail | 16 ⚠ | 25 | −13.2% | 0.77 | 11.1% | 31 |
| A4 | Put | base k1.5 tp/sl | fail | 59 | 36 | −16.5% | 0.62 | 24.1% | 42 |
| A4 | **Call** | **base k1.5 (no weekly context), time5** | **pass** | **39** | 46 | **+16.5%** | **1.42** | 10.1% | 56 |
| A4 | both | base k1.5 tp/sl | fail | 98 | 40 | −8.2% | 0.80 | 27.6% | 48 |

The A4 Call selection, per split: discovery n 73, +25.0%, PF 1.72; validation n 37,
+23.6%, PF 1.64; holdout n 39, +16.5%, PF 1.42. Controls (same exit): Calls every 5th day
−3.4% (n 9,241, hit 54%), with weekly context −4.7%.

Robustness (`A4_CALL_ROBUSTNESS.md`, post-hoc, not used for selection):
* zig-zag size: k 1.5 is a **peak** — k 1.25: +8.0% (holdout −8.4%), k 1.75: +6.7% (holdout
  +1.4%), k 2.0: −0.6% (holdout −11.4%). k_fine 0.5–0.75 at k 1.5 all positive in every
  split (+15.6% / +22.4% / +24.0%).
* per symbol (all periods): SPY +27.0% (28), QQQ +16.2% (25), AAPL +76.2% (21), NVDA +22.6%
  (13), AMZN +32.1% (24), MSFT −1.2% (29), TSLA −49.7% (9). **Without AAPL: +13.6% (n 128),
  holdout +12.1% (n 31).**
* costs: spread 10% + 2% slippage → +14.2%; IV 1.6 × RV / 1.15 × VIX → +6.5%; IV 1.0 × RV /
  0.85 × VIX → +47.6%. SPY+QQQ only (VIX/VXN-priced) +21.9% (n 53); with IV/RV ≤ 1.5: +11.5% (n 43).
* exits (measured on the weekly-context version, n 57): time3 +15.2%, time5 +22.2%, time8 +19.4%,
  wave stop+target +16.2%, tp50/sl50 +6.7%, tp100/sl50 +6.2% — the time exit is best; tight
  option stops hurt.
* requiring the weekly impulse context: +22.2% overall but −1.5% without AAPL — the context
  filter does not help. Strict impulse rules: n 30, +20.2%.
* the Put mirror (end of bearish wave C): −30% / −57% / −52% (disc/val/hold) — strongly negative.
* MACD, Fibonacci price/time, wave-vs-MA, S/R, double bottom: higher averages on tiny
  samples (n 5–36) — not distinguishable from noise; not used.

**Verdict A: the daily Call variant is the only result in this round that passed
validation and holdout and beat its control.** It is fragile (zig-zag size), rare (~3–4
signals per symbol per year), modeled (no real option prices) and multiple-tested (51
variants × 3 directions × 4 configurations). It is shipped **experimental, off by default,
Paper only** so it can be observed on real fills. The intraday specs and the Put side are
not shipped.

## 2.6 Default (composite) strategy with / without the IV/RV filter

`COMPOSITE_IVRV.md`: Analyzer + DecisionEngine with default AccountSettings at every
completed bar, app-like exits (stop −35%, TP +90%, trailing 20% after +30%, ≤ 10 days, out
2 days before expiry), first Friday ≥ 7 days. MODELED.

| tf | universe | filter | n | win % | expectancy | PF | holdout n / exp |
|---|---|---|---|---|---|---|---|
| 1h (2 y) | all 7 | none | 1157 | 31 | −10.3% | 0.65 | 285 / −10.4% |
| 1h | SPY+QQQ | none | 321 | 31 | −11.0% | 0.62 | 77 / −17.5% |
| 1h | SPY+QQQ | IV/RV ≤ 1.5 | 216 | 34 | −6.2% | 0.78 | 40 / −10.3% |
| 1h | SPY+QQQ | IV/RV ≤ 1.2 | 131 | 33 | −7.0% | 0.75 | — |
| 1h | SPY+QQQ | break-even ≤ 1× expected | 317 | 31 | −10.6% | 0.63 | — |
| 15m (60 d) | all 7 | none | 147 | 27 | −14.7% | 0.51 | 46 / −12.4% |
| 15m | SPY+QQQ | IV/RV ≤ 1.5 | 30 | 37 | −9.9% | 0.65 | 8 ⚠⚠ / +6.5% |

The filter (only testable on SPY/QQQ, where the IV proxy varies) removes about a third of
the entries and roughly halves the loss per trade, in every split — but the strategy stays
clearly negative, and in this model the effect is partly mechanical (the same VIX proxy
prices the option). Round 4's real-price study did not confirm a consistent effect. Keep
the filter optional; it is not a fix for the default strategy. The break-even rule at 1.0
almost never binds for ATM weeklies (break-even ≈ 0.4 × IV/RV × expected move).

## 2.7 Recommendations and settings

| item | decision | settings |
|---|---|---|
| IV/RV filter | optional per account (done in 5.1); worth enabling on SPY/QQQ Paper accounts to collect real IV/RV data | `ivRvFilterEnabled: true`, `maxIvRvRatio: 1.5`, `rvLookbackDays: 20`, `maxBreakevenToExpectedMove: 0` (off) |
| A — daily Elliott Call | **experimental, off by default, Paper only** | `strategy: elliottDaily`, `elliottZigZagAtr: 1.5`, `elliottFineAtr: 0.6`, `elliottRequireWeeklyContext: false`, `elliottAllowPuts: false`, `allowPuts: false`, `minDaysToExpiry: 2`, `maxDaysToExpiry: 9`, `targetDelta: 0.5`, `maxHoldingDays: 7`, `exitDaysBeforeExpiry: 1`, `stopLossPercent: 90`, `takeProfitPercent: 1000`, `trailingActivationPercent: 1000`, `partialTakeProfitFraction: 0`, `exitOnOppositeSignal: false`, `exitOnUnderlyingInvalidation: false`, `scaleInEnabled: false`, `riskPerTradePercent` ≤ 1, watchlist SPY QQQ AAPL NVDA AMZN (MSFT/TSLA were flat/negative) — one button "تطبيق الإعدادات المقترحة" applies all but risk/watchlist |
| A — intraday specs (15m/5m) | don't add (n < 10 per split; cannot be validated with public data) | — |
| A — Put mirror | don't add | — |
| B — MTF RSI (all pairs, both directions, 70 and 75) | don't add (fails holdout; spec pair untestable on 60 days) | — |

Paper protocol for A: run ≥ 6 months (expect only ~10–20 signals across 5 symbols), compare
the report's per-trade P&L against the modeled +15–20% per trade; abandon if, after 20
trades, expectancy ≤ 0 or real IV/RV at entry is far above the 1.3 assumed for stocks.

## 2.8 App changes (versionCode 7)

* `AccountSettings.strategy` (`composite` default, `elliottDaily` experimental) + Elliott
  parameters with Arabic help and ranges; `withElliottDailyPreset()`.
* Settings: "الاستراتيجية" section — dropdown, red experimental warning, parameters,
  "تطبيق الإعدادات المقترحة" button. Risk card shows the strategy and the IV/RV filter state.
* Engine: for `elliottDaily` accounts the entry decision comes from the last completed daily
  bar (computed once per NY day per symbol), journal reason "استراتيجية إليوت اليومية
  (تجريبية)", engine attribution `strategy:elliottDaily` in the report, one use per signal;
  all safety rules (market hours, Call/Put lock, caps, cooldown, kill switch, pause, IV/RV
  filter) apply unchanged.
* Tests: core `strategies_test.dart` (13: alignment, zig-zag causality, impulse context,
  Elliott wave-2/C rules both directions, invalid wave 2, filters only subtract, no
  look-ahead on prefixes, RSI Put/Call mirror, window, slow-zone requirement, 75 vs 70,
  completed slow bars), `elliott_engine_test.dart` (3: preset valid/off by default, replay
  on real AAPL daily bars → one tagged Call next session, used once, nothing the day before;
  composite unaffected). App: strategy selection + warning + preset save.

## 2.9 Limits

* All option P&L is modeled; real weekly IV for single stocks is unknown (proxy 1.3 × RV).
* Daily-bar backtests fill at the next open; the app enters at the first cycle of the next
  session (similar but not identical). Daily history before 2007 uses current DST rules
  (bar end times may be off by an hour; daily logic unaffected).
* Multiple testing: ~600 variant × direction combinations were evaluated; one passed. Its
  holdout (n 39) is the main evidence, and it is modest.
