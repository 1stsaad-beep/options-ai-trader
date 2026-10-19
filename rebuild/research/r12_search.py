"""Round 12 step 3: combination search on DISCOVERY only (group-A symbols, before 2024).
Outcome of a signal = a ±5 % bracket from the bar close up to the close of the next session:
  long:  +5 % if +5 % is touched first, -5 % if -5 % first, else the return at the horizon close (short = mirror).
For every single / pair / triple of features: n, P(target first), P(stop first), mean outcome E, and E in each half
(2020-21, 2022-23).  python r12_search.py 15 30 60  -> results/r12/search_<F>.csv"""
import sys
from itertools import combinations
from pathlib import Path
import numpy as np, pandas as pd

OUT = Path("results/r12")
FAM = ("t_", "m_", "v_", "vo_", "p_", "c_")


def fam(c):
    return next(p for p in sorted(FAM, key=len, reverse=True) if c.startswith(p))


def outcome(P):
    o = np.where(P.up_next, 0.05, np.where(P.dn_next, -0.05, P.ret_next.clip(-0.05, 0.05)))
    return o.astype(np.float32)


def search(F, min_n=300, top=40):
    P = pd.read_pickle(OUT / f"panel_{F}.pkl")
    P = P[(P.grp == "A") & (P.t < "2024-01-01")].reset_index(drop=True)
    cols = [c for c in P.columns if c.startswith(FAM)]
    X = P[cols].to_numpy(np.float32); K = len(cols)
    o = outcome(P); up = P.up_next.to_numpy(np.float32); dn = P.dn_next.to_numpy(np.float32)
    h1 = (P.t < "2022-01-01").to_numpy(np.float32); h2 = 1 - h1
    base = dict(n=len(P), up=up.mean(), dn=dn.mean(), E=o.mean())
    print(F, "discovery rows", len(P), "base", {k: round(float(v), 4) for k, v in base.items()}, flush=True)
    rows = []
    for d, sgn, hit, miss in (("LONG", 1, up, dn), ("SHORT", -1, dn, up)):
        od = sgn * o
        W = np.stack([np.ones_like(od), od, hit, miss, h1, od * h1, h2, od * h2], 1)    # weights per row
        # singles + pairs: M[i,j,w] = sum_r X[r,i] X[r,j] W[r,w]
        if True:
            M = np.zeros((K, K, W.shape[1]), np.float32)
            for w in range(W.shape[1]):
                M[:, :, w] = X.T @ (X * W[:, [w]])
        def rec(idx, v):
            n, s, ht, ms, n1, s1, n2, s2 = v
            if n < min_n or n1 < min_n / 3 or n2 < min_n / 3: return
            rows.append(dict(dir=d, combo=" + ".join(cols[i] for i in idx), k=len(idx), n=int(n), p_hit=ht / n, p_miss=ms / n,
                             E=s / n, E_h1=s1 / n1, E_h2=s2 / n2))
        for i in range(K):
            rec((i,), M[i, i])
            for j in range(i + 1, K):
                rec((i, j), M[i, j])
        # triples among features that appear in a decent pair
        R = pd.DataFrame([r for r in rows if r["dir"] == d and r["k"] == 2])
        R["score"] = np.minimum(R.E_h1, R.E_h2)
        keep = sorted({cols.index(c) for cb in R.nlargest(150, "score").combo for c in cb.split(" + ")})
        for i in keep:
            m = X[:, i] > 0
            Xi = X[m][:, keep]; Wi = W[m]
            Mi = np.zeros((len(keep), len(keep), W.shape[1]), np.float32)
            for w in range(W.shape[1]):
                Mi[:, :, w] = Xi.T @ (Xi * Wi[:, [w]])
            for a, b in combinations(range(len(keep)), 2):
                j, k = keep[a], keep[b]
                if i < j < k and len({fam(cols[i]), fam(cols[j]), fam(cols[k])}) >= 2:
                    rec((i, j, k), Mi[a, b])
        print(F, d, "rows so far", len(rows), flush=True)
    R = pd.DataFrame(rows); R["score"] = np.minimum(R.E_h1, R.E_h2); R["frame"] = F
    for k, v in base.items(): R[f"base_{k}"] = v
    R.sort_values("score", ascending=False).to_csv(OUT / f"search_{F}.csv", index=False)
    for d in ("LONG", "SHORT"):
        print(R[R.dir == d].nlargest(top, "score")[["combo", "n", "p_hit", "p_miss", "E", "E_h1", "E_h2"]].round(4).to_string(index=False))
    return R


if __name__ == "__main__":
    for F in map(int, sys.argv[1:] or ["15", "30", "60"]):
        search(F)
