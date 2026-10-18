# Default (composite) strategy with / without the IV/RV filter

Analyzer + DecisionEngine with default AccountSettings (minScore 35.0, ≥ 2 engines, trend alignment) evaluated at every completed bar (window 300 bars). Exits like the app defaults: stop −35.0%, take profit +90.0%, trailing 20.0% after +30.0%, max 10 sessions, out 2 days before expiry; contract ATM, first Friday ≥ 7 days. MODELED option prices. The IV/RV filter only varies for SPY (VIX) and QQQ (VXN); for single stocks the IV proxy is a fixed 1.3 × RV20, so IV/RV is constant and the filter is not testable there.

## h1 (2023-11-17 → 2026-10-16); discovery < 2025-05-02 ≤ validation < 2026-01-23 ≤ holdout

| universe | filter | dir | split  n | win % | expectancy | PF | total (2%/trade) | max DD | dir. hit % |
|---|---|---|---|---|---|---|---|---|---|---|
| all 7 | none | both | disc | 564 | 34 | -6.4% | 0.78 | -72.7% | 84.5% | 46 |
| all 7 | none | both | val | 308 | 27 | -17.4% | 0.45 | -107.3% | 112.5% | 44 |
| all 7 | none | both | hold | 285 | 31 | -10.4% | 0.65 | -59.4% | 64.1% | 44 |
| all 7 | none | both | **all** | 1157 | 31 | -10.3% | 0.65 | -239.4% | 241.9% | 45 |
| all 7 | none | call | disc | 307 | 32 | -9.8% | 0.65 | -60.4% | 60.4% | 49 |
| all 7 | none | call | val | 183 | 27 | -18.7% | 0.40 | -68.5% | 70.2% | 49 |
| all 7 | none | call | hold | 144 | 32 | -9.5% | 0.67 | -27.3% | 27.3% | 48 |
| all 7 | none | call | **all** | 634 | 31 | -12.3% | 0.58 | -156.2% | 156.2% | 48 |
| all 7 | none | put | disc | 257 | 35 | -2.4% | 0.92 | -12.3% | 35.4% | 43 |
| all 7 | none | put | val | 125 | 26 | -15.5% | 0.51 | -38.8% | 45.3% | 38 |
| all 7 | none | put | hold | 141 | 30 | -11.4% | 0.64 | -32.1% | 41.5% | 40 |
| all 7 | none | put | **all** | 523 | 32 | -8.0% | 0.74 | -83.2% | 86.7% | 41 |
| SPY+QQQ | none | both | disc | 164 | 38 | -1.5% | 0.94 | -5.0% | 20.9% | 46 |
| SPY+QQQ | none | both | val | 80 | 23 | -24.3% | 0.24 | -38.9% | 38.9% | 41 |
| SPY+QQQ | none | both | hold | 77 | 25 | -17.5% | 0.41 | -26.9% | 28.4% | 38 |
| SPY+QQQ | none | both | **all** | 321 | 31 | -11.0% | 0.62 | -70.8% | 72.3% | 43 |
| SPY+QQQ | none | call | disc | 85 | 35 | -10.0% | 0.64 | -16.9% | 19.0% | 46 |
| SPY+QQQ | none | call | val | 51 | 24 | -25.7% | 0.20 | -26.2% | 27.3% | 49 |
| SPY+QQQ | none | call | hold | 31 | 32 | -10.3% | 0.60 | -6.4% | 7.9% | 52 |
| SPY+QQQ | none | call | **all** | 167 | 31 | -14.8% | 0.49 | -49.5% | 50.5% | 48 |
| SPY+QQQ | none | put | disc | 79 | 41 | +7.5% | 1.28 | +11.9% | 14.7% | 47 |
| SPY+QQQ | none | put | val | 29 ⚠ | 21 | -21.9% | 0.31 | -12.7% | 12.8% | 28 |
| SPY+QQQ | none | put | hold | 46 | 20 | -22.3% | 0.31 | -20.5% | 23.9% | 28 |
| SPY+QQQ | none | put | **all** | 154 | 31 | -6.9% | 0.76 | -21.3% | 32.1% | 38 |
| SPY+QQQ | IV/RV ≤ 1.5 | both | disc | 135 | 39 | +0.8% | 1.03 | +2.1% | 17.7% | 47 |
| SPY+QQQ | IV/RV ≤ 1.5 | both | val | 41 | 20 | -25.4% | 0.25 | -20.8% | 20.8% | 34 |
| SPY+QQQ | IV/RV ≤ 1.5 | both | hold | 40 | 30 | -10.3% | 0.61 | -8.2% | 11.3% | 48 |
| SPY+QQQ | IV/RV ≤ 1.5 | both | **all** | 216 | 34 | -6.2% | 0.78 | -26.9% | 32.4% | 45 |
| SPY+QQQ | IV/RV ≤ 1.5 | call | disc | 69 | 39 | -6.4% | 0.76 | -8.8% | 12.3% | 48 |
| SPY+QQQ | IV/RV ≤ 1.5 | call | val | 23 ⚠ | 22 | -25.6% | 0.30 | -11.8% | 13.1% | 35 |
| SPY+QQQ | IV/RV ≤ 1.5 | call | hold | 17 ⚠ | 47 | +7.2% | 1.40 | +2.5% | 2.9% | 65 |
| SPY+QQQ | IV/RV ≤ 1.5 | call | **all** | 109 | 37 | -8.3% | 0.70 | -18.1% | 23.1% | 48 |
| SPY+QQQ | IV/RV ≤ 1.5 | put | disc | 66 | 39 | +8.2% | 1.31 | +10.9% | 12.4% | 47 |
| SPY+QQQ | IV/RV ≤ 1.5 | put | val | 18 ⚠ | 17 | -25.0% | 0.18 | -9.0% | 9.0% | 33 |
| SPY+QQQ | IV/RV ≤ 1.5 | put | hold | 23 ⚠ | 17 | -23.2% | 0.28 | -10.7% | 13.7% | 35 |
| SPY+QQQ | IV/RV ≤ 1.5 | put | **all** | 107 | 31 | -4.1% | 0.85 | -8.8% | 20.5% | 42 |
| SPY+QQQ | IV/RV ≤ 1.2 | both | disc | 92 | 37 | -2.3% | 0.91 | -4.3% | 16.0% | 47 |
| SPY+QQQ | IV/RV ≤ 1.2 | both | val | 20 ⚠ | 20 | -21.5% | 0.32 | -8.6% | 8.6% | 40 |
| SPY+QQQ | IV/RV ≤ 1.2 | both | hold | 19 ⚠ | 26 | -14.6% | 0.45 | -5.5% | 8.8% | 47 |
| SPY+QQQ | IV/RV ≤ 1.2 | both | **all** | 131 | 33 | -7.0% | 0.75 | -18.4% | 19.7% | 46 |
| SPY+QQQ | IV/RV ≤ 1.2 | call | disc | 48 | 35 | -12.8% | 0.54 | -12.3% | 12.9% | 46 |
| SPY+QQQ | IV/RV ≤ 1.2 | call | val | 10 ⚠ | 20 | -24.3% | 0.31 | -4.9% | 6.3% | 50 |
| SPY+QQQ | IV/RV ≤ 1.2 | call | hold | 7 ⚠⚠ | 43 | +3.4% | 1.16 | +0.5% | 3.0% | 57 |
| SPY+QQQ | IV/RV ≤ 1.2 | call | **all** | 65 | 34 | -12.8% | 0.55 | -16.7% | 17.1% | 48 |
| SPY+QQQ | IV/RV ≤ 1.2 | put | disc | 44 | 39 | +9.1% | 1.35 | +8.0% | 8.2% | 48 |
| SPY+QQQ | IV/RV ≤ 1.2 | put | val | 10 ⚠ | 20 | -18.7% | 0.34 | -3.7% | 4.7% | 30 |
| SPY+QQQ | IV/RV ≤ 1.2 | put | hold | 12 ⚠ | 17 | -25.0% | 0.13 | -6.0% | 6.0% | 42 |
| SPY+QQQ | IV/RV ≤ 1.2 | put | **all** | 66 | 32 | -1.3% | 0.95 | -1.7% | 10.5% | 44 |
| SPY+QQQ | break-even ≤ 1.0× expected | both | disc | 164 | 38 | -1.5% | 0.94 | -5.0% | 20.9% | 46 |
| SPY+QQQ | break-even ≤ 1.0× expected | both | val | 76 | 22 | -23.4% | 0.25 | -35.5% | 35.6% | 42 |
| SPY+QQQ | break-even ≤ 1.0× expected | both | hold | 77 | 25 | -17.5% | 0.41 | -26.9% | 28.4% | 38 |
| SPY+QQQ | break-even ≤ 1.0× expected | both | **all** | 317 | 31 | -10.6% | 0.63 | -67.5% | 69.0% | 43 |
| SPY+QQQ | break-even ≤ 1.0× expected | call | disc | 85 | 35 | -10.0% | 0.64 | -16.9% | 19.0% | 46 |
| SPY+QQQ | break-even ≤ 1.0× expected | call | val | 48 | 23 | -25.2% | 0.20 | -24.2% | 25.4% | 50 |
| SPY+QQQ | break-even ≤ 1.0× expected | call | hold | 31 | 32 | -10.3% | 0.60 | -6.4% | 7.9% | 52 |
| SPY+QQQ | break-even ≤ 1.0× expected | call | **all** | 164 | 31 | -14.5% | 0.49 | -47.5% | 48.6% | 48 |
| SPY+QQQ | break-even ≤ 1.0× expected | put | disc | 79 | 41 | +7.5% | 1.28 | +11.9% | 14.7% | 47 |
| SPY+QQQ | break-even ≤ 1.0× expected | put | val | 28 ⚠ | 21 | -20.2% | 0.33 | -11.3% | 11.4% | 29 |
| SPY+QQQ | break-even ≤ 1.0× expected | put | hold | 46 | 20 | -22.3% | 0.31 | -20.5% | 23.9% | 28 |
| SPY+QQQ | break-even ≤ 1.0× expected | put | **all** | 153 | 31 | -6.5% | 0.78 | -19.9% | 30.9% | 38 |

