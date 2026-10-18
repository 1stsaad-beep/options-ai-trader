# Round 4b — development on real option prices

Fill: 5-min option-bar VWAP ± half-spread (ETF 1.5%, stock 3%) + $0.65/contract/side.

## Dev 2024-02 → 2025-06 (all variants)

| strategy | variant | n | REAL exp | @VWAP | win | t | model exp |
|---|---|---|---|---|---|---|---|
| A Trend-dip @15:50 | {'delta': 0.7, 'min_days': 2, 'target_atr': 0.75, 'stop_atr': 1.0} | 155 | -13.0% | -8.0% | 0.41 | -2.33 | -2.4% |
| A Trend-dip @15:50 | {'delta': 0.7, 'min_days': 2, 'target_atr': None, 'stop_atr': None} | 132 | -14.4% | -9.5% | 0.42 | -2.31 | -1.3% |
| A Trend-dip @15:50 | {'delta': 0.7, 'min_days': 5, 'target_atr': 0.75, 'stop_atr': 1.0} | 125 | -13.6% | -8.7% | 0.46 | -2.68 | -12.2% |
| A Trend-dip @15:50 | {'delta': 0.7, 'min_days': 5, 'target_atr': None, 'stop_atr': None} | 98 | -14.6% | -9.8% | 0.48 | -2.36 | -10.0% |
| A Trend-dip @15:50 | {'delta': 0.85, 'min_days': 2, 'target_atr': 0.75, 'stop_atr': 1.0} | 123 | -12.1% | -7.2% | 0.43 | -2.30 | -7.8% |
| A Trend-dip @15:50 | {'delta': 0.85, 'min_days': 2, 'target_atr': None, 'stop_atr': None} | 103 | -12.7% | -7.7% | 0.42 | -1.93 | -2.8% |
| A Trend-dip @15:50 | {'delta': 0.85, 'min_days': 5, 'target_atr': 0.75, 'stop_atr': 1.0} | 79 | -13.4% | -8.6% | 0.46 | -2.47 | -12.4% |
| A Trend-dip @15:50 | {'delta': 0.85, 'min_days': 5, 'target_atr': None, 'stop_atr': None} | 66 | -16.9% | -12.2% | 0.45 | -2.28 | -12.5% |
| B Wave-2/B exhaustion @15:50 | {'delta': 0.5, 'min_days': 2} | 15 | -1.9% | +3.5% | 0.47 | -0.09 | -11.0% |
| B Wave-2/B exhaustion @15:50 | {'delta': 0.5, 'min_days': 5} | 15 | -9.3% | -4.3% | 0.47 | -0.56 | -22.5% |
| B Wave-2/B exhaustion @15:50 | {'delta': 0.7, 'min_days': 2} | 14 | -11.3% | -6.1% | 0.50 | -0.67 | -17.1% |
| B Wave-2/B exhaustion @15:50 | {'delta': 0.7, 'min_days': 5} | 14 | -14.6% | -9.6% | 0.50 | -1.03 | -23.2% |
| B Wave-2/B exhaustion @15:50 | {'delta': 0.85, 'min_days': 2} | 10 | -9.7% | -4.5% | 0.50 | -0.54 | -9.9% |
| B Wave-2/B exhaustion @15:50 | {'delta': 0.85, 'min_days': 5} | 10 | -10.1% | -4.9% | 0.50 | -0.66 | -15.0% |
| C ORB-5 in play | {'delta': 0.7} | 231 | -10.9% | -5.8% | 0.18 | -3.10 | -2.0% |
| D Noise-area momentum | {'delta': 0.7} | 403 | -0.2% | +2.9% | 0.30 | -0.04 | +18.6% |
| C ORB-5 in play | {'delta': 0.85} | 194 | -6.3% | -1.1% | 0.18 | -1.70 | -0.5% |
| D Noise-area momentum | {'delta': 0.85} | 401 | -1.6% | +1.4% | 0.32 | -0.68 | +3.1% |
| Pre-FOMC (ETFs) | {'delta': 0.5, 'exit_at': '12:00'} | 33 | +13.9% | +17.3% | 0.55 | 1.67 | +17.9% |
| Pre-FOMC (ETFs) | {'delta': 0.5, 'exit_at': '13:55'} | 33 | +1.3% | +4.4% | 0.39 | 0.11 | +23.7% |
| Pre-FOMC (ETFs) | {'delta': 0.7, 'exit_at': '12:00'} | 28 | +9.6% | +13.0% | 0.54 | 1.34 | +10.9% |
| Pre-FOMC (ETFs) | {'delta': 0.7, 'exit_at': '13:55'} | 32 | +2.6% | +5.8% | 0.41 | 0.28 | +13.8% |

## Test 2025-07 → 2026-10 (best dev variant per strategy, n ≥ 20, frozen)

| strategy | chosen | dev n | dev REAL exp | test n | **test REAL exp** | test @VWAP | test win | test t | test model exp |
|---|---|---|---|---|---|---|---|---|---|
| A Trend-dip @15:50 | {'delta': 0.85, 'min_days': 2, 'target_atr': 0.75, 'stop_atr': 1.0} | 123 | -12.1% | 132 | **-9.8%** | -5.0% | 0.41 | -2.23 | -7.9% |
| C ORB-5 in play | {'delta': 0.85} | 194 | -6.3% | 162 | **-6.2%** | -0.6% | 0.27 | -1.83 | +1.8% |
| D Noise-area momentum | {'delta': 0.7} | 403 | -0.2% | 380 | **-4.1%** | -1.2% | 0.29 | -1.15 | +1.5% |
| Pre-FOMC (ETFs) | {'delta': 0.5, 'exit_at': '12:00'} | 33 | +13.9% | 30 | **-5.9%** | -3.0% | 0.43 | -0.97 | -14.7% |