"""Test 3 — do swing durations relate by Fibonacci ratios more than chance? (PREREG_ROUND_W2.json)"""
import numpy as np
import pandas as pd
import r7_lib as L7
from . import bars as B, pivots as PV

FIB = np.log(np.array([0.618, 1.0, 1.618, 2.618]))


def share(d):
    r = np.log(d[2:] / d[:-2])
    return np.mean(np.min(np.abs(r[:, None] - FIB[None, :]), axis=1) <= np.log(1.1)), len(r)


def run(tf, n_shuf=1000, seed=0):
    rng = np.random.default_rng(seed); obs_hits = 0; obs_n = 0; per_sym = []
    for s in L7.ORIG + L7.NEW:
        b = B.bars(s, tf)
        if tf == "D": b = b[b.index >= "2000-01-01"]
        pv = PV.zigzag(b, 2.5)
        d = np.diff(pv.i).astype(float); d = d[d > 0]
        if len(d) < 20: continue
        sh, n = share(d); obs_hits += sh * n; obs_n += n; per_sym.append(d)
    obs = obs_hits / obs_n
    null = []
    for _ in range(n_shuf):
        h = 0; n = 0
        for d in per_sym:
            sh, m = share(rng.permutation(d)); h += sh * m; n += m
        null.append(h / n)
    null = np.array(null)
    return dict(tf=tf, observed=obs, null_mean=null.mean(), null_q975=np.quantile(null, 0.975), n_ratios=obs_n,
                PASS=bool(obs > np.quantile(null, 0.975)))
