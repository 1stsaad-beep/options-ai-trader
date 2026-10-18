"""Intraday / swing strategies for minute, 5-minute and hourly bars.

All functions return the standard signal frame (dir/stop/target/reason) and are
causal: a decision at bar t uses only bars <= t; the backtester fills at t+1 open.

1. wave_divergence()  — RSI/MACD divergence at the end of wave 2 (-> wave 3) and at
                        the end of wave B (-> wave C), bullish and bearish.
2. orb()              — 5-minute opening-range breakout (Zarattini/Barbon/Aziz style).
3. vwap_pullback()    — trend-day pullback to session VWAP, then reclaim.
(RCB and TPB from engines_v2 run unchanged on hourly bars.)
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from . import indicators as ind


def _frame(df, d, stop, tgt, reason):
    return pd.DataFrame({"dir": d, "stop": stop, "target": tgt, "reason": reason}, index=df.index)


# ---------------------------------------------------------------------------
# 1) Wave-2 / Wave-B divergence
# ---------------------------------------------------------------------------

@dataclass
class WDParams:
    left: int = 3                  # pivot confirmation (bars)
    right: int = 2
    swing_atr: float = 1.5         # zig-zag ignores swings smaller than x ATR
    leg1_min_atr: float = 3.0      # wave 1 / wave A must be at least x ATR
    retr_min: float = 0.382        # wave 2 / wave B retracement window
    retr_max: float = 0.886
    divergence: str = "either"     # "rsi" | "macd" | "either" | "both" | "none"
    arm_bars: int = 10             # bars to wait for the trigger after the pivot is confirmed
    trigger_lookback: int = 3      # trigger: close beyond the last N bars' extreme
    stop_buffer_atr: float = 0.25
    target_leg: float = 1.0        # target = end of wave 2/B +/- x * wave 1/A
    setups: str = "both"           # "w2" | "b" | "both"
    allow_puts: bool = True


class _ZigZagATR:
    def __init__(self, atr, k):
        self.atr, self.k, self.out = atr, k, []
        self.changed = False

    def add(self, p):  # p = (index, confirmed_index, price, is_high)
        self.changed = False
        if not self.out:
            self.out.append(p)
            self.changed = True
            return
        last = self.out[-1]
        if last[3] == p[3]:
            if (p[2] > last[2]) if p[3] else (p[2] < last[2]):
                self.out[-1] = p
                self.changed = True
            return
        a = self.atr[p[0]]
        if np.isfinite(a) and abs(p[2] - last[2]) < self.k * a:
            return
        self.out.append(p)
        self.changed = True


def wave_divergence(df: pd.DataFrame, p: WDParams = WDParams()) -> pd.DataFrame:
    n = len(df)
    c, h, l = (df[k].to_numpy() for k in ("close", "high", "low"))
    atr = ind.atr(df).to_numpy()
    rsi = ind.rsi(df["close"]).to_numpy()
    hist = ind.macd_hist(df["close"]).to_numpy()
    ema20 = ind.ema(df["close"], 20).to_numpy()
    piv = ind.pivots(df, p.left, p.right)
    zz = _ZigZagATR(atr, p.swing_atr)
    known = []
    out_d = np.zeros(n, dtype=int)
    out_s = np.full(n, np.nan)
    out_t = np.full(n, np.nan)
    out_r = np.array([""] * n, dtype=object)
    armed = None   # dict
    j = 0

    def div_ok(cur, ref_hidden, internal, bull):
        """cur/ref = pivot tuples. Returns (rsi_div, macd_div)."""
        res = {"rsi": False, "macd": False}
        for name, osc in (("rsi", rsi), ("macd", hist)):
            oc = osc[cur[0]]
            if not np.isfinite(oc):
                continue
            # hidden divergence vs. the start of the leg
            orf = osc[ref_hidden[0]]
            if np.isfinite(orf):
                if bull and cur[2] > ref_hidden[2] and oc < orf:
                    res[name] = True
                if not bull and cur[2] < ref_hidden[2] and oc > orf:
                    res[name] = True
            # regular divergence vs. an internal pivot of the correction
            for q in internal:
                oq = osc[q[0]]
                if not np.isfinite(oq):
                    continue
                if bull and cur[2] < q[2] and oc > oq:
                    res[name] = True
                if not bull and cur[2] > q[2] and oc < oq:
                    res[name] = True
        return res

    for t in range(n):
        new_swing = False
        while j < len(piv) and piv[j][1] <= t:
            known.append(piv[j])
            zz.add(piv[j])
            new_swing |= zz.changed
            j += 1
        if new_swing and len(zz.out) >= 3 and np.isfinite(atr[t]):
            s0, s1, s2 = zz.out[-3:]
            bull = not s2[3]                       # last swing is a low -> bullish setup
            leg1 = abs(s1[2] - s0[2])
            retr = abs(s1[2] - s2[2]) / leg1 if leg1 > 0 else 9
            ok = leg1 >= p.leg1_min_atr * atr[t] and p.retr_min <= retr <= p.retr_max
            ok &= (s2[2] > s0[2]) if bull else (s2[2] < s0[2])
            if ok and (bull or p.allow_puts):
                # structure break: did leg 1 exceed the swing before s0?  -> wave 1 (impulse) else wave A
                prev_same = [q for q in zz.out[:-3] if q[3] == s1[3]]
                bos = bool(prev_same) and ((s1[2] > prev_same[-1][2]) if bull else (s1[2] < prev_same[-1][2]))
                tag = "W2->3" if bos else "B->C"
                if p.setups == "both" or (p.setups == "w2" and bos) or (p.setups == "b" and not bos):
                    internal = [q for q in known if q[3] == s2[3] and s1[0] < q[0] < s2[0]]
                    dv = div_ok(s2, s0, internal, bull)
                    need = {"rsi": dv["rsi"], "macd": dv["macd"], "either": dv["rsi"] or dv["macd"],
                            "both": dv["rsi"] and dv["macd"], "none": True}[p.divergence]
                    if need:
                        d = 1 if bull else -1
                        stop = s2[2] - d * p.stop_buffer_atr * atr[t]
                        tgt = s2[2] + d * p.target_leg * leg1
                        kinds = "+".join(k for k, v in dv.items() if v) or "no-div"
                        armed = dict(d=d, pivot=s2[2], stop=stop, tgt=tgt, until=t + p.arm_bars,
                                     why=f"{tag} {'bull' if bull else 'bear'} div[{kinds}] retr={retr:.2f}")
        if armed is None:
            continue
        d = armed["d"]
        if t > armed["until"] or (d > 0 and l[t] < armed["pivot"]) or (d < 0 and h[t] > armed["pivot"]):
            armed = None
            continue
        lb = p.trigger_lookback
        if t < lb or not np.isfinite(ema20[t]):
            continue
        if d > 0:
            trig = c[t] > h[t - lb:t].max() and c[t] > ema20[t]
        else:
            trig = c[t] < l[t - lb:t].min() and c[t] < ema20[t]
        if trig and (armed["tgt"] - c[t]) * d > 0 and (c[t] - armed["stop"]) * d > 0:
            out_d[t], out_s[t], out_t[t], out_r[t] = d, armed["stop"], armed["tgt"], armed["why"]
            armed = None
    return _frame(df, out_d, out_s, out_t, out_r)


# ---------------------------------------------------------------------------
# session helpers (intraday bars, exchange time)
# ---------------------------------------------------------------------------

def session_vwap(df: pd.DataFrame) -> pd.Series:
    tp = (df["high"] + df["low"] + df["close"]) / 3
    day = df.index.normalize()
    pv = (tp * df["volume"]).groupby(day).cumsum()
    vv = df["volume"].groupby(day).cumsum().replace(0, np.nan)
    return pv / vv


# ---------------------------------------------------------------------------
# 2) Opening-range breakout (5-minute bars)
# ---------------------------------------------------------------------------

@dataclass
class ORBParams:
    or_bars: int = 1               # opening range = first N bars (1 x 5m = 5 minutes)
    rvol_min: float = 1.0          # opening-range volume vs. its 14-session average
    min_body_atr: float = 0.0      # |close-open| of the OR bar in daily-ATR units
    target_r: float = 10.0         # profit target in R (R = OR range); EOD exit usually first
    allow_puts: bool = True


def orb(df: pd.DataFrame, p: ORBParams = ORBParams()) -> pd.DataFrame:
    """Direction of the opening range candle; entry at the next bar open; stop at
    the opposite end of the opening range; flat at end of day (set in ExitRules)."""
    n = len(df)
    day = df.index.normalize()
    pos_in_day = df.groupby(day).cumcount().to_numpy()
    o, h, l, c, v = (df[k].to_numpy() for k in ("open", "high", "low", "close", "volume"))
    out_d = np.zeros(n, dtype=int)
    out_s = np.full(n, np.nan)
    out_t = np.full(n, np.nan)
    out_r = np.array([""] * n, dtype=object)
    or_vols = []
    first_idx = np.nonzero(pos_in_day == 0)[0]
    for k, i0 in enumerate(first_idx):
        i1 = i0 + p.or_bars - 1
        if i1 >= n or day[i1] != day[i0]:
            continue
        hi, lo = h[i0:i1 + 1].max(), l[i0:i1 + 1].min()
        vol = v[i0:i1 + 1].sum()
        hist_v = or_vols[-14:]
        or_vols.append(vol)
        if len(hist_v) < 5 or vol < p.rvol_min * np.mean(hist_v):
            continue
        direction = int(np.sign(c[i1] - o[i0]))
        if direction == 0 or (direction < 0 and not p.allow_puts):
            continue
        rng = hi - lo
        if rng <= 0:
            continue
        stop = lo if direction > 0 else hi
        out_d[i1], out_s[i1] = direction, stop
        out_t[i1] = c[i1] + direction * p.target_r * rng
        out_r[i1] = f"ORB {'up' if direction > 0 else 'down'} rvol={vol / np.mean(hist_v):.2f}"
    return _frame(df, out_d, out_s, out_t, out_r)


# ---------------------------------------------------------------------------
# 3) VWAP trend pullback (5-minute or 1-minute bars)
# ---------------------------------------------------------------------------

@dataclass
class VWAPParams:
    trend_bars: int = 6            # bars closed on the trend side of VWAP before the pullback
    start_time: str = "10:00"
    last_entry: str = "14:30"
    touch_atr: float = 0.10        # pullback low within x ATR of VWAP
    clv_min: float = 0.6
    target_r: float = 2.0
    allow_puts: bool = True


def vwap_pullback(df: pd.DataFrame, p: VWAPParams = VWAPParams()) -> pd.DataFrame:
    n = len(df)
    vw = session_vwap(df).to_numpy()
    e9 = ind.ema(df["close"], 9).to_numpy()
    e21 = ind.ema(df["close"], 21).to_numpy()
    atr = ind.atr(df).to_numpy()
    clv = ind.close_location(df).to_numpy()
    o, h, l, c = (df[k].to_numpy() for k in ("open", "high", "low", "close"))
    hhmm = df.index.strftime("%H:%M")
    day = df.index.normalize()
    out_d = np.zeros(n, dtype=int)
    out_s = np.full(n, np.nan)
    out_t = np.full(n, np.nan)
    out_r = np.array([""] * n, dtype=object)
    k = p.trend_bars
    for t in range(k + 1, n):
        if hhmm[t] < p.start_time or hhmm[t] > p.last_entry or day[t - k - 1] != day[t]:
            continue
        if not (np.isfinite(vw[t]) and np.isfinite(atr[t]) and np.isfinite(e21[t])):
            continue
        prior = slice(t - k - 1, t - 1)
        up_trend = (c[prior] > vw[prior]).all() and e9[t] > e21[t]
        dn_trend = (c[prior] < vw[prior]).all() and e9[t] < e21[t]
        if up_trend and l[t] <= vw[t] + p.touch_atr * atr[t] and c[t] > vw[t] and c[t] > o[t] and clv[t] >= p.clv_min:
            stop = l[t] - 0.1 * atr[t]
            out_d[t], out_s[t] = 1, stop
            out_t[t] = c[t] + p.target_r * (c[t] - stop)
            out_r[t] = "VWAP pullback reclaim (up-trend day)"
        elif p.allow_puts and dn_trend and h[t] >= vw[t] - p.touch_atr * atr[t] and c[t] < vw[t] and c[t] < o[t] \
                and clv[t] <= 1 - p.clv_min:
            stop = h[t] + 0.1 * atr[t]
            out_d[t], out_s[t] = -1, stop
            out_t[t] = c[t] - p.target_r * (stop - c[t])
            out_r[t] = "VWAP pullback reject (down-trend day)"
    return _frame(df, out_d, out_s, out_t, out_r)


# ---------------------------------------------------------------------------
# P5 (as published) and N5 (in-play + VWAP exit) — 5-minute bars
# ---------------------------------------------------------------------------

def daily_atr_from_intraday(df: pd.DataFrame, n: int = 14) -> pd.Series:
    """ATR of daily bars built from intraday bars, known at the open (previous days only)."""
    day = df.index.normalize()
    d = df.groupby(day).agg(open=("open", "first"), high=("high", "max"), low=("low", "min"), close=("close", "last"))
    a = ind.atr(d, n).shift(1)
    return pd.Series(a.reindex(day).to_numpy(), index=df.index)


def orb_published(df: pd.DataFrame, rvol_min: float = 1.0, stop_atr_frac: float = 0.10) -> pd.DataFrame:
    """Zarattini-Barbon-Aziz: direction of the first 5-minute candle, entry at the
    next open, stop at 10% of the 14-day ATR from the entry area, exit at the close;
    only 'stocks in play' (opening volume >= its 14-day average)."""
    base = orb(df, ORBParams(rvol_min=rvol_min, target_r=1e9))
    datr = daily_atr_from_intraday(df).to_numpy()
    c = df["close"].to_numpy()
    d = base["dir"].to_numpy()
    stop = np.where(d != 0, c - d * stop_atr_frac * datr, np.nan)
    base["stop"] = stop
    base["target"] = np.nan
    base["reason"] = np.where(d != 0, "ORB (published: 10% ATR stop, EOD exit)", "")
    return base


def orb_inplay_vwap(df: pd.DataFrame, rvol_min: float = 2.0) -> pd.DataFrame:
    """N5: ORB only when opening volume >= 2x its 14-day average; stop at the
    opposite end of the opening range; exit when price closes back across the
    session VWAP (trend day failed) or at the end of the day."""
    base = orb(df, ORBParams(rvol_min=rvol_min, target_r=1e9))
    vw = session_vwap(df)
    c = df["close"]
    base["target"] = np.nan
    base["xl"] = (c < vw).to_numpy()
    base["xs"] = (c > vw).to_numpy()
    base["reason"] = np.where(base["dir"] != 0, "ORB in-play (RVOL>=2) + VWAP exit", "")
    return base
