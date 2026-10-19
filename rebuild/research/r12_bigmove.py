"""Round 12b: NON-directional version — combinations after which the stock moves >=5 % in EITHER direction
(touches +5 % or -5 % before the close of the next session).  Discovery = group A, 2020-2023 only.
Selection metric: P(big move) per signal day, robust over 2 time halves x 2 symbol halves (one signal per symbol-day)."""
import numpy as np, pandas as pd
from itertools import combinations
from pathlib import Path
OUT = Path("results/r12"); FAM = ("t_", "m_", "v_", "vo_", "p_", "c_")
rows = []
for F in (15, 30, 60):
    P = pd.read_pickle(OUT / f"panel_{F}.pkl"); P = P[(P.grp == "A") & (P.t < "2024-01-01")].reset_index(drop=True)
    P["day"] = P.t.dt.normalize()
    # one row per symbol-day for the search? keep bars but weight each bar by 1/(bars of that combo that day) is complex -> use bars, then re-check per day
    cols = [c for c in P.columns if c.startswith(FAM)]
    X = P[cols].to_numpy(np.float32); big = (P.up_next | P.dn_next).to_numpy(np.float32)
    h1 = (P.t < "2022-01-01").to_numpy(np.float32)
    W = np.stack([np.ones_like(big), big, h1, big * h1], 1)
    M = np.stack([X.T @ (X * W[:, [w]]) for w in range(4)], -1)
    K = len(cols); base = big.mean()
    cand = []
    for i in range(K):
        for j in range(i, K):
            n, b, n1, b1 = M[i, j]
            if n >= 400 and n1 >= 130 and n - n1 >= 130:
                cand.append(((i,) if i == j else (i, j), min(b1 / n1, (b - b1) / (n - n1)), n))
    top = sorted({c for cb, _, _ in sorted(cand, key=lambda x: -x[1])[:120] for c in cb})
    for i in top:
        m = X[:, i] > 0; Xi = X[m][:, top]; Wi = W[m]
        Mi = np.stack([Xi.T @ (Xi * Wi[:, [w]]) for w in range(4)], -1)
        for a, b_ in combinations(range(len(top)), 2):
            j, k = top[a], top[b_]
            if i < j < k:
                n, b, n1, b1 = Mi[a, b_]
                if n >= 400 and n1 >= 130 and n - n1 >= 130:
                    cand.append(((i, j, k), min(b1 / n1, (b - b1) / (n - n1)), n))
    cand = sorted(cand, key=lambda x: -x[1])[:400]
    syms = sorted(P.sym.unique()); sh = P.sym.map({s: k % 2 for k, s in enumerate(syms)}).astype(int).to_numpy()
    th = (P.t >= "2022-01-01").astype(int).to_numpy()
    for cb, sc, n in cand:
        m = np.logical_and.reduce([X[:, c] > 0 for c in cb])
        T = pd.DataFrame({"sym": P.sym[m].to_numpy(), "day": P.day[m].to_numpy(), "big": big[m], "sh": sh[m], "th": th[m],
                          "up": P.up_next[m].to_numpy(), "dn": P.dn_next[m].to_numpy()}).groupby(["sym", "day"]).head(1)
        cell = T.groupby(["sh", "th"]).big.agg(["mean", "size"])
        if len(cell) < 4 or cell["size"].min() < 25: continue
        rows.append(dict(frame=F, combo=" + ".join(cols[c] for c in cb), k=len(cb), sym_days=len(T), days=T.day.nunique(),
                         p_big=T.big.mean(), p_up=T.up.mean(), p_dn=T.dn.mean(), cell_min=cell["mean"].min(), base=base))
    print(F, len(rows), "base", round(base, 3), flush=True)
R = pd.DataFrame(rows).sort_values("cell_min", ascending=False); R.to_csv(OUT / "bigmove_search.csv", index=False)
pd.set_option("display.width", 250); pd.set_option("display.max_colwidth", 70)
print(R.head(50).round(3).to_string(index=False))
