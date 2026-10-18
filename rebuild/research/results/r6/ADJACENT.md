# Round 6 — adjacent thresholds (backtested)

| strategy | variant | model validation n / return | REAL n / return | REAL t |
|---|---|---|---|---|
| S1 MTF-Momentum Call | as specified | 190 / +9.2% | 106 / +1.0% | 0.13 |
| S1 MTF-Momentum Call | {'rsi_lo': 25} | 76 / -2.7% | 46 / -14.1% | -1.51 |
| S1 MTF-Momentum Call | {'rsi_lo': 35} | 375 / +0.7% | 200 / -5.3% | -1.07 |
| S1 MTF-Momentum Call | {'h_max': 30} | 133 / +9.9% | 79 / -2.6% | -0.34 |
| S1 MTF-Momentum Call | {'h_max': 40} | 216 / +5.7% | 125 / -1.8% | -0.27 |
| S1 MTF-Momentum Call | {'adx_min': 15} | 192 / +9.6% | 107 / +0.6% | 0.08 |
| S1 MTF-Momentum Call | {'vol_mult': 1.0} | 222 / +7.5% | 124 / -0.8% | -0.12 |
| S1 MTF-Momentum Call | {'confirm': False} | 1348 / +4.3% | 719 / -2.9% | -1.15 |
| S2 Downtrend-Regime Put | as specified | 152 / -12.9% | 55 / -15.3% | -1.59 |
| S2 Downtrend-Regime Put | {'ob': 75, 'cross': 70} | 80 / +8.4% | 31 / -17.8% | -1.59 |
| S2 Downtrend-Regime Put | {'ob': 65, 'cross': 60} | 190 / -13.3% | 65 / -15.0% | -1.73 |
| S2 Downtrend-Regime Put | {'adx_min': 20} | 215 / -10.7% | 71 / -21.6% | -2.75 |
| S2 Downtrend-Regime Put | {'adx_min': 30} | 102 / -14.0% | 35 / -11.4% | -0.86 |
| S2 Downtrend-Regime Put | {'vol_mult': 1.0} | 180 / -10.6% | 70 / -4.1% | -0.45 |
| S3 Squeeze-Breakout Call (60m) | as specified | 630 / -7.0% | 330 / -2.0% | -0.45 |
| S3 Squeeze-Breakout Call (60m) | {'pct': 0.1} | 476 / -8.7% | 251 / -7.6% | -1.52 |
| S3 Squeeze-Breakout Call (60m) | {'pct': 0.3} | 738 / -6.6% | 377 / -1.2% | -0.29 |
| S3 Squeeze-Breakout Call (60m) | {'vol_mult': 1.2} | 719 / -5.3% | 378 / -0.2% | -0.06 |
| S3 Squeeze-Breakout Call (60m) | {'vol_mult': 2.0} | 484 / -4.1% | 252 / -0.7% | -0.13 |
| S3 Squeeze-Breakout Call (daily @15:50) | as specified | 86 / +15.6% | 34 / +22.4% | 1.28 |
| S3 Squeeze-Breakout Call (daily @15:50) | {'pct': 0.1} | 68 / +21.2% | 28 / +17.4% | 0.98 |
| S3 Squeeze-Breakout Call (daily @15:50) | {'pct': 0.3} | 100 / +15.7% | 41 / +20.1% | 1.27 |
| S3 Squeeze-Breakout Call (daily @15:50) | {'vol_mult': 1.2} | 149 / +10.4% | 66 / +18.5% | 1.66 |
| S3 Squeeze-Breakout Call (daily @15:50) | {'vol_mult': 2.0} | 37 / +10.3% | 16 / +26.2% | 1.10 |