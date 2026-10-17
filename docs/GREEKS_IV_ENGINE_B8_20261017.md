# Batch B8 — Greeks and implied-volatility engine (2026-10-17)

Branch: `work/greeks-iv-b8` (stacked on B5). Pure computation on the phone, with no network and no server. Existing provider Greek checks (`option_greeks.dart`) are unchanged.

## Contents (`mobile/lib/option_pricing.dart`, version `oat-bsm-crr-v1`)
- `normCdf`: Cody/Hart double-precision approximation (error < 1e-14).
- `europeanGreeks`: generalized Black-Scholes-Merton with continuous yield q. Price, delta, gamma, theta (per year, plus `thetaPerDay`), vega and rho (per 1.00, plus per point).
- `americanPrice` / `americanGreeks`: CRR tree (default 200 steps). Delta/gamma/theta from the tree; vega/rho by central bumping.
- `impliedVolatility`: Newton plus bisection inside a bracket [0.001, 5.0] for European; bisection on the tree for American. Fails closed with a reason:
  - `INVALID_INPUT`, `PRICE_BELOW_INTRINSIC`, `PRICE_ABOVE_UPPER_BOUND`, `NO_TIME_VALUE` (time value ≤ half a cent by default), `VOLATILITY_ABOVE_RANGE`, `NOT_CONVERGED`.
- `yearsToExpiry`: ACT/365 to the close of the last session on the existing shared calendar (`market_paper_policy.dart`). Null outside the supported calendar.

## Reference tests (`test/option_pricing_test.dart`, 11 tests)
- Hull Example 15.6 (call 4.7594 / put 0.8086).
- Hull Greek letters example (S=49, K=50: delta 0.522, gamma 0.066, theta −4.31/yr, vega 12.1, rho 8.91).
- Haug (Complete Guide): Merton put 2.4648; deltas 0.5946/−0.3566; gamma 0.0278; put theta −31.1924; call rho 38.7325.
- Hull American put tree (4.49 at 5 steps, ≈4.28 at 500).
- Hull IV (21/20 call at 1.875 → 23.5%).
- Round trips for European and American; finite-difference agreement for all Greeks; put-call parity; standard normal CDF values.
- One reference value I recalled from Haug (vega 18.9358) did not match an independent Python calculation (18.5027), so I removed it rather than tuning the code to match. Vega is covered by the Hull value and finite differences.

## Evidence
`docs/evidence/greeks-iv-b8-20261017/`: analyze clean, **1084** tests (B5: 1073), debug APK, secret scan 0, SHA256SUMS.

## Not proven / OPEN
- Discrete cash dividends, exercise ahead of a dividend, adjusted/non-standard deliverables, borrow cost, and a smile/term structure are not modeled.
- The risk-free rate and dividend yield are user/caller inputs (no external source in this phase).
- Model values are labeled as model values and do not qualify entry by themselves; their use for eligibility is in B9.
