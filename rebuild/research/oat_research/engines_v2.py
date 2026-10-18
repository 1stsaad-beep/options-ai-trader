"""Improved / new engines. Every function returns a signal frame indexed like
``df`` with columns dir (+1 call / -1 put / 0), stop, target (underlying prices)
and reason. All rules are causal (use data <= t) and deterministic.

* quality_gate()      — filter layer for the traditional engines (regime, market
                        regime, confirmation trigger, volume, option-cost, room).
* compression_breakout() — NEW "RCB": Regime-gated Compression Breakout.
* trend_pullback()       — "TPB": Trend Pullback Reclaim.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from . import indicators as ind


@dataclass
class Ctx:
    """Shared causal series for one symbol (+ optional market series)."""
    df: pd.DataFrame
    spy: pd.DataFrame | None = None

    def __post_init__(self):
        df = self.df
        c = df["close"]
        self.sma50 = ind.sma(c, 50)
        self.sma200 = ind.sma(c, 200)
        self.ema20 = ind.ema(c, 20)
        self.atr = ind.atr(df)
        self.adx = ind.adx(df)
        self.rsi2 = ind.rsi(c, 2)
        self.clv = ind.close_location(df)
        self.vol20 = ind.sma(df["volume"], 20)
        self.rv20 = ind.realized_vol(c, 20)
        self.rv_pct = ind.rolling_percentile(self.rv20, 252)
        self.bbw_pct = ind.rolling_percentile(ind.bb_width(c, 20), 126)
        self.atr_ratio = ind.atr(df, 5) / ind.atr(df, 50)
        self.ret63 = c / c.shift(63) - 1
        if self.spy is not None:
            s = self.spy["close"].reindex(df.index).ffill()
            m200 = ind.sma(s, 200)
            self.mkt_up = (s > m200) | m200.isna()
            self.mkt_dn = (s < m200) | m200.isna()
            self.mkt_ret63 = (s / s.shift(63) - 1).fillna(0.0)
        else:
            self.mkt_up = pd.Series(True, index=df.index)
            self.mkt_dn = pd.Series(True, index=df.index)
            self.mkt_ret63 = pd.Series(0.0, index=df.index)

    def regime(self, direction: int, strict: bool = True) -> pd.Series:
        c = self.df["close"]
        if direction > 0:
            r = c > self.sma200
            if strict:
                r &= self.sma50 > self.sma200
            return r & self.mkt_up
        r = c < self.sma200
        if strict:
            r &= self.sma50 < self.sma200
        return r & self.mkt_dn


def _frame(df, d, stop, tgt, reason):
    return pd.DataFrame({"dir": d, "stop": stop, "target": tgt, "reason": reason}, index=df.index)


# ---------------------------------------------------------------------------
# 1) Quality gate for traditional engines
# ---------------------------------------------------------------------------

@dataclass
class GateParams:
    regime: bool = True
    strict_regime: bool = True
    confirm_window: int = 3        # bars allowed for the trigger after the raw signal
    trigger: bool = True           # close beyond prior bar's extreme + close location
    clv_min: float = 0.6
    vol_mult: float = 1.0          # trigger volume >= x * 20d average (1.0 = off-ish)
    rv_pct_max: float = 0.80       # skip when realised vol is in the top 20% of its year
    min_room_atr: float = 1.5      # distance to target in ATR
    default_target_atr: float = 2.5
    max_stop_atr: float = 3.0
    default_stop_atr: float = 1.5
    calls_only: bool = False


def quality_gate(ctx: Ctx, raw: pd.DataFrame, gp: GateParams = GateParams()) -> pd.DataFrame:
    df = ctx.df
    n = len(df)
    c, h, l, v = (df[k].to_numpy() for k in ("close", "high", "low", "volume"))
    a = ctx.atr.to_numpy()
    clv, vol20, rvp = ctx.clv.to_numpy(), ctx.vol20.to_numpy(), ctx.rv_pct.to_numpy()
    reg_up = ctx.regime(1, gp.strict_regime).to_numpy()
    reg_dn = ctx.regime(-1, gp.strict_regime).to_numpy()
    rd, rs, rt, rr = (raw[k].to_numpy() for k in ("dir", "stop", "target", "reason"))
    out_d = np.zeros(n, dtype=int)
    out_s = np.full(n, np.nan)
    out_t = np.full(n, np.nan)
    out_r = np.array([""] * n, dtype=object)
    armed = None  # (direction, expiry_index, stop, target, reason)
    for t in range(1, n):
        if rd[t] != 0 and not (gp.calls_only and rd[t] < 0):
            armed = (int(rd[t]), t + gp.confirm_window, rs[t], rt[t], rr[t])
        if armed is None or t > armed[1] or not np.isfinite(a[t]):
            if armed is not None and t > armed[1]:
                armed = None
            continue
        d, _, stop, tgt, why = armed
        if gp.regime and not (reg_up[t] if d > 0 else reg_dn[t]):
            continue
        if gp.trigger:
            ok = (c[t] > h[t - 1] and clv[t] >= gp.clv_min) if d > 0 else (c[t] < l[t - 1] and clv[t] <= 1 - gp.clv_min)
            if not ok:
                continue
        if np.isfinite(vol20[t]) and v[t] < gp.vol_mult * vol20[t]:
            continue
        if np.isfinite(rvp[t]) and rvp[t] > gp.rv_pct_max:
            continue
        if not np.isfinite(stop) or abs(c[t] - stop) > gp.max_stop_atr * a[t] or (stop - c[t]) * d >= 0:
            stop = c[t] - d * gp.default_stop_atr * a[t]
        if not np.isfinite(tgt) or (tgt - c[t]) * d <= 0:
            tgt = c[t] + d * gp.default_target_atr * a[t]
        if abs(tgt - c[t]) < gp.min_room_atr * a[t]:
            continue
        out_d[t], out_s[t], out_t[t], out_r[t] = d, stop, tgt, f"gated[{why}]"
        armed = None
    return _frame(df, out_d, out_s, out_t, out_r)


# ---------------------------------------------------------------------------
# 2) NEW: Regime-gated Compression Breakout (RCB)
# ---------------------------------------------------------------------------

@dataclass
class RCBParams:
    lookback: int = 20             # Donchian breakout window
    squeeze_pct: float = 0.25      # BB-width percentile (126d) must have been <= this ...
    squeeze_window: int = 5        # ... on at least one of the last N bars
    atr_ratio_max: float = 0.80    # alternative squeeze: ATR5/ATR50 <= x (either qualifies)
    clv_min: float = 0.60
    vol_mult: float = 1.3
    rel_strength: bool = True      # 63d return above the market's (calls) / below (puts)
    stop_atr: float = 1.5          # stop = max(breakout level - 0.5 ATR, close - stop_atr*ATR)
    target_atr: float = 3.0
    strict_regime: bool = True
    allow_puts: bool = True


def compression_breakout(ctx: Ctx, p: RCBParams = RCBParams()) -> pd.DataFrame:
    df = ctx.df
    c = df["close"]
    hh = df["high"].rolling(p.lookback).max().shift(1)
    ll = df["low"].rolling(p.lookback).min().shift(1)
    squeeze = (ctx.bbw_pct.shift(1).rolling(p.squeeze_window).min() <= p.squeeze_pct) | \
              (ctx.atr_ratio.shift(1) <= p.atr_ratio_max)
    vol_ok = df["volume"] >= p.vol_mult * ctx.vol20.shift(1)
    rs_up = (ctx.ret63 > ctx.mkt_ret63) if p.rel_strength else True
    rs_dn = (ctx.ret63 < ctx.mkt_ret63) if p.rel_strength else True
    up = ctx.regime(1, p.strict_regime) & squeeze & (c > hh) & (ctx.clv >= p.clv_min) & vol_ok & rs_up
    dn = ctx.regime(-1, p.strict_regime) & squeeze & (c < ll) & (ctx.clv <= 1 - p.clv_min) & vol_ok & rs_dn
    if not p.allow_puts:
        dn &= False
    d = np.where(up, 1, np.where(dn, -1, 0))
    a = ctx.atr
    stop = np.where(up, np.maximum(hh - 0.5 * a, c - p.stop_atr * a),
                    np.where(dn, np.minimum(ll + 0.5 * a, c + p.stop_atr * a), np.nan))
    tgt = np.where(up, c + p.target_atr * a, np.where(dn, c - p.target_atr * a, np.nan))
    reason = np.where(up, "RCB: squeeze->20d high breakout, vol+, RS+", np.where(dn, "RCB: squeeze->20d low breakdown", ""))
    return _frame(df, d, stop, tgt, reason)


# ---------------------------------------------------------------------------
# 3) Trend Pullback Reclaim (TPB)
# ---------------------------------------------------------------------------

@dataclass
class TPBParams:
    adx_min: float = 20.0
    rsi2_max: float = 10.0          # pullback depth (calls); puts use 100 - x
    pullback_window: int = 3        # RSI2 extreme within the last N bars
    clv_min: float = 0.5
    stop_lookback: int = 5
    stop_buffer_atr: float = 0.25
    target_atr: float = 2.5
    strict_regime: bool = True
    allow_puts: bool = True


def trend_pullback(ctx: Ctx, p: TPBParams = TPBParams()) -> pd.DataFrame:
    df = ctx.df
    c, h, l = df["close"], df["high"], df["low"]
    a = ctx.atr
    dipped = (ctx.rsi2.rolling(p.pullback_window).min() <= p.rsi2_max).shift(1).fillna(False).astype(bool)
    popped = (ctx.rsi2.rolling(p.pullback_window).max() >= 100 - p.rsi2_max).shift(1).fillna(False).astype(bool)
    trending = ctx.adx >= p.adx_min
    up = ctx.regime(1, p.strict_regime) & trending & dipped & (c > h.shift(1)) & (ctx.clv >= p.clv_min) & (c > ctx.sma50)
    dn = ctx.regime(-1, p.strict_regime) & trending & popped & (c < l.shift(1)) & (ctx.clv <= 1 - p.clv_min) & (c < ctx.sma50)
    if not p.allow_puts:
        dn &= False
    lo = l.rolling(p.stop_lookback).min() - p.stop_buffer_atr * a
    hi = h.rolling(p.stop_lookback).max() + p.stop_buffer_atr * a
    d = np.where(up, 1, np.where(dn, -1, 0))
    stop = np.where(up, lo, np.where(dn, hi, np.nan))
    tgt = np.where(up, c + p.target_atr * a, np.where(dn, c - p.target_atr * a, np.nan))
    reason = np.where(up, "TPB: uptrend, RSI2 dip, reclaim of prior high", np.where(dn, "TPB: downtrend, RSI2 pop, loss of prior low", ""))
    return _frame(df, d, stop, tgt, reason)


def combine(*frames: pd.DataFrame) -> pd.DataFrame:
    """First non-zero signal wins per bar (priority = argument order); conflicting
    directions on the same bar cancel."""
    base = frames[0].copy()
    base["dir"] = 0
    base[["stop", "target"]] = np.nan
    base["reason"] = ""
    for i in range(len(base)):
        dirs = {int(f["dir"].iat[i]) for f in frames if f["dir"].iat[i] != 0}
        if len(dirs) != 1:
            continue
        for f in frames:
            if f["dir"].iat[i] != 0:
                base.iloc[i, base.columns.get_loc("dir")] = f["dir"].iat[i]
                base.iloc[i, base.columns.get_loc("stop")] = f["stop"].iat[i]
                base.iloc[i, base.columns.get_loc("target")] = f["target"].iat[i]
                base.iloc[i, base.columns.get_loc("reason")] = f["reason"].iat[i]
                break
    return base
