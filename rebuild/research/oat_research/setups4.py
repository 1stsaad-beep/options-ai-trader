"""Round 4 setups, built for weekly (<= 7 day) long options.

Every function returns a frame aligned to the symbol's bars with columns
  dir (+1 call / -1 put / 0), stop, target (underlying levels or NaN -> engine ATR rule),
  score (ranking when several signals compete), reason,
  min_days (calendar days the contract must cover, NaN = engine default),
  xsched (scheduled exit at this bar's CLOSE, known in advance),
  xcond  (conditional exit decided at this close, filled at the NEXT open).
All series are causal: a signal at bar t uses data up to bar t's close.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import indicators as ind
from .engines_v2 import Ctx
from .wave_lab import candidates as wave_candidates
from .intraday import WDParams

ETFS = ("SPY", "QQQ", "IWM")


def frame(df, d, stop=np.nan, target=np.nan, score=0.0, reason="", min_days=np.nan, xsched=False, xcond=False):
    return pd.DataFrame({"dir": d, "stop": stop, "target": target, "score": score, "reason": reason,
                         "min_days": min_days, "xsched": xsched, "xcond": xcond}, index=df.index)


def trading_calendar(spy_index: pd.DatetimeIndex, extra_days: int = 60) -> pd.DatetimeIndex:
    """Exchange days = SPY history + future weekdays (fixes the round-3 'last row looks
    like a month end' bug: the current, unfinished month is no longer truncated)."""
    fut = pd.bdate_range(spy_index[-1] + pd.Timedelta(days=1), periods=extra_days)
    return spy_index.append(fut)


# ---------------------------------------------------------------- 1. ETF dip (S2 lineage)
def etf_dip(ctx: Ctx, vix: pd.Series | None, rsi2_max=10.0, vix_max=35.0) -> pd.DataFrame:
    df, c = ctx.df, ctx.df["close"]
    vix_ok = True if vix is None else (vix.reindex(df.index).ffill() < vix_max)
    up = (c > ctx.sma200) & (ctx.rsi2 < rsi2_max) & vix_ok
    return frame(df, np.where(up, 1, 0), score=np.where(up, rsi2_max - ctx.rsi2, 0.0),
                 reason=np.where(up, "ETF dip: RSI2 low above SMA200", ""),
                 xcond=((c > ind.sma(c, 5)) | (ctx.rsi2 > 70)).to_numpy())


def etf_rip_put(ctx: Ctx, rsi2_min=90.0) -> pd.DataFrame:
    df, c = ctx.df, ctx.df["close"]
    dn = (c < ctx.sma200) & (ctx.rsi2 > rsi2_min)
    return frame(df, np.where(dn, -1, 0), score=np.where(dn, ctx.rsi2 - rsi2_min, 0.0),
                 reason=np.where(dn, "bear rally: RSI2 high below SMA200", ""),
                 xcond=((c < ind.sma(c, 5)) | (ctx.rsi2 < 30)).to_numpy())


# ---------------------------------------------------------------- 2. VIX spike reversal
def vix_reversal(ctx: Ctx, vix: pd.Series, spike=1.20, drop=0.05, trend=False) -> pd.DataFrame:
    """Yesterday VIX closed >= spike x its 10-day average; today VIX falls >= drop and
    the ETF closes up on the day -> Call. Fear is unwinding."""
    df, c = ctx.df, ctx.df["close"]
    v = vix.reindex(df.index).ffill()
    ratio = v / ind.sma(v, 10)
    sig = (ratio.shift(1) >= spike) & (v <= v.shift(1) * (1 - drop)) & (c > df["open"])
    if trend:
        sig &= c > ctx.sma200
    return frame(df, np.where(sig, 1, 0), score=np.where(sig, ratio.shift(1).fillna(0), 0.0),
                 reason=np.where(sig, "VIX spike reversal", ""),
                 xcond=(v >= v.shift(1) * 1.10).to_numpy())


# ---------------------------------------------------------------- 3. gap and go (daily)
def gap_go(ctx: Ctx, gap_atr=0.25, clv_min=0.7) -> pd.DataFrame:
    df = ctx.df
    o, h, l, c = df["open"], df["high"], df["low"], df["close"]
    a = ctx.atr.shift(1)
    g_up = (o - h.shift(1)) / a
    g_dn = (l.shift(1) - o) / a
    up = (g_up >= gap_atr) & (c > o) & (ctx.clv >= clv_min) & (c > ctx.sma50) & (ctx.sma50 > ctx.sma200) & ctx.mkt_up
    dn = (g_dn >= gap_atr) & (c < o) & (ctx.clv <= 1 - clv_min) & (c < ctx.sma50) & (ctx.sma50 < ctx.sma200) & ctx.mkt_dn
    d = np.where(up, 1, np.where(dn, -1, 0))
    return frame(df, d, stop=np.where(up, l, np.where(dn, h, np.nan)),
                 score=np.where(up, g_up, np.where(dn, g_dn, 0.0)),
                 reason=np.where(up, "gap up held", np.where(dn, "gap down held", "")))


# ---------------------------------------------------------------- 4. turn of month
def tom(ctx: Ctx, cal: pd.DatetimeIndex, trend=True) -> pd.DataFrame:
    """Enter at the open of the last trading day of the month (signal at the close of
    the day before), exit at the close of the 3rd trading day of the new month."""
    df = ctx.df
    s = pd.Series(cal, index=cal)
    per = s.dt.to_period("M")
    from_end = per.groupby(per).cumcount(ascending=False)
    from_start = per.groupby(per).cumcount()
    sig = (from_end.reindex(df.index) == 1).fillna(False)
    if trend:
        sig &= ctx.mkt_up & (df["close"] > ctx.sma200)
    exit_day = (from_start.reindex(df.index) == 2).fillna(False)
    # contract must cover: entry day -> 3rd day of next month (<= 7 calendar days)
    nxt = pd.Series(cal[from_start.to_numpy() == 2], index=cal[from_start.to_numpy() == 2])
    cover = []
    for t in df.index:
        if sig.get(t, False):
            later = nxt[nxt.index > t]
            cover.append((later.index[0] - t).days if len(later) else 7)
        else:
            cover.append(np.nan)
    return frame(df, np.where(sig, 1, 0), score=0.0, reason=np.where(sig, "turn of month", ""),
                 min_days=cover, xsched=exit_day.to_numpy())


# ---------------------------------------------------------------- 5. waves
def weekly_trend(df: pd.DataFrame) -> pd.Series:
    """Higher timeframe for daily bars: price above its 30-week (150-day) average and the
    average rising over 4 weeks."""
    c = df["close"]
    m = ind.sma(c, 150)
    return (c > m) & (m > m.shift(20))


def daily_trend_for_intraday(intraday: pd.DataFrame, daily: pd.DataFrame) -> pd.Series:
    """Higher timeframe for hourly bars: previous completed day above SMA50 and SMA50 rising."""
    c = daily["close"]
    m = ind.sma(c, 50)
    up = ((c > m) & (m > m.shift(10))).astype(float)
    up.index = up.index.normalize()
    prev = up.shift(1)
    return pd.Series(prev.reindex(intraday.index.normalize()).to_numpy(), index=intraday.index)


def wave(df: pd.DataFrame, spy: pd.DataFrame | None, htf_up: pd.Series, tag="W2", p: WDParams = WDParams(),
         target_mode="s1") -> tuple[pd.DataFrame, pd.DataFrame]:
    """Wave 2->3 (tag W2) or B->C (tag B) thrust with the round-3 confirmations made
    mandatory: higher-timeframe trend, SMA200 side, price holding the wave-start anchored
    VWAP. Target: end of wave 1/A (`s1`, the near target) or the classic projection."""
    cand = wave_candidates(df, p, spy, htf_up)
    sig = frame(df, 0)
    if cand.empty:
        return sig, cand
    keep = cand[(cand.tag == tag) & cand.trend200 & cand.avwap_hold & (cand.htf == 1.0)]
    a = ind.atr(df).to_numpy()
    for r in keep.itertuples():
        i = r.t
        sig.iloc[i, sig.columns.get_loc("dir")] = r.dir
        sig.iloc[i, sig.columns.get_loc("stop")] = r.stop
        if target_mode == "classic":
            sig.iloc[i, sig.columns.get_loc("target")] = r.target
        sig.iloc[i, sig.columns.get_loc("score")] = r.leg1_atr
        sig.iloc[i, sig.columns.get_loc("reason")] = f"{tag} thrust (HTF+SMA200+AVWAP)"
    return sig, keep


# ---------------------------------------------------------------- 6. breakout (control)
def breakout20(ctx: Ctx) -> pd.DataFrame:
    df, c = ctx.df, ctx.df["close"]
    up = (c > df["high"].rolling(20).max().shift(1)) & (ctx.adx >= 20) & ctx.regime(1) & (ctx.clv >= 0.6)
    return frame(df, np.where(up, 1, 0), stop=np.where(up, c - 1.5 * ctx.atr, np.nan), score=np.where(up, ctx.adx, 0.0),
                 reason=np.where(up, "20-day breakout in trend", ""))


# ---------------------------------------------------------------- 7. hourly opening-range (first hour)
def orb_hour(df: pd.DataFrame, daily: pd.DataFrame, rvol_min=1.5) -> pd.DataFrame:
    """First 60-minute range on hourly bars. Signal at the close of the 10:30 or 11:30
    bar when it closes beyond the first-hour range, in the direction of the first hour's
    body, on a 'stock in play' (first-hour volume >= rvol_min x its 20-day average).
    Exit at the session close (scheduled)."""
    t = df.index
    day = t.normalize()
    first = df.groupby(day).head(1)
    fh = pd.DataFrame({"hi": first["high"].to_numpy(), "lo": first["low"].to_numpy(),
                       "body": np.sign(first["close"].to_numpy() - first["open"].to_numpy()),
                       "vol": first["volume"].to_numpy()}, index=first.index.normalize())
    fh["rvol"] = fh["vol"] / fh["vol"].rolling(20).mean().shift(1)
    m = fh.reindex(day)
    m.index = t
    hour = t.hour + t.minute / 60
    window = (hour >= 10.4) & (hour < 12.0)          # bars starting 10:30 and 11:30 (exchange time)
    up = window & (df["close"] > m["hi"]) & (m["body"] > 0) & (m["rvol"] >= rvol_min)
    dn = window & (df["close"] < m["lo"]) & (m["body"] < 0) & (m["rvol"] >= rvol_min)
    # one signal per day
    first_sig = (up | dn).groupby(day).cumsum() == 1
    up &= first_sig
    dn &= first_sig
    nxt_day = pd.Series(day, index=t).shift(-1)
    last_bar = (nxt_day != day).to_numpy()
    d = np.where(up, 1, np.where(dn, -1, 0))
    return frame(df, d, stop=np.where(up, m["lo"], np.where(dn, m["hi"], np.nan)),
                 score=np.where(up | dn, m["rvol"], 0.0), reason=np.where(up, "first-hour breakout", np.where(dn, "first-hour breakdown", "")),
                 xsched=last_bar)


# ---------------------------------------------------------------- 8. pre-FOMC drift (Lucca & Moench 2015)
def load_fomc(path="static/fomc.csv") -> pd.DatetimeIndex:
    return pd.DatetimeIndex(pd.read_csv(path, comment="#")["date"].pipe(pd.to_datetime))


def pre_fomc(ctx: Ctx, fomc: pd.DatetimeIndex, cal: pd.DatetimeIndex, trend=False) -> pd.DataFrame:
    """Signal at the close two sessions before the statement -> enter at the open of the
    day before, exit (scheduled) at the close of statement day. Calendar is public in advance."""
    df = ctx.df
    pos = {d: i for i, d in enumerate(cal)}
    sig_days, exit_days, cover = set(), set(), {}
    for f in fomc:
        if f in pos and pos[f] >= 2:
            s = cal[pos[f] - 2]
            sig_days.add(s)
            exit_days.add(f)
            cover[s] = (f - cal[pos[f] - 1]).days
    sig = pd.Series(df.index.isin(list(sig_days)), index=df.index)
    if trend:
        sig &= df["close"] > ctx.sma200
    return frame(df, np.where(sig, 1, 0), reason=np.where(sig, "pre-FOMC drift", ""),
                 min_days=[cover.get(t, np.nan) if sig.get(t, False) else np.nan for t in df.index],
                 xsched=df.index.isin(list(exit_days)))


# ---------------------------------------------------------------- 9. event gap drift (PEAD proxy)
def event_gap(ctx: Ctx, gap_atr=1.5, rvol=2.5, clv=0.5, trend=True) -> pd.DataFrame:
    """No earnings calendar is available, so earnings-type events are detected from the
    tape: an opening gap >= gap_atr x ATR on >= rvol x average volume that HOLDS into
    the close (close beyond the open, close-location in the gap's direction).
    Enter next open in the gap's direction (post-announcement drift)."""
    df = ctx.df
    o, h, l, c, v = df["open"], df["high"], df["low"], df["close"], df["volume"]
    a = ctx.atr.shift(1)
    g = (o - c.shift(1)) / a
    rv = v / ctx.vol20.shift(1)
    up = (g >= gap_atr) & (rv >= rvol) & (c >= o) & (ctx.clv >= clv)
    dn = (g <= -gap_atr) & (rv >= rvol) & (c <= o) & (ctx.clv <= 1 - clv)
    if trend:
        up &= ctx.mkt_up
        dn &= ctx.mkt_dn | (c < ctx.sma200)
    d = np.where(up, 1, np.where(dn, -1, 0))
    return frame(df, d, stop=np.where(up, l, np.where(dn, h, np.nan)), score=np.where(d != 0, g.abs(), 0.0),
                 reason=np.where(up, "event gap up held", np.where(dn, "event gap down held", "")))


# ---------------------------------------------------------------- 10. pre-holiday (Ariel 1990)
def pre_holiday(ctx: Ctx, cal: pd.DatetimeIndex) -> pd.DataFrame:
    """Sessions followed by a weekday market holiday (a gap of > 1 weekday to the next
    session). Signal two sessions before -> enter the open of the session before the
    holiday, exit at the close of the first session after it."""
    df = ctx.df
    cal = pd.DatetimeIndex(cal)
    nb = np.busday_count(cal[:-1].values.astype("datetime64[D]"), cal[1:].values.astype("datetime64[D]"))
    pre = [cal[i] for i in range(len(nb)) if nb[i] > 1]
    pos = {d: i for i, d in enumerate(cal)}
    sig_days, exit_days, cover = set(), set(), {}
    for p in pre:
        i = pos[p]
        if i >= 1 and i + 1 < len(cal):
            sig_days.add(cal[i - 1])
            exit_days.add(cal[i + 1])
            cover[cal[i - 1]] = (cal[i + 1] - cal[i]).days
    sig = pd.Series(df.index.isin(list(sig_days)), index=df.index) & ctx.mkt_up
    return frame(df, np.where(sig, 1, 0), reason=np.where(sig, "pre-holiday", ""),
                 min_days=[cover.get(t, np.nan) if sig.get(t, False) else np.nan for t in df.index],
                 xsched=df.index.isin(list(exit_days)))


# ================================================================ intraday helpers (5-minute source)
def resample(df5: pd.DataFrame, minutes: int) -> pd.DataFrame:
    """Session-anchored resample of 5-minute bars (bars start 09:30)."""
    if minutes == 5:
        return df5
    day = df5.index.normalize()
    off = (df5.index - day - pd.Timedelta(hours=9, minutes=30)) // pd.Timedelta(minutes=minutes)
    key = day + pd.Timedelta(hours=9, minutes=30) + off * pd.Timedelta(minutes=minutes)
    g = df5.groupby(key)
    out = pd.DataFrame({"open": g["open"].first(), "high": g["high"].max(), "low": g["low"].min(),
                        "close": g["close"].last(), "volume": g["volume"].sum()})
    out.index.name = "date"
    return out


def last_bar_of_day(df: pd.DataFrame) -> np.ndarray:
    day = df.index.normalize()
    return (pd.Series(day, index=df.index).shift(-1) != day).to_numpy()


def pre_fomc_intraday(df: pd.DataFrame, fomc: pd.DatetimeIndex, exit_hhmm=(13, 55), enter_hhmm=(15, 50)) -> pd.DataFrame:
    """Lucca-Moench window on intraday bars: enter near the close the day BEFORE the
    statement (signal on the bar that starts at enter_hhmm - bar, filled next bar open),
    exit (scheduled) at the close of the bar ending at exit_hhmm on statement day, i.e.
    before the 14:00 announcement."""
    t = df.index
    day = t.normalize()
    days = pd.DatetimeIndex(sorted(set(day)))
    pos = {d: i for i, d in enumerate(days)}
    pre = {days[pos[f] - 1] for f in fomc if f in pos and pos[f] >= 1}
    minutes = t.hour * 60 + t.minute
    step = int((t[1] - t[0]).total_seconds() // 60) if len(t) > 1 else 5
    sig = day.isin(list(pre)) & (minutes == enter_hhmm[0] * 60 + enter_hhmm[1] - step)
    ex = day.isin(list(fomc)) & (minutes + step == exit_hhmm[0] * 60 + exit_hhmm[1] + (5 if step == 5 else 0))
    return frame(df, np.where(sig, 1, 0), reason=np.where(sig, "pre-FOMC (intraday)", ""), min_days=0, xsched=ex)


def orb5(df: pd.DataFrame, rvol_min=2.0, atr_stop=0.10, daily: pd.DataFrame | None = None) -> pd.DataFrame:
    """Zarattini-Barbon-Aziz 5-minute ORB, restricted to 'stocks in play': first 5-minute
    bar volume >= rvol_min x its 14-day average. Direction = first bar's body. Signal on the
    first bar (entry at the 09:35 open), stop = 10% of daily ATR beyond entry... implemented
    as the opposite end of the opening bar or atr_stop x daily ATR, whichever is nearer.
    Exit at the session close (scheduled)."""
    t = df.index
    day = t.normalize()
    is_first = pd.Series(day, index=t).shift(1) != day
    first = df[is_first.to_numpy()]
    vol_avg = first["volume"].rolling(14).mean().shift(1)
    rv = (first["volume"] / vol_avg).reindex(t).fillna(0)
    body = np.sign(df["close"] - df["open"])
    up = is_first & (rv >= rvol_min) & (body > 0)
    dn = is_first & (rv >= rvol_min) & (body < 0)
    stop_up, stop_dn = df["low"], df["high"]
    if daily is not None:
        from .indicators import atr as _atr
        da = _atr(daily).shift(1)
        da.index = da.index.normalize()
        a = pd.Series(da.reindex(day).to_numpy(), index=t)
        stop_up = np.maximum(df["low"], df["close"] - atr_stop * a)
        stop_dn = np.minimum(df["high"], df["close"] + atr_stop * a)
    d = np.where(up, 1, np.where(dn, -1, 0))
    return frame(df, d, stop=np.where(up, stop_up, np.where(dn, stop_dn, np.nan)), score=np.where(d != 0, rv, 0.0),
                 reason=np.where(up, "ORB5 long (in play)", np.where(dn, "ORB5 short (in play)", "")),
                 min_days=0, xsched=last_bar_of_day(df))


# ---------------------------------------------------------------- 11. wave-2 / wave-B exhaustion (round-4 innovation)
def wave_exhaustion(ctx: Ctx, htf_up: pd.Series | None = None, swing_atr=1.5, leg_min_atr=3.0,
                    retr_lo=0.382, retr_hi=0.786, rsi2_buy=10.0, rsi2_sell=90.0, require_bos=True,
                    allow_puts=True, control=False) -> pd.DataFrame:
    """Enter at the END of a wave-2 (or wave-B) correction instead of after the thrust.

    Causal state at bar t (confirmed zig-zag pivots only):
      wave 1 = last confirmed swing low s0 -> swing high s1 (>= leg_min_atr ATR) that broke
               the previous swing high (structure break, `require_bos`),
      wave 2 = price now retracing: retracement of wave 1 at today's low in [retr_lo, retr_hi]
               and the close still above s0 and above the anchored VWAP from s0,
      trigger = short-term exhaustion: RSI(2) < rsi2_buy at the (15:50) close.
    Higher-timeframe trend must agree (htf_up), symbol above SMA200.
    Mirror for Puts (wave B rally inside a down-trend, RSI(2) > rsi2_sell).
    Target = 0.75 ATR (engine) ; invalidation stop = wave start s0 (beyond it the count is wrong).
    `control=True` drops the wave conditions (keeps trend + RSI2) to measure what the
    wave structure adds."""
    from .intraday import _ZigZagATR
    df = ctx.df
    n = len(df)
    h, l, c, v = (df[k].to_numpy() for k in ("high", "low", "close", "volume"))
    tp = (h + l + c) / 3
    a = ctx.atr.to_numpy()
    rsi2 = ctx.rsi2.to_numpy()
    s200 = ctx.sma200.to_numpy()
    htf = htf_up.reindex(df.index).fillna(False).to_numpy() if htf_up is not None else np.ones(n, bool)
    htf_dn = (~htf_up.reindex(df.index).fillna(True)).to_numpy() if htf_up is not None else np.ones(n, bool)
    piv = ind.pivots(df, 3, 2)
    zz = _ZigZagATR(a, swing_atr)
    cv = np.cumsum(tp * v)
    cvol = np.cumsum(v)
    d = np.zeros(n, int)
    stop = np.full(n, np.nan)
    score = np.zeros(n)
    reason = np.array([""] * n, dtype=object)
    j = 0
    for t in range(n):
        while j < len(piv) and piv[j][1] <= t:
            zz.add(piv[j]); j += 1
        if not np.isfinite(a[t]) or not np.isfinite(s200[t]) or not np.isfinite(rsi2[t]):
            continue
        if control:
            if rsi2[t] < rsi2_buy and c[t] > s200[t] and htf[t]:
                d[t] = 1; reason[t] = "control: trend + RSI2"
            elif allow_puts and rsi2[t] > rsi2_sell and c[t] < s200[t] and htf_dn[t]:
                d[t] = -1; reason[t] = "control: trend + RSI2"
            continue
        if len(zz.out) < 3:
            continue
        s_last = zz.out[-1]
        s_prev = zz.out[-2]
        for direction in (1, -1):
            if direction == 1:
                # last confirmed pivot is a HIGH (s1), before it a LOW (s0)
                if not s_last[3] or s_prev[3]:
                    continue
                s0, s1 = s_prev, s_last
                if not (rsi2[t] < rsi2_buy and c[t] > s200[t] and htf[t]):
                    continue
                leg = s1[2] - s0[2]
                retr = (s1[2] - l[t]) / leg if leg > 0 else 9
                older = [q for q in zz.out[:-2] if q[3]]
                bos = bool(older) and s1[2] > older[-1][2]
                if t <= s1[0]:
                    continue
                av = (cv[t] - cv[s0[0] - 1]) / (cvol[t] - cvol[s0[0] - 1]) if s0[0] > 0 else np.nan
                ok = leg >= leg_min_atr * a[t] and retr_lo <= retr <= retr_hi and c[t] > s0[2] and (bos or not require_bos)
                ok &= np.isfinite(av) and c[t] > av
            else:
                if not allow_puts or s_last[3] or not s_prev[3]:
                    continue
                s0, s1 = s_prev, s_last
                if not (rsi2[t] > rsi2_sell and c[t] < s200[t] and htf_dn[t]):
                    continue
                leg = s0[2] - s1[2]
                retr = (h[t] - s1[2]) / leg if leg > 0 else 9
                older = [q for q in zz.out[:-2] if not q[3]]
                bos = bool(older) and s1[2] < older[-1][2]
                if t <= s1[0]:
                    continue
                av = (cv[t] - cv[s0[0] - 1]) / (cvol[t] - cvol[s0[0] - 1]) if s0[0] > 0 else np.nan
                ok = leg >= leg_min_atr * a[t] and retr_lo <= retr <= retr_hi and c[t] < s0[2] and (bos or not require_bos)
                ok &= np.isfinite(av) and c[t] < av
            if ok:
                d[t] = direction
                stop[t] = s0[2] - direction * 0.1 * a[t]
                score[t] = leg / a[t]
                reason[t] = "wave-2 exhaustion (RSI2)" if direction == 1 else "wave-B exhaustion (RSI2)"
                break
    return frame(df, d, stop=stop, score=score, reason=reason)


# ---------------------------------------------------------------- 12. noise-area intraday momentum (Zarattini, Aziz & Barbon 2024)
def noise_momentum(df5: pd.DataFrame, lookback=14, vm=1.0, check_every=30, last_entry="15:00") -> pd.DataFrame:
    """5-minute bars. sigma(t) = average over the last `lookback` sessions of |close(t)/open - 1|
    at the same time of day. Bounds: UB = max(open, prev close) * (1 + vm*sigma),
    LB = min(open, prev close) * (1 - vm*sigma). Decisions only on bars that END on a
    :00/:30 mark. Long when close > UB, short when close < LB; exit (next bar open) when the
    close crosses back through max(UB, session VWAP) / min(LB, VWAP); scheduled exit at the
    session's last bar."""
    t = df5.index
    day = t.normalize()
    tod = (t - day)
    o_day = df5.groupby(day)["open"].transform("first")
    c = df5["close"]
    move = (c / o_day - 1).abs()
    piv = pd.DataFrame({"day": day, "tod": tod, "m": move.to_numpy()}).pivot_table(index="day", columns="tod", values="m")
    sig_tab = piv.rolling(lookback, min_periods=lookback).mean().shift(1)
    sigma = sig_tab.stack().reindex(pd.MultiIndex.from_arrays([day, tod])).to_numpy()
    daily_close = df5.groupby(day)["close"].last()
    prev_close = daily_close.shift(1).reindex(day).to_numpy()
    o = o_day.to_numpy()
    ub = np.maximum(o, prev_close) * (1 + vm * sigma)
    lb = np.minimum(o, prev_close) * (1 - vm * sigma)
    tp = (df5["high"] + df5["low"] + df5["close"]) / 3
    pv = (tp * df5["volume"]).groupby(day).cumsum()
    vv = df5["volume"].groupby(day).cumsum()
    vwap = (pv / vv).to_numpy()
    end_min = (t.hour * 60 + t.minute + 5)
    check = (end_min % check_every == 0)
    lh, lm = map(int, last_entry.split(":"))
    can_enter = check & (end_min <= lh * 60 + lm) & (end_min > 9 * 60 + 30 + 5)
    cc = c.to_numpy()
    up = can_enter & (cc > ub)
    dn = can_enter & (cc < lb)
    # first signal of each day only (one round trip per day)
    first = pd.Series(up | dn, index=t).groupby(day).cumsum().to_numpy() == 1
    up &= first
    dn &= first
    exit_long = check & (cc < np.fmax(ub, vwap))
    exit_short = check & (cc > np.fmin(lb, vwap))
    d = np.where(up, 1, np.where(dn, -1, 0))
    side = pd.Series(np.where(d != 0, d, np.nan), index=t).groupby(day).ffill().fillna(0).to_numpy()
    xcond = ((side > 0) & exit_long) | ((side < 0) & exit_short)
    return frame(df5, d, score=0.0, reason=np.where(up, "noise-area breakout up", np.where(dn, "noise-area breakout down", "")),
                 min_days=0, xsched=last_bar_of_day(df5), xcond=xcond)
