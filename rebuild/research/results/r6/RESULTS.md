# Round 6 — the three proposed strategies, backtested as specified

All results are **backtested**. *model* = Black-Scholes, IV proxy × real-calibrated term multiplier; *REAL* = the same trades re-priced on real option prints (Alpaca, 2024-02-05 → 2026-10-16), fill = 5-min VWAP ± half-spread (ETF 1.5 %, stock 3 %) + $0.65/contract/side.
Return per trade is on premium paid incl. commissions. maxDD* = sequential equity with 2 % of equity per trade (model rows: daily NAV of the simulator).

## S1 MTF-Momentum Call

**A. Underlying (daily-ATR units, direction-adjusted), entry next bar open**

| period | n | +0.5 ATR before stop same day | within 2d | close same day | close day 2 | t(day 2) |
|---|---|---|---|---|---|---|
| discovery 2016–20 | 166 | 24% | 62% | +0.052 | +0.084 | 0.99 |
| validation 2021–26/04 | 219 | 25% | 58% | -0.010 | +0.173 | 2.63 |
| holdout 26/04–26/10 | 23 | 30% | 65% | +0.077 | -0.088 | -0.71 |

**B. Weekly options — model (backtested)**

| test | n | win | avg win | avg loss | return/trade | PF | t | maxDD* |
|---|---|---|---|---|---|---|---|---|
| model — discovery | 151 | 0.48 | +59.0% | -42.3% | **+6.7%** | 1.31 | 1.34 | -11.4% |
| model — validation | 190 | 0.46 | +72.8% | -45.8% | **+9.2%** | 1.37 | 1.35 | -12.8% |
| model — holdout | 24 | 0.38 | +75.3% | -50.3% | **-3.2%** | 0.90 | -0.23 | -5.7% |
| model validation — 2× costs | 190 | 0.46 | +64.1% | -48.2% | **+3.2%** | 1.12 | 0.50 | -18.4% |
| model validation — without 5 best | 185 | 0.45 | +52.2% | -45.8% | **-1.8%** | 0.93 | -0.43 | -23.1% |
| model validation — ETFs | 31 | 0.35 | +53.5% | -43.5% | **-9.1%** | 0.68 | -0.98 | -8.5% |
| model validation — single stocks | 159 | 0.48 | +75.6% | -46.3% | **+12.7%** | 1.53 | 1.62 | -12.9% |
| model — year 2021 | 38 | 0.47 | +66.9% | -41.1% | **+10.1%** | 1.47 | 0.95 | -7.8% |
| model — year 2022 | 22 | 0.45 | +44.4% | -40.0% | **-1.6%** | 0.93 | -0.15 | -4.2% |
| model — year 2023 | 38 | 0.45 | +102.3% | -45.6% | **+20.6%** | 1.82 | 0.96 | -6.8% |
| model — year 2024 | 46 | 0.41 | +85.1% | -45.3% | **+8.6%** | 1.32 | 0.51 | -9.9% |
| model — year 2025 | 31 | 0.55 | +50.0% | -56.6% | **+1.9%** | 1.07 | 0.17 | -5.2% |
| model — year 2026 | 39 | 0.41 | +77.1% | -50.0% | **+2.1%** | 1.07 | 0.19 | -10.5% |

**C. Weekly options — REAL option prices 2024-02 → 2026-10 (backtested; 106 of 112 trades matched to a traded contract)**

