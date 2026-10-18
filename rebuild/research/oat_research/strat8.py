"""Round 8: the three strategies of 'Options_AI_Trader_Detailed_Research_AR.pdf', literal rules.

Signals are placed on 5-minute bars (index = bar start). A signal on the bar that CLOSES at the
decision time is filled at the next bar's open (= the decision time). Target / stop are absolute
underlying levels computed at the decision from A0 (the ATR the rule names); the engine checks them
on completed 5-minute closes and exits at the next bar open. Time exits are scheduled at the close of
the bar that ends at the rule's exit time.

Proxy (documented): no earnings calendar is available. For A, an 'earnings event session' is a
session that gaps 0.5-1.5 x A0 on volume >= 2.0 x its 20-day average, with no other such event in
the previous 40 sessions (quarterly spacing). B and C skip sessions inside the earnings proxy
window (event day and the 2 sessions after) via strat6.event_block.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import indicators as ind
from .setups4 import frame
from .strat6 import event_block


def day_table(df5: pd.DataFrame) -> pd.DataFrame:
    """One row per session: open, close/vwap/cum-volume at every 5-minute END time."""
    t = df5.index
    day = t.normalize()
    end_min = (t.hour * 60 + t.minute + 5).to_numpy()
    tp = ((df5["high"] + df5["low"] + df5["close"]) / 3).to_numpy()
    v = df5["volume"].to_numpy()
    d = pd.DataFrame({"day": day, "end": end_min, "c": df5["close"].to_numpy(), "o": df5["open"].to_numpy(),
                      "h": df5["high"].to_numpy(), "l": df5["low"].to_numpy(), "v": v, "pv": tp * v})
    d["cv"] = d.groupby("day")["v"].cumsum()
    d["cpv"] = d.groupby("day")["pv"].cumsum()
    d["vwap"] = d["cpv"] / d["cv"]
    return d


def at(d: pd.DataFrame, hhmm: str, col: str) -> pd.Series:
    h, m = map(int, hhmm.split(":"))
    x = d[d.end == h * 60 + m].set_index("day")[col]
    return x


def bar_index(df5: pd.DataFrame, day: pd.Timestamp, end_hhmm: str):
    """Integer position of the 5-min bar that ENDS at hh:mm on `day` (or None)."""
    h, m = map(int, end_hhmm.split(":"))
    ts = day + pd.Timedelta(hours=h, minutes=m - 5)
    return ts


def _empty(df5):
    f = frame(df5, 0)
    f["xsched"] = False
    return f


# ---------------------------------------------------------------- A: earnings-gap acceptance
def strat_a(df5, daily, spy_daily, vix=None, gap_lo=0.5, gap_hi=1.5, clv_min=0.75, vol_mult=1.5, ev_vol=2.0, spacing=40,
            hold_band=0.25, tgt=1.0, stp=0.5):
    f = _empty(df5)
    c, o, h, l, v = (daily[k] for k in ("close", "open", "high", "low", "volume"))
    a14 = ind.atr(daily)
    A0 = a14.shift(1)                       # ATR from the session before the event session
    gap = (o - c.shift(1)) / A0
    vavg = v.rolling(20).mean().shift(1)
    proxy = (gap.abs() >= 0.5) & (v >= ev_vol * vavg)
    spy_ok = (spy_daily["close"] > ind.sma(spy_daily["close"], 200)).reindex(daily.index).ffill().shift(1).fillna(False)
    clv = (c - l) / (h - l)
    days = daily.index
    last_ev = -10**9
    d5 = day_table(df5)
    c935 = at(d5, "09:35", "c")
    idx = {t: i for i, t in enumerate(df5.index)}
    for i in range(len(days)):
        if not (np.isfinite(gap.iloc[i]) and bool(proxy.iloc[i])):
            continue
        spaced = i - last_ev >= spacing
        last_ev = i
        if not spaced:
            continue
        g = gap.iloc[i]
        ok = (gap_lo <= g <= gap_hi) and c.iloc[i] >= o.iloc[i] and h.iloc[i] > l.iloc[i] and clv.iloc[i] >= clv_min \
            and v.iloc[i] >= vol_mult * vavg.iloc[i] and bool(spy_ok.iloc[i])
        if not ok or i + 1 >= len(days):
            continue
        nxt = days[i + 1].normalize()
        if nxt not in c935.index or (nxt - days[i].normalize()).days > 4:
            continue
        a0 = A0.iloc[i]
        if abs(c935.loc[nxt] - c.iloc[i]) > hold_band * a0:
            continue
        sig_bar = nxt + pd.Timedelta(hours=9, minutes=30)          # bar 09:30-09:35, fill at 09:35 open
        if sig_bar not in idx:
            continue
        j = idx[sig_bar]
        s0 = df5["close"].iloc[j]
        f.iloc[j, f.columns.get_loc("dir")] = 1
        f.iloc[j, f.columns.get_loc("target")] = s0 + tgt * a0
        f.iloc[j, f.columns.get_loc("stop")] = s0 - stp * a0
        f.iloc[j, f.columns.get_loc("reason")] = "A earnings-gap acceptance"
        # time exit: the session after entry at 09:35 -> bar 09:30 of that session
        if i + 2 < len(days):
            ex = days[i + 2].normalize() + pd.Timedelta(hours=9, minutes=30)
            if ex in idx:
                f.iloc[idx[ex], f.columns.get_loc("xsched")] = True
    return f


# ---------------------------------------------------------------- B: bear-market broad selling put
def strat_b(df5, daily, spy_daily, sectors5: dict, vix=None, drop=0.5, vol_mult=1.5, breadth_min=7, tgt=0.6, stp=0.35, gap_max=0.5,
            ext=1.5, regime=True):
    f = _empty(df5)
    d5 = day_table(df5)
    o = d5[d5.end == 9 * 60 + 35].set_index("day")["o"]
    c1030, c1230 = at(d5, "10:30", "c"), at(d5, "12:30", "c")
    cv1030, cv1230 = at(d5, "10:30", "cv"), at(d5, "12:30", "cv")
    wv = (cv1230 - cv1030)
    wv_avg = wv.rolling(20).mean().shift(1)
    dc = daily["close"]
    A0 = ind.atr(daily).shift(1); A0.index = A0.index.normalize()
    pc = dc.shift(1); pc.index = pc.index.normalize()
    s200 = (dc < ind.sma(dc, 200)).shift(1); s200.index = s200.index.normalize()
    sc = spy_daily["close"]; m50 = ind.sma(sc, 50)
    spy_reg = ((sc < ind.sma(sc, 200)) & (m50 < m50.shift(20))).shift(1); spy_reg.index = spy_reg.index.normalize()
    # breadth
    br = None
    for s, x in sectors5.items():
        t5 = day_table(x)
        weak = (at(t5, "12:30", "c") < at(t5, "12:30", "vwap")) & (at(t5, "12:30", "c") < at(t5, "10:30", "c"))
        br = weak.astype(int) if br is None else br.add(weak.astype(int), fill_value=0)
    blk = pd.Series(event_block(daily, vix, daily), index=daily.index.normalize())
    idx = {t: i for i, t in enumerate(df5.index)}
    for day in c1230.index:
        try:
            a0 = A0.loc[day]; p = pc.loc[day]
        except KeyError:
            continue
        if not (np.isfinite(a0) and np.isfinite(p)) or day not in o.index or day not in c1030.index:
            continue
        ok = (not regime or (bool(spy_reg.get(day, False)) and bool(s200.get(day, False)))) and not bool(blk.get(day, False))
        ok = ok and abs(o.loc[day] - p) <= gap_max * a0 and (c1230.loc[day] - c1030.loc[day]) <= -drop * a0
        ok = ok and np.isfinite(wv_avg.get(day, np.nan)) and wv.loc[day] >= vol_mult * wv_avg.loc[day]
        ok = ok and br is not None and br.get(day, 0) >= breadth_min and (c1230.loc[day] - p) >= -ext * a0
        if not ok:
            continue
        sb = day + pd.Timedelta(hours=12, minutes=25)
        xb = day + pd.Timedelta(hours=15, minutes=25)
        if sb not in idx or xb not in idx:
            continue
        j = idx[sb]; s0 = c1230.loc[day]
        f.iloc[j, f.columns.get_loc("dir")] = -1
        f.iloc[j, f.columns.get_loc("target")] = s0 - tgt * a0
        f.iloc[j, f.columns.get_loc("stop")] = s0 + stp * a0
        f.iloc[j, f.columns.get_loc("reason")] = "B broad selling put"
        f.iloc[idx[xb], f.columns.get_loc("xsched")] = True
    return f


# ---------------------------------------------------------------- C: laggard catch-up call
def strat_c(df5, daily, ref5, ref_daily, vix=None, z_max=-2.0, lag_atr=0.9, ref_up=0.4, confirm=0.10, tgt=0.75, stp=0.35, gap_max=0.5,
            lookback=60):
    f = _empty(df5)
    d5, r5 = day_table(df5), day_table(ref5)
    so = d5[d5.end == 9 * 60 + 35].set_index("day")["o"]; ro = r5[r5.end == 9 * 60 + 35].set_index("day")["o"]
    s1130, s1200 = at(d5, "11:30", "c"), at(d5, "12:00", "c")
    r1130, r1200 = at(r5, "11:30", "c"), at(r5, "12:00", "c")
    dc, rc = daily["close"], ref_daily["close"].reindex(daily.index).ffill()
    lr_s, lr_r = np.log(dc).diff(), np.log(rc).diff()
    A0 = ind.atr(daily).shift(1); A0.index = A0.index.normalize()
    AQ = ind.atr(ref_daily).shift(1); AQ.index = AQ.index.normalize()
    pc = dc.shift(1); pc.index = pc.index.normalize()
    up200 = (dc > ind.sma(dc, 200)).shift(1); up200.index = up200.index.normalize()
    q50 = (rc > ind.sma(rc, 50)).shift(1); q50.index = q50.index.normalize()
    blk = pd.Series(event_block(daily, vix, daily), index=daily.index.normalize())
    morning_s = np.log(s1130 / so); morning_r = np.log(r1130 / ro)
    m = pd.DataFrame({"s": morning_s, "r": morning_r}).dropna()
    lrs = lr_s.copy(); lrs.index = lrs.index.normalize(); lrr = lr_r.copy(); lrr.index = lrr.index.normalize()
    idx = {t: i for i, t in enumerate(df5.index)}
    days = list(m.index)
    for k, day in enumerate(days):
        if k < lookback:
            continue
        try:
            a0, aq, p = A0.loc[day], AQ.loc[day], pc.loc[day]
        except KeyError:
            continue
        if not (bool(up200.get(day, False)) and bool(q50.get(day, False))) or bool(blk.get(day, False)):
            continue
        # beta from the last 60 COMPLETED daily log returns
        hist_d = lrs.loc[:day - pd.Timedelta(days=1)].tail(lookback); hist_q = lrr.reindex(hist_d.index)
        ok = hist_d.notna() & hist_q.notna()
        if ok.sum() < 40:
            continue
        beta = float(np.clip(np.polyfit(hist_q[ok], hist_d[ok], 1)[0], 0.25, 2.5))
        prev = m.iloc[k - lookback:k]
        res = prev["s"] - beta * prev["r"]
        mu, sd = res.mean(), res.std(ddof=1)
        if not sd > 0:
            continue
        if abs(so.loc[day] - p) > gap_max * a0 or (r1130.loc[day] - ro.loc[day]) < ref_up * aq:
            continue
        z = ((m.loc[day, "s"] - beta * m.loc[day, "r"]) - mu) / sd
        fair = so.loc[day] * np.exp(beta * m.loc[day, "r"] + mu)
        if z > z_max or (fair - s1130.loc[day]) < lag_atr * a0:
            continue
        if day not in s1200.index or day not in r1200.index:
            continue
        if (s1200.loc[day] - s1130.loc[day]) < confirm * a0 or (r1200.loc[day] - r1130.loc[day]) < -0.10 * aq:
            continue
        sb = day + pd.Timedelta(hours=11, minutes=55); xb = day + pd.Timedelta(hours=15, minutes=45)
        if sb not in idx or xb not in idx:
            continue
        j = idx[sb]; s0 = s1200.loc[day]
        f.iloc[j, f.columns.get_loc("dir")] = 1
        f.iloc[j, f.columns.get_loc("target")] = s0 + tgt * a0
        f.iloc[j, f.columns.get_loc("stop")] = s0 - stp * a0
        f.iloc[j, f.columns.get_loc("reason")] = "C laggard catch-up"
        f.iloc[idx[xb], f.columns.get_loc("xsched")] = True
    return f
