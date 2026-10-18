# Analysis & decision engines (v2)

All engines live in `trader_core/lib/src/analysis/` and are **pure, deterministic
Dart functions** `List<Candle> → List<EngineSignal>`. No LLM, no network, no
randomness. Same candles in → same signals out, on every device.

## 1. Causality rules (read first)

* Candles are oldest-first; an engine may only look at the list it receives.
* Swing points come from `confirmedPivots(left: 3, right: 2)`: a pivot at bar `i`
  is known only at bar `i + 2` (`Pivot.confirmedIndex`). Engines never act on a
  pivot before it is confirmed. Test: `pivots: a pivot is confirmed only ...`.
* `alternatingSwings` merges consecutive same-kind pivots (keeps the extreme)
  and drops swings smaller than `minMoveFraction` of price → a clean zig-zag.
* Every `EngineSignal` carries `knownAtIndex`, the bar where it became knowable.

## 2. `EngineSignal`

| Field | Meaning |
|---|---|
| `engine` | `EngineId` (trend, momentum, divergence, harmonic, elliott, classical) |
| `bias` | bullish / bearish / neutral |
| `strength` | 0..1 quality (ratio fit, confirmation, agreement) |
| `pattern` | machine name, e.g. `GARTLEY`, `WAVE3_START`, `REGULAR_BULLISH_RSI_MACD` |
| `reasonAr` | Arabic explanation — copied verbatim into the decision journal |
| `invalidation` | underlying price where the idea is wrong (used as an exit trigger) |
| `targets` | underlying price targets, nearest first |

## 3. Engines

### Trend (`trendEngine`)
EMA20/EMA50/EMA200 alignment + ADX(14). Bullish when `close > EMA20 > EMA50`
(and above EMA200 when 200 bars exist); mirror for bearish.
`strength = 0.4 + 0.3·min(ADX/40,1) + 0.3·clamp(EMA20 slope over 5 bars / ATR)`.
Invalidation = EMA50.

### Momentum (`momentumEngine`)
Three votes: RSI(14) > 55 / < 45; MACD(12,26,9) histogram sign + direction;
Stochastic(14,3,3) K vs D outside the 80/20 extremes. Needs ≥2 agreeing votes.
Strength = votes/3, ×0.6 when RSI is already > 75 (bull) / < 25 (bear) — late
momentum is penalised, not rewarded.

### Divergence (`divergenceEngine`)
Last two confirmed swing lows (bullish) / highs (bearish), 5–60 bars apart,
second one confirmed within the last 8 bars.

| Kind | Price | RSI |
|---|---|---|
| Regular bullish | lower low | higher low |
| Hidden bullish | higher low | lower low |
| Regular bearish | higher high | lower high |
| Hidden bearish | lower high | higher high |

MACD histogram agreeing adds strength. Invalidation = second swing; target =
the opposite swing between the two. Dropped if price already broke the swing.

### Harmonic (`harmonicEngine`)
Last five alternating swings = X A B C D, D confirmed within 6 bars.
Prices are multiplied by `sign` (+1 when X is a low) so one rule set covers both
directions. Ratios (tolerance ±0.04; CD/BC ±0.08):

| Pattern | AB/XA | BC/AB | CD/BC | AD/XA | D vs X |
|---|---|---|---|---|---|
| Gartley | 0.618 | 0.382–0.886 | 1.272–1.618 | 0.786 | inside |
| Bat | 0.382–0.5 | 0.382–0.886 | 1.618–2.618 | 0.886 | inside |
| Butterfly | 0.786 | 0.382–0.886 | 1.618–2.618 | 1.272–1.618 | beyond |
| Crab | 0.382–0.618 | 0.382–0.886 | 2.24–3.618 | 1.618 | beyond |
| Cypher | AB/XA 0.382–0.618, XC/XA 1.272–1.414, CD/XC 0.786 | | | | inside |

D must lie in the **PRZ** = overlap of the XA-projected and BC-projected D zones.
Invalidation = D − 8% of XA; targets = 38.2% and 61.8% retracement of AD.
Silent once price has hit target 1 or broken invalidation.

### Elliott (`elliottEngine`)
On swings with `minMoveFraction 0.6%`. Hard rules for an impulse: wave 2 never
beyond the start of wave 1; wave 4 never enters wave-1 territory; wave 3 never
the shortest of 1/3/5. Scenarios (both directions):

