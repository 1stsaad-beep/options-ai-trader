# Real implied volatility at entry as a filter

IV/RV = implied vol of the bought contract (real print) / 20-day realised vol of the underlying.

| strategy | period | n | median IV/RV | REAL exp: IV/RV below dev median | REAL exp: above | n below |
|---|---|---|---|---|---|---|
| A Trend-dip @15:50 | dev | 202 | 1.28 | -16.5% | +3.3% | 101 |
| A Trend-dip @15:50 | test | 206 | 1.31 | +2.6% | +4.2% | 99 |
| C ORB-5 in play | dev | 252 | 1.95 | -13.7% | -9.1% | 126 |
| C ORB-5 in play | test | 219 | 1.88 | -14.2% | -12.5% | 112 |
| D Noise-area momentum | dev | 380 | 2.14 | -4.9% | +2.1% | 190 |
| D Noise-area momentum | test | 354 | 1.94 | -5.3% | -2.4% | 221 |
| Pre-FOMC (ETFs) | dev | 33 | 1.45 | -1.0% | +29.7% | 17 |
| Pre-FOMC (ETFs) | test | 30 | 1.51 | -7.1% | -4.8% | 14 |

Threshold = the DEV median IV/RV of each strategy (fixed before looking at test).

## Pooled (all four), real return by IV/RV bucket

| IV/RV bucket | dev n | dev REAL exp | test n | test REAL exp |
|---|---|---|---|---|
| 0–0.9 | 51 | -13.3% | 50 | +9.4% |
| 0.9–1.1 | 67 | -9.4% | 64 | +2.2% |
| 1.1–1.3 | 104 | -9.4% | 97 | -11.9% |
| 1.3–1.6 | 140 | -6.1% | 169 | -1.6% |
| 1.6–99 | 505 | -2.3% | 429 | -7.1% |