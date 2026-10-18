# Round 5 — options test

## A. Calibrated model (IV proxy × real-calibrated term multiplier), weekly options

| strategy | period | chosen delta / min days / (target, stop, max bars) | n | win | exp/trade | PF | t(week) |
|---|---|---|---|---|---|---|---|
| MTF-RSI Calls (15m re-entry, RSI14 25) | DISC | (0.5, 2, (0.75, 1.0, 52)) | 185 | 0.64 | +20.4% | 2.01 | 2.40 |
| MTF-RSI Calls (15m re-entry, RSI14 25) | VALID | (0.5, 2, (0.75, 1.0, 52)) | 201 | 0.55 | +14.8% | 1.70 | 2.87 |
| MTF-RSI Calls (15m re-entry, RSI14 25) | HOLD | (0.5, 2, (0.75, 1.0, 52)) | 14 | 0.64 | +42.3% | 3.85 | 3.61 |
| MTF Elliott Calls (developed) | DISC | (0.7, 2, (1.0, 1.0, 104)) | 1014 | 0.48 | -3.0% | 0.87 | -3.14 |
| MTF Elliott Calls (developed) | VALID | (0.7, 2, (1.0, 1.0, 104)) | 880 | 0.44 | -6.2% | 0.77 | -3.27 |
| MTF Elliott Calls (developed) | HOLD | (0.7, 2, (1.0, 1.0, 104)) | 98 | 0.41 | -6.1% | 0.83 | -0.26 |

## B. Real option prices (2024-02 → 2026-10), same trades

- **MTF-RSI Calls (15m re-entry, RSI14 25) — dev:** n 54, REAL exp +8.6%, @VWAP +14.8%, win 0.50, median IV/RV20 1.33, median break-even 0.23 ATR/day, model +18.8%
- **MTF-RSI Calls (15m re-entry, RSI14 25) — test:** n 46, REAL exp +18.0%, @VWAP +24.9%, win 0.70, median IV/RV20 1.37, median break-even 0.21 ATR/day, model +28.7%
- **MTF Elliott Calls (developed) — dev:** n 247, REAL exp -4.6%, @VWAP +0.6%, win 0.44, median IV/RV20 1.13, median break-even 0.16 ATR/day, model -6.3%
- **MTF Elliott Calls (developed) — test:** n 199, REAL exp -7.8%, @VWAP -2.6%, win 0.39, median IV/RV20 1.22, median break-even 0.17 ATR/day, model -7.1%

## C. Volatility filter — thresholds chosen on dev, applied once to test

| strategy | filter | threshold (from dev) | dev kept n / REAL exp | test kept n / REAL exp | test unfiltered |
|---|---|---|---|---|---|
| MTF-RSI Calls (15m re-entry, RSI14 25) | iv_rv ≤ th | 1.3 | 24 / +12.4% | 21 / **+23.1%** | +18.0% |
| MTF-RSI Calls (15m re-entry, RSI14 25) | iv_yz ≤ th | 1.5 | 33 / +10.7% | 32 / **+34.9%** | +18.0% |
| MTF-RSI Calls (15m re-entry, RSI14 25) | be_atr ≤ th | 0.5 | 54 / +8.6% | 46 / **+18.0%** | +18.0% |
| MTF Elliott Calls (developed) | iv_rv ≤ th | 1.1 | 111 / -1.7% | 73 / **+6.0%** | -7.8% |
| MTF Elliott Calls (developed) | iv_yz ≤ th | 1.2 | 159 / -2.5% | 108 / **-2.7%** | -7.8% |
| MTF Elliott Calls (developed) | be_atr ≤ th | 0.2 | 191 / -3.2% | 140 / **-10.0%** | -7.8% |