| Pattern | Condition | Bias | Invalidation | Targets |
|---|---|---|---|---|
| `WAVE3_START` | [0,1,2], wave 2 = 36–80% of wave 1, price above 2 | with trend (stronger after breaking 1) | start of 1 | 1 + 0.618·W1, 2 + 1.618·W1 |
| `WAVE5_START` | valid [0..4], W3 ≥ W1, wave 4 = 20–62% of W3 | with trend | top of 1 | 4 + 0.618·W1, 4 + W1 |
| `IMPULSE_DONE` | complete [0..5] | against (ABC expected) | end of 5 | 38.2% / 61.8% of the impulse |
| `WAVE_C` | impulse, then A and B (38–89% of A) | against | end of 5 | C = 0.618·A, C = A |

Strength rises with Fibonacci closeness (wave 2 ≈ 0.59, wave 4 ≈ 0.382, W3 ≈ 1.618·W1).

### Classical (`classicalEngine`)
* **Double top/bottom**: peaks within 1.5%, ≥ 2% deep, ≥ 8 bars apart, signal on a
  close through the neckline (the middle swing), within 6 bars of the break.
  Measured-move target = neckline ± height.
* **Head & shoulders / inverse**: 5 swings, head beyond both shoulders, shoulders
  within 3%; sloping neckline through the two troughs; close-through break.
* **Triangles**: last 4 swings (2 highs, 2 lows); flat top + rising lows = ascending,
  falling highs + flat bottom = descending, both converging = symmetrical; signal on
  a close outside the boundary; breakouts in the natural direction get 0.7, others 0.5.
* **Range breakout**: close beyond the previous 20-bar high/low when that range is
  < 12% of price (strength 0.45).

## 4. Composite score (`Analyzer`)

Each engine contributes its single strongest signal; an engine that produced
conflicting directions of similar strength (within 0.1) abstains.

```
score = 100 × Σ(weight × strength × sign) / Σ(weight of every enabled engine)
```

Silent engines stay in the denominator, so one loud engine cannot reach a high
score alone. Weights are per account (`AccountSettings.engineWeights`; 0 disables).

## 5. Decision engine (`DecisionEngine`, `TradingEngine`)

Per account, every cycle:

1. **Follow orders** — book fills (incremental), cancel orders older than
   `orderTimeoutCycles` and mark the contract for far-side repricing.
2. **Snapshot** — balances, positions, working orders straight from the broker
   (the broker is the source of truth; engine memory is re-synced to it).
3. **Exits** (first match wins): stop-loss % of premium → underlying invalidation
   (saved at entry) → `exitDaysBeforeExpiry` → trailing stop (arms after
   `trailingActivationPercent`, exits on `trailingStopPercent` drop from the
   peak) → full take-profit → opposite composite signal → max holding days →
   partial take-profit (once). Protective exits sell at the bid.
4. **Scale-in** (optional) — winner ≥ `scaleInMinProfitPercent` and score ≥
   `scaleInMinScore` in the same direction, at most `maxScaleIns` times.
5. **Entries** — for flat watchlist symbols only: |score| ≥ `minScore`, ≥
   `minAgreeingEngines` engines agree, trend not opposite (optional), right
   allowed, daily-loss limit not hit, open-position slots available. Contract =
   closest to `targetDelta` within the DTE window with spread ≤ `maxSpreadPercent`
   and OI ≥ `minOpenInterest`. Size = min(risk-per-trade, max position %,
   remaining exposure, buying power, max contracts).

### Opposite-direction lock (`DirectionLock`)
A Call and a Put on the same underlying can never coexist in one account. The
lock counts held quantity **and** every working order (pending / partially
filled, buy or sell). It is checked when deciding and again on freshly fetched
broker state right before submitting. A flip therefore takes at least two
cycles: cycle N exits the old side; the same cycle refuses any entry on that
underlying; cycle N+1 (old side fully gone, no working orders) may open the
other side. Tests: `trading_test.dart` (lock group) and `engine_test.dart`
("flip", "a working Call order locks out a Put").

## 6. Extending

* New engine: write `List<EngineSignal> myEngine(List<Candle> c)`, add an
  `EngineId`, register it in `Analyzer.defaultEngines`, add a default weight in
  `AccountSettings`, add a fixture test built with `path()` / `candlesFromCloses()`.
* Keep engines causal and silent when unsure; return an empty list instead of a
  weak neutral signal.
