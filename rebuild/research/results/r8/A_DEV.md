# Strategy A — development (selection on discovery 2016–2020, underlying expectancy in ATR)

| variant | DISC trades | DISC underlying E[ATR] | VALID trades | VALID underlying E[ATR] |
|---|---|---|---|---|
| {'hold_band': 0.25, 'gap_hi': 1.5, 'spacing': 40, 'clv_min': 0.75} | 2 | +nan | 4 | +0.557 |
| {'hold_band': 0.25, 'gap_hi': 1.5, 'spacing': 40, 'clv_min': 0.5} | 4 | -0.149 | 7 | +0.297 |
| {'hold_band': 0.25, 'gap_hi': 1.5, 'spacing': 1, 'clv_min': 0.75} | 4 | -0.459 | 8 | +0.021 |
| {'hold_band': 0.25, 'gap_hi': 1.5, 'spacing': 1, 'clv_min': 0.5} | 6 | -0.258 | 12 | +0.039 |
| {'hold_band': 0.25, 'gap_hi': 3.0, 'spacing': 40, 'clv_min': 0.75} | 2 | +nan | 4 | +0.557 |
| {'hold_band': 0.25, 'gap_hi': 3.0, 'spacing': 40, 'clv_min': 0.5} | 5 | -0.185 | 7 | +0.297 |
| {'hold_band': 0.25, 'gap_hi': 3.0, 'spacing': 1, 'clv_min': 0.75} | 5 | -0.199 | 8 | +0.021 |
| {'hold_band': 0.25, 'gap_hi': 3.0, 'spacing': 1, 'clv_min': 0.5} | 10 | -0.081 | 13 | +0.013 |
| {'hold_band': 0.5, 'gap_hi': 1.5, 'spacing': 40, 'clv_min': 0.75} | 3 | -0.262 | 7 | +0.449 |
| {'hold_band': 0.5, 'gap_hi': 1.5, 'spacing': 40, 'clv_min': 0.5} | 5 | -0.100 | 10 | +0.299 |
| {'hold_band': 0.5, 'gap_hi': 1.5, 'spacing': 1, 'clv_min': 0.75} | 13 | +0.071 | 18 | +0.039 |
| {'hold_band': 0.5, 'gap_hi': 1.5, 'spacing': 1, 'clv_min': 0.5} | 17 | +0.005 | 23 | +0.023 |
| {'hold_band': 0.5, 'gap_hi': 3.0, 'spacing': 40, 'clv_min': 0.75} | 3 | -0.262 | 8 | +0.407 |
| {'hold_band': 0.5, 'gap_hi': 3.0, 'spacing': 40, 'clv_min': 0.5} | 6 | -0.138 | 12 | +0.290 |
| {'hold_band': 0.5, 'gap_hi': 3.0, 'spacing': 1, 'clv_min': 0.75} | 18 | +0.040 | 19 | +0.043 |
| {'hold_band': 0.5, 'gap_hi': 3.0, 'spacing': 1, 'clv_min': 0.5} | 26 | -0.026 | 26 | +0.028 |
| {'hold_band': 99, 'gap_hi': 1.5, 'spacing': 40, 'clv_min': 0.75} | 9 | +0.149 | 9 | +0.295 |
| {'hold_band': 99, 'gap_hi': 1.5, 'spacing': 40, 'clv_min': 0.5} | 13 | +0.164 | 15 | +0.159 |
| {'hold_band': 99, 'gap_hi': 1.5, 'spacing': 1, 'clv_min': 0.75} | 24 | +0.040 | 27 | +0.204 |
| {'hold_band': 99, 'gap_hi': 1.5, 'spacing': 1, 'clv_min': 0.5} | 31 | -0.007 | 37 | +0.113 |
| {'hold_band': 99, 'gap_hi': 3.0, 'spacing': 40, 'clv_min': 0.75} | 13 | +0.076 | 12 | +0.347 |
| {'hold_band': 99, 'gap_hi': 3.0, 'spacing': 40, 'clv_min': 0.5} | 19 | +0.094 | 20 | +0.191 |
| {'hold_band': 99, 'gap_hi': 3.0, 'spacing': 1, 'clv_min': 0.75} | 33 | +0.012 | 32 | +0.231 |
| {'hold_band': 99, 'gap_hi': 3.0, 'spacing': 1, 'clv_min': 0.5} | 45 | -0.022 | 47 | +0.094 |

**Chosen on discovery:** {'hold_band': 99, 'gap_hi': 3.0, 'spacing': 1, 'clv_min': 0.5}

## Judgement of the developed variant (backtested)

| test | n | win | avg win | avg loss | return/trade | PF | t | maxDD* |
|---|---|---|---|---|---|---|---|---|
| model discovery — without contract filters | 45 | 0.33 | +39.2% | -31.5% | **-7.9%** | 0.62 | -1.39 | -8.1% |
| model discovery — with contract filters | 4 | 0.00 | +0.0% | -39.5% | **-39.5%** | 0.00 | -5.83 | -2.0% |
| model validation — without contract filters | 47 | 0.36 | +48.2% | -30.5% | **-2.1%** | 0.89 | -0.34 | -8.2% |
| model validation — with contract filters | 3 | 0.67 | +54.7% | -35.1% | **+24.8%** | 3.12 | 0.72 | -0.7% |
| model holdout — without contract filters | 10 | 0.30 | +101.9% | -27.5% | **+11.3%** | 1.59 | 0.39 | -2.8% |
| model holdout — with contract filters | 2 | — | — | — | — | — | — | — |
| REAL development symbols — all matched | 28 | 0.18 | +84.9% | -36.0% | **-14.4%** | 0.51 | -1.39 | -10.1% |
| REAL development symbols — with report's contract filters | 3 | 0.33 | +108.4% | -10.9% | **+28.9%** | 4.99 | 0.73 | -0.3% |
| REAL development symbols — all matched, dev 24/02–25/06 | 9 | 0.00 | +0.0% | -37.8% | **-37.8%** | 0.00 | -7.75 | -6.4% |
| REAL development symbols — all matched, test 25/07–26/10 | 19 | 0.26 | +84.9% | -34.8% | **-3.3%** | 0.87 | -0.23 | -4.4% |
| REAL development symbols — all matched, 2× half-spread | 28 | 0.18 | +74.1% | -39.7% | **-19.4%** | 0.41 | -1.99 | -11.9% |
| REAL development symbols — all matched, without 5 best | 23 | 0.00 | +0.0% | -36.0% | **-36.0%** | 0.00 | -11.06 | -15.2% |
| REAL NEW symbols (never used) — all matched | 33 | 0.24 | +33.3% | -39.1% | **-21.6%** | 0.27 | -3.41 | -13.6% |
| REAL NEW symbols (never used) — with report's contract filters | 7 | 0.14 | +10.3% | -32.8% | **-26.7%** | 0.05 | -3.45 | -3.4% |
| REAL NEW symbols (never used) — all matched, dev 24/02–25/06 | 23 | 0.22 | +29.4% | -36.4% | **-22.1%** | 0.22 | -3.26 | -10.2% |
| REAL NEW symbols (never used) — all matched, test 25/07–26/10 | 10 | 0.30 | +39.6% | -46.2% | **-20.4%** | 0.37 | -1.40 | -4.0% |
| REAL NEW symbols (never used) — all matched, 2× half-spread | 33 | 0.24 | +25.5% | -42.7% | **-26.2%** | 0.19 | -4.38 | -15.9% |
| REAL NEW symbols (never used) — all matched, without 5 best | 28 | 0.11 | +15.3% | -39.1% | **-33.3%** | 0.05 | -7.22 | -16.8% |