"""Option P&L model for backtests without historical option quotes.

Real historical option chains (OPRA) are not available here, so option prices
are MODELLED with Black–Scholes from the underlying path:

* Implied vol proxy  IV_t = vrp * (0.5*RV20_t + 0.5*RV120_t), floored at 10%.
  vrp (default 1.10) represents the usual premium of implied over realised vol.
  If a VIX series is supplied for an index ETF, IV_t = VIX_t/100 instead.
  IV is re-estimated every day, so vol expansion/contraction after entry
  (vega P&L) is included — derived from realised data only, never the future.
* Skew: puts and OTM-downside strikes get +skew*|ln(K/S)| vol; calls above spot get
  a small discount (typical equity smirk).
* Costs: buy at mid*(1+half_spread), sell at mid*(1-half_spread), with
  half_spread = max(spread_pct/2, $0.02/premium); $0.65 commission per contract per side.
* Strike chosen by target |delta| on a realistic strike grid; fixed DTE at entry.

This model ignores dividends, early exercise, earnings IV crush and intraday
option liquidity. Results are approximations; Paper trading with real quotes is
the final arbiter.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

from .indicators import realized_vol

SQRT2 = math.sqrt(2.0)


def ncdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / SQRT2))


def bs(is_call: bool, s: float, k: float, t: float, vol: float, r: float = 0.04) -> tuple[float, float]:
    """Price and delta. t in years."""
    if t <= 0 or vol <= 0:
        intr = max(0.0, s - k) if is_call else max(0.0, k - s)
        return intr, (1.0 if s > k else 0.0) if is_call else (-1.0 if s < k else 0.0)
    sq = vol * math.sqrt(t)
    d1 = (math.log(s / k) + (r + 0.5 * vol * vol) * t) / sq
    d2 = d1 - sq
    df = math.exp(-r * t)
    if is_call:
        return s * ncdf(d1) - k * df * ncdf(d2), ncdf(d1)
    return k * df * ncdf(-d2) - s * ncdf(-d1), ncdf(d1) - 1.0


def strike_step(s: float) -> float:
    return 0.5 if s < 25 else 1.0 if s < 100 else 2.5 if s < 250 else 5.0


@dataclass
class OptionCosts:
    spread_pct: float = 0.04        # full bid-ask spread as fraction of mid (liquid mega-cap ~2-5%)
    min_half_spread: float = 0.02   # dollars per share
    commission: float = 0.65        # per contract per side
    vrp: float = 1.10
    skew: float = 0.8
    rate: float = 0.04


def iv_series(df: pd.DataFrame, costs: OptionCosts, vix: pd.Series | None = None, bpd: int = 1) -> pd.Series:
    """bpd = bars per trading day (1 daily, 7 hourly, 390 one-minute). Windows are
    expressed in trading days so every timeframe gets a comparable IV proxy."""
    if vix is not None:
        iv = (vix.reindex(df.index, method="ffill") / 100.0)
        return iv.clip(lower=0.08)
    rv20 = realized_vol(df["close"], 20 * bpd, 252 * bpd)
    rv120 = realized_vol(df["close"], 120 * bpd, 252 * bpd)
    # Short histories (intraday downloads) lack 120 days: use the 20-day value alone.
    if bpd > 1:
        rv20 = rv20.fillna(realized_vol(df["close"], 5 * bpd, 252 * bpd))
    blend = (0.5 * rv20 + 0.5 * rv120).fillna(rv20)
    return (costs.vrp * blend).clip(lower=0.10)


def strike_vol(atm_iv: float, s: float, k: float, is_call: bool, skew: float) -> float:
    m = math.log(k / s)
    if m < 0:  # downside strikes are richer
        return atm_iv * (1 + skew * -m)
    return atm_iv * max(0.85, 1 - 0.3 * skew * m)


def choose_strike(is_call: bool, s: float, dte_days: float, atm_iv: float, target_delta: float,
                  costs: OptionCosts) -> float:
    step = strike_step(s)
    t = dte_days / 365.0
    best_k, best_err = None, 9e9
    base = round(s / step) * step
    for j in range(-40, 41):
        k = base + j * step
        if k <= 0:
            continue
        v = strike_vol(atm_iv, s, k, is_call, costs.skew)
        _, d = bs(is_call, s, k, t, v, costs.rate)
        err = abs(abs(d) - target_delta)
        if err < best_err:
            best_k, best_err = k, err
    return float(best_k)


def mid_price(is_call: bool, s: float, k: float, days_left: float, atm_iv: float, costs: OptionCosts) -> float:
    v = strike_vol(atm_iv, s, k, is_call, costs.skew)
    p, _ = bs(is_call, s, k, max(days_left, 0) / 365.0, v, costs.rate)
    return max(p, 0.01)


def buy_price(mid: float, costs: OptionCosts) -> float:
    return mid + max(costs.min_half_spread, mid * costs.spread_pct / 2)


def sell_price(mid: float, costs: OptionCosts) -> float:
    return max(0.0, mid - max(costs.min_half_spread, mid * costs.spread_pct / 2))


def option_delta(is_call: bool, s: float, k: float, days_left: float, atm_iv: float, costs: OptionCosts) -> float:
    v = strike_vol(atm_iv, s, k, is_call, costs.skew)
    return bs(is_call, s, k, max(days_left, 0) / 365.0, v, costs.rate)[1]


def np_finite(x) -> bool:
    return x is not None and np.isfinite(x)
