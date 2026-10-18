"""Candidate enhancement filters (all causal, daily), evaluated on every strategy.
Each column is boolean "condition favourable for a CALL" at the close of that day.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import indicators as ind


def _weekly_macd_pos(close: pd.Series) -> pd.Series:
    w = close.resample("W-FRI").last()
    line = ind.ema(w, 12) - ind.ema(w, 26)
    # weekly value known after the week closes -> shift one week, then forward-fill daily
    return (line > 0).astype(float).where(line.notna()).shift(1).reindex(close.index, method="ffill")


def _avwap_ytd(df: pd.DataFrame) -> pd.Series:
    tp = (df["high"] + df["low"] + df["close"]) / 3
    yr = df.index.year
    pv = (tp * df["volume"]).groupby(yr).cumsum()
    vv = df["volume"].groupby(yr).cumsum()
    return pv / vv


def build(data: dict[str, pd.DataFrame], vix: pd.Series) -> dict[str, pd.DataFrame]:
    spy = data["SPY"]
    sc = spy["close"]
    s50, s200 = ind.sma(sc, 50), ind.sma(sc, 200)
    v = vix.reindex(spy.index).ffill()
    mkt = pd.DataFrame({
        "mkt>SMA200": sc > s200,
        "mkt>SMA50": sc > s50,
        "mkt SMA50 rising": s50 > s50.shift(10),
        "VIX<20": v < 20,
        "VIX<25": v < 25,
        "VIX falling (<SMA20)": v < ind.sma(v, 20),
    }, index=spy.index)
    # breadth among the 15-symbol universe
    above50 = pd.DataFrame({s: df["close"] > ind.sma(df["close"], 50) for s, df in data.items()}).reindex(spy.index)
    above200 = pd.DataFrame({s: df["close"] > ind.sma(df["close"], 200) for s, df in data.items()}).reindex(spy.index)
    mkt["breadth50>=60%"] = above50.mean(axis=1) >= 0.6
    mkt["breadth200>=60%"] = above200.mean(axis=1) >= 0.6
    # cross-sectional 12-1 month momentum rank
    mom = pd.DataFrame({s: df["close"].shift(21) / df["close"].shift(252) - 1 for s, df in data.items()}).reindex(spy.index)
    rank = mom.rank(axis=1, ascending=False)
    out = {}
    for s, df in data.items():
        c = df["close"]
        a = ind.atr(df)
        s50s = ind.sma(c, 50)
        rv = ind.realized_vol(c, 20)
        obv = ind.obv(df)
        up_v = df["volume"].where(c.diff() > 0, 0).rolling(20).sum()
        dn_v = df["volume"].where(c.diff() < 0, 0).rolling(20).sum()
        r14 = ind.rsi(c, 14)
        f = pd.DataFrame(index=df.index)
        for col in mkt.columns:
            f[col] = mkt[col].reindex(df.index).fillna(False).astype(bool)
        f["sym SMA50 rising"] = s50s > s50s.shift(10)
        f["ADX>=20"] = ind.adx(df) >= 20
        f["12-1 mom top half"] = (rank[s] <= 7).reindex(df.index).fillna(False)
        f["12-1 mom top 3"] = (rank[s] <= 3).reindex(df.index).fillna(False)
        f["RS63 > SPY"] = (c / c.shift(63)) > (spy["close"] / spy["close"].shift(63)).reindex(df.index)
        f["low realised vol (pct<50)"] = ind.rolling_percentile(rv, 252) < 0.5
        f["not extended (<3 ATR over SMA50)"] = (c - s50s) / a < 3
        f["OBV rising (20d)"] = obv > obv.shift(20)
        f["up/down volume > 1.2"] = (up_v / dn_v.replace(0, np.nan)) > 1.2
        f["weekly MACD > 0"] = (_weekly_macd_pos(c) == 1.0)
        f["RSI14 in 50-70"] = (r14 >= 50) & (r14 <= 70)
        f["above YTD anchored VWAP"] = c > _avwap_ytd(df)
        f["within 10% of 52w high"] = c >= 0.9 * df["high"].rolling(252).max()
        out[s] = f.fillna(False).astype(bool)
    return out
