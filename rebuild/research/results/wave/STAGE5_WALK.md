# Wave engine — stage 5 walk-forward (last generation, no look-ahead)

45 symbols, 2023-03 → 2026-09. Forecast = current leg continues to the first Fibonacci target before the scenario's invalidation.
Random-walk benchmark: P(target first) = stop distance / (target + stop distance). edge = hit − that. exp_R = mean outcome in units of risk.

## By forecaster
|                 |    n |   resolved |   hit |   p_rw |   edge |     R |   exp_R |     t |
|:----------------|-----:|-----------:|------:|-------:|-------:|------:|--------:|------:|
| ('5', 'naive')  | 4440 |      0.978 | 0.524 |  0.518 |  0.006 | 1     |   0.037 | 2.062 |
| ('5', 'wave1')  | 4226 |      0.638 | 0.553 |  0.555 | -0.002 | 1.047 |   0.022 | 0.683 |
| ('5', 'wave2')  | 3445 |      0.667 | 0.551 |  0.556 | -0.005 | 0.978 |   0.013 | 0.108 |
| ('60', 'naive') | 4791 |      0.986 | 0.554 |  0.544 |  0.01  | 0.886 |   0.054 | 0.871 |
| ('60', 'wave1') | 4913 |      0.709 | 0.547 |  0.566 | -0.019 | 1.001 |   0.027 | 0.938 |
| ('60', 'wave2') | 3921 |      0.741 | 0.566 |  0.575 | -0.009 | 0.829 |   0.036 | 0.102 |

## Wave 1 by current wave
|                         |    n |   resolved |   hit |   p_rw |   edge |     R |   exp_R |      t |
|:------------------------|-----:|-----------:|------:|-------:|-------:|------:|--------:|-------:|
| ('5', 'ENDING_DIAG:3')  |   69 |      0.594 | 0.561 |  0.517 |  0.044 | 1.126 |   0.097 |  0.74  |
| ('5', 'FLAT:C')         |  580 |      0.759 | 0.598 |  0.615 | -0.017 | 0.72  |  -0.009 | -0.08  |
| ('5', 'IMPULSE:3')      | 2586 |      0.57  | 0.469 |  0.48  | -0.011 | 1.606 |   0.021 |  1.181 |
| ('5', 'IMPULSE:5')      |  386 |      0.795 | 0.648 |  0.64  |  0.008 | 0.53  |   0.042 |  1.385 |
| ('5', 'TRIANGLE:C')     |  269 |      0.781 | 0.905 |  0.839 |  0.065 | 0.186 |   0.046 |  1.537 |
| ('5', 'ZIGZAG:C')       |  284 |      0.63  | 0.536 |  0.508 |  0.028 | 1.279 |   0.076 |  1.072 |
| ('60', 'ENDING_DIAG:3') |   77 |      0.623 | 0.625 |  0.621 |  0.004 | 0.621 |   0.066 |  0.629 |
| ('60', 'ENDING_DIAG:5') |   30 |      0.9   | 0.667 |  0.703 | -0.036 | 0.302 |  -0.045 | -0.028 |
| ('60', 'FLAT:C')        |  679 |      0.829 | 0.573 |  0.599 | -0.027 | 0.75  |  -0.019 |  0.615 |
| ('60', 'IMPULSE:3')     | 3031 |      0.649 | 0.486 |  0.507 | -0.021 | 1.538 |   0.042 |  1.168 |
| ('60', 'IMPULSE:5')     |  413 |      0.879 | 0.629 |  0.636 | -0.006 | 0.563 |   0.042 | -0.232 |
| ('60', 'TRIANGLE:C')    |  280 |      0.782 | 0.849 |  0.831 |  0.019 | 0.181 |  -0.027 | -1.339 |
| ('60', 'ZIGZAG:C')      |  377 |      0.721 | 0.52  |  0.562 | -0.042 | 1.017 |   0.013 | -0.447 |

