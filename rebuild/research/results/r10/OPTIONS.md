# Big-move combination as a trade (backtested)

Rule: BB-width percentile > 80 % AND 20-day return < −10 % AND SPY 5-day return < −3 % → buy at 15:50, exit 15:50 two sessions later.

- **orig: stock only, all 5-minute history** — 421 trades, mean +0.75 %, median +1.05 %, win 59 %, t 2.68
- **new: stock only, all 5-minute history** — 165 trades, mean +2.46 %, median +1.87 %, win 71 %, t 5.98

| universe | period | STOCK | CALL (weekly) | SPREAD (weekly) | LONG (45–90 d, Δ0.75) |
|---|---|---|---|---|---|
| orig | 2024-02→2026-10 | +2.4% (n 73, t 3.30, win 66%) | +19.5% (n 64, t 1.71, win 48%) | +5.7% (n 63, t 0.70, win 52%) | +4.6% (n 4, t 1.47, win 75%) |
| orig | 2024-02→2025-06 | +2.4% (n 71, t 3.22, win 66%) | +20.8% (n 63, t 1.81, win 49%) | +6.6% (n 62, t 0.82, win 53%) | +4.6% (n 4, t 1.47, win 75%) |
| orig | 2025-07→2026-10 | — | — | — | — |
| orig | 2× half-spread | | +13.0% (n 64, t 1.21, win 48%) | -7.3% (n 63, t -1.01, win 44%) | -1.5% (n 4, t -0.50, win 25%) |
| orig | entries by month | 2024-08: 11, 2025-02: 3, 2025-03: 28, 2025-04: 29, 2025-11: 1, 2026-03: 1 | | | |
| new | 2024-02→2026-10 | +2.6% (n 155, t 6.06, win 73%) | +18.6% (n 106, t 1.83, win 45%) | +4.3% (n 81, t 0.62, win 46%) | -5.7% (n 11, t -0.63, win 27%) |
| new | 2024-02→2025-06 | +2.7% (n 149, t 6.24, win 74%) | +16.3% (n 100, t 1.87, win 46%) | +3.3% (n 78, t 0.50, win 46%) | -3.1% (n 10, t -0.32, win 30%) |
| new | 2025-07→2026-10 | -0.3% (n 6, t -0.11, win 33%) | +57.2% (n 6, t 0.50, win 33%) | +31.8% (n 3, t 0.33, win 33%) | — |
| new | 2× half-spread | | +11.7% (n 106, t 1.22, win 39%) | -9.5% (n 81, t -1.57, win 37%) | -11.2% (n 11, t -1.31, win 27%) |
| new | entries by month | 2024-04: 3, 2024-08: 22, 2025-02: 1, 2025-03: 37, 2025-04: 86, 2025-11: 4, 2026-03: 2 | | | |