| test | n | win | avg win | avg loss | return/trade | PF | t | maxDD* |
|---|---|---|---|---|---|---|---|---|
| REAL — all | 106 | 0.43 | +70.9% | -52.6% | **+1.0%** | 1.03 | 0.13 | -12.4% |
| REAL — with IV/RV20 ≤ 1.3 (as specified) | 63 | 0.38 | +71.3% | -52.0% | **-5.0%** | 0.84 | -0.57 | -17.4% |
| REAL — dev 2024-02→2025-06 | 47 | 0.38 | +71.0% | -51.6% | **-4.6%** | 0.85 | -0.38 | -12.4% |
| REAL — test 2025-07→2026-10 | 59 | 0.47 | +70.8% | -53.6% | **+5.5%** | 1.19 | 0.59 | -11.7% |
| REAL — filtered, test only | 31 | 0.48 | +81.6% | -48.5% | **+14.5%** | 1.58 | 1.05 | -4.2% |
| REAL — 2× half-spread | 106 | 0.42 | +64.7% | -53.2% | **-4.3%** | 0.86 | -0.61 | -14.6% |
| REAL — at VWAP, no spread | 106 | 0.43 | +80.5% | -50.1% | **+6.6%** | 1.23 | 0.83 | -10.8% |
| REAL — without 5 best | 101 | 0.41 | +54.1% | -52.6% | **-9.3%** | 0.70 | -1.60 | -22.4% |
| REAL — ETFs | 26 | 0.35 | +53.9% | -45.2% | **-10.9%** | 0.63 | -1.04 | -9.3% |
| REAL — single stocks | 80 | 0.46 | +75.0% | -55.5% | **+4.9%** | 1.16 | 0.52 | -11.4% |
| REAL — without NVDA/TSLA/AMD/META | 71 | 0.41 | +78.3% | -51.3% | **+1.6%** | 1.05 | 0.17 | -11.6% |
| REAL — year 2024 | 37 | 0.38 | +73.0% | -48.9% | **-2.8%** | 0.91 | -0.19 | -11.7% |
| REAL — year 2025 | 29 | 0.52 | +65.2% | -56.5% | **+6.5%** | 1.24 | 0.48 | -5.5% |
| REAL — year 2026 | 40 | 0.42 | +74.2% | -53.9% | **+0.5%** | 1.02 | 0.05 | -11.7% |

Model on the same matched trades: +6.6% per trade; median real/model entry price: 0.83; median IV/RV20 at entry: 1.22.

## S2 Downtrend-Regime Put

**A. Underlying (daily-ATR units, direction-adjusted), entry next bar open**

| period | n | +0.5 ATR before stop same day | within 2d | close same day | close day 2 | t(day 2) |
|---|---|---|---|---|---|---|
| discovery 2016–20 | 135 | 21% | 45% | -0.036 | -0.062 | -0.99 |
| validation 2021–26/04 | 187 | 19% | 41% | -0.034 | -0.014 | -0.24 |
| holdout 26/04–26/10 | 2 | 50% | 50% | +0.032 | +0.318 | — |

**B. Weekly options — model (backtested)**

| test | n | win | avg win | avg loss | return/trade | PF | t | maxDD* |
|---|---|---|---|---|---|---|---|---|
| model — discovery | 108 | 0.32 | +44.8% | -45.2% | **-16.0%** | 0.48 | -3.41 | -32.3% |
| model — validation | 152 | 0.30 | +58.8% | -44.1% | **-12.9%** | 0.58 | -2.97 | -28.5% |
| model — holdout | 2 | — | — | — | — | — | — | — |
| model validation — 2× costs | 149 | 0.31 | +50.8% | -47.4% | **-17.1%** | 0.48 | -4.04 | -40.1% |
| model validation — without 5 best | 147 | 0.28 | +48.7% | -44.1% | **-18.2%** | 0.43 | -4.88 | -41.1% |
| model validation — ETFs | 42 | 0.29 | +72.1% | -50.7% | **-15.6%** | 0.57 | -1.61 | -11.6% |
| model validation — single stocks | 110 | 0.31 | +54.2% | -41.5% | **-11.9%** | 0.58 | -2.50 | -23.1% |
| model — year 2021 | 8 | 0.00 | +0.0% | -56.0% | **-56.0%** | 0.00 | -11.37 | -7.4% |
| model — year 2022 | 79 | 0.35 | +53.0% | -45.4% | **-10.5%** | 0.64 | -1.81 | -17.9% |
| model — year 2023 | 8 | 0.38 | +58.9% | -40.2% | **-3.1%** | 0.88 | -0.15 | -3.4% |
| model — year 2024 | 10 | 0.60 | +47.8% | -39.2% | **+13.0%** | 1.83 | 0.86 | -2.1% |
| model — year 2025 | 30 | 0.13 | +106.1% | -39.7% | **-20.3%** | 0.41 | -1.84 | -13.9% |
| model — year 2026 | 19 | 0.32 | +59.4% | -39.9% | **-8.6%** | 0.69 | -0.69 | -4.0% |

**C. Weekly options — REAL option prices 2024-02 → 2026-10 (backtested; 55 of 61 trades matched to a traded contract)**

