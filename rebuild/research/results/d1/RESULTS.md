# Study results (real data)

Symbols: AAPL, AMD, AMZN, COST, GOOGL, IWM, JPM, META, MSFT, NVDA, QQQ, SPY, TSLA, UNH, XOM
Period: 2012-01-03 → 2026-10-16
In-sample < 2020 ≤ out-of-sample

## A. Signal quality on the underlying (entry next open, ATR units)

| engine | IS n | IS fwd10 | IS hit | OOS n | OOS fwd10 | OOS t | OOS hit |
|---|---|---|---|---|---|---|---|
| baseline_composite | 3807 | 0.058 | 0.28 | 3275 | 0.219 | 5.08 | 0.29 |
| raw_divergence | 6478 | 0.023 | 0.28 | 5160 | -0.046 | -1.37 | 0.29 |
| gated_divergence | 236 | 0.455 | 0.33 | 215 | 0.501 | 3.13 | 0.32 |
| raw_harmonic | 79 | 0.223 | 0.25 | 89 | 1.068 | 3.66 | 0.42 |
| gated_harmonic | 1 | -1.564 | 0.00 | 4 | 2.927 | 3.02 | 0.75 |
| raw_elliott | 8211 | 0.018 | 0.28 | 7953 | 0.131 | 4.84 | 0.28 |
| gated_elliott | 322 | 0.307 | 0.31 | 338 | 0.450 | 3.30 | 0.29 |
| raw_classical | 6500 | 0.020 | 0.27 | 5039 | 0.101 | 2.87 | 0.30 |
| gated_classical | 686 | 0.258 | 0.30 | 525 | 0.522 | 4.92 | 0.36 |
| raw_trend | 19161 | 0.196 | 0.28 | 15902 | 0.228 | 11.51 | 0.29 |
| gated_trend | 1514 | 0.197 | 0.30 | 1399 | 0.555 | 7.69 | 0.32 |
| raw_momentum | 12980 | -0.016 | 0.28 | 11285 | 0.072 | 3.08 | 0.29 |
| gated_momentum | 1302 | 0.195 | 0.29 | 1226 | 0.575 | 7.46 | 0.34 |
| gated_composite | 335 | 0.498 | 0.31 | 332 | 0.327 | 2.26 | 0.31 |
| rcb | 247 | 0.543 | 0.34 | 205 | 0.374 | 1.99 | 0.34 |
| tpb | 303 | 0.489 | 0.32 | 371 | 0.353 | 2.67 | 0.28 |
| rcb_calls | 243 | 0.543 | 0.34 | 171 | 0.446 | 2.10 | 0.34 |
| tpb_calls | 279 | 0.537 | 0.33 | 312 | 0.461 | 3.09 | 0.28 |
| rcb+tpb | 546 | 0.513 | 0.33 | 567 | 0.364 | 3.33 | 0.30 |

## B. Option backtest, default rules, full period

| engine | trades | win | avg win | avg loss | exp/trade | PF | CAGR | maxDD | Sharpe |
|---|---|---|---|---|---|---|---|---|---|
| baseline_composite | 696 | 0.29 | 0.518 | -0.495 | -0.200 | 0.46 | -0.302 | -0.995 | -2.44 |
| raw_divergence | 724 | 0.30 | 0.279 | -0.359 | -0.165 | 0.32 | -0.344 | -0.998 | -2.73 |
| gated_divergence | 300 | 0.43 | 0.563 | -0.445 | -0.012 | 0.86 | -0.024 | -0.460 | -0.16 |
| raw_harmonic | 71 | 0.39 | 0.246 | -0.276 | -0.070 | 0.54 | -0.014 | -0.209 | -0.45 |
| gated_harmonic | 5 | 0.60 | 0.621 | -0.273 | 0.263 | 3.45 | 0.003 | -0.022 | 0.23 |
| raw_elliott | 697 | 0.35 | 0.405 | -0.448 | -0.151 | 0.54 | -0.337 | -0.998 | -2.06 |
| gated_elliott | 501 | 0.44 | 0.612 | -0.443 | 0.016 | 0.95 | -0.016 | -0.560 | -0.02 |
| raw_classical | 672 | 0.34 | 0.351 | -0.453 | -0.178 | 0.62 | -0.341 | -0.998 | -2.29 |
| gated_classical | 678 | 0.44 | 0.520 | -0.429 | -0.015 | 0.75 | -0.068 | -0.803 | -0.32 |
| raw_trend | 613 | 0.29 | 0.602 | -0.534 | -0.200 | 0.59 | -0.353 | -0.998 | -2.15 |
| gated_trend | 1116 | 0.42 | 0.587 | -0.425 | 0.005 | 0.81 | -0.070 | -0.899 | -0.19 |
| raw_momentum | 683 | 0.30 | 0.565 | -0.466 | -0.161 | 0.59 | -0.320 | -0.997 | -1.99 |
| gated_momentum | 1162 | 0.42 | 0.590 | -0.418 | 0.010 | 0.88 | -0.052 | -0.840 | -0.08 |
| gated_composite | 519 | 0.44 | 0.561 | -0.440 | -0.000 | 0.86 | -0.036 | -0.652 | -0.16 |
| rcb | 342 | 0.40 | 0.662 | -0.387 | 0.036 | 1.05 | 0.008 | -0.484 | 0.13 |
| tpb | 405 | 0.40 | 0.599 | -0.455 | -0.031 | 0.75 | -0.058 | -0.671 | -0.36 |
| rcb_calls | 313 | 0.40 | 0.682 | -0.392 | 0.037 | 1.06 | 0.009 | -0.475 | 0.13 |
| tpb_calls | 367 | 0.41 | 0.586 | -0.463 | -0.031 | 0.75 | -0.055 | -0.638 | -0.35 |
| rcb+tpb | 661 | 0.39 | 0.635 | -0.428 | -0.011 | 0.80 | -0.060 | -0.720 | -0.23 |

