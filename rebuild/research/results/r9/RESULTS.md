# Round 9 — same signals, four instruments, REAL option prices 2024-02 → 2026-10 (backtested)

Return per trade: STOCK on notional; CALL/LONG on premium; SPREAD on net debit. Each leg pays a half-spread (ETF 1.5 %, stock 3 %) + $0.65/contract/side.

## SQZ

| universe | period | STOCK | CALL (weekly) | SPREAD (weekly) | LONG (45–90 d, Δ0.75) |
|---|---|---|---|---|---|
| orig | all | +0.9% (n 36, t 1.47, win 53%) | +19.4% (n 34, t 1.10, win 47%) | -4.5% (n 34, t -0.40, win 47%) | +0.1% (n 20, t 0.02, win 55%) |
| orig | 2024-02→2025-06 | +0.7% (n 22, t 0.98, win 59%) | +15.3% (n 20, t 0.72, win 50%) | -5.1% (n 20, t -0.34, win 50%) | -1.4% (n 12, t -0.16, win 50%) |
| orig | 2025-07→2026-10 | +1.2% (n 14, t 1.08, win 43%) | +25.3% (n 14, t 0.81, win 43%) | -3.7% (n 14, t -0.20, win 43%) | +2.4% (n 8, t 0.32, win 62%) |
| orig | 2× half-spread | | +12.4% (n 34, t 0.75, win 47%) | -22.1% (n 34, t -2.40, win 35%) | -5.7% (n 20, t -1.01, win 55%) |
| new | all | +0.3% (n 79, t 0.88, win 53%) | +11.9% (n 73, t 1.06, win 48%) | -5.8% (n 72, t -0.72, win 50%) | -7.0% (n 37, t -1.53, win 46%) |
| new | 2024-02→2025-06 | +0.7% (n 47, t 1.24, win 57%) | +17.6% (n 44, t 1.17, win 52%) | -0.4% (n 44, t -0.04, win 52%) | -8.1% (n 20, t -1.22, win 45%) |
| new | 2025-07→2026-10 | -0.1% (n 32, t -0.22, win 47%) | +3.4% (n 29, t 0.20, win 41%) | -14.2% (n 28, t -1.20, win 46%) | -5.7% (n 17, t -0.89, win 47%) |
| new | 2× half-spread | | +5.4% (n 73, t 0.51, win 45%) | -20.8% (n 72, t -3.02, win 40%) | -12.4% (n 37, t -2.89, win 38%) |

## TDL

| universe | period | STOCK | CALL (weekly) | SPREAD (weekly) | LONG (45–90 d, Δ0.75) |
|---|---|---|---|---|---|
| orig | all | +0.4% (n 317, t 1.95, win 57%) | -4.2% (n 298, t -0.89, win 45%) | -9.9% (n 289, t -2.62, win 47%) | -2.6% (n 89, t -1.10, win 49%) |
| orig | 2024-02→2025-06 | +0.1% (n 153, t 0.52, win 55%) | -9.5% (n 144, t -1.36, win 41%) | -15.1% (n 139, t -2.67, win 42%) | -0.1% (n 42, t -0.02, win 57%) |
| orig | 2025-07→2026-10 | +0.5% (n 164, t 2.39, win 60%) | +0.8% (n 154, t 0.13, win 49%) | -5.2% (n 150, t -1.02, win 52%) | -4.9% (n 47, t -1.86, win 43%) |
| orig | 2× half-spread | | -9.2% (n 298, t -2.09, win 44%) | -20.5% (n 289, t -6.09, win 42%) | -7.9% (n 89, t -3.50, win 36%) |
| new | all | +0.3% (n 564, t 1.87, win 58%) | -10.5% (n 444, t -2.51, win 38%) | -15.0% (n 404, t -4.34, win 39%) | -10.5% (n 89, t -3.71, win 34%) |
| new | 2024-02→2025-06 | +0.1% (n 303, t 0.64, win 56%) | -9.6% (n 244, t -1.78, win 41%) | -15.4% (n 224, t -3.47, win 41%) | -13.5% (n 48, t -3.16, win 29%) |
| new | 2025-07→2026-10 | +0.4% (n 261, t 2.00, win 60%) | -11.6% (n 200, t -1.77, win 34%) | -14.4% (n 180, t -2.66, win 38%) | -6.9% (n 41, t -1.97, win 39%) |
| new | 2× half-spread | | -15.7% (n 444, t -3.99, win 36%) | -25.9% (n 404, t -8.49, win 31%) | -15.7% (n 89, t -5.91, win 26%) |

## FOMC