| test | n | win | avg win | avg loss | return/trade | PF | t | maxDD* |
|---|---|---|---|---|---|---|---|---|
| REAL — all | 55 | 0.29 | +80.3% | -54.5% | **-15.3%** | 0.60 | -1.59 | -21.2% |
| REAL — with IV/RV20 ≤ 1.4 (as specified) | 45 | 0.29 | +71.7% | -53.5% | **-17.3%** | 0.54 | -1.72 | -21.2% |
| REAL — dev 2024-02→2025-06 | 36 | 0.31 | +79.1% | -54.6% | **-13.7%** | 0.64 | -1.15 | -12.8% |
| REAL — test 2025-07→2026-10 | 19 | 0.26 | +83.1% | -54.5% | **-18.3%** | 0.54 | -1.11 | -8.9% |
| REAL — filtered, test only | 14 | 0.29 | +83.4% | -52.2% | **-13.4%** | 0.64 | -0.67 | -7.2% |
| REAL — 2× half-spread | 55 | 0.27 | +75.8% | -55.5% | **-19.7%** | 0.51 | -2.16 | -24.1% |
| REAL — at VWAP, no spread | 55 | 0.29 | +90.2% | -52.0% | **-10.6%** | 0.71 | -1.05 | -18.4% |
| REAL — without 5 best | 50 | 0.22 | +49.4% | -54.5% | **-31.7%** | 0.26 | -4.53 | -29.0% |
| REAL — ETFs | 13 | 0.23 | +115.7% | -65.5% | **-23.7%** | 0.53 | -0.94 | -6.9% |
| REAL — single stocks | 42 | 0.31 | +72.2% | -50.8% | **-12.7%** | 0.64 | -1.26 | -14.8% |
| REAL — without NVDA/TSLA/AMD/META | 35 | 0.26 | +103.4% | -51.5% | **-11.7%** | 0.69 | -0.89 | -14.1% |
| REAL — year 2024 | 8 | 0.50 | +70.4% | -60.2% | **+5.1%** | 1.17 | 0.20 | -3.8% |
| REAL — year 2025 | 32 | 0.22 | +84.0% | -56.6% | **-25.8%** | 0.42 | -2.09 | -17.1% |
| REAL — year 2026 | 15 | 0.33 | +83.1% | -47.1% | **-3.7%** | 0.88 | -0.19 | -4.0% |

Model on the same matched trades: -14.6% per trade; median real/model entry price: 0.74; median IV/RV20 at entry: 0.95.

## S3 Squeeze-Breakout Call (60m)

**A. Underlying (daily-ATR units, direction-adjusted), entry next bar open**

| period | n | +0.5 ATR before stop same day | within 2d | close same day | close day 2 | t(day 2) |
|---|---|---|---|---|---|---|
| discovery 2016–20 | 922 | 19% | 48% | +0.018 | +0.070 | 2.39 |
| validation 2021–26/04 | 806 | 19% | 48% | -0.011 | +0.048 | 1.49 |
| holdout 26/04–26/10 | 84 | 14% | 43% | -0.060 | +0.036 | 0.41 |

**B. Weekly options — model (backtested)**

| test | n | win | avg win | avg loss | return/trade | PF | t | maxDD* |
|---|---|---|---|---|---|---|---|---|
| model — discovery | 735 | 0.36 | +71.6% | -52.1% | **-7.0%** | 0.79 | -2.76 | -66.9% |
| model — validation | 630 | 0.36 | +73.9% | -52.2% | **-7.0%** | 0.79 | -2.40 | -62.9% |
| model — holdout | 71 | 0.34 | +74.6% | -51.0% | **-8.6%** | 0.75 | -1.08 | -20.0% |
| model validation — 2× costs | 584 | 0.35 | +67.2% | -55.2% | **-12.3%** | 0.66 | -4.20 | -79.6% |
| model validation — without 5 best | 625 | 0.35 | +66.8% | -52.2% | **-10.1%** | 0.70 | -4.00 | -78.4% |
| model validation — ETFs | 122 | 0.32 | +52.5% | -50.9% | **-17.8%** | 0.48 | -3.61 | -37.5% |
| model validation — single stocks | 508 | 0.37 | +78.4% | -52.6% | **-4.4%** | 0.87 | -1.29 | -57.3% |
| model — year 2021 | 142 | 0.43 | +86.2% | -56.3% | **+4.9%** | 1.15 | 0.68 | -14.9% |
| model — year 2022 | 78 | 0.24 | +48.0% | -50.8% | **-26.7%** | 0.30 | -4.81 | -34.7% |
| model — year 2023 | 144 | 0.33 | +70.0% | -52.2% | **-11.5%** | 0.67 | -1.81 | -38.3% |
| model — year 2024 | 140 | 0.37 | +70.2% | -52.8% | **-7.1%** | 0.79 | -1.23 | -32.8% |
| model — year 2025 | 108 | 0.35 | +71.8% | -46.6% | **-4.9%** | 0.84 | -0.77 | -15.2% |
| model — year 2026 | 89 | 0.36 | +80.8% | -53.1% | **-5.0%** | 0.85 | -0.66 | -24.1% |

