"""Round 12 step 3b (discovery only): robustness of the top candidates — one trade per symbol per day,
4 cells = 2 time halves x 2 symbol halves of group A.  -> results/r12/robust.csv"""
import numpy as np, pandas as pd
from pathlib import Path
from r12_search import outcome
OUT = Path("results/r12"); COST = 0.001
rows = []
for F in (15, 30, 60):
    P = pd.read_pickle(OUT / f"panel_{F}.pkl"); P = P[(P.grp == "A") & (P.t < "2024-01-01")].reset_index(drop=True)
    syms = sorted(P.sym.unique()); half = {s: i % 2 for i, s in enumerate(syms)}
    P["sh"] = P.sym.map(half).astype(int); P["th"] = (P.t >= "2022-01-01").astype(int); P["day"] = P.t.dt.normalize()
    o = outcome(P)
    S = pd.read_csv(OUT / f"search_{F}.csv")
    for d in ("LONG", "SHORT"):
        sg = 1 if d == "LONG" else -1
        for cb in S[S.dir == d].nlargest(400, "score").combo:
            fs = cb.split(" + "); m = np.logical_and.reduce([P[c].to_numpy() for c in fs])
            T = P.loc[m, ["sym", "day", "sh", "th"]].assign(o=sg * o[m] - COST).groupby(["sym", "day"], observed=True).head(1)
            if len(T) < 100: continue
            cell = T.groupby(["sh", "th"]).o.agg(["mean", "size"])
            if len(cell) < 4 or cell["size"].min() < 20: continue
            dm = T.groupby("day").o.mean()
            rows.append(dict(frame=F, dir=d, combo=cb, trades=len(T), days=len(dm), E=T.o.mean(), win=(T.o > 0).mean(),
                             cell_min=cell["mean"].min(), t_day=dm.mean() / dm.std(ddof=1) * np.sqrt(len(dm))))
    print(F, len(rows), flush=True)
R = pd.DataFrame(rows).sort_values("cell_min", ascending=False); R.to_csv(OUT / "robust.csv", index=False)
pd.set_option("display.width", 250); pd.set_option("display.max_colwidth", 70)
for d in ("LONG", "SHORT"):
    print(R[(R.dir == d)].head(30).round(4).to_string(index=False))
