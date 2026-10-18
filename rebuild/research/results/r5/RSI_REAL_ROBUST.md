# MTF-RSI Calls — real option prices, neighbours and robustness (2024-02 → 2026-10)

## Neighbouring parameters (same contract/exit rule)

| variant | n | REAL exp | @VWAP | win | t |
|---|---|---|---|---|---|
| RSI14 25 reentry 15m | 100 | +12.9% | +19.4% | 0.59 | 1.87 |
| RSI14 30 reentry 15m | 254 | -1.1% | +4.6% | 0.49 | -0.24 |
| RSI14 20 reentry 15m | 17 | +7.3% | +13.4% | 0.59 | 0.42 |
| RSI9 25 reentry 15m | 271 | -7.1% | -2.0% | 0.44 | -1.72 |
| RSI14 25 fail 15m | 99 | +16.5% | +23.1% | 0.59 | 2.42 |
| RSI14 30 div 15m | 115 | +3.5% | +9.4% | 0.49 | 0.52 |
| RSI9 30 reentry 15m | 568 | -6.8% | -1.5% | 0.41 | -2.33 |
| RSI14 30 reentry 5m | 361 | +1.7% | +7.5% | 0.48 | 0.45 |

## Contract / exit neighbours (signal RSI14 25 re-entry, 15m)

| delta / min days / (target, stop, bars) | n | REAL exp | @VWAP | win | t |
|---|---|---|---|---|---|
| (0.5, 5, (0.75, 1.0, 52)) | 95 | +6.7% | +12.9% | 0.59 | 1.26 |
| (0.7, 2, (0.75, 1.0, 52)) | 72 | +5.1% | +11.2% | 0.57 | 0.81 |
| (0.5, 2, (0.5, 1.0, 26)) | 103 | -3.5% | +2.0% | 0.50 | -0.74 |
| (0.5, 2, (1.0, 1.0, 104)) | 99 | +10.2% | +16.5% | 0.53 | 1.28 |

## Robustness of the base variant

| cut | n | REAL exp | @VWAP | win | t |
|---|---|---|---|---|---|
| all | 100 | +12.9% | +19.4% | 0.59 | 1.87 |
| double half-spread (3% ETF / 6% stock) | 100 | +6.8% | | | |
| without the 5 best trades | 95 | +5.2% | +11.2% | 0.57 | 0.83 |
| ETFs only | 16 | +0.5% | +3.5% | 0.62 | 0.04 |
| stocks only | 84 | +15.3% | +22.4% | 0.58 | 1.94 |
| without NVDA/TSLA/AMD/META | 70 | +13.5% | +19.8% | 0.63 | 1.64 |
| year 2024 | 28 | +16.6% | +23.1% | 0.57 | 1.27 |
| year 2025 | 42 | +2.4% | +8.3% | 0.52 | 0.22 |
| year 2026 | 30 | +24.2% | +31.5% | 0.70 | 2.01 |

Trades per symbol: AAPL 11, TSLA 10, UNH 9, AMD 9, QQQ 8, NVDA 7, GOOGL 7, AMZN 6, MSFT 6, COST 5, JPM 5, XOM 5, META 4, SPY 4, IWM 4