## m15 (2026-07-24 → 2026-10-16); discovery < 2026-09-04 ≤ validation < 2026-09-25 ≤ holdout

| universe | filter | dir | split  n | win % | expectancy | PF | total (2%/trade) | max DD | dir. hit % |
|---|---|---|---|---|---|---|---|---|---|---|
| all 7 | none | both | disc | 62 | 29 | -10.9% | 0.67 | -13.5% | 30.2% | 42 |
| all 7 | none | both | val | 39 | 18 | -23.6% | 0.23 | -18.4% | 18.8% | 36 |
| all 7 | none | both | hold | 46 | 33 | -12.4% | 0.53 | -11.4% | 14.1% | 43 |
| all 7 | none | both | **all** | 147 | 27 | -14.7% | 0.51 | -43.3% | 55.6% | 41 |
| all 7 | none | call | disc | 39 | 36 | -2.8% | 0.91 | -2.2% | 17.6% | 46 |
| all 7 | none | call | val | 21 ⚠ | 19 | -18.9% | 0.39 | -8.0% | 8.3% | 38 |
| all 7 | none | call | hold | 24 ⚠ | 25 | -23.4% | 0.13 | -11.2% | 11.2% | 46 |
| all 7 | none | call | **all** | 84 | 29 | -12.7% | 0.57 | -21.4% | 33.8% | 44 |
| all 7 | none | put | disc | 23 ⚠ | 17 | -24.7% | 0.34 | -11.4% | 16.0% | 35 |
| all 7 | none | put | val | 18 ⚠ | 17 | -29.0% | 0.04 | -10.4% | 10.6% | 33 |
| all 7 | none | put | hold | 22 ⚠ | 41 | -0.3% | 0.99 | -0.1% | 6.7% | 41 |
| all 7 | none | put | **all** | 63 | 25 | -17.4% | 0.44 | -22.0% | 30.4% | 37 |
| SPY+QQQ | none | both | disc | 17 ⚠ | 35 | -14.6% | 0.49 | -5.0% | 9.3% | 41 |
| SPY+QQQ | none | both | val | 12 ⚠ | 17 | -21.6% | 0.37 | -5.2% | 5.2% | 17 |
| SPY+QQQ | none | both | hold | 10 ⚠ | 40 | +1.0% | 1.05 | +0.2% | 2.6% | 60 |
| SPY+QQQ | none | both | **all** | 39 | 31 | -12.8% | 0.55 | -10.0% | 16.7% | 38 |
| SPY+QQQ | none | call | disc | 10 ⚠ | 40 | -6.3% | 0.79 | -1.3% | 5.7% | 40 |
| SPY+QQQ | none | call | val | 6 ⚠⚠ | 33 | -7.6% | 0.77 | -0.9% | 3.1% | 33 |
| SPY+QQQ | none | call | hold | 4 ⚠⚠ | 0 | -31.6% | 0.00 | -2.5% | 2.5% | 50 |
| SPY+QQQ | none | call | **all** | 20 ⚠ | 30 | -11.7% | 0.62 | -4.7% | 9.0% | 40 |
| SPY+QQQ | none | put | disc | 7 ⚠⚠ | 29 | -26.6% | 0.03 | -3.7% | 3.7% | 43 |
| SPY+QQQ | none | put | val | 6 ⚠⚠ | 0 | -35.6% | 0.00 | -4.3% | 4.3% | 0 |
| SPY+QQQ | none | put | hold | 6 ⚠⚠ | 67 | +22.6% | 2.59 | +2.7% | 0.9% | 67 |
| SPY+QQQ | none | put | **all** | 19 ⚠ | 32 | -13.9% | 0.46 | -5.3% | 8.8% | 37 |
| SPY+QQQ | IV/RV ≤ 1.5 | both | disc | 16 ⚠ | 38 | -12.4% | 0.55 | -4.0% | 8.3% | 44 |
| SPY+QQQ | IV/RV ≤ 1.5 | both | val | 6 ⚠⚠ | 17 | -24.8% | 0.39 | -3.0% | 4.8% | 17 |
| SPY+QQQ | IV/RV ≤ 1.5 | both | hold | 8 ⚠⚠ | 50 | +6.5% | 1.32 | +1.0% | 2.4% | 63 |
| SPY+QQQ | IV/RV ≤ 1.5 | both | **all** | 30 | 37 | -9.9% | 0.65 | -5.9% | 13.2% | 43 |
| SPY+QQQ | IV/RV ≤ 1.5 | call | disc | 9 ⚠⚠ | 44 | -1.5% | 0.95 | -0.3% | 4.8% | 44 |
| SPY+QQQ | IV/RV ≤ 1.5 | call | val | 4 ⚠⚠ | 25 | -16.0% | 0.59 | -1.3% | 3.1% | 25 |
| SPY+QQQ | IV/RV ≤ 1.5 | call | hold | 3 ⚠⚠ | 33 | -20.9% | 0.16 | -1.3% | 1.5% | 67 |
| SPY+QQQ | IV/RV ≤ 1.5 | call | **all** | 16 ⚠ | 38 | -8.7% | 0.71 | -2.8% | 7.2% | 44 |
| SPY+QQQ | IV/RV ≤ 1.5 | put | disc | 7 ⚠⚠ | 29 | -26.6% | 0.03 | -3.7% | 3.7% | 43 |
| SPY+QQQ | IV/RV ≤ 1.5 | put | val | 2 ⚠⚠ | 0 | -42.3% | 0.00 | -1.7% | 1.7% | 0 |
| SPY+QQQ | IV/RV ≤ 1.5 | put | hold | 5 ⚠⚠ | 60 | +22.9% | 2.34 | +2.3% | 0.9% | 60 |
| SPY+QQQ | IV/RV ≤ 1.5 | put | **all** | 14 ⚠ | 36 | -11.1% | 0.57 | -3.1% | 6.3% | 43 |
| SPY+QQQ | IV/RV ≤ 1.2 | both | disc | 12 ⚠ | 25 | -18.4% | 0.42 | -4.4% | 7.3% | 33 |
| SPY+QQQ | IV/RV ≤ 1.2 | both | val | 0 | — | — | — | — | — | — |
| SPY+QQQ | IV/RV ≤ 1.2 | both | hold | 0 | — | — | — | — | — | — |
| SPY+QQQ | IV/RV ≤ 1.2 | both | **all** | 12 ⚠ | 25 | -18.4% | 0.42 | -4.4% | 7.3% | 33 |
| SPY+QQQ | IV/RV ≤ 1.2 | call | disc | 6 ⚠⚠ | 33 | -4.8% | 0.84 | -0.6% | 3.6% | 33 |
| SPY+QQQ | IV/RV ≤ 1.2 | call | val | 0 | — | — | — | — | — | — |
| SPY+QQQ | IV/RV ≤ 1.2 | call | hold | 0 | — | — | — | — | — | — |
| SPY+QQQ | IV/RV ≤ 1.2 | call | **all** | 6 ⚠⚠ | 33 | -4.8% | 0.84 | -0.6% | 3.6% | 33 |
| SPY+QQQ | IV/RV ≤ 1.2 | put | disc | 6 ⚠⚠ | 17 | -31.9% | 0.00 | -3.8% | 3.8% | 33 |
| SPY+QQQ | IV/RV ≤ 1.2 | put | val | 0 | — | — | — | — | — | — |
| SPY+QQQ | IV/RV ≤ 1.2 | put | hold | 0 | — | — | — | — | — | — |
| SPY+QQQ | IV/RV ≤ 1.2 | put | **all** | 6 ⚠⚠ | 17 | -31.9% | 0.00 | -3.8% | 3.8% | 33 |
| SPY+QQQ | break-even ≤ 1.0× expected | both | disc | 17 ⚠ | 35 | -14.6% | 0.49 | -5.0% | 9.3% | 41 |
| SPY+QQQ | break-even ≤ 1.0× expected | both | val | 12 ⚠ | 17 | -21.6% | 0.37 | -5.2% | 5.2% | 17 |
| SPY+QQQ | break-even ≤ 1.0× expected | both | hold | 10 ⚠ | 40 | +1.0% | 1.05 | +0.2% | 2.6% | 60 |
| SPY+QQQ | break-even ≤ 1.0× expected | both | **all** | 39 | 31 | -12.8% | 0.55 | -10.0% | 16.7% | 38 |
| SPY+QQQ | break-even ≤ 1.0× expected | call | disc | 10 ⚠ | 40 | -6.3% | 0.79 | -1.3% | 5.7% | 40 |
| SPY+QQQ | break-even ≤ 1.0× expected | call | val | 6 ⚠⚠ | 33 | -7.6% | 0.77 | -0.9% | 3.1% | 33 |
| SPY+QQQ | break-even ≤ 1.0× expected | call | hold | 4 ⚠⚠ | 0 | -31.6% | 0.00 | -2.5% | 2.5% | 50 |
| SPY+QQQ | break-even ≤ 1.0× expected | call | **all** | 20 ⚠ | 30 | -11.7% | 0.62 | -4.7% | 9.0% | 40 |
| SPY+QQQ | break-even ≤ 1.0× expected | put | disc | 7 ⚠⚠ | 29 | -26.6% | 0.03 | -3.7% | 3.7% | 43 |
| SPY+QQQ | break-even ≤ 1.0× expected | put | val | 6 ⚠⚠ | 0 | -35.6% | 0.00 | -4.3% | 4.3% | 0 |
| SPY+QQQ | break-even ≤ 1.0× expected | put | hold | 6 ⚠⚠ | 67 | +22.6% | 2.59 | +2.7% | 0.9% | 67 |
| SPY+QQQ | break-even ≤ 1.0× expected | put | **all** | 19 ⚠ | 32 | -13.9% | 0.46 | -5.3% | 8.8% | 37 |
