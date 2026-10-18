# Round 4 — weekly options simulation

Contracts expire ≤ 7 calendar days after entry (first Friday ≥ entry + min_days). Spreads: ETF 3%, stocks 6% of mid.
Conditional exits are decided at a close and filled at the next open. Budget 2% of NAV per trade, max 5 open.

## Discovery 1999–2012: grid (delta × exit × expiry) → chosen rule

| setup | chosen: delta / (target ATR, stop ATR, max days) / min days | n | win | avg win | avg loss | exp/trade | PF | t(week) |
|---|---|---|---|---|---|---|---|---|
| ETF dip | 0.7 / (0.5, 1.0, 2) / 2 | 357 | 0.48 | +60.4% | -45.8% | +5.6% | 1.19 | 3.46 |
| ETF bear-rally puts | 0.5 / (0.5, 1.0, 2) / 2 | 207 | 0.45 | +74.9% | -48.0% | +7.8% | 1.24 | 1.69 |
| Pre-FOMC | 0.5 / (None, None, None) / 2 | 320 | 0.56 | +94.6% | -55.5% | +28.0% | 2.17 | 3.32 |
| Turn of month | 0.7 / (None, None, None) / 2 | 283 | 0.48 | +52.7% | -50.9% | -0.7% | 0.94 | -0.24 |
| Turn of month (stocks) | 0.5 / (None, None, None) / 2 | 538 | 0.36 | +107.7% | -64.4% | -1.7% | 0.92 | -0.32 |
| Pre-holiday | 0.7 / (None, None, None) / 2 | 278 | 0.42 | +42.5% | -48.2% | -10.0% | 0.61 | -1.84 |
| Event gap drift | 0.7 / (None, None, None) / 5 | 74 | 0.42 | +88.5% | -62.3% | +0.9% | 1.00 | -0.49 |
| Wave 2->3 daily | 0.5 / (0.5, 1.0, 2) / 2 | 613 | 0.40 | +79.5% | -56.1% | -1.2% | 0.94 | -0.97 |
| Wave B->C daily | 0.5 / (0.75, 1.0, 3) / 2 | 102 | 0.44 | +116.6% | -55.4% | +20.5% | 1.66 | 1.90 |
| VIX spike reversal | 0.7 / (1.0, 1.0, 4) / 5 | 88 | 0.50 | +37.1% | -40.7% | -1.8% | 0.89 | -0.41 |
| 20-day breakout | 0.7 / (None, None, None) / 5 | 633 | 0.41 | +84.5% | -63.0% | -1.9% | 0.89 | -0.48 |
| Wave-2/B exhaustion (new) | 0.5 / (0.5, 1.0, 2) / 2 | 106 | 0.48 | +69.7% | -57.2% | +3.9% | 1.13 | 1.04 |
| Control: trend + RSI2 (no wave) | 0.5 / (0.5, 1.0, 2) / 2 | 2311 | 0.44 | +86.3% | -55.6% | +6.7% | 1.12 | 5.33 |

## Validation 2013 – 2026-04-15 (rules frozen above, run once)

| setup | n | win | avg win | avg loss | exp/trade | PF | t(week) | 2× spreads exp | CAGR* | maxDD* | median hours held |
|---|---|---|---|---|---|---|---|---|---|---|---|
| ETF dip | 417 | 0.50 | +48.2% | -42.2% | +2.9% | 1.11 | 1.91 | -0.7% | +1.4% | -25.1% | 30 |
| ETF bear-rally puts | 125 | 0.37 | +92.5% | -49.4% | +2.8% | 1.06 | 0.99 | -0.7% | +0.3% | -20.3% | 30 |
| Pre-FOMC | 315 | 0.47 | +89.9% | -56.7% | +11.7% | 1.31 | 1.36 | +7.1% | +4.5% | -30.3% | 30 |
| Turn of month | 369 | 0.44 | +53.3% | -53.7% | -6.8% | 0.72 | -1.30 | -10.1% | -3.9% | -47.9% | 126 |
| Turn of month (stocks) | 668 | 0.35 | +119.6% | -64.8% | -1.0% | 0.92 | -0.17 | -6.6% | -2.7% | -70.0% | 126 |
| Pre-holiday | 326 | 0.39 | +44.8% | -51.7% | -14.4% | 0.60 | -2.68 | -17.2% | -6.0% | -62.2% | 102 |
| Event gap drift | 81 | 0.42 | +87.8% | -57.8% | +3.3% | 1.06 | 0.76 | -1.9% | +0.2% | -16.2% | 222 |
| Wave 2->3 daily | 696 | 0.41 | +80.2% | -55.2% | -0.3% | 0.98 | -1.00 | -5.5% | -1.0% | -56.0% | 30 |
| Wave B->C daily | 171 | 0.43 | +114.1% | -69.7% | +9.8% | 1.21 | 1.01 | +3.4% | +2.2% | -23.6% | 54 |
| VIX spike reversal | 202 | 0.50 | +43.3% | -40.3% | +1.1% | 1.04 | 0.43 | -2.0% | +0.2% | -19.0% | 72 |
| 20-day breakout | 906 | 0.44 | +87.5% | -64.1% | +3.3% | 1.08 | -0.59 | -0.2% | +2.9% | -50.5% | 198 |
| Wave-2/B exhaustion (new) | 125 | 0.47 | +101.3% | -55.9% | +18.3% | 1.60 | 1.99 | +11.6% | +3.2% | -9.9% | 30 |
| Control: trend + RSI2 (no wave) | 2457 | 0.45 | +96.0% | -56.3% | +11.5% | 1.29 | 5.31 | +5.1% | +42.5% | -46.7% | 30 |

*Each setup alone, 2% of NAV premium per trade.