## C. Walk-forward (3y train → 1y test, parameters chosen on train only)

### rcb

OOS trades 212, win 0.36, avg win 0.670, avg loss -0.386, expectancy/trade -0.007 (t=-0.18), PF 0.97, positive years 5/11, approx. max DD (4% premium per trade) -0.226

| test year | params | trades | win | exp | PF | return | maxDD |
|---|---|---|---|---|---|---|---|
| 2016-2016 | `{"lookback": 20, "squeeze_pct": 0.2, "vol_mult": 1.5, "target_atr": 2.5, "c_target_delta": 0.5, "x_time_stop_days": 8}` | 21 | 0.33 | -0.138 | 0.46 | -0.145 | -0.219 |
| 2017-2017 | `{"lookback": 20, "squeeze_pct": 0.35, "vol_mult": 1.5, "target_atr": 4.0, "c_target_delta": 0.5, "x_time_stop_days": 15}` | 29 | 0.41 | 0.076 | 1.20 | 0.067 | -0.098 |
| 2018-2018 | `{"lookback": 55, "squeeze_pct": 0.35, "vol_mult": 1.5, "target_atr": 4.0, "c_target_delta": 0.5, "x_time_stop_days": 15}` | 16 | 0.25 | -0.053 | 0.77 | -0.042 | -0.125 |
| 2019-2019 | `{"lookback": 55, "squeeze_pct": 0.35, "vol_mult": 1.2, "target_atr": 4.0, "c_target_delta": 0.7, "x_time_stop_days": 15}` | 24 | 0.29 | -0.048 | 0.73 | -0.037 | -0.147 |
| 2020-2020 | `{"lookback": 20, "squeeze_pct": 0.2, "vol_mult": 1.2, "target_atr": 4.0, "c_target_delta": 0.7, "x_time_stop_days": 15}` | 28 | 0.43 | 0.045 | 1.15 | 0.046 | -0.143 |
| 2021-2021 | `{"lookback": 55, "squeeze_pct": 0.2, "vol_mult": 1.5, "target_atr": 4.0, "c_target_delta": 0.5, "x_time_stop_days": 15}` | 14 | 0.36 | 0.121 | 1.47 | 0.062 | -0.079 |
| 2022-2022 | `{"lookback": 55, "squeeze_pct": 0.2, "vol_mult": 1.5, "target_atr": 4.0, "c_target_delta": 0.5, "x_time_stop_days": 15}` | 8 | 0.38 | -0.167 | 0.32 | -0.045 | -0.078 |
| 2023-2023 | `{"lookback": 20, "squeeze_pct": 0.2, "vol_mult": 1.5, "target_atr": 2.5, "c_target_delta": 0.7, "x_time_stop_days": 15}` | 14 | 0.64 | 0.254 | 2.77 | 0.126 | -0.029 |
| 2024-2024 | `{"lookback": 20, "squeeze_pct": 0.35, "vol_mult": 1.5, "target_atr": 2.5, "c_target_delta": 0.7, "x_time_stop_days": 15}` | 16 | 0.19 | -0.214 | 0.30 | -0.100 | -0.146 |
| 2025-2025 | `{"lookback": 20, "squeeze_pct": 0.35, "vol_mult": 1.2, "target_atr": 4.0, "c_target_delta": 0.7, "x_time_stop_days": 15}` | 25 | 0.40 | 0.034 | 1.17 | 0.030 | -0.089 |
| 2026-2026 | `{"lookback": 20, "squeeze_pct": 0.35, "vol_mult": 1.2, "target_atr": 2.5, "c_target_delta": 0.5, "x_time_stop_days": 8}` | 17 | 0.24 | -0.087 | 0.55 | -0.064 | -0.089 |

