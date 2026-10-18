# Round 4 — model trades replayed on real option prices (2024-02-05 → 2026-10-16)

Fill = 5-minute option-bar VWAP at the entry / exit time, plus a half-spread (ETF 1.5%, stock 3%) and $0.65/contract each side.
`model` = the same trades priced by the Black-Scholes proxy used everywhere else in round 4.

| strategy | trades | matched | model exp/trade | REAL exp/trade | REAL @ VWAP (no spread) | REAL win | REAL PF | REAL t | corr(model, real) | model entry px / real |
|---|---|---|---|---|---|---|---|---|---|---|
| A Trend-dip @15:50 | 439 | 409 | +19.2% | **-1.7%** | +3.7% | 0.47 | 0.95 | -0.44 | 0.76 | 0.85 |
| B Wave-2/B exhaustion @15:50 | 25 | 22 | -10.4% | **-3.7%** | +1.4% | 0.45 | 0.90 | -0.22 | 0.90 | 0.93 |
| C ORB-5 in play | 493 | 476 | +24.4% | **-12.1%** | -6.9% | 0.19 | 0.58 | -3.91 | 0.80 | 0.60 |
| D Noise-area momentum | 785 | 783 | +10.3% | **-2.1%** | +0.9% | 0.30 | 0.91 | -0.80 | 0.87 | 0.88 |

PF here = sum of winning returns / sum of losing returns (equal premium per trade). t = i.i.d. t-statistic.