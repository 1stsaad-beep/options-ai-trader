# Intraday / hourly strategy study (real Yahoo data)

Fixed parameters (no fitting). A = first half of the dataset, B = second half. Option P&L is modelled (Black–Scholes, IV from realised vol, spreads, $0.65/contract/side).

## h1: 15 symbols, 2023-11-17 → 2026-10-16 (split 2025-05-02)

| strategy | signals | fwd (ATR) A / B | hit A / B | trades | win | avg win | avg loss | exp/trade | PF | t | exp A / B | maxDD* |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| WD div=none | 2016 | +0.02 / -0.11 | +0.32 / +0.32 | 1028 | +0.42 | +0.307 | -0.304 | -0.045 | +0.74 | -3.83 | -0.034 / -0.077 | -0.903 |
| WD div=rsi | 629 | +0.01 / -0.07 | +0.31 / +0.30 | 541 | +0.42 | +0.315 | -0.306 | -0.045 | +0.74 | -2.77 | -0.024 / -0.071 | -0.713 |
| WD div=macd | 799 | -0.01 / -0.40 | +0.29 / +0.31 | 563 | +0.38 | +0.336 | -0.310 | -0.067 | +0.65 | -4.09 | -0.048 / -0.096 | -0.808 |
| WD div=either | 952 | -0.02 / -0.32 | +0.29 / +0.30 | 648 | +0.39 | +0.332 | -0.312 | -0.063 | +0.67 | -4.12 | -0.039 / -0.106 | -0.849 |
| WD div=both | 474 | +0.00 / -0.15 | +0.32 / +0.31 | 428 | +0.40 | +0.329 | -0.304 | -0.050 | +0.73 | -2.67 | -0.038 / -0.062 | -0.631 |
| WD W2->3 only (either) | 822 | +0.01 / -0.36 | +0.30 / +0.31 | 585 | +0.39 | +0.331 | -0.315 | -0.064 | +0.67 | -3.98 | -0.038 / -0.106 | -0.836 |
| WD B->C only (either) | 138 | -0.04 / +0.18 | +0.29 / +0.29 | 135 | +0.42 | +0.245 | -0.289 | -0.063 | +0.62 | -2.24 | -0.061 / -0.066 | -0.325 |
| RCB | 715 | +0.25 / +0.04 | +0.37 / +0.34 | 513 | +0.36 | +0.338 | -0.247 | -0.038 | +0.76 | -2.58 | -0.021 / -0.055 | -0.604 |
| TPB | 1073 | +0.23 / +0.02 | +0.34 / +0.39 | 715 | +0.42 | +0.393 | -0.299 | -0.012 | +0.93 | -0.66 | +0.029 / -0.051 | -0.686 |

fwd = directional move 10 bars after entry (ATR units); hit = +2 ATR before -1 ATR within 14 bars; maxDD* = sequential curve with 4% of equity in premium per trade.
