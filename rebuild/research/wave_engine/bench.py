"""Count-recovery benchmark on synthetic series: does the counter put the TRUE top-degree count first / in the top 2?"""
from __future__ import annotations
import numpy as np
import pandas as pd
from . import synth as S, pivots as PV, count as C, gen as G


def engine_bounds(z):
    out = []
    for j, (pat, idx) in enumerate(z.parts):
        for m, i in enumerate(idx[1:]):
            out.append((int(z.bx[i]), pat, __import__("wave_engine.patterns", fromlist=["x"]).labels(pat)[m]))
    return out


def norm_pat(p):
    return {"IMPULSE": "M", "LEADING_DIAG": "M", "ENDING_DIAG": "M"}.get(p, p)


def match(z, truth, tol):
    eb = engine_bounds(z)
    tb = list(zip(truth["bounds"][1:], truth["labels"]))
    if len(eb) != len(tb): return False
    for (bi, pat, lab), (ti, (tp, tl)) in zip(eb, tb):
        if lab != tl or abs(bi - ti) > tol: return False
        if norm_pat(pat) != norm_pat(tp) and not (tp == "FLAT" and pat == "FLAT"): return False
    return True


def state_match(z, truth, tol):
    """what matters for trading: same current wave label/pattern family and same start of the current leg."""
    eb = engine_bounds(z)
    if len(eb) < 2: return False
    (b_prev, _, _), (b_now, pat, lab) = eb[-2], eb[-1]
    tp, tl = truth["labels"][-1]
    return lab == tl and norm_pat(pat) == norm_pat(tp) and abs(b_prev - truth["bounds"][-2]) <= tol


def ranked(df, scorer=None, top=0, bottom_up=False, bu_top=25):
    out = []
    for k in G.adaptive_ks(df, "D"):
        pv = PV.zigzag(df, k, tf="D")
        out += C.count(pv, start=0 if len(pv) else None, top=top)
    if scorer: 
        for z in out: z.score = scorer(z, df)
    out.sort(key=lambda z: -z.score)
    # de-duplicate identical labelings across k
    seen, res = set(), []
    for z in out:
        key = tuple(engine_bounds(z)); key = tuple((round(b / 3), p, l) for b, p, l in key)
        if key in seen: continue
        seen.add(key); res.append(z)
    if bottom_up:
        from .bottomup import rescore
        res = rescore(res, df, top=bu_top)
    return res


def run(n_seeds=12, depth=2, noise=0.25, scorer=None, cases=None, bottom_up=False):
    rows = []
    for case in (cases or S.CASES):
        for seed in range(n_seeds):
            df, truth = S.make(case, seed, depth, noise)
            tol = max(2, int(0.02 * len(df)))
            sc = ranked(df, scorer, bottom_up=bottom_up)
            pos = next((i for i, z in enumerate(sc) if match(z, truth, tol)), None)
            spos = next((i for i, z in enumerate(sc) if state_match(z, truth, tol)), None)
            rows.append(dict(case=case, seed=seed, bars=len(df), n_scen=len(sc), rank=pos, srank=spos))
    R = pd.DataFrame(rows)
    S_ = R.groupby("case").agg(top1=("rank", lambda r: (r == 0).mean()), top2=("rank", lambda r: (r <= 1).mean()),
                               found=("rank", lambda r: r.notna().mean()), scen=("n_scen", "mean"),
                               now1=("srank", lambda r: (r == 0).mean()), now2=("srank", lambda r: (r <= 1).mean()))
    return R, S_
