"""Round 7 — one pre-declared hypothesis test after the diagnosis (declared here before running):
the edge of buying short-term oversold/breakout Calls exists only in relative-strength LEADERS.
Leader = previous close > SMA200 AND 126-day return > SPY's 126-day return (both from the previous day).
Caveat: formulated after seeing that the original 15 (all long-term leaders) worked and the new 30 did not.
python r7_leader.py -> results/r7/LEADER.md"""
import numpy as np, pandas as pd
import r7_lib as L7
from oat_research import indicators as ind, strat6 as S6
from r4_common import load_daily

d1all, _ = load_daily()
spy = d1all["SPY"]["close"]
L = ["# Leader filter (pre-declared hypothesis test, real option prices 2024-02 → 2026-10)", "", *L7.HDR]
for uname in ("orig", "new"):
    U = L7.Universe(uname)
    for name in ("MTF-RSI Call", "Squeeze-Breakout Call (daily @15:50)", "Trend-Dip Call @15:50"):
        fn, base = L7.CANDIDATES[name]
        bars, sigs, bm = fn(U)
        for s in U.syms:
            c = U.full[s]["close"]
            sp = spy.reindex(c.index).ffill()
            leader = (c > ind.sma(c, 200)) & (c / c.shift(126) > sp / sp.shift(126))
            lv = S6._prev_daily(leader, sigs[s])
            sigs[s].loc[~(lv == True), "dir"] = 0
        tr, _ = L7.SD.run(bars, sigs, L7.cfg(name, bm, base["delta"], base["md"], base["ex"]), U.full, U.ivs, L7.costs(U.full), *L7.REAL)
        df = L7.realize(L7.replay_path(tr, U.factor))
        L.append(L7.row(f"{uname} — {name} + leader", L7.stats(df)))
        for lo, hi, nm in ((pd.Timestamp("2000-01-01"), L7.DEV_END, "2024-02→2025-06"), (L7.DEV_END, pd.Timestamp("2030-01-01"), "2025-07→2026-10")):
            L.append(L7.row(f"   ↳ {nm}", L7.stats(df[(df.entry > lo) & (df.entry <= hi)] if len(df) else df)))
        print(L[-3], flush=True)
open("results/r7/LEADER.md", "w").write("\n".join(L)); print("\n".join(L))
