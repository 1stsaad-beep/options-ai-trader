# Round 4 — time-to-target study (discovery 1999–2012, daily bars)

Entry = next open. Units = daily ATR(14) at the signal. Stop = −1 ATR (a bar touching both counts as stop first).
pX_dN = share of setups that touched +X ATR **before the stop** within N trading days (day 1 = entry day).

| setup | n | +0.5 d1 | +0.5 d2 | +0.75 d2 | +1 d1 | +1 d2 | +1 d3 | +1 d5 | +1.5 d5 | median days to +1 | stop ≤5d | MFE d1 | MFE d2 | close d1 | close d2 | close d5 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| ETF dip (calls) | 503 | 43% | 59% | 44% | 9% | 30% | 40% | 50% | 35% | 2.0 | 47% | 0.46 | 0.71 | -0.01 | 0.10 | 0.23 |
| ETF bear-rally (puts) | 306 | 37% | 61% | 42% | 6% | 25% | 38% | 49% | 30% | 3.0 | 35% | 0.40 | 0.64 | 0.06 | 0.18 | 0.22 |
| VIX spike reversal (calls) | 93 | 41% | 55% | 34% | 9% | 17% | 31% | 43% | 23% | 3.0 | 51% | 0.46 | 0.59 | -0.06 | -0.21 | 0.03 |
| Gap & go (both) | 516 | 37% | 52% | 36% | 10% | 24% | 34% | 46% | 29% | 2.0 | 44% | 0.36 | 0.57 | -0.00 | 0.03 | 0.05 |
| Turn of month (calls) | 1102 | 31% | 57% | 40% | 7% | 27% | 37% | 47% | 31% | 2.0 | 47% | 0.34 | 0.61 | -0.08 | 0.10 | 0.22 |
| 20-day breakout (calls) | 1385 | 38% | 52% | 37% | 11% | 24% | 33% | 43% | 28% | 2.0 | 49% | 0.37 | 0.57 | 0.04 | 0.03 | 0.15 |
| Pre-FOMC (calls, ETFs) | 323 | 36% | 66% | 51% | 6% | 33% | 45% | 53% | 35% | 2.0 | 39% | 0.38 | 0.79 | 0.03 | 0.26 | 0.28 |
| Event gap drift (both) | 84 | 43% | 54% | 45% | 20% | 26% | 30% | 48% | 23% | 2.0 | 39% | 0.41 | 0.72 | 0.19 | 0.14 | 0.20 |
| Pre-holiday (calls, ETFs) | 284 | 28% | 53% | 38% | 4% | 25% | 35% | 46% | 28% | 2.0 | 42% | 0.31 | 0.60 | 0.04 | 0.14 | 0.14 |
| Wave 2->3 daily (HTF) | 618 | 39% | 57% | 39% | 9% | 23% | 33% | 44% | 27% | 2.0 | 46% | 0.40 | 0.61 | 0.01 | -0.00 | -0.06 |
| Wave B->C daily (HTF) | 102 | 40% | 56% | 41% | 8% | 26% | 35% | 49% | 33% | 2.0 | 37% | 0.39 | 0.64 | 0.05 | 0.22 | 0.13 |
| BASELINE calls: any day above SMA200 | 22749 | 37% | 54% | 38% | 9% | 25% | 35% | 45% | 29% | 2.0 | 46% | 0.38 | 0.58 | 0.01 | 0.04 | 0.14 |
| BASELINE puts: any day below SMA200 | 10788 | 37% | 53% | 37% | 9% | 24% | 33% | 42% | 26% | 2.0 | 48% | 0.38 | 0.56 | -0.01 | -0.02 | -0.05 |

## Entry weekday (all setups pooled)

| weekday | n | +0.5 within 2d | +1 within 2d | mean close d2 (ATR) |
|---|---|---|---|---|
| Mon | 998 | 59% | 27% | +0.10 |
| Tue | 1049 | 56% | 27% | +0.04 |
| Wed | 1009 | 58% | 26% | +0.08 |
| Thu | 894 | 53% | 24% | +0.06 |
| Fri | 1366 | 54% | 25% | +0.09 |

## Hourly bars, discovery 2023-11-17 → 2025-04-30 (horizon in trading days, 7 bars/day)

| setup | n | +0.5 same day | +0.5 d2 | +1 same day | +1 d2 | stop ≤5d | close same day | close d2 |
|---|---|---|---|---|---|---|---|---|
| First-hour breakout (in play) | 232 | 25% | 52% | 4% | 26% | 55% | -0.01 | 0.03 |
| Wave 2->3 hourly (daily HTF) | 311 | 19% | 49% | 4% | 21% | 50% | -0.00 | -0.00 |
| Wave B->C hourly (daily HTF) | 95 | 21% | 46% | 4% | 20% | 47% | 0.04 | 0.05 |