### tpb

OOS trades 415, win 0.39, avg win 0.487, avg loss -0.385, expectancy/trade -0.044 (t=-1.80), PF 0.81, positive years 5/11, approx. max DD (4% premium per trade) -0.592

| test year | params | trades | win | exp | PF | return | maxDD |
|---|---|---|---|---|---|---|---|
| 2016-2016 | `{"rsi2_max": 5, "adx_min": 25, "target_atr": 2.0, "c_target_delta": 0.6, "x_time_stop_days": 5}` | 8 | 0.12 | -0.312 | 0.04 | -0.098 | -0.104 |
| 2017-2017 | `{"rsi2_max": 5, "adx_min": 25, "target_atr": 2.0, "c_target_delta": 0.6, "x_time_stop_days": 10}` | 10 | 0.50 | 0.138 | 1.42 | 0.043 | -0.070 |
| 2018-2018 | `{"rsi2_max": 10, "adx_min": 15, "target_atr": 3.0, "c_target_delta": 0.75, "x_time_stop_days": 10}` | 39 | 0.46 | 0.012 | 1.00 | -0.000 | -0.190 |
| 2019-2019 | `{"rsi2_max": 10, "adx_min": 15, "target_atr": 3.0, "c_target_delta": 0.75, "x_time_stop_days": 10}` | 44 | 0.43 | -0.009 | 0.95 | -0.014 | -0.169 |
| 2020-2020 | `{"rsi2_max": 20, "adx_min": 15, "target_atr": 2.0, "c_target_delta": 0.6, "x_time_stop_days": 10}` | 84 | 0.39 | -0.056 | 0.76 | -0.186 | -0.290 |
| 2021-2021 | `{"rsi2_max": 10, "adx_min": 15, "target_atr": 3.0, "c_target_delta": 0.75, "x_time_stop_days": 10}` | 61 | 0.31 | -0.156 | 0.47 | -0.273 | -0.295 |
| 2022-2022 | `{"rsi2_max": 20, "adx_min": 15, "target_atr": 3.0, "c_target_delta": 0.75, "x_time_stop_days": 10}` | 73 | 0.41 | 0.009 | 1.03 | 0.008 | -0.111 |
| 2023-2023 | `{"rsi2_max": 10, "adx_min": 25, "target_atr": 2.0, "c_target_delta": 0.6, "x_time_stop_days": 5}` | 17 | 0.35 | 0.010 | 1.13 | 0.009 | -0.044 |
| 2024-2024 | `{"rsi2_max": 5, "adx_min": 25, "target_atr": 2.0, "c_target_delta": 0.75, "x_time_stop_days": 5}` | 12 | 0.50 | -0.123 | 0.41 | -0.045 | -0.067 |
| 2025-2025 | `{"rsi2_max": 10, "adx_min": 15, "target_atr": 3.0, "c_target_delta": 0.6, "x_time_stop_days": 10}` | 41 | 0.44 | 0.004 | 0.98 | -0.009 | -0.122 |
| 2026-2026 | `{"rsi2_max": 10, "adx_min": 15, "target_atr": 3.0, "c_target_delta": 0.6, "x_time_stop_days": 10}` | 26 | 0.27 | -0.100 | 0.79 | -0.048 | -0.113 |

### gated_composite

OOS trades 277, win 0.47, avg win 0.594, avg loss -0.449, expectancy/trade 0.040 (t=1.11), PF 1.17, positive years 6/11, approx. max DD (4% premium per trade) -0.201

