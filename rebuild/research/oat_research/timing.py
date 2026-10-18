"""Round 4 timing engine: how fast does the underlying move after a setup?

For every signal (entry at the next bar's open) we walk forward bar by bar and record,
in units of the previous day's ATR:
  * the first bar on which each target (+0.5 / +0.75 / +1 / +1.5 ATR) is touched,
  * whether the stop (-k ATR, or the signal's own stop if tighter/looser) was touched first
    (a bar touching both counts as STOP FIRST - conservative),
  * maximum favourable / adverse excursion after 1..5 days.
The same is computed for a baseline of every bar that satisfies only the setup's regime
(e.g. 'close above SMA200' for calls) so each setup's lift over 'just being in the trend'
is visible.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import indicators as ind

TARGETS = (0.5, 0.75, 1.0, 1.5)


def walk(df: pd.DataFrame, entries: list[tuple[int, int]], datr: pd.Series, horizon_days: int = 5,
         stop_atr: float = 1.0, bars_per_day: int = 1) -> pd.DataFrame:
    """entries = [(signal_bar_index, direction)]. datr = daily ATR aligned to df's index
    (value known at the signal bar)."""
    o, h, l, c = (df[k].to_numpy() for k in ("open", "high", "low", "close"))
    a_arr = datr.to_numpy()
    days = df.index.normalize()
    H = horizon_days * bars_per_day
    rows = []
    for t, d in entries:
        e_i = t + 1
        if e_i + H > len(df) or not np.isfinite(a_arr[t]) or a_arr[t] <= 0:
            continue
        a = a_arr[t]
        e = o[e_i]
        d0 = days[e_i]
        hit = {k: np.nan for k in TARGETS}
        stopped_at = np.nan
        mfe = np.zeros(horizon_days)
        mae = np.zeros(horizon_days)
        close_ret = np.full(horizon_days, np.nan)
        best = worst = 0.0
        day_no = 0
        for j in range(e_i, min(len(df), e_i + H + bars_per_day * 3)):
            # trading-day number since entry (0 = entry day)
            if j > e_i and days[j] != days[j - 1]:
                day_no += 1
            if day_no >= horizon_days:
                break
            fav = ((h[j] - e) if d > 0 else (e - l[j])) / a
            adv = ((e - l[j]) if d > 0 else (h[j] - e)) / a
            best, worst = max(best, fav), max(worst, adv)
            mfe[day_no], mae[day_no] = best, worst
            close_ret[day_no] = d * (c[j] - e) / a
            if np.isnan(stopped_at) and adv >= stop_atr:
                stopped_at = day_no
            for k in TARGETS:
                if np.isnan(hit[k]) and fav >= k and np.isnan(stopped_at):
                    hit[k] = day_no
        mfe = pd.Series(mfe).replace(0, np.nan).ffill().fillna(0).to_numpy()
        row = dict(t=t, date=df.index[t], dir=d, weekday=df.index[e_i].weekday(), stopped=stopped_at)
        for k in TARGETS:
            row[f"hit{k}"] = hit[k]
        for q in range(horizon_days):
            row[f"mfe{q + 1}"] = mfe[q]
            row[f"mae{q + 1}"] = mae[q]
            row[f"ret{q + 1}"] = close_ret[q]
        rows.append(row)
    return pd.DataFrame(rows)


def summarize(w: pd.DataFrame, horizon_days: int = 5) -> dict:
    if w.empty:
        return {"n": 0}
    out = {"n": len(w)}
    for k in TARGETS:
        col = w[f"hit{k}"]
        for dd in (1, 2, 3, 5):
            out[f"p{k}_d{dd}"] = float((col < dd).mean())   # touched within dd trading days (day 0 = entry day)
        out[f"med_days{k}"] = float(col.dropna().median() + 1) if col.notna().any() else np.nan
    out["p_stop_d5"] = float((w["stopped"] < horizon_days).mean())
    for q in (1, 2, 3, 5):
        out[f"mfe{q}"] = float(w[f"mfe{q}"].median())
        out[f"ret{q}"] = float(w[f"ret{q}"].mean())
    return out
