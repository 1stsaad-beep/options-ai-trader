"""Round 5 shared: data, periods, underlying-outcome evaluation."""
from __future__ import annotations

import numpy as np
import pandas as pd

from oat_research import data as D
from oat_research import indicators as ind
from oat_research import intraday4 as I4
from oat_research import setups4 as S4
from oat_research import timing as T
from r4_common import fmt, load_daily

SYMS = ["SPY", "QQQ", "IWM", "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "AMD", "JPM", "XOM", "UNH", "COST"]
DISC = (pd.Timestamp("2016-01-01"), pd.Timestamp("2020-12-31 23:59"))
VALID = (pd.Timestamp("2021-01-01"), pd.Timestamp("2026-04-15 23:59"))
HOLD = (pd.Timestamp("2026-04-16"), pd.Timestamp("2026-10-16 23:59"))


def load():
    d1, vols = load_daily()
    m5 = {s: D.load_csv(f"data/m5a/{s}.csv") for s in SYMS}
    full = {s: I4.daily_asof(df, "16:00", d1[s]) for s, df in m5.items()}
    return m5, full, vols


def prev_day_atr(bars: pd.DataFrame, daily: pd.DataFrame) -> pd.Series:
    a = ind.atr(daily).shift(1)
    a.index = a.index.normalize()
    return pd.Series(a.reindex(bars.index.normalize()).to_numpy(), index=bars.index)


def outcomes(bars: pd.DataFrame, sig: pd.DataFrame, daily: pd.DataFrame, bpd: int, period) -> pd.DataFrame:
    """Underlying outcomes for every signal in `period` (entry = next bar open)."""
    a = prev_day_atr(bars, daily)
    m = (sig["dir"] != 0) & (sig.index >= period[0]) & (sig.index <= period[1])
    idx = np.flatnonzero(m.to_numpy())
    ent = [(int(i), int(sig["dir"].iloc[i])) for i in idx]
    w = T.walk(bars, ent, a, horizon_days=3, bars_per_day=bpd)
    if w.empty:
        return w
    o, c = bars["open"].to_numpy(), bars["close"].to_numpy()
    av = a.to_numpy()
    k = max(1, bpd // 7)  # ~1 hour
    w["ret1h"] = [d * (c[min(t + k, len(c) - 1)] - o[t + 1]) / av[t] for t, d in zip(w.t, w.dir)]
    return w


def summary(w: pd.DataFrame) -> dict:
    if w is None or w.empty:
        return dict(n=0)
    return dict(n=len(w), p05_d1=(w["hit0.5"] < 1).mean(), p05_d2=(w["hit0.5"] < 2).mean(), p1_d2=(w["hit1.0"] < 2).mean(),
                stop_d2=(w["stopped"] < 2).mean(), r1h=w["ret1h"].mean(), r_eod=w["ret1"].mean(), r_d2=w["ret2"].mean(),
                r_d3=w["ret3"].mean(), t_d2=w["ret2"].mean() / w["ret2"].std(ddof=1) * np.sqrt(len(w)) if len(w) > 2 else np.nan)


HDR = ("| variant | period | n | +0.5 ATR before stop, same day | within 2 days | +1 ATR within 2d | stop within 2d | 1h (ATR) | close same day | close day 2 | t(day 2) |",
       "|---|---|---|---|---|---|---|---|---|---|---|")


def line(name, per, s):
    if s["n"] == 0:
        return f"| {name} | {per} | 0 |" + " — |" * 8
    p = lambda x: f"{x * 100:.0f}%"
    return (f"| {name} | {per} | {s['n']} | {p(s['p05_d1'])} | {p(s['p05_d2'])} | {p(s['p1_d2'])} | {p(s['stop_d2'])} | "
            f"{s['r1h']:+.3f} | {s['r_eod']:+.3f} | {s['r_d2']:+.3f} | {fmt(s['t_d2'])} |")