| test year | params | trades | win | exp | PF | return | maxDD |
|---|---|---|---|---|---|---|---|
| 2016-2016 | `{"vol_mult": 1.3, "rv_pct_max": 0.9, "c_target_delta": 0.7, "x_time_stop_days": 15}` | 21 | 0.33 | -0.125 | 0.53 | -0.103 | -0.142 |
| 2017-2017 | `{"vol_mult": 1.0, "rv_pct_max": 0.6, "c_target_delta": 0.7, "x_time_stop_days": 15}` | 42 | 0.64 | 0.147 | 1.67 | 0.230 | -0.095 |
| 2018-2018 | `{"vol_mult": 1.0, "rv_pct_max": 0.6, "c_target_delta": 0.7, "x_time_stop_days": 15}` | 30 | 0.57 | 0.068 | 1.18 | 0.053 | -0.096 |
| 2019-2019 | `{"vol_mult": 1.0, "rv_pct_max": 0.6, "c_target_delta": 0.5, "x_time_stop_days": 15}` | 25 | 0.40 | 0.142 | 1.47 | 0.116 | -0.095 |
| 2020-2020 | `{"vol_mult": 1.0, "rv_pct_max": 0.6, "c_target_delta": 0.5, "x_time_stop_days": 15}` | 24 | 0.58 | 0.116 | 1.52 | 0.099 | -0.088 |
| 2021-2021 | `{"vol_mult": 1.0, "rv_pct_max": 0.6, "c_target_delta": 0.5, "x_time_stop_days": 15}` | 42 | 0.33 | -0.043 | 0.82 | -0.097 | -0.174 |
| 2022-2022 | `{"vol_mult": 1.0, "rv_pct_max": 0.6, "c_target_delta": 0.7, "x_time_stop_days": 15}` | 17 | 0.53 | 0.177 | 1.99 | 0.114 | -0.081 |
| 2023-2023 | `{"vol_mult": 1.0, "rv_pct_max": 0.6, "c_target_delta": 0.7, "x_time_stop_days": 15}` | 44 | 0.43 | -0.014 | 0.92 | -0.031 | -0.157 |
| 2024-2024 | `{"vol_mult": 1.3, "rv_pct_max": 0.9, "c_target_delta": 0.7, "x_time_stop_days": 8}` | 18 | 0.44 | -0.037 | 0.78 | -0.029 | -0.109 |
| 2025-2025 | `{"vol_mult": 1.3, "rv_pct_max": 0.6, "c_target_delta": 0.7, "x_time_stop_days": 8}` | 10 | 0.40 | 0.035 | 1.31 | 0.017 | -0.045 |
| 2026-2026 | `{"vol_mult": 1.3, "rv_pct_max": 0.6, "c_target_delta": 0.7, "x_time_stop_days": 8}` | 4 | 0.25 | -0.238 | 0.32 | -0.030 | -0.045 |

## D. Robustness (default parameters, no fitting)

### Cost sensitivity (expectancy per trade)

| engine | spread 2/4% vrp1.1 | spread 4/8% vrp1.1 | spread 2/4% vrp1.25 |
|---|---|---|---|
| rcb | 0.036 | -0.004 | 0.003 |
| tpb | -0.031 | -0.063 | -0.051 |
| rcb+tpb | -0.011 | -0.050 | -0.033 |
| gated_composite | -0.000 | -0.025 | -0.021 |
| baseline_composite | -0.130 | -0.162 | -0.133 |

### Per symbol (rcb+tpb, default rules)

| symbol | trades | win | exp |
|---|---|---|---|
| AAPL | 63 | 0.38 | -0.068 |
| AMD | 45 | 0.38 | 0.080 |
| AMZN | 59 | 0.37 | 0.032 |
| COST | 33 | 0.52 | -0.007 |
| GOOGL | 65 | 0.42 | 0.112 |
| IWM | 39 | 0.38 | 0.024 |
| JPM | 52 | 0.35 | 0.003 |
| META | 30 | 0.47 | 0.061 |
| MSFT | 41 | 0.37 | -0.029 |
| NVDA | 64 | 0.38 | -0.186 |
| QQQ | 41 | 0.41 | 0.008 |
| SPY | 34 | 0.41 | -0.073 |
| TSLA | 33 | 0.42 | 0.011 |
| UNH | 37 | 0.38 | -0.026 |
| XOM | 25 | 0.28 | -0.117 |

### Exit reasons (rcb+tpb)

```
                   count      mean
reason                            
time                 199  0.011716
option_stop          178 -0.606226
underlying_stop      110 -0.346518
underlying_target    105  0.679287
option_target         45  1.449513
trailing              24 -0.016392
```
