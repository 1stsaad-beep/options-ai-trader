"""Round 12 — intraday feature library + big-move labels (±5 %) for combination discovery.

For one symbol and one frame (15 / 30 / 60 minutes) build, for every bar (value known at the bar CLOSE):
  * ~60 binary technical features in families: trend, momentum, volatility, volume, price structure, context
  * labels: first touch of +5 % / -5 % (from the bar close) up to the close of the NEXT session (and same-session variant)
All features are causal (use data up to and including the signal bar; daily features use the PREVIOUS session).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from oat_research import indicators as ind, setups4 as S4

MOVE = 0.05


# ------------------------------------------------------------------ helpers
def daily_from_m5(m5: pd.DataFrame) -> pd.DataFrame:
    g = m5.groupby(m5.index.normalize())
    return pd.DataFrame({"open": g["open"].first(), "high": g["high"].max(), "low": g["low"].min(),
                         "close": g["close"].last(), "volume": g["volume"].sum()})


def _di(df, n=14):
    up = df["high"].diff(); dn = -df["low"].diff()
    pdm = up.where((up > dn) & (up > 0), 0.0); mdm = dn.where((dn > up) & (dn > 0), 0.0)
    tr = ind.wilder(ind.true_range(df), n)
    return 100 * ind.wilder(pdm, n) / tr, 100 * ind.wilder(mdm, n) / tr


def labels(b: pd.DataFrame, K: int) -> pd.DataFrame:
    """first-touch ±5 % from the close of bar i, scanning bars i+1 .. end (end = last bar of NEXT session / same session)."""
    c = b["close"].to_numpy(); hi = b["high"].to_numpy(); lo = b["low"].to_numpy(); n = len(c)
    day = b.index.normalize(); pos = np.arange(n)
    last = pd.Series(pos, index=b.index).groupby(day).transform("max").to_numpy()
    nxt_last = np.where(last + 1 < n, last[np.minimum(last + 1, n - 1)], n - 1)
    out = {}
    for name, end in (("next", nxt_last), ("same", last)):
        fu = np.full(n, 10 ** 6); fd = np.full(n, 10 ** 6)
        for k in range(1, K + 1):
            j = pos + k; ok = (j <= end) & (j < n); jj = np.minimum(j, n - 1)
            u = ok & (hi[jj] >= c * (1 + MOVE)) & (fu == 10 ** 6); d = ok & (lo[jj] <= c * (1 - MOVE)) & (fd == 10 ** 6)
            fu[u] = k; fd[d] = k
        out[f"up_{name}"] = (fu < fd)
        out[f"dn_{name}"] = (fd < fu)
        out[f"ret_{name}"] = c[end] / c - 1
    out["valid_next"] = nxt_last > last                      # a next session exists
    return pd.DataFrame(out, index=b.index)


def features(m5: pd.DataFrame, spy5: pd.DataFrame, F: int, vix: pd.Series | None = None) -> pd.DataFrame:
    b = S4.resample(m5, F)
    c, h, l, o, v = b["close"], b["high"], b["low"], b["open"], b["volume"]
    day = b.index.normalize()
    tod = np.asarray((b.index - day) / pd.Timedelta(minutes=1)).astype(int)          # bar start minutes since midnight
    bar_end = tod + F
    f = {}
    # ---------------- trend
    e9, e20, e50 = ind.ema(c, 9), ind.ema(c, 20), ind.ema(c, 50)
    pv = ((h + l + c) / 3 * v).groupby(day).cumsum() / v.groupby(day).cumsum().replace(0, np.nan)
    f["t_above_ema20"] = c > e20; f["t_below_ema20"] = c < e20
    f["t_stack_up"] = (e9 > e20) & (e20 > e50); f["t_stack_dn"] = (e9 < e20) & (e20 < e50)
    f["t_above_vwap"] = c > pv; f["t_below_vwap"] = c < pv
    f["t_cross_vwap_up"] = (c > pv) & (c.shift() <= pv.shift()) & (day == day.to_series().shift().to_numpy())
    f["t_cross_vwap_dn"] = (c < pv) & (c.shift() >= pv.shift()) & (day == day.to_series().shift().to_numpy())
    adx = ind.adx(b); pdi, mdi = _di(b)
    f["t_adx_strong_up"] = (adx > 25) & (pdi > mdi); f["t_adx_strong_dn"] = (adx > 25) & (mdi > pdi)
    f["t_adx_low"] = adx < 15
    # daily (previous session) trend
    D = daily_from_m5(m5)
    dsma50 = ind.sma(D["close"], 50); dsma20 = ind.sma(D["close"], 20)
    prev = lambda s: s.shift(1).reindex(day).to_numpy()
    f["t_daily_up"] = prev(D["close"] > dsma50) == True
    f["t_daily_dn"] = prev(D["close"] < dsma50) == True
    f["t_daily_above20"] = prev(D["close"] > dsma20) == True
    # ---------------- momentum
    r = ind.rsi(c, 14); mh = ind.macd_hist(c)
    f["m_rsi_os"] = r < 30; f["m_rsi_ob"] = r > 70
    f["m_rsi_x50_up"] = (r > 50) & (r.shift() <= 50); f["m_rsi_x50_dn"] = (r < 50) & (r.shift() >= 50)
    f["m_rsi_hook_up"] = (r.shift() < 30) & (r >= 30); f["m_rsi_hook_dn"] = (r.shift() > 70) & (r <= 70)
    f["m_macd_x_up"] = (mh > 0) & (mh.shift() <= 0); f["m_macd_x_dn"] = (mh < 0) & (mh.shift() >= 0)
    f["m_macd_rising"] = (mh > mh.shift()) & (mh.shift() > mh.shift(2)); f["m_macd_falling"] = (mh < mh.shift()) & (mh.shift() < mh.shift(2))
    k = ind.stoch_k(b); dd = k.rolling(3).mean()
    f["m_stoch_x_up_os"] = (k > dd) & (k.shift() <= dd.shift()) & (k < 25)
    f["m_stoch_x_dn_ob"] = (k < dd) & (k.shift() >= dd.shift()) & (k > 75)
    sig = np.log(c).diff().rolling(130, min_periods=60).std()
    z4 = (c / c.shift(4) - 1) / (sig * 2)
    f["m_thrust_up"] = z4 > 2; f["m_thrust_dn"] = z4 < -2
    lo20 = l.rolling(20).min(); hi20 = h.rolling(20).max(); rmin = r.rolling(20).min().shift(); rmax = r.rolling(20).max().shift()
    f["m_bull_div"] = (l <= lo20) & (r > rmin + 5) & (r < 40)
    f["m_bear_div"] = (h >= hi20) & (r < rmax - 5) & (r > 60)
    # daily momentum (previous session)
    dr = ind.rsi(D["close"], 14)
    f["m_daily_rsi_os"] = prev(dr < 30) == True; f["m_daily_rsi_ob"] = prev(dr > 70) == True
    droc = D["close"] / D["close"].shift(20) - 1
    f["m_daily_capit"] = prev(droc < -0.15) == True; f["m_daily_strong"] = prev(droc > 0.20) == True
    # ---------------- volatility
    bbw = ind.bb_width(c, 20)
    q20 = bbw.rolling(260, min_periods=120).quantile(0.2).shift(); q80 = bbw.rolling(260, min_periods=120).quantile(0.8).shift()
    f["v_bb_squeeze"] = bbw <= q20; f["v_bb_expand"] = bbw >= q80
    f["v_bb_expand_new"] = (bbw >= q80) & (bbw.shift(3) <= q20.shift(3))
    atr = ind.atr(b, 20); mid = ind.sma(c, 20); sd = c.rolling(20).std(ddof=0)
    ttm = (mid + 2 * sd < mid + 1.5 * atr) & (mid - 2 * sd > mid - 1.5 * atr)
    f["v_ttm_squeeze"] = ttm; f["v_ttm_fire"] = (~ttm) & ttm.shift(1, fill_value=False) & ttm.shift(2, fill_value=False)
    rng = h - l
    f["v_nr7"] = rng <= rng.rolling(7).min(); f["v_inside"] = (h <= h.shift()) & (l >= l.shift())
    f["v_wide_bar"] = rng > 2.5 * atr.shift()
    dtr = ind.atr(D, 14) / D["close"]
    f["v_daily_atr_high"] = prev(dtr > dtr.rolling(120, min_periods=60).quantile(0.8)) == True
    f["v_daily_atr_low"] = prev(dtr < dtr.rolling(120, min_periods=60).quantile(0.2)) == True
    drng = D["high"] - D["low"]
    f["v_daily_nr7"] = prev(drng <= drng.rolling(7).min()) == True
    f["v_daily_inside"] = prev((D["high"] <= D["high"].shift()) & (D["low"] >= D["low"].shift())) == True
    # ---------------- volume
    key = tod
    vt = pd.DataFrame({"v": v.to_numpy(), "key": key, "day": day}, index=b.index)
    avg = vt.groupby("key")["v"].transform(lambda s: s.rolling(20, min_periods=10).mean().shift())
    rv = v / avg.replace(0, np.nan)
    f["vo_relvol2"] = rv > 2; f["vo_relvol4"] = rv > 4; f["vo_relvol_low"] = rv < 0.6
    cumv = v.groupby(day).cumsum()
    vt["cumv"] = cumv.to_numpy()
    cavg = vt.groupby("key")["cumv"].transform(lambda s: s.rolling(20, min_periods=10).mean().shift())
    drv = cumv / cavg.replace(0, np.nan)
    f["vo_in_play2"] = drv > 2; f["vo_in_play4"] = drv > 4
    ob = ind.obv(b)
    f["vo_obv_hi"] = ob >= ob.rolling(50).max(); f["vo_obv_lo"] = ob <= ob.rolling(50).min()
    # ---------------- price structure
    f["p_break_hi20"] = c > hi20.shift(); f["p_break_lo20"] = c < lo20.shift()
    hi60 = h.rolling(60).max().shift(); lo60 = l.rolling(60).min().shift()
    f["p_break_hi60"] = c > hi60; f["p_break_lo60"] = c < lo60
    pdh = prev(D["high"]); pdl = prev(D["low"]); pdc = prev(D["close"])
    f["p_above_pdh"] = c.to_numpy() > pdh; f["p_below_pdl"] = c.to_numpy() < pdl
    dopen = o.groupby(day).transform("first")
    gap = dopen.to_numpy() / pdc - 1
    f["p_gap_up2"] = gap > 0.02; f["p_gap_dn2"] = gap < -0.02; f["p_gap_up5"] = gap > 0.05; f["p_gap_dn5"] = gap < -0.05
    m5d = m5.index.normalize(); m5t = (m5.index - m5d) / pd.Timedelta(minutes=1)
    orr = m5[m5t < 600].groupby(m5d[m5t < 600]).agg(orh=("high", "max"), orl=("low", "min"))      # first 30 minutes
    orh = orr["orh"].reindex(day).to_numpy(); orl = orr["orl"].reindex(day).to_numpy()
    after = bar_end >= 600
    f["p_orb_up"] = after & (c.to_numpy() > orh); f["p_orb_dn"] = after & (c.to_numpy() < orl)
    dhi = h.groupby(day).cummax(); dlo = l.groupby(day).cummin()
    f["p_at_day_high"] = c >= dhi * 0.997; f["p_at_day_low"] = c <= dlo * 1.003
    dchg = c.to_numpy() / pdc - 1
    f["p_day_up3"] = dchg > 0.03; f["p_day_dn3"] = dchg < -0.03
    body = (c - o).abs(); lw = np.minimum(c, o) - l; uw = h - np.maximum(c, o)
    f["p_hammer"] = (lw > 2 * body) & (uw < body) & (rng > atr)
    f["p_shooting"] = (uw > 2 * body) & (lw < body) & (rng > atr)
    f["p_bull_engulf"] = (c > o) & (c.shift() < o.shift()) & (c >= o.shift()) & (o <= c.shift())
    f["p_bear_engulf"] = (c < o) & (c.shift() > o.shift()) & (c <= o.shift()) & (o >= c.shift())
    clv = (c - l) / rng.replace(0, np.nan)
    f["p_close_strong"] = clv > 0.8; f["p_close_weak"] = clv < 0.2
    # ---------------- context
    sb = S4.resample(spy5, F).reindex(b.index)
    sc = sb["close"]; sday = sc.groupby(day).transform("first")
    sD = daily_from_m5(spy5)
    spdc = sD["close"].shift(1).reindex(day).to_numpy()
    sch = sc.to_numpy() / spdc - 1
    f["c_spy_up1"] = sch > 0.01; f["c_spy_dn1"] = sch < -0.01
    f["c_spy_trend_up"] = (sD["close"] > ind.sma(sD["close"], 50)).shift(1).reindex(day).to_numpy() == True
    f["c_spy_trend_dn"] = (sD["close"] < ind.sma(sD["close"], 50)).shift(1).reindex(day).to_numpy() == True
    f["c_rel_strong"] = (dchg - sch) > 0.03; f["c_rel_weak"] = (dchg - sch) < -0.03
    f["c_first_hour"] = bar_end <= 630; f["c_last_hour"] = tod >= 900
    if vix is not None:
        vx = vix.shift(1).reindex(day).to_numpy()
        f["c_vix_high"] = vx > 25; f["c_vix_low"] = vx < 15
    X = pd.DataFrame({k: np.asarray(val, dtype=bool) if not isinstance(val, pd.Series) else val.fillna(False).astype(bool).to_numpy()
                      for k, val in f.items()}, index=b.index)
    return b, X
