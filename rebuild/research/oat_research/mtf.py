"""Round 5: multi-timeframe helpers + the MTF-RSI strategy.

All alignment is by bar END time: a higher-timeframe value is usable on a lower-timeframe
bar only if the higher bar ended at or before the lower bar's end (causal)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import indicators as ind
from .setups4 import frame, resample


def bar_end(df: pd.DataFrame, minutes: int) -> pd.Series:
    st = df.index
    close = st.normalize() + pd.Timedelta(hours=16)
    return pd.Series(np.minimum(st + pd.Timedelta(minutes=minutes), close), index=st)


def align(htf_values: pd.Series, htf_end: pd.Series, ltf_end: pd.Series) -> pd.Series:
    """Value of the last higher-TF bar with end <= each lower-TF bar end."""
    a = pd.DataFrame({"t": htf_end.to_numpy(), "v": htf_values.to_numpy()}).sort_values("t")
    b = pd.DataFrame({"t": ltf_end.to_numpy(), "i": np.arange(len(ltf_end))}).sort_values("t")
    m = pd.merge_asof(b, a, on="t", direction="backward").sort_values("i")
    return pd.Series(m["v"].to_numpy(), index=ltf_end.index)


def frames(df5: pd.DataFrame):
    m15 = resample(df5, 15)
    h1 = resample(df5, 60)
    return m15, h1


# ---------------------------------------------------------------- MTF RSI
def mtf_rsi(df5: pd.DataFrame, n: int = 14, ob: float = 70.0, os_: float = 30.0, trigger: str = "reentry",
            ltf: int = 15, n_ltf: int | None = None) -> pd.DataFrame:
    """Put: hourly RSI > ob. On the lower TF the RSI was overbought, dropped below ob and
    comes back above ob while the hourly is still > ob.
      trigger = 'reentry'  -> signal on the bar where the lower-TF RSI re-enters (> ob)
                'fail'     -> after the re-entry, signal when the lower-TF RSI crosses back below ob
                              (hourly still > ob)
                'div'      -> 'fail' AND bearish divergence: the second lower-TF peak made a
                              higher (or equal) price high with a lower RSI peak
    Call: mirror with os_. Signals on the lower-TF bars (index = bar start)."""
    lo = resample(df5, ltf)
    h1 = resample(df5, 60)
    r_l = ind.rsi(lo["close"], n_ltf or n).to_numpy()
    r_h = align(ind.rsi(h1["close"], n), bar_end(h1, 60), bar_end(lo, ltf)).to_numpy()
    hi, lw = lo["high"].to_numpy(), lo["low"].to_numpy()
    N = len(lo)
    d = np.zeros(N, int)
    reason = np.array([""] * N, dtype=object)
    for side in (-1, 1):
        # side -1 = put logic on overbought; +1 = call logic on oversold (mirror)
        thr_h, thr_l = (ob, ob) if side == -1 else (os_, os_)
        ext = (lambda x, t: x > t) if side == -1 else (lambda x, t: x < t)
        state = 0          # 0 none, 1 first extreme seen, 2 left extreme, 3 re-entered
        pk1_p = pk1_r = pk2_p = pk2_r = np.nan
        for i in range(1, N):
            if not (np.isfinite(r_h[i]) and np.isfinite(r_l[i])):
                continue
            if not ext(r_h[i], thr_h):
                state = 0
                continue
            p = hi[i] if side == -1 else lw[i]
            better = (lambda a, b: a > b) if side == -1 else (lambda a, b: a < b)
            if state == 0:
                if ext(r_l[i], thr_l):
                    state, pk1_p, pk1_r = 1, p, r_l[i]
            elif state == 1:
                if ext(r_l[i], thr_l):
                    if better(p, pk1_p): pk1_p = p
                    if better(r_l[i], pk1_r): pk1_r = r_l[i]
                else:
                    state = 2
            elif state == 2:
                if ext(r_l[i], thr_l):
                    state, pk2_p, pk2_r = 3, p, r_l[i]
                    if trigger == "reentry" and d[i] == 0:
                        d[i] = side; reason[i] = "MTF-RSI re-entry"
                        state = 0
            elif state == 3:
                if ext(r_l[i], thr_l):
                    if better(p, pk2_p): pk2_p = p
                    if better(r_l[i], pk2_r): pk2_r = r_l[i]
                else:
                    ok = True
                    if trigger == "div":
                        ok = (not better(pk1_p, pk2_p)) and better(pk1_r, pk2_r)   # price HH (LL), RSI LH (HL)
                    if trigger in ("fail", "div") and ok and d[i] == 0:
                        d[i] = side; reason[i] = f"MTF-RSI {trigger}"
                    state = 0
    return frame(lo, d, reason=reason)
