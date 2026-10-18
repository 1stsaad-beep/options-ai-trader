"""Five published strategies (replicated as published, adapted only to emit
Call/Put signals) and five new strategies derived from them.

Every function returns the standard frame: dir, stop, target, reason and the
optional exit columns xl (close a Call) / xs (close a Put). All causal.

Published (sources in SIX_STRATEGIES_REPORT.md):
  P1 tsmom_monthly      Time-series momentum / 10-month trend (Moskowitz-Ooi-Pedersen 2012, Faber 2007)
  P2 connors_rsi2       RSI(2) pullback above the 200-day average (Connors & Alvarez)
  P3 high_52w           New 52-week high momentum (George & Hwang 2004)
  P4 turtle_20          Donchian 20-day breakout, 10-day exit, 2N stop (Turtle System 1)
  P5 ORB                5-minute opening-range breakout (Zarattini, Barbon & Aziz 2024) -> intraday.orb

New (designed for long options: fewer, faster, cheaper-vol entries):
  N1 trend_dip          RSI2 + IBS capitulation inside an up-trend, VIX regime cap, SMA5 exit
  N2 high_squeeze       52-week-high proximity + volatility squeeze + 20-day breakout + RS
  N3 turtle_quality     55-day breakout gated by ADX, market regime, relative strength, cheap vol
  N4 tom_trend          Turn-of-month window, only in a market up-trend
  N5 orb_inplay_vwap    ORB only for 'stocks in play' (RVOL>=2), exit on VWAP loss -> intraday
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from . import indicators as ind
from .engines_v2 import Ctx


def _frame(df, d, stop=np.nan, target=np.nan, reason="", xl=False, xs=False):
    return pd.DataFrame({"dir": d, "stop": stop, "target": target, "reason": reason, "xl": xl, "xs": xs}, index=df.index)


def _w(cond, a, b=np.nan):
    return np.where(cond, a, b)


# ---------------------------------------------------------------- P1
def tsmom_monthly(ctx: Ctx) -> pd.DataFrame:
    """Last trading day of each month: 12-month return > 0 and close > SMA200 -> Call;
    < 0 and below -> Put. Held ~1 month (time stop in the config)."""
    df = ctx.df
    c = df["close"]
    month_end = pd.Series(df.index.to_period("M"), index=df.index)
    last = month_end != month_end.shift(-1)
    r12 = c / c.shift(252) - 1
    up = last & (r12 > 0) & (c > ctx.sma200)
    dn = last & (r12 < 0) & (c < ctx.sma200)
    d = np.where(up, 1, np.where(dn, -1, 0))
    return _frame(df, d, reason=_w(up, "TSMOM up", _w(dn, "TSMOM down", "")))


# ---------------------------------------------------------------- P2
def connors_rsi2(ctx: Ctx, lo=10, hi=90) -> pd.DataFrame:
    df = ctx.df
    c = df["close"]
    sma5 = ind.sma(c, 5)
    up = (c > ctx.sma200) & (ctx.rsi2 < lo)
    dn = (c < ctx.sma200) & (ctx.rsi2 > hi)
    d = np.where(up, 1, np.where(dn, -1, 0))
    return _frame(df, d, reason=_w(up, "RSI2<10 above SMA200", _w(dn, "RSI2>90 below SMA200", "")),
                  xl=(c > sma5).to_numpy(), xs=(c < sma5).to_numpy())


# ---------------------------------------------------------------- P3
def high_52w(ctx: Ctx) -> pd.DataFrame:
    df = ctx.df
    c, h, l = df["close"], df["high"], df["low"]
    hh = h.rolling(252).max().shift(1)
    ll = l.rolling(252).min().shift(1)
    first_up = (c > hh) & ~((c.shift(1) > hh.shift(1)).rolling(20).max().fillna(0).astype(bool))
    first_dn = (c < ll) & ~((c.shift(1) < ll.shift(1)).rolling(20).max().fillna(0).astype(bool))
    a = ctx.atr
    d = np.where(first_up, 1, np.where(first_dn, -1, 0))
    return _frame(df, d, stop=_w(first_up, c - 2 * a, _w(first_dn, c + 2 * a)),
                  reason=_w(first_up, "new 52-week high", _w(first_dn, "new 52-week low", "")))


# ---------------------------------------------------------------- P4
def turtle_20(ctx: Ctx) -> pd.DataFrame:
    df = ctx.df
    c, h, l = df["close"], df["high"], df["low"]
    n = ind.atr(df, 20)
    up = c > h.rolling(20).max().shift(1)
    dn = c < l.rolling(20).min().shift(1)
    d = np.where(up, 1, np.where(dn, -1, 0))
    return _frame(df, d, stop=_w(up, c - 2 * n, _w(dn, c + 2 * n)),
                  reason=_w(up, "Turtle 20-day breakout", _w(dn, "Turtle 20-day breakdown", "")),
                  xl=(c < l.rolling(10).min().shift(1)).to_numpy(), xs=(c > h.rolling(10).max().shift(1)).to_numpy())


# ---------------------------------------------------------------- N1
def trend_dip(ctx: Ctx, vix: pd.Series | None = None, rsi2_max=5.0, ibs_max=0.25, vix_max=35.0) -> pd.DataFrame:
    """Deeper capitulation than P2 (RSI2<5 AND close in the bottom quarter of the
    day's range) in a confirmed up-trend; skipped when VIX > 35 (crash regime:
    options too expensive, dips keep going). Exit on close > SMA5 or RSI2 > 70."""
    df = ctx.df
    c = df["close"]
    sma5 = ind.sma(c, 5)
    vix_ok = True if vix is None else (vix.reindex(df.index).ffill() < vix_max)
    up = (c > ctx.sma200) & (ctx.sma50 > ctx.sma200) & ctx.mkt_up & (ctx.rsi2 < rsi2_max) & (ctx.clv < ibs_max) & vix_ok
    d = np.where(up, 1, 0)
    lo5 = df["low"].rolling(5).min()
    return _frame(df, d, stop=_w(up, lo5 - 1.5 * ctx.atr), reason=_w(up, "trend dip: RSI2<5 & IBS<0.25", ""),
                  xl=((c > sma5) | (ctx.rsi2 > 70)).to_numpy())


# ---------------------------------------------------------------- N2
def high_squeeze(ctx: Ctx) -> pd.DataFrame:
    df = ctx.df
    c, h = df["close"], df["high"]
    near = c >= 0.97 * h.rolling(252).max().shift(1)
    squeeze = ctx.bbw_pct.shift(1).rolling(5).min() <= 0.30
    brk = c > h.rolling(20).max().shift(1)
    vol = df["volume"] >= 1.2 * ctx.vol20.shift(1)
    rs = ctx.ret63 > ctx.mkt_ret63
    up = near & squeeze & brk & vol & rs & ctx.mkt_up & (ctx.clv >= 0.5)
    a = ctx.atr
    stop = np.maximum(df["low"].rolling(10).min(), c - 2 * a)
    return _frame(df, np.where(up, 1, 0), stop=_w(up, stop), target=_w(up, c + 4 * a),
                  reason=_w(up, "52w-high squeeze breakout", ""), xl=(c < ind.ema(c, 20)).to_numpy())


# ---------------------------------------------------------------- N3
def turtle_quality(ctx: Ctx) -> pd.DataFrame:
    df = ctx.df
    c, h, l = df["close"], df["high"], df["low"]
    a = ctx.atr
    cheap = ctx.rv_pct <= 0.7
    up = (c > h.rolling(55).max().shift(1)) & (ctx.adx >= 20) & ctx.regime(1) & (ctx.ret63 > ctx.mkt_ret63) & cheap
    dn = (c < l.rolling(55).min().shift(1)) & (ctx.adx >= 20) & ctx.regime(-1) & (ctx.ret63 < ctx.mkt_ret63) & cheap
    d = np.where(up, 1, np.where(dn, -1, 0))
    return _frame(df, d, stop=_w(up, c - 2 * a, _w(dn, c + 2 * a)),
                  reason=_w(up, "55-day breakout, ADX, RS, cheap vol", _w(dn, "55-day breakdown, ADX, RS", "")),
                  xl=(c < l.rolling(20).min().shift(1)).to_numpy(), xs=(c > h.rolling(20).max().shift(1)).to_numpy())


# ---------------------------------------------------------------- N4
def tom_trend(ctx: Ctx, calendar: pd.DatetimeIndex) -> pd.DataFrame:
    """Signal at the close of the 5th-to-last trading day (entry next open = T-4),
    exit at the close of the 3rd trading day of the new month. Market and symbol
    above SMA200. `calendar` = trading days (SPY index), so no future dates are used
    beyond the published exchange calendar."""
    df = ctx.df
    cal = pd.Series(calendar, index=calendar)
    per = cal.dt.to_period("M")
    rank_from_end = per.groupby(per).cumcount(ascending=False)  # 0 = last day
    rank_from_start = per.groupby(per).cumcount()               # 0 = first day
    sig_day = rank_from_end.reindex(df.index) == 4
    exit_day = rank_from_start.reindex(df.index) == 2
    up = sig_day & ctx.mkt_up & (df["close"] > ctx.sma200)
    a = ctx.atr
    return _frame(df, np.where(up, 1, 0), stop=_w(up, df["close"] - 3 * a), reason=_w(up, "turn-of-month window", ""),
                  xl=exit_day.fillna(False).to_numpy())


# ---------------------------------------------------------------- extra published (round 2)
def dual_momentum(ctxs: dict, data: dict, top: int = 3) -> dict:
    """Antonacci dual momentum adapted to single names: at each month end rank the
    universe by 12-1 month return; buy Calls on the top `top` names whose own
    12-month return is positive (absolute momentum) while SPY > SMA200."""
    spy = data["SPY"]
    mom = pd.DataFrame({s: df["close"].shift(21) / df["close"].shift(252) - 1 for s, df in data.items()}).reindex(spy.index)
    abs12 = pd.DataFrame({s: df["close"] / df["close"].shift(252) - 1 for s, df in data.items()}).reindex(spy.index)
    rank = mom.rank(axis=1, ascending=False)
    per = pd.Series(spy.index.to_period("M"), index=spy.index)
    month_end = per != per.shift(-1)
    mkt_up = spy["close"] > ind.sma(spy["close"], 200)
    out = {}
    for s, df in data.items():
        pick = (month_end & mkt_up & (rank[s] <= top) & (abs12[s] > 0)).reindex(df.index).fillna(False)
        out[s] = _frame(df, np.where(pick, 1, 0), reason=np.where(pick, "dual momentum top-3", ""))
    return out


def nr7_trend(ctx: Ctx) -> pd.DataFrame:
    """Crabel NR7 in an up-trend: yesterday had the narrowest range of 7 days and
    today closes above yesterday's high; stop below yesterday's low."""
    df = ctx.df
    rng = df["high"] - df["low"]
    nr7_prev = (rng == rng.rolling(7).min()).shift(1).fillna(False).astype(bool)
    c = df["close"]
    up = nr7_prev & (c > df["high"].shift(1)) & (c > ctx.sma50) & (ctx.sma50 > ctx.sma200) & ctx.mkt_up
    a = ctx.atr
    return _frame(df, np.where(up, 1, 0), stop=_w(up, df["low"].shift(1) - 0.1 * a), target=_w(up, c + 2.5 * a),
                  reason=_w(up, "NR7 breakout in up-trend", ""))
