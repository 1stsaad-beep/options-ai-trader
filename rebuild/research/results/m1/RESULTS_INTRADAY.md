# Intraday / hourly strategy study (real Yahoo data)

Fixed parameters (no fitting). A = first half of the dataset, B = second half. Option P&L is modelled (Black–Scholes, IV from realised vol, spreads, $0.65/contract/side).

## m1: 15 symbols, 2026-09-21 → 2026-10-16 (split 2026-10-04)

| strategy | signals | fwd (ATR) A / B | hit A / B | trades | win | avg win | avg loss | exp/trade | PF | t | exp A / B | maxDD* |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| WD div=none | 3242 | -0.08 / +0.05 | +0.31 / +0.33 | 1152 | +0.38 | +0.131 | -0.154 | -0.046 | +0.51 | -9.07 | -0.050 / -0.044 | -0.884 |
| WD div=rsi | 902 | -0.15 / -0.15 | +0.32 / +0.29 | 517 | +0.36 | +0.158 | -0.179 | -0.058 | +0.49 | -6.52 | -0.047 / -0.063 | -0.732 |
| WD div=macd | 1213 | -0.17 / +0.01 | +0.29 / +0.31 | 656 | +0.38 | +0.155 | -0.172 | -0.048 | +0.55 | -6.22 | -0.048 / -0.049 | -0.753 |
| WD div=either | 1448 | -0.12 / -0.01 | +0.31 / +0.31 | 731 | +0.38 | +0.151 | -0.172 | -0.050 | +0.53 | -6.81 | -0.046 / -0.052 | -0.799 |
| WD div=both | 663 | -0.26 / -0.15 | +0.30 / +0.28 | 413 | +0.37 | +0.162 | -0.178 | -0.051 | +0.54 | -5.11 | -0.039 / -0.057 | -0.610 |
| WD W2->3 only (either) | 1255 | -0.07 / +0.03 | +0.30 / +0.31 | 665 | +0.37 | +0.161 | -0.176 | -0.049 | +0.55 | -6.19 | -0.044 / -0.052 | -0.773 |
| WD B->C only (either) | 194 | -0.45 / -0.34 | +0.35 / +0.37 | 118 | +0.43 | +0.109 | -0.178 | -0.054 | +0.47 | -3.40 | -0.083 / -0.042 | -0.250 |
| VWAP pullback | 311 | -0.43 / -0.07 | +0.31 / +0.30 | 208 | +0.30 | +0.135 | -0.146 | -0.062 | +0.40 | -6.13 | -0.084 / -0.050 | -0.408 |

fwd = directional move 10 bars after entry (ATR units); hit = +2 ATR before -1 ATR within 30 bars; maxDD* = sequential curve with 4% of equity in premium per trade.
