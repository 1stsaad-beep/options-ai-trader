"""Drift-matched null: for every forecast (symbol, direction, target %, stop %), the probability of hitting the
target before the stop from RANDOM dates of the same symbol in the same direction, same horizon.  Skill = engine
hit rate minus this empirical probability (the market's own drift is inside both)."""
import numpy as np
import pandas as pd
from . import bars as B

H = 150


def outcome(hi, lo, i, up, tp, sp, price):
    t = price * (1 + tp) if up else price * (1 - tp)
    s = price * (1 - sp) if up else price * (1 + sp)
    h = hi[i + 1:i + 1 + H]; l = lo[i + 1:i + 1 + H]
    th = (h >= t) if up else (l <= t); ts = (l <= s) if up else (h >= s)
    a = np.argmax(th) if th.any() else H + 1; b = np.argmax(ts) if ts.any() else H + 1
    if a == b == H + 1: return np.nan
    return 1.0 if a < b else (0.5 if a == b else 0.0)


def evaluate(D, tf="D", n_null=40, seed=0, start="2008-01-01"):
    rng = np.random.default_rng(seed); rows = []
    for sym, g in D[D.tf == tf].groupby("sym"):
        b = B.bars(sym, tf); hi, lo, cl = b["high"].to_numpy(), b["low"].to_numpy(), b["close"].to_numpy()
        pos = {t: i for i, t in enumerate(b.index)}
        valid = np.flatnonzero((b.index >= start) & (np.arange(len(b)) < len(b) - H - 1))
        for r in g.itertuples():
            i = pos.get(r.t)
            if i is None or i + H >= len(b): continue
            price = cl[i]; tp = abs(r.target / price - 1); sp = abs(r.stop / price - 1)
            eng = outcome(hi, lo, i, r.up, tp, sp, price)
            js = rng.choice(valid, n_null)
            nul = np.nanmean([outcome(hi, lo, j, r.up, tp, sp, cl[j]) for j in js])
            rows.append(dict(sym=sym, who=r.who, up=r.up, t=r.t, eng=eng, null=nul))
    return pd.DataFrame(rows)