| universe | period | STOCK | CALL (weekly) | SPREAD (weekly) | LONG (45–90 d, Δ0.75) |
|---|---|---|---|---|---|
| orig | all | +0.2% (n 63, t 1.93, win 57%) | +4.2% (n 63, t 0.77, win 49%) | -3.2% (n 63, t -0.78, win 43%) | -0.5% (n 16, t -0.25, win 62%) |
| orig | 2024-02→2025-06 | +0.4% (n 33, t 2.37, win 67%) | +13.9% (n 33, t 1.67, win 55%) | +5.1% (n 33, t 0.83, win 52%) | +2.3% (n 8, t 0.69, win 75%) |
| orig | 2025-07→2026-10 | -0.0% (n 30, t -0.06, win 47%) | -6.5% (n 30, t -1.05, win 43%) | -12.3% (n 30, t -2.48, win 33%) | -3.3% (n 8, t -1.68, win 50%) |
| orig | 2× half-spread | | +1.1% (n 63, t 0.21, win 48%) | -9.3% (n 63, t -2.45, win 25%) | -3.5% (n 16, t -1.78, win 19%) |

## S1

| universe | period | STOCK | CALL (weekly) | SPREAD (weekly) | LONG (45–90 d, Δ0.75) |
|---|---|---|---|---|---|
| orig | all | +2.6% (n 237, t 3.97, win 60%) | — | — | -1.3% (n 92, t -0.16, win 42%) |
| orig | 2024-02→2025-06 | +3.0% (n 114, t 3.92, win 67%) | — | — | +0.8% (n 37, t 0.08, win 49%) |
| orig | 2025-07→2026-10 | +2.2% (n 123, t 2.14, win 54%) | — | — | -2.7% (n 55, t -0.24, win 38%) |
| orig | 2× half-spread | | — | — | -6.6% (n 92, t -0.89, win 39%) |
| new | all | +3.4% (n 387, t 5.01, win 58%) | — | — | +0.3% (n 79, t 0.03, win 39%) |
| new | 2024-02→2025-06 | +3.8% (n 200, t 5.41, win 65%) | — | — | +0.4% (n 34, t 0.03, win 38%) |
| new | 2025-07→2026-10 | +3.0% (n 187, t 2.50, win 51%) | — | — | +0.2% (n 45, t 0.01, win 40%) |
| new | 2× half-spread | | — | — | -5.6% (n 79, t -0.57, win 34%) |

## S3

| universe | period | STOCK | CALL (weekly) | SPREAD (weekly) | LONG (45–90 d, Δ0.75) |
|---|---|---|---|---|---|
| orig | all | +0.8% (n 22, t 0.68, win 45%) | — | — | +4.6% (n 10, t 0.13, win 30%) |
| orig | 2024-02→2025-06 | +0.7% (n 10, t 0.38, win 50%) | — | — | -31.1% (n 5, t -3.37, win 20%) |
| orig | 2025-07→2026-10 | +0.9% (n 12, t 0.55, win 42%) | — | — | +40.3% (n 5, t 0.59, win 40%) |
| orig | 2× half-spread | | — | — | -1.0% (n 10, t -0.03, win 20%) |
| new | all | +0.4% (n 34, t 0.30, win 44%) | — | — | -3.8% (n 6, t -0.12, win 33%) |
| new | 2024-02→2025-06 | +2.8% (n 16, t 1.54, win 56%) | — | — | +45.8% (n 3, t 1.00, win 67%) |
| new | 2025-07→2026-10 | -1.8% (n 18, t -1.05, win 33%) | — | — | -53.5% (n 3, t -4.38, win 0%) |
| new | 2× half-spread | | — | — | -9.4% (n 6, t -0.33, win 33%) |

## Pre-registered acceptance check

| signal | instrument | orig > 0 | new > 0 | pooled t > 1 | both halves > 0 | 2× spreads > 0 | **verdict** |
|---|---|---|---|---|---|---|---|
| SQZ | CALL | ✅ | ✅ | ✅ | ✅ | ✅ | **Paper candidate** |
| SQZ | SPREAD | ❌ | ❌ | ❌ | ❌ | ❌ | **reject** |
| SQZ | LONG | ✅ | ❌ | ❌ | ❌ | ❌ | **reject** |
| TDL | CALL | ❌ | ❌ | ❌ | ❌ | ❌ | **reject** |
| TDL | SPREAD | ❌ | ❌ | ❌ | ❌ | ❌ | **reject** |
| TDL | LONG | ❌ | ❌ | ❌ | ❌ | ❌ | **reject** |
| FOMC | CALL | ✅ | n/a | ❌ | ❌ | ✅ | **reject** |
| FOMC | SPREAD | ❌ | n/a | ❌ | ❌ | ❌ | **reject** |
| FOMC | LONG | ❌ | n/a | ❌ | ❌ | ❌ | **reject** |
| S1 | CALL | ❌ | ❌ | ❌ | ❌ | ❌ | **reject** |
| S1 | SPREAD | ❌ | ❌ | ❌ | ❌ | ❌ | **reject** |
| S1 | LONG | ❌ | ✅ | ❌ | ❌ | ❌ | **reject** |
| S3 | CALL | ❌ | ❌ | ❌ | ❌ | ❌ | **reject** |
| S3 | SPREAD | ❌ | ❌ | ❌ | ❌ | ❌ | **reject** |
| S3 | LONG | ✅ | ❌ | ❌ | ❌ | ❌ | **reject** |