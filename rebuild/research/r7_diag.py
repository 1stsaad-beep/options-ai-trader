"""Round 7 diagnosis: on the NEW universe, is the failure in the signal (underlying) or in the option cost?"""
import numpy as np, pandas as pd
import r7_lib as L7
from oat_research import setups4 as S4
from r5_common import outcomes
out = ["# Diagnosis — underlying move vs option result (2024-02 → 2026-10)", "",
       "| universe | strategy | signals | underlying close day 2 (ATR) | P(+0.5 ATR before −1 ATR, 2d) | median IV/RV20 at entry (real) |", "|---|---|---|---|---|---|"]
st = pd.read_pickle("results/r7/judge.pkl")
for uname in ("orig", "new"):
    U = L7.Universe(uname)
    for name in L7.CANDIDATES:
        fn, _ = L7.CANDIDATES[name]
        bars, sigs, bm = fn(U)
        bpd = 26 if bm == 15 else 5
        ws = [outcomes(bars[s], sigs[s], U.full[s], bpd, L7.REAL) for s in U.syms]
        w = pd.concat([x for x in ws if not x.empty])
        out.append(f"| {uname} | {name} | {len(w)} | {w.ret2.mean():+.3f} | {(w['hit0.5'] < 2).mean()*100:.0f}% | |")
    print(uname, flush=True)
# per-symbol real result, MTF-RSI base on new
df = st[("new", "MTF-RSI Call", "base")]
g = df.groupby("sym")["ret"].agg(["size", "mean"]).sort_values("mean")
out += ["", "MTF-RSI Call (base) on the new universe — real return by symbol: " + ", ".join(f"{s} {r['mean']*100:+.0f}% ({int(r['size'])})" for s, r in g.iterrows())]
open("results/r7/DIAG.md", "w").write("\n".join(out)); print("\n".join(out))
