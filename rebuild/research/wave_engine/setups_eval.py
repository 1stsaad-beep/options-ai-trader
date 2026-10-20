"""Evaluation of the decision-point setups vs a drift-matched null (pre-registered: PREREG_SETUPS.json)."""
import glob
import numpy as np
import pandas as pd
import r7_lib as L7
from . import bars as B


def _out(hi, lo, cl, i, up, tp, sp, H):
    e = cl[i]; t = e * (1 + tp) if up else e * (1 - tp); s = e * (1 - sp) if up else e * (1 + sp)
    h = hi[i + 1:i + 1 + H]; l = lo[i + 1:i + 1 + H]
    th = (h >= t) if up else (l <= t); ts = (l <= s) if up else (h >= s)
    a = np.argmax(th) if th.any() else 10 ** 9; b = np.argmax(ts) if ts.any() else 10 ** 9
    R = tp / sp
    if a == b == 10 ** 9:
        end = min(len(cl) - 1, i + H); return np.nan, ((cl[end] - e) if up else (e - cl[end])) / (e * sp)
    if a < b: return 1.0, R
    if b < a: return 0.0, -1.0
    return 0.5, (R - 1) / 2


def add_null(D, n=40, seed=0):
    rng = np.random.default_rng(seed); out = []
    for (sym, tf), g in D.groupby(["sym", "tf"]):
        b = B.bars(sym, tf); hi, lo, cl = b["high"].to_numpy(), b["low"].to_numpy(), b["close"].to_numpy()
        st = {"5": "2025-07-01", "60": "2023-03-01", "D": "2008-01-01"}[tf]
        base = np.flatnonzero(b.index >= st)
        g = g.copy(); nh, nr = [], []
        for r in g.itertuples():
            tp = abs(r.target / r.entry - 1); sp = abs(r.stop / r.entry - 1)
            valid = base[base < len(b) - r.H - 1]
            js = rng.choice(valid, n)
            res = [_out(hi, lo, cl, j, r.up, tp, sp, r.H) for j in js]
            nh.append(np.nanmean([x[0] for x in res]) if any(np.isfinite(x[0]) for x in res) else np.nan)
            nr.append(np.nanmean([x[1] for x in res]))
        g["null_hit"] = nh; g["null_r"] = nr
        out.append(g)
    D = pd.concat(out)
    D["grp"] = np.where(D.sym.isin(L7.ORIG), "orig15", "new30")
    D["skill_hit"] = D.hit - D.null_hit
    D["skill_r"] = D.r - D.null_r
    return D


VARIANTS = {"A_all": lambda d: d.index == d.index,
            "B_parent": lambda d: d.p_agree == True,
            "C_parent_grand": lambda d: (d.p_agree == True) & (d.g_agree == True),
            "D_inner5": lambda d: d.inner > 0,
            "E_all_filters": lambda d: (d.p_agree == True) & (d.g_agree == True) & (d.inner > 0)}


def stat(x):
    x = x.dropna(subset=["r"])
    if len(x) < 3: return pd.Series(dict(n=len(x)))
    day = x.groupby(x.t.dt.normalize()).skill_r.mean()
    return pd.Series(dict(n=len(x), hit=x.hit.mean(), null_hit=x.null_hit.mean(), skill_hit=x.skill_hit.mean(),
                          r=x.r.mean(), null_r=x.null_r.mean(), skill_r=x.skill_r.mean(),
                          t=day.mean() / day.std(ddof=1) * np.sqrt(len(day)) if len(day) > 2 else np.nan))


def verdict(D):
    rows = []
    for (tf, setup), g in D.groupby(["tf", "setup"]):
        for v, f in VARIANTS.items():
            x = g[f(g)]
            s = stat(x)
            cells = {f"{gr}_{'up' if u else 'dn'}": stat(y) for (gr, u), y in x.groupby(["grp", "up"])}
            ok = (s.get("skill_hit", -1) >= 0.05 and s.get("skill_r", -1) > 0 and s.get("t", 0) >= 2 and
                  len(cells) == 4 and all(c.get("skill_hit", -1) >= 0 for c in cells.values()))
            r = dict(tf=tf, setup=setup, variant=v, PASS=ok, **{k: s.get(k) for k in ("n", "hit", "null_hit", "skill_hit", "r", "null_r", "skill_r", "t")})
            for k, c in cells.items(): r[f"{k}_skill"] = c.get("skill_hit"); r[f"{k}_n"] = c.get("n")
            rows.append(r)
    return pd.DataFrame(rows)


def load():
    fs = sorted(glob.glob("results/wave/setups_*_*.pkl"))
    return pd.concat([pd.read_pickle(f) for f in fs], ignore_index=True)
