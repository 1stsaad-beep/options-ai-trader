"""Round 6: the three externally proposed strategies, implemented exactly as specified
(file Options_AI_Trader_3_Strategies.pdf). Everything causal: higher-timeframe values are
aligned by bar END time, daily values come from the previous completed session.

Ambiguities in the specification and how they are resolved (fixed BEFORE any test):
  S1  'crosses below 30 then back above 30' -> state machine on the 15-min RSI; the signal is
      the 15-min bar whose RSI closes back above 30 after having closed below 30, while the
      hourly RSI (last completed) is < 35 throughout. MACD(12,26,9) histogram, ADX(14) and the
      20-bar volume average are on the 15-min bars.
  S2  'after being > 70': the 15-min RSI was > 70 within the last 8 bars (2 hours) and now
      closes < 65. 'price rejects near previous high or SMA20': the high of the last 4 bars
      reached the 15-min SMA20 or came within 0.3 x ATR(15m) of the prior 20-bar high, and the
      signal bar closes below its open. 'volume confirmation': volume > 1.2 x 20-bar average.
      STATE (daily RSI14 > 60 or hourly RSI14 > 55) is applied as written.
  S3  squeeze = Bollinger width (20,2) percentile rank over the last 100 bars <= 20 % on any of
      the 5 bars before the breakout bar; breakout = close > upper band and volume > 1.5 x
      20-bar average; one signal per squeeze episode. Two versions: 60-min bars and daily
      bars acted on at 15:50.
  All  'skip earnings +/-2 days': no earnings calendar is available, so earnings-type events are
      detected from the tape (open gap >= 1.5 ATR on >= 2.5x volume) and the 2 sessions AFTER
      such an event are skipped; the 2 sessions BEFORE cannot be known causally (limitation).
      'extreme VIX': skip when the previous VIX close > 35.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import indicators as ind
from .mtf import align, bar_end
from .setups4 import frame, resample


def dmi(df: pd.DataFrame, n: int = 14):
    h, l, c = df["high"], df["low"], df["close"]
    up, dn = h.diff(), -l.diff()
    pdm = pd.Series(np.where((up > dn) & (up > 0), up, 0.0), index=df.index)
    ndm = pd.Series(np.where((dn > up) & (dn > 0), dn, 0.0), index=df.index)
    tr = ind.true_range(df)
    atr = ind.wilder(tr, n)
    pdi = 100 * ind.wilder(pdm, n) / atr
    ndi = 100 * ind.wilder(ndm, n) / atr
    dx = 100 * (pdi - ndi).abs() / (pdi + ndi)
    return pdi, ndi, ind.wilder(dx, n)


def _prev_daily(series: pd.Series, bars: pd.DataFrame) -> np.ndarray:
    s = series.shift(1)
    s.index = s.index.normalize()
    return s.reindex(bars.index.normalize()).to_numpy()


def event_block(daily: pd.DataFrame, vix: pd.Series | None, bars: pd.DataFrame) -> np.ndarray:
    """True where trading is blocked: within 2 sessions after an earnings-type gap, or VIX>35."""
    a = ind.atr(daily).shift(1)
    g = (daily["open"] - daily["close"].shift(1)).abs() / a
    rv = daily["volume"] / ind.sma(daily["volume"], 20).shift(1)
    ev = (g >= 1.5) & (rv >= 2.5)
    # event day itself: the opening gap is known at the open (volume is not) -> block on the gap alone
    blk = (g >= 1.5) | ev.shift(1, fill_value=False) | ev.shift(2, fill_value=False)
    if vix is not None:
        v = vix.reindex(daily.index).ffill().shift(1)
        blk |= v > 35
    blk.index = blk.index.normalize()
    return blk.reindex(bars.index.normalize()).fillna(False).to_numpy().astype(bool)


# ---------------------------------------------------------------- S1
def s1_mtf_momentum_call(df5, daily, vix=None, rsi_lo=30.0, h_max=35.0, adx_min=20.0, vol_mult=1.2, confirm=True):
    lo = resample(df5, 15)
    h1 = resample(df5, 60)
    r15 = ind.rsi(lo["close"], 14).to_numpy()
    rh = align(ind.rsi(h1["close"], 14), bar_end(h1, 60), bar_end(lo, 15)).to_numpy()
    hist = ind.macd_hist(lo["close"]).to_numpy()
    adx = ind.adx(lo).to_numpy()
    vol = lo["volume"].to_numpy()
    va = ind.sma(lo["volume"], 20).shift(1).to_numpy()
    s200 = _prev_daily(daily["close"] > ind.sma(daily["close"], 200), lo)
    blk = event_block(daily, vix, lo)
    d = np.zeros(len(lo), int)
    below = False
    for i in range(1, len(lo)):
        if not (np.isfinite(rh[i]) and np.isfinite(r15[i])) or rh[i] >= h_max:
            below = False
            continue
        if r15[i] < rsi_lo:
            below = True
            continue
        if below and r15[i] >= rsi_lo:
            below = False
            ok = s200[i] == True and not blk[i]
            if confirm:
                ok = ok and hist[i] > 0 and adx[i] > adx_min and np.isfinite(va[i]) and vol[i] > vol_mult * va[i]
            if ok:
                d[i] = 1
    return lo, frame(lo, d, reason=np.where(d != 0, "S1 MTF-momentum call", ""))


# ---------------------------------------------------------------- S2
def s2_downtrend_put(df5, daily, vix=None, ob=70.0, cross=65.0, adx_min=25.0, vol_mult=1.2, lookback=8):
    lo = resample(df5, 15)
    h1 = resample(df5, 60)
    c = lo["close"]
    r15 = ind.rsi(c, 14).to_numpy()
    rh = align(ind.rsi(h1["close"], 14), bar_end(h1, 60), bar_end(lo, 15)).to_numpy()
    pdi, ndi, adx_d = dmi(daily)
    reg = (daily["close"] < ind.sma(daily["close"], 200)) & (adx_d > adx_min) & (ndi > pdi)
    reg_v = _prev_daily(reg, lo)
    rsi_d = _prev_daily(ind.rsi(daily["close"], 14), lo)
    sma20 = ind.sma(c, 20).to_numpy()
    a15 = ind.atr(lo).to_numpy()
    hh20 = lo["high"].rolling(20).max().shift(4).to_numpy()
    h4 = lo["high"].rolling(4).max().to_numpy()
    vol = lo["volume"].to_numpy()
    va = ind.sma(lo["volume"], 20).shift(1).to_numpy()
    op, cl = lo["open"].to_numpy(), c.to_numpy()
    was_ob = pd.Series(r15 > ob).rolling(lookback, min_periods=1).max().shift(1).fillna(0).to_numpy().astype(bool)
    blk = event_block(daily, vix, lo)
    d = np.zeros(len(lo), int)
    for i in range(1, len(lo)):
        if not (r15[i] < cross <= r15[i - 1]) or not was_ob[i]:
            continue
        if not (reg_v[i] == True) or blk[i]:
            continue
        if not ((np.isfinite(rsi_d[i]) and rsi_d[i] > 60) or (np.isfinite(rh[i]) and rh[i] > 55)):
            continue
        rej = (h4[i] >= sma20[i]) or (np.isfinite(hh20[i]) and h4[i] >= hh20[i] - 0.3 * a15[i])
        if rej and cl[i] < op[i] and np.isfinite(va[i]) and vol[i] > vol_mult * va[i]:
            d[i] = -1
    return lo, frame(lo, d, reason=np.where(d != 0, "S2 downtrend-regime put", ""))


# ---------------------------------------------------------------- S3
def _squeeze_signals(bars, daily_reg, pct=0.20, vol_mult=1.5, n_rank=100):
    c = bars["close"]
    mid = ind.sma(c, 20)
    sd = c.rolling(20).std(ddof=0)
    up = mid + 2 * sd
    bw = (4 * sd / mid)
    rank = bw.rolling(n_rank).apply(lambda x: (x[:-1] < x[-1]).mean(), raw=True)
    sq = (rank <= pct).shift(1).rolling(5, min_periods=1).max().fillna(0).astype(bool)
    va = ind.sma(bars["volume"], 20).shift(1)
    brk = (c > up) & (bars["volume"] > vol_mult * va) & sq & daily_reg
    # one signal per squeeze episode: first breakout after the squeeze
    prev = brk.shift(1, fill_value=False).rolling(10, min_periods=1).max().astype(bool)
    return (brk & ~prev).to_numpy()


def s3_squeeze_call_hourly(df5, daily, vix=None, pct=0.20, vol_mult=1.5):
    h1 = resample(df5, 60)
    reg = pd.Series(_prev_daily(daily["close"] > ind.sma(daily["close"], 50), h1), index=h1.index).fillna(False).astype(bool)
    sig = _squeeze_signals(h1, reg, pct, vol_mult) & ~event_block(daily, vix, h1)
    return h1, frame(h1, np.where(sig, 1, 0), reason=np.where(sig, "S3 squeeze breakout (60m)", ""))


def s3_squeeze_call_daily_asof(asof: pd.DataFrame, daily: pd.DataFrame, vix=None, pct=0.20, vol_mult=1.5):
    """Daily bars whose close is the 15:50 price; signal acted on at 15:50 (to_segments)."""
    reg = pd.Series(_prev_daily(daily["close"] > ind.sma(daily["close"], 50), asof), index=asof.index).fillna(False).astype(bool)
    # same-day volume up to 15:50 vs the full-day average of previous days: scale by 390/380
    a2 = asof.copy()
    a2["volume"] = a2["volume"] * 390 / 380
    sig = _squeeze_signals(a2, reg, pct, vol_mult) & ~event_block(daily, vix, asof)
    return frame(asof, np.where(sig, 1, 0), reason=np.where(sig, "S3 squeeze breakout (daily @15:50)", ""))
