"""Round 4 intraday builders (source: Alpaca 5-minute SIP bars, 2016+).

segment_bars  : a few irregular bars per session so daily strategies can act at 15:50
                (enter/exit 10 minutes before the close) and the pre-FOMC trade can exit
                at 13:55 (before the 14:00 statement).
daily_asof    : a daily OHLC series whose 'close' is the price at a cut-off time
                (default 15:50). Indicators computed on it are known at that time, so a
                signal can be acted on the same afternoon without look-ahead.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

CUTS = ("09:30", "10:30", "12:00", "13:55", "15:50", "16:00")


def _mins(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def segment_bars(df5: pd.DataFrame, cuts=CUTS) -> pd.DataFrame:
    """Bars [cut_i, cut_{i+1}) for every session; index = segment start, column end."""
    t = df5.index
    day = t.normalize()
    m = t.hour * 60 + t.minute
    edges = np.array([_mins(c) for c in cuts])
    seg = np.searchsorted(edges, m, side="right") - 1
    ok = (seg >= 0) & (seg < len(edges) - 1)
    d5 = df5[ok]
    seg = seg[ok]
    day = day[ok]
    start = day + pd.to_timedelta(edges[seg], unit="m")
    endt = day + pd.to_timedelta(edges[seg + 1], unit="m")
    g = d5.groupby(start)
    out = pd.DataFrame({"open": g["open"].first(), "high": g["high"].max(), "low": g["low"].min(), "close": g["close"].last(),
                        "volume": g["volume"].sum()})
    out["end"] = pd.Series(endt, index=start).groupby(level=0).first()
    out.index.name = "date"
    return out


def daily_asof(df5: pd.DataFrame, cutoff="15:50", history: pd.DataFrame | None = None) -> pd.DataFrame:
    """Daily bars built from 5-minute bars that START before `cutoff`. Volume is scaled to
    a full-day estimate by the same-time ratio (simple: x 1.0, volume is only used in
    ratios against the same series). Older history (e.g. Yahoo daily) is prepended."""
    t = df5.index
    m = t.hour * 60 + t.minute
    d5 = df5[m < _mins(cutoff)]
    day = d5.index.normalize()
    g = d5.groupby(day)
    out = pd.DataFrame({"open": g["open"].first(), "high": g["high"].max(), "low": g["low"].min(), "close": g["close"].last(),
                        "volume": g["volume"].sum()})
    out.index.name = "date"
    if history is not None:
        h = history[history.index < out.index[0]][["open", "high", "low", "close", "volume"]]
        # scale history to the intraday source at the junction (adjustment differences)
        f = out["close"].iloc[0] / history["close"].reindex([out.index[0]]).iloc[0] if out.index[0] in history.index else 1.0
        h = h.copy()
        h[["open", "high", "low", "close"]] *= f
        out = pd.concat([h, out])
    return out


def to_segments(sig_daily: pd.DataFrame, seg: pd.DataFrame, at="13:55") -> pd.DataFrame:
    """Place a daily signal frame (computed on daily_asof) on the segment whose START is
    `at` (that segment ends at the cut-off; the trade fills at the next segment's open).
    Columns xsched/xcond are placed the same way."""
    out = pd.DataFrame(index=seg.index, columns=sig_daily.columns)
    out["dir"] = 0
    out["xsched"] = False
    out["xcond"] = False
    h, m = map(int, at.split(":"))
    keys = sig_daily.index + pd.Timedelta(hours=h, minutes=m)
    present = keys.isin(seg.index)
    src = sig_daily[present]
    out.loc[keys[present], :] = src.to_numpy()
    out["dir"] = out["dir"].fillna(0).astype(int)
    for col in ("stop", "target", "score", "min_days"):
        if col in out:
            out[col] = pd.to_numeric(out[col], errors="coerce")
    out["reason"] = out["reason"].fillna("")
    out["xsched"] = out["xsched"].fillna(False).astype(bool)
    out["xcond"] = out["xcond"].fillna(False).astype(bool)
    return out
