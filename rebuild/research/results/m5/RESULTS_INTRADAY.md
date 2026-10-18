# Intraday / hourly strategy study (real Yahoo data)

Fixed parameters (no fitting). A = first half of the dataset, B = second half. Option P&L is modelled (Black–Scholes, IV from realised vol, spreads, $0.65/contract/side).

## m5: 15 symbols, 2026-07-24 → 2026-10-16 (split 2026-09-04)

| strategy | signals | fwd (ATR) A / B | hit A / B | trades | win | avg win | avg loss | exp/trade | PF | t | exp A / B | maxDD* |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| WD div=none | 1928 | -0.05 / +0.17 | +0.23 / +0.24 | 943 | +0.36 | +0.206 | -0.191 | -0.046 | +0.62 | -5.85 | -0.060 / -0.034 | -0.855 |
| WD div=rsi | 635 | +0.11 / +0.24 | +0.23 / +0.25 | 444 | +0.42 | +0.171 | -0.180 | -0.032 | +0.69 | -3.13 | -0.038 / -0.027 | -0.474 |
| WD div=macd | 809 | -0.15 / +0.10 | +0.22 / +0.19 | 554 | +0.39 | +0.168 | -0.187 | -0.050 | +0.56 | -5.44 | -0.049 / -0.051 | -0.694 |
| WD div=either | 976 | -0.01 / +0.09 | +0.23 / +0.22 | 621 | +0.40 | +0.167 | -0.186 | -0.046 | +0.59 | -5.32 | -0.050 / -0.043 | -0.702 |
| WD div=both | 468 | -0.08 / +0.31 | +0.22 / +0.22 | 354 | +0.41 | +0.173 | -0.181 | -0.036 | +0.66 | -3.06 | -0.040 / -0.033 | -0.446 |
| WD W2->3 only (either) | 756 | -0.02 / +0.15 | +0.22 / +0.22 | 512 | +0.41 | +0.167 | -0.191 | -0.044 | +0.61 | -4.48 | -0.045 / -0.043 | -0.614 |
| WD B->C only (either) | 221 | +0.04 / -0.11 | +0.26 / +0.21 | 168 | +0.38 | +0.143 | -0.179 | -0.059 | +0.48 | -4.00 | -0.062 / -0.056 | -0.340 |
| ORB 5m | 311 | +0.00 / +0.09 | +0.27 / +0.32 | 222 | +0.36 | +0.452 | -0.275 | -0.013 | +0.93 | -0.46 | +0.001 / -0.025 | -0.245 |
| VWAP pullback | 619 | -0.06 / +0.01 | +0.13 / +0.22 | 436 | +0.35 | +0.171 | -0.176 | -0.055 | +0.52 | -5.90 | -0.076 / -0.037 | -0.645 |

fwd = directional move 10 bars after entry (ATR units); hit = +2 ATR before -1 ATR within 12 bars; maxDD* = sequential curve with 4% of equity in premium per trade.
