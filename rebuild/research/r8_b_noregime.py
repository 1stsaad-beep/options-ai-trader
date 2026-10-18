"""Round 8 — B without the bear-market regime (pre-declared extra development: the literal regime leaves
no testable sample). Everything else literal. python r8_b_noregime.py -> results/r8/B_NOREGIME.md"""
import numpy as np, pandas as pd
import r7_lib as L7, r8_run as M, r8_dev as Dv, r4_real_options as R
from r4_common import costs
syms = ["SPY", "QQQ", "IWM"]
Dt = M.Data(syms); c1 = costs(Dt.daily)
L = ["# Strategy B without the bear-market regime (backtested)", "", *L7.HDR]
for kw in (dict(regime=False), dict(regime=False, breadth_min=5, drop=0.3, vol_mult=1.2)):
    sigs = M.signals("B", Dt, syms, **kw)
    b = {s: Dt.m5[s] for s in syms}
    L.append(f"| **{kw}** — signals {sum(int((f['dir']!=0).sum()) for f in sigs.values())} | | | | | | | | |")
    for pn, per in (("model discovery", M.DISC), ("model validation", M.VALID), ("model holdout", M.HOLD)):
        tr, _ = Dv.RUN(b, sigs, Dv.cfg("B", False), Dt, c1, per)
        L.append(L7.row(f"{pn} — no contract filters", M.tstats([t.net_ret for t in tr])))
        mv = [t.direction * (t.exit_spot - t.entry_spot) / t.entry_spot * 100 for t in tr]
        if mv: L.append(f"| ↳ underlying move/trade {np.mean(mv):+.3f}% (n {len(mv)}) | | | | | | | | |")
    tr, _ = Dv.RUN(b, sigs, Dv.cfg("B", False), Dt, c1, M.REAL)
    rows = M.real_filters("B", L7.replay_path(tr, {s: (R.stock_daily(s, "raw") / R.stock_daily(s, "all")).dropna() for s in syms}), Dt)
    L.append(L7.row("REAL 2024-26 — all matched", L7.stats(M.realize_list(rows, only_pass=False))))
    L.append(L7.row("REAL 2024-26 — with report's contract filters", L7.stats(M.realize_list(rows))))
open("results/r8/B_NOREGIME.md", "w").write("\n".join(L)); print("\n".join(L))