**C. Weekly options — REAL option prices 2024-02 → 2026-10 (backtested; 330 of 354 trades matched to a traded contract)**

| test | n | win | avg win | avg loss | return/trade | PF | t | maxDD* |
|---|---|---|---|---|---|---|---|---|
| REAL — all | 330 | 0.34 | +98.3% | -54.3% | **-2.0%** | 0.94 | -0.45 | -27.7% |
| REAL — with IV/RV20 ≤ 1.25 (as specified) | 228 | 0.32 | +105.9% | -58.4% | **-6.5%** | 0.84 | -1.15 | -29.9% |
| REAL — dev 2024-02→2025-06 | 167 | 0.35 | +103.9% | -55.8% | **-0.4%** | 0.99 | -0.06 | -27.7% |
| REAL — test 2025-07→2026-10 | 163 | 0.34 | +92.5% | -52.7% | **-3.7%** | 0.89 | -0.61 | -24.7% |
| REAL — filtered, test only | 104 | 0.31 | +101.8% | -56.6% | **-7.9%** | 0.80 | -0.98 | -24.7% |
| REAL — 2× half-spread | 330 | 0.34 | +89.4% | -56.1% | **-7.2%** | 0.81 | -1.68 | -42.2% |
| REAL — at VWAP, no spread | 330 | 0.35 | +106.7% | -52.5% | **+3.4%** | 1.10 | 0.72 | -22.8% |
| REAL — without 5 best | 325 | 0.33 | +91.0% | -54.3% | **-6.0%** | 0.83 | -1.42 | -37.8% |
| REAL — ETFs | 78 | 0.29 | +74.2% | -53.9% | **-16.1%** | 0.58 | -2.15 | -24.2% |
| REAL — single stocks | 252 | 0.36 | +104.5% | -54.4% | **+2.3%** | 1.07 | 0.43 | -16.1% |
| REAL — without NVDA/TSLA/AMD/META | 250 | 0.32 | +94.7% | -55.5% | **-8.0%** | 0.79 | -1.60 | -37.9% |
| REAL — year 2024 | 127 | 0.34 | +103.9% | -55.9% | **-1.8%** | 0.95 | -0.24 | -18.5% |
| REAL — year 2025 | 118 | 0.32 | +87.6% | -48.1% | **-4.4%** | 0.86 | -0.65 | -16.1% |
| REAL — year 2026 | 85 | 0.38 | +103.6% | -60.9% | **+1.0%** | 1.03 | 0.11 | -24.7% |

Model on the same matched trades: -8.0% per trade; median real/model entry price: 0.81; median IV/RV20 at entry: 1.08.

## S3 Squeeze-Breakout Call (daily @15:50)

**A. Underlying (daily-ATR units, direction-adjusted), entry next bar open**

| period | n | +0.5 ATR before stop same day | within 2d | close same day | close day 2 | t(day 2) |
|---|---|---|---|---|---|---|
| discovery 2016–20 | 103 | 0% | 58% | -0.001 | +0.260 | 3.34 |
| validation 2021–26/04 | 87 | 0% | 57% | -0.026 | +0.190 | 1.77 |
| holdout 26/04–26/10 | 5 | 0% | 60% | +0.004 | -0.012 | -0.03 |

**B. Weekly options — model (backtested)**