## Wave 1 by probability bucket
|                                             |    n |   resolved |   hit |   p_rw |   edge |     R |   exp_R |     t |
|:--------------------------------------------|-----:|-----------:|------:|-------:|-------:|------:|--------:|------:|
| ('5', Interval(0.0, 0.15, closed='right'))  |  123 |      0.618 | 0.526 |  0.485 |  0.041 | 1.54  |   0.02  | 0.199 |
| ('5', Interval(0.15, 0.3, closed='right'))  | 1883 |      0.617 | 0.504 |  0.521 | -0.017 | 1.264 |   0.006 | 1.115 |
| ('5', Interval(0.3, 0.5, closed='right'))   | 1519 |      0.649 | 0.545 |  0.55  | -0.005 | 1.047 |   0.017 | 0.014 |
| ('5', Interval(0.5, 1.0, closed='right'))   |  701 |      0.675 | 0.698 |  0.662 |  0.035 | 0.542 |   0.077 | 1.123 |
| ('60', Interval(0.0, 0.15, closed='right')) |  144 |      0.66  | 0.579 |  0.59  | -0.011 | 0.974 |   0.053 | 0.367 |
| ('60', Interval(0.15, 0.3, closed='right')) | 2349 |      0.7   | 0.52  |  0.552 | -0.032 | 1.107 |   0.023 | 0.656 |
| ('60', Interval(0.3, 0.5, closed='right'))  | 1644 |      0.713 | 0.549 |  0.549 |  0     | 1.087 |   0.049 | 1.075 |
| ('60', Interval(0.5, 1.0, closed='right'))  |  776 |      0.736 | 0.616 |  0.635 | -0.02  | 0.562 |  -0.012 | 0.679 |

## Wave 1 by direction (up profits = market drift)
|               |    n |   resolved |   hit |   p_rw |   edge |     R |   exp_R |      t |
|:--------------|-----:|-----------:|------:|-------:|-------:|------:|--------:|-------:|
| ('5', False)  | 2064 |      0.66  | 0.528 |  0.554 | -0.026 | 1.023 |  -0.055 | -1.214 |
| ('5', True)   | 2162 |      0.617 | 0.579 |  0.556 |  0.023 | 1.081 |   0.096 |  1.619 |
| ('60', False) | 2157 |      0.713 | 0.483 |  0.552 | -0.069 | 1.065 |  -0.06  | -1.936 |
| ('60', True)  | 2756 |      0.706 | 0.598 |  0.577 |  0.021 | 0.95  |   0.095 |  2.591 |

## Verdict
No edge over a driftless random walk on 1-hour or 5-minute; no current-wave subgroup, probability bucket or year holds up. Up-forecast profits mirror the naive continuation forecaster (market drift).
## Stage 5b (pre-registered in PREREG_STAGE5B.json)
- **T2 confluence (1h, 5m):** no filter (daily trend, MACD side, EMA50 slope, all three) passed; up forecasts positive / down negative everywhere = drift.
- **T1 daily, 45 symbols, 2008-2026:** vs a driftless random walk, up forecasts +10-13 %, down forecasts -12-16 % (same for the naive forecaster) = drift.
  Against a **drift-matched null** (same symbol, same direction, same target/stop %, random dates):
  wave 1 up +2.0 % (t 1.6), down -3.0 %; wave 2 up +2.4 %, down -1.5 %; naive up +0.9 %, down -3.2 %.
- **Verdict:** no forecasting edge on daily, hourly or 5-minute. Per the pre-registration the engine is delivered as an
  analysis / labelling tool with an explicit "no proven trading edge" notice, not as a signal generator.

## Decision-point test (pre-registered in PREREG_SETUPS.json)
Setups: early wave 3 after a confirmed 1-2 (stop = end of 2, target = 1.0 x wave 1) and early wave 5 after a confirmed 4
(stop = end of 4, target = 0.618 x wave 1); variants add parent / grandparent agreement and a 5-wave inner wave 1.
Benchmark: drift-matched null (same symbol, direction, target/stop %, horizon, random dates).
- **1-hour, 45 symbols, 6,075 setups:** skill +0.3 % (all) ... -2.8 % (parent + grandparent) ... -4.0 % (wave 5 + parent + grandparent). No pass; more Elliott context made it slightly worse.
- **Daily, 45 symbols 2008-2026, 3,664 setups:** skill +1.6 % (all early-3, t -0.6), +3.4 % (inner 5), +2.5 % (early-5 + parent + grandparent, t 1.1), +7.1 % on 25 trades with all filters (t 1.2). No pass; small positive tilt, statistically indistinguishable from zero.
- **5-minute (original 15, 2025-07 → 2026-09):** interim on 6 symbols negative; remaining symbols running.
- **Verdict:** neither decision points nor multi-generation context give a measurable edge. Elliott counting does not carry predictive information beyond drift in these tests.
- **5-minute decision points (14 of the original 15 symbols, 2025-07 → 2026-09, 6,883 setups):** early-3 skill -0.1 % (all), parent -1.5 %, parent+grand -1.1 %; early-5 all -1.4 %. One cell (early-5 + all filters, 30 trades) +15.6 % (t 2.1) — a single small cell out of ~60 variant cells tested, not counted as a pass.
