"""Round 6 — adjacent thresholds (model validation 2021-2026/04 and REAL 2024-2026).
python r6_adjacent.py -> results/r6/ADJACENT.md"""
import numpy as np, pandas as pd
import r6_run as M
from oat_research import shortdated as SD
from r4_common import costs
from r5_common import VALID

VARIANTS = {
    "S1 MTF-Momentum Call": [dict(), dict(rsi_lo=25), dict(rsi_lo=35), dict(h_max=30), dict(h_max=40), dict(adx_min=15), dict(vol_mult=1.0),
                             dict(confirm=False)],
    "S2 Downtrend-Regime Put": [dict(), dict(ob=75, cross=70), dict(ob=65, cross=60), dict(adx_min=20), dict(adx_min=30), dict(vol_mult=1.0)],
    "S3 Squeeze-Breakout Call (60m)": [dict(), dict(pct=0.10), dict(pct=0.30), dict(vol_mult=1.2), dict(vol_mult=2.0)],
    "S3 Squeeze-Breakout Call (daily @15:50)": [dict(), dict(pct=0.10), dict(pct=0.30), dict(vol_mult=1.2), dict(vol_mult=2.0)],
}
L = ["# Round 6 — adjacent thresholds (backtested)", "", "| strategy | variant | model validation n / return | REAL n / return | REAL t |", "|---|---|---|---|---|"]
for name, vs in VARIANTS.items():
    for kw in vs:
        bars, sigs = M.signals(name, **kw)
        tr, _ = SD.run(bars, sigs, M.cfg(name), M.full, M.ivs, costs(M.full), *VALID)
        mv = M.tstats([t.net_ret for t in tr])
        ok, _ = M.real(name, bars, sigs)
        rv = M.tstats(ok.real) if len(ok) else dict(n=0)
        f = lambda st, k: M.fmt(st.get(k), k == "exp") if st["n"] >= 3 else "—"
        L.append(f"| {name} | {kw or 'as specified'} | {mv['n']} / {f(mv, 'exp')} | {rv['n']} / {f(rv, 'exp')} | {f(rv, 't')} |")
        print(L[-1], flush=True)
open("results/r6/ADJACENT.md", "w").write("\n".join(L))