| test | n | win | avg win | avg loss | return/trade | PF | t | maxDD* |
|---|---|---|---|---|---|---|---|---|
| model — discovery | 102 | 0.48 | +79.9% | -51.0% | **+11.9%** | 1.45 | 1.64 | -11.4% |
| model — validation | 86 | 0.43 | +107.6% | -53.8% | **+15.6%** | 1.51 | 1.33 | -10.6% |
| model — holdout | 4 | 0.00 | +0.0% | -63.0% | **-63.0%** | 0.00 | -4.37 | -4.3% |
| model validation — 2× costs | 86 | 0.43 | +95.9% | -56.5% | **+9.1%** | 1.28 | 0.82 | -14.9% |
| model validation — without 5 best | 81 | 0.40 | +70.4% | -53.8% | **-4.7%** | 0.85 | -0.63 | -18.8% |
| model validation — ETFs | 7 | 0.57 | +43.0% | -57.1% | **+0.1%** | 1.00 | 0.00 | -2.1% |
| model validation — single stocks | 79 | 0.42 | +115.4% | -53.6% | **+17.0%** | 1.54 | 1.34 | -10.7% |
| model — year 2021 | 22 | 0.32 | +112.7% | -57.1% | **-3.1%** | 0.92 | -0.15 | -7.8% |
| model — year 2022 | 6 | 0.33 | +81.4% | -54.7% | **-9.3%** | 0.74 | -0.30 | -4.3% |
| model — year 2023 | 25 | 0.40 | +54.6% | -48.3% | **-7.1%** | 0.75 | -0.59 | -6.3% |
| model — year 2024 | 19 | 0.47 | +193.5% | -57.9% | **+61.2%** | 3.01 | 1.52 | -4.6% |
| model — year 2025 | 11 | 0.73 | +82.1% | -49.4% | **+46.2%** | 4.43 | 2.14 | -1.2% |
| model — year 2026 | 7 | 0.14 | +84.5% | -60.5% | **-39.8%** | 0.23 | -1.79 | -4.9% |

**C. Weekly options — REAL option prices 2024-02 → 2026-10 (backtested; 34 of 36 trades matched to a traded contract)**

| test | n | win | avg win | avg loss | return/trade | PF | t | maxDD* |
|---|---|---|---|---|---|---|---|---|
| REAL — all | 34 | 0.47 | +116.8% | -61.5% | **+22.4%** | 1.69 | 1.28 | -5.3% |
| REAL — with IV/RV20 ≤ 1.25 (as specified) | 15 | 0.33 | +132.6% | -63.5% | **+1.9%** | 1.04 | 0.07 | -8.0% |
| REAL — dev 2024-02→2025-06 | 20 | 0.50 | +102.2% | -61.4% | **+20.4%** | 1.67 | 0.97 | -5.3% |
| REAL — test 2025-07→2026-10 | 14 | 0.43 | +141.2% | -61.7% | **+25.3%** | 1.72 | 0.81 | -4.5% |
| REAL — filtered, test only | 6 | 0.33 | +199.1% | -55.3% | **+29.5%** | 1.80 | 0.49 | -3.2% |
| REAL — 2× half-spread | 34 | 0.47 | +104.2% | -63.7% | **+15.3%** | 1.45 | 0.93 | -5.7% |
| REAL — at VWAP, no spread | 34 | 0.47 | +130.2% | -59.2% | **+30.0%** | 1.96 | 1.61 | -5.0% |
| REAL — without 5 best | 29 | 0.38 | +84.3% | -61.5% | **-6.2%** | 0.84 | -0.44 | -7.3% |
| REAL — ETFs | 1 | — | — | — | — | — | — | — |
| REAL — single stocks | 33 | 0.48 | +116.8% | -60.8% | **+25.3%** | 1.81 | 1.42 | -4.5% |
| REAL — without NVDA/TSLA/AMD/META | 23 | 0.43 | +117.3% | -63.7% | **+15.0%** | 1.42 | 0.73 | -7.9% |
| REAL — year 2024 | 16 | 0.44 | +116.6% | -66.1% | **+13.8%** | 1.37 | 0.54 | -5.3% |
| REAL — year 2025 | 10 | 0.70 | +95.2% | -46.5% | **+52.7%** | 4.78 | 2.17 | -1.5% |
| REAL — year 2026 | 8 | 0.25 | +193.4% | -62.1% | **+1.8%** | 1.04 | 0.04 | -4.0% |

Model on the same matched trades: +40.4% per trade; median real/model entry price: 0.90; median IV/RV20 at entry: 1.29.
