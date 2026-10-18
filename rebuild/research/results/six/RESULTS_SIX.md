# Published vs. new strategies — real data

Daily: 15 symbols. A = 2013–2019, B = 2020–2026. Returns are per trade on option premium (modelled).

## 1. Daily, fixed pre-declared rules

| strategy | trades | win | avg win | avg loss | exp/trade | PF | t | A / B exp | 2× spreads | fwd10 ATR A / B | maxDD* |
|---|---|---|---|---|---|---|---|---|---|---|---|
| P1 TSMOM monthly | 595 | +0.47 | +83.0% | -52.9% | +10.6% | +1.38 | +2.97 | +7.4% / +13.8% | +6.6% | +0.19 / +0.41 | -38.1% |
| P2 Connors RSI2 | 1284 | +0.55 | +25.7% | -32.6% | -0.8% | +0.95 | -0.68 | -2.5% / +3.1% | -4.8% | +0.40 / +0.19 | -71.7% |
| P3 52-week high | 435 | +0.41 | +77.4% | -44.8% | +5.2% | +1.20 | +1.40 | +1.6% / +9.8% | +2.2% | +0.09 / +0.55 | -47.0% |
| P4 Turtle 20/10 | 801 | +0.29 | +100.0% | -41.9% | -0.8% | +0.97 | -0.25 | -4.4% / +4.7% | -4.2% | +0.03 / +0.16 | -82.4% |
| N1 Trend-dip (RSI2+IBS+VIX) | 362 | +0.61 | +20.4% | -33.3% | -0.6% | +0.95 | -0.33 | -2.0% / +2.1% | -4.4% | +0.80 / +0.27 | -31.7% |
| N2 52w-high squeeze | 277 | +0.35 | +64.4% | -38.0% | -1.8% | +0.93 | -0.50 | -5.8% / +7.6% | -4.5% | +0.32 / +0.46 | -53.9% |
| N3 Turtle-55 quality | 372 | +0.44 | +73.3% | -47.5% | +6.1% | +1.23 | +1.35 | +0.4% / +14.0% | +2.7% | +0.23 / +0.52 | -45.3% |
| N4 Turn-of-month trend | 696 | +0.43 | +57.3% | -42.6% | +0.4% | +1.01 | +0.14 | -2.2% / +3.4% | -4.1% | +0.33 / +0.49 | -64.6% |

*maxDD = sequential curve, 4% of equity in premium per trade. fwd10 = underlying move 10 days after entry (ATR).

## 2. Contract selection on A only, tested on B

| strategy | chosen (delta, DTE, premium stop) | B trades | B win | B avg win | B avg loss | B exp/trade | B PF | B t | B CAGR | B maxDD | positive years (A+B) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| P1 TSMOM monthly | 0.75, 35, None | 338 | +0.52 | +72.6% | -59.6% | +8.9% | +1.31 | +1.98 | +6.7% | -25.5% | 10/14 |
| P2 Connors RSI2 | 0.6, 35, None | 802 | +0.59 | +26.6% | -29.5% | +3.8% | +1.32 | +2.87 | +5.8% | -10.3% | 8/14 |
| P3 52-week high | 0.75, 35, None | 165 | +0.44 | +90.3% | -50.9% | +10.7% | +1.38 | +1.59 | +4.4% | -12.1% | 9/14 |
| P4 Turtle 20/10 | 0.6, 35, None | 536 | +0.31 | +133.0% | -52.9% | +4.0% | +1.11 | +0.76 | +4.0% | -35.1% | 5/14 |
| N1 Trend-dip (RSI2+IBS+VIX) | 0.6, 35, None | 237 | +0.62 | +30.3% | -31.6% | +6.5% | +1.54 | +2.63 | +3.2% | -6.6% | 8/14 |
| N2 52w-high squeeze | 0.6, 60, None | 105 | +0.39 | +74.1% | -34.6% | +7.9% | +1.37 | +1.20 | +1.7% | -6.4% | 7/14 |
| N3 Turtle-55 quality | 0.75, 60, None | 140 | +0.49 | +73.4% | -39.9% | +15.9% | +1.79 | +2.40 | +5.6% | -8.0% | 7/14 |
| N4 Turn-of-month trend | 0.6, 35, 0.5 | 321 | +0.45 | +53.9% | -40.8% | +2.3% | +1.10 | +0.66 | +1.7% | -28.9% | 6/14 |

## 3. 5-minute (2026-07-24 → 2026-10-16, 15 symbols)

| strategy | trades | win | avg win | avg loss | exp/trade | PF | t | first / second half |
|---|---|---|---|---|---|---|---|---|
| P5 ORB (published) | 222 | +0.23 | +127.8% | -31.6% | +4.3% | +1.18 | +0.71 | +3.3% / +5.1% |
| N5 ORB in-play + VWAP exit | 51 | +0.27 | +143.6% | -23.3% | +22.5% | +2.33 | +1.41 | +3.5% / +32.9% |