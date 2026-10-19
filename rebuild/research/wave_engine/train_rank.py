"""Learning-to-rank on synthetic series with known counts: conditional-logit (softmax over the candidates of one
chart) on scenario features.  Train seeds and test seeds are disjoint.  Output: results/wave/rank_weights.json"""
from __future__ import annotations
import json, sys, time
from pathlib import Path
import numpy as np
import pandas as pd
from . import synth as S, bench as BN, patterns as PT

OUT = Path("results/wave"); OUT.mkdir(parents=True, exist_ok=True)


def featurize(z):
    f = {}
    for j, (pat, idx) in enumerate(z.parts):
        f[f"p{j}_{pat}"] = 1.0
        f[f"p{j}_legs"] = len(idx) - 1
    for k, v in z.feats.items():
        f[k] = float(v)
    f["n_parts"] = len(z.parts)
    f["irregular"] = float(getattr(z, "irr", 0))
    f["prior_score"] = float(z.score)
    return f


def collect(seeds, depths=(2, 3), noises=(0.25, 0.5), path=None):
    rows = []
    for depth in depths:
        for noise in noises:
            for case in S.CASES:
                for seed in seeds:
                    df, t = S.make(case, seed, depth, noise)
                    tol = max(2, int(0.02 * len(df)))
                    sc = BN.ranked(df, bottom_up=True, bu_top=60)[:60]
                    for r, z in enumerate(sc):
                        f = featurize(z)
                        f.update(inst=f"{case}|{seed}|{depth}|{noise}", y=float(BN.match(z, t, tol)), ys=float(BN.state_match(z, t, tol)), rank0=r)
                        rows.append(f)
                print(depth, noise, case, len(rows), flush=True)
                if path: pd.DataFrame(rows).to_pickle(path)
    return pd.DataFrame(rows)


def fit(D, target="ys", l2=0.3, iters=400, lr=0.05):
    cols = [c for c in D.columns if c not in ("inst", "y", "ys", "rank0", "prior_score")]
    X = D[cols].fillna(0).to_numpy(float); mu = X.mean(0); sd = X.std(0) + 1e-9; Xs = (X - mu) / sd
    groups = D["inst"].to_numpy(); y = D[target].to_numpy()
    keep = pd.Series(y).groupby(groups).transform("max").to_numpy() > 0       # instances where a true count exists
    Xs, y, groups = Xs[keep], y[keep], groups[keep]
    gi = pd.factorize(groups)[0]; G = gi.max() + 1
    w = np.zeros(Xs.shape[1])
    for it in range(iters):
        s = Xs @ w
        s = s - pd.Series(s).groupby(gi).transform("max").to_numpy()
        e = np.exp(s); Z = np.bincount(gi, e, G)[gi]; p = e / Z
        # target distribution: uniform over the true candidates of each instance
        tz = np.bincount(gi, y, G)[gi]; q = np.where(y > 0, y / np.maximum(tz, 1), 0)
        g = Xs.T @ (p - q) / G + l2 * w / G
        w -= lr * g * 50
    return dict(cols=cols, w=w.tolist(), mu=mu.tolist(), sd=sd.tolist())


def evaluate(D, model, target="ys"):
    X = D[model["cols"]].fillna(0).to_numpy(float); s = ((X - np.array(model["mu"])) / np.array(model["sd"])) @ np.array(model["w"])
    D = D.assign(s=s)
    res = {}
    for name, key in (("hand", "rank0"), ("learned", "s")):
        asc = name == "hand"
        top = D.sort_values(key, ascending=asc).groupby("inst").head(1)
        top2 = D.sort_values(key, ascending=asc).groupby("inst").head(2).groupby("inst")[target].max()
        res[name] = dict(top1=top[target].mean(), top2=top2.mean(), n=D.inst.nunique())
    return res


if __name__ == "__main__":
    if sys.argv[1:] == ["train"]:
        collect(range(0, 14), path=OUT / "rank_train.pkl"); sys.exit()
    if sys.argv[1:] == ["test"]:
        collect(range(100, 106), path=OUT / "rank_test.pkl"); sys.exit()
    tr = pd.read_pickle(OUT / "rank_train.pkl"); te = pd.read_pickle(OUT / "rank_test.pkl")
    for target in ("ys", "y"):
        m = fit(tr, target)
        json.dump(m, open(OUT / f"rank_weights_{target}.json", "w"))
        print(target, "train", evaluate(tr, m, target), "test", evaluate(te, m, target))
