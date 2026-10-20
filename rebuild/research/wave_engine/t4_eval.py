"""T4a: pick the scenario whose current wave best matches its indicator 'personality'; compare with scenario 1."""
import numpy as np
import pandas as pd
from . import bars as B, personality as PS
from .setups_eval import _out

H = 150


def outcomes(X, n_null=30, seed=0):
    """outcomes aligned with the row order of X (fixed horizon H) + drift-matched null."""
    rng = np.random.default_rng(seed); res = []; cache = {}
    for r in X.itertuples():
        key = (r.sym, r.tf)
        if key not in cache:
            b = B.bars(r.sym, r.tf); st = {"5": "2023-03-01", "60": "2023-03-01", "D": "2008-01-01"}[r.tf]
            cache[key] = (b["high"].to_numpy(), b["low"].to_numpy(), b["close"].to_numpy(), {t: i for i, t in enumerate(b.index)},
                          np.flatnonzero((b.index >= st) & (np.arange(len(b)) < len(b) - H - 1)))
        hi, lo, cl, pos, base = cache[key]
        i = pos.get(r.t)
        if i is None or i + 2 >= len(cl): res.append((np.nan,) * 4); continue
        tp = abs(r.target / cl[i] - 1); sp = abs(r.stop / cl[i] - 1)
        if sp <= 0 or tp <= 0: res.append((np.nan,) * 4); continue
        e = _out(hi, lo, cl, i, r.up, tp, sp, H)
        ns = [_out(hi, lo, cl, j, r.up, tp, sp, H) for j in rng.choice(base, n_null)]
        res.append((e[0], e[1], np.nanmean([x[0] for x in ns]) if any(np.isfinite(x[0]) for x in ns) else np.nan, np.nanmean([x[1] for x in ns])))
    return res


def run(D):
    W = D[D.who.isin(["wave1", "wave2"])].copy()
    W["m"] = [PS.match(r.sym, r.tf, r.t, r.cur, r.up) for r in W.itertuples()]
    piv = W.pivot_table(index=["sym", "tf", "t"], columns="who", values="m", aggfunc="first")
    both = piv.dropna(how="all")
    choose2 = both.index[(both["wave2"].fillna(-1) > both["wave1"].fillna(-1))]
    W = W.set_index(["sym", "tf", "t"])
    has2 = W[W.who == "wave2"].index
    w1 = W[W.who == "wave1"]; w1 = w1[w1.index.isin(has2)]             # instants where a choice exists
    w2 = W[W.who == "wave2"]
    chosen = pd.concat([w1[~w1.index.isin(choose2)], w2[w2.index.isin(choose2) & w2.index.isin(w1.index)]])
    out = {}
    for name, X in (("scenario1", w1), ("chosen_by_personality", chosen)):
        X = X.reset_index()
        o = outcomes(X)
        X = X.assign(hit=[x[0] for x in o], r=[x[1] for x in o], null_hit=[x[2] for x in o], null_r=[x[3] for x in o])
        X["skill_hit"] = X.hit - X.null_hit; X["skill_r"] = X.r - X.null_r
        out[name] = X
    return out
