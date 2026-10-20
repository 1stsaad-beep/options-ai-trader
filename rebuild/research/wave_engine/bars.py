"""Bars at any timeframe for one symbol, loaded lazily and cut to a time window (no global candle cap).
Timeframes: 'M' monthly, 'W' weekly, 'D' daily (from daily files, 1998+), '60' hourly and '5' five-minute
(from 5-minute files: original 15 symbols 2016+, new 30 symbols 2023+). Hourly bars are session-anchored at 09:30."""
from __future__ import annotations
from functools import lru_cache
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
TF_ORDER = ["M", "W", "D", "60", "5"]           # coarse -> fine
TF_MINUTES = {"M": 21 * 390, "W": 5 * 390, "D": 390, "60": 60, "5": 5}

# Optional data provider (used by a backend such as ATLAS instead of the research CSV files):
#   daily(sym) / m5(sym) -> DataFrame indexed by NAIVE New York time, columns open/high/low/close/volume,
#   regular session only for 5-minute bars, oldest first.  Monthly history before the daily data is optional.
_PROVIDER = {}


def set_provider(daily=None, m5=None, monthly=None):
    _PROVIDER.clear()
    _PROVIDER.update({k: v for k, v in dict(daily=daily, m5=m5, monthly=monthly).items() if v is not None})
    _daily.cache_clear(); _m5.cache_clear(); _full.cache_clear()


@lru_cache(maxsize=64)
def _daily(sym: str) -> pd.DataFrame:
    if "daily" in _PROVIDER:
        return _PROVIDER["daily"](sym)[["open", "high", "low", "close", "volume"]]
    from oat_research import data as D
    for p in (ROOT / "data/d1" / f"{sym}.csv", ROOT / "data/d1x" / f"{sym}.csv", ROOT / "data/d1v" / f"{sym}.csv"):
        if p.exists():
            return D.load_csv(str(p))[["open", "high", "low", "close", "volume"]]
    raise FileNotFoundError(sym)


@lru_cache(maxsize=16)
def _m5(sym: str) -> pd.DataFrame:
    if "m5" in _PROVIDER:
        return _PROVIDER["m5"](sym)[["open", "high", "low", "close", "volume"]]
    from oat_research import data as D
    for p in (ROOT / "data/m5a" / f"{sym}.csv", ROOT / "data/m5x" / f"{sym}.csv", ROOT / "data/m5v" / f"{sym}.csv"):
        if p.exists():
            return D.load_csv(str(p))[["open", "high", "low", "close", "volume"]]
    raise FileNotFoundError(sym)


def _agg(df, key):
    g = df.groupby(key)
    out = pd.DataFrame({"open": g["open"].first(), "high": g["high"].max(), "low": g["low"].min(),
                        "close": g["close"].last(), "volume": g["volume"].sum()})
    out["t_end"] = g.apply(lambda x: x.index[-1])          # last source bar in the aggregate (for causality)
    return out


@lru_cache(maxsize=64)
def _full(sym: str, tf: str) -> pd.DataFrame:
    if tf in ("M", "W", "D"):
        d = _daily(sym)
        if tf == "D":
            out = d.copy(); out["t_end"] = out.index; return out
        key = d.index.to_period("M" if tf == "M" else "W-FRI").start_time
        out = _agg(d, key)
        mo = ROOT / "data/mo" / f"{sym}.csv"
        if tf == "M" and "monthly" in _PROVIDER:
            m = _PROVIDER["monthly"](sym)
            mo = None
            old = m[m.index.to_period("M").start_time < out.index[0]].copy() if m is not None and len(m) else m
            if old is not None and len(old):
                old.index = old.index.to_period("M").start_time
                old["t_end"] = [i + pd.offsets.MonthEnd(0) for i in old.index]
                out = pd.concat([old[["open", "high", "low", "close", "volume", "t_end"]], out])
        elif tf == "M" and "daily" not in _PROVIDER and mo.exists():          # older months from the since-listing monthly file, rescaled at the seam
            from oat_research import data as D
            m = D.load_csv(str(mo))[["open", "high", "low", "close", "volume"]]
            m.index = m.index.to_period("M").start_time
            old = m[m.index < out.index[0]]
            if len(old):
                seam = out.index[0]
                if seam in m.index:
                    f = out["close"].iloc[0] / m.loc[seam, "close"]
                    old = old.copy(); old[["open", "high", "low", "close"]] *= f
                old = old.copy(); old["t_end"] = [i + pd.offsets.MonthEnd(0) for i in old.index]
                out = pd.concat([old, out])
        return out
    m = _m5(sym)
    if tf == "5":
        out = m.copy(); out["t_end"] = out.index; return out
    day = m.index.normalize()
    off = (m.index - day - pd.Timedelta(hours=9, minutes=30)) // pd.Timedelta(minutes=int(tf))
    key = day + pd.Timedelta(hours=9, minutes=30) + off * pd.Timedelta(minutes=int(tf))
    return _agg(m, key)


def bars(sym: str, tf: str, start=None, end=None) -> pd.DataFrame:
    """Bars whose source data ends at or before `end` (an as-of time; partial last bar allowed = what you'd see live)."""
    df = _full(sym, tf)
    if start is not None:
        df = df[df.index >= pd.Timestamp(start)]
    if end is not None:
        df = df[df["t_end"] <= pd.Timestamp(end)]
    return df


def available(sym: str, tf: str):
    df = _full(sym, tf)
    return (df.index[0], df["t_end"].iloc[-1]) if len(df) else (None, None)
