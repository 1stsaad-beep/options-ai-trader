"""Round 4b: same signals, longer expiries, real prices (2024-02 -> 2026-10). Is the
'< 1 week' constraint what destroys the edge?  python r4_real_dte.py -> results/r4/REAL_DTE.md"""
import json
import numpy as np, pandas as pd
import r4_real_options as R
from r4_real_dev import trades_for, stats
from r4_final import build
from r4_common import OUT, fmt
B = build()
factor = {s: (R.stock_daily(s, "raw") / R.stock_daily(s, "all")).dropna() for s in B["full"]}
P = (pd.Timestamp("2024-02-05"), pd.Timestamp("2026-10-16 23:59"))
L = ["# Same signals, longer expiries — real option prices 2024-02 → 2026-10", "",
     "| strategy | expiry ≥ entry + | delta | n | REAL exp | @VWAP | win | t | model exp | underlying move/trade |", "|---|---|---|---|---|---|---|---|---|---|"]
runs = [("A Trend-dip @15:50", dict(min_days=md, delta=dl)) for md in (2, 7, 14, 28) for dl in (0.5, 0.7)]
runs += [("Pre-FOMC (ETFs)", dict(delta=0.5, exit_at="12:00", min_days=md)) for md in (2, 14, 28)]
out = {}
for name, kw in runs:
    tr = trades_for(B, name, kw, P)
    if name.startswith("Pre-FOMC") and kw["min_days"] != 2:
        # pre-FOMC frames carry min_days=2 per signal: re-run with the override
        from r4_real_dev import pre_fomc_sigs, make_cfg
        from oat_research import shortdated as SD
        from r4_common import costs
        sigs = pre_fomc_sigs(B, kw["exit_at"])
        for s in sigs: sigs[s]["min_days"] = np.where(sigs[s]["dir"] != 0, kw["min_days"], np.nan)
        tr, _ = SD.run({s: B["seg"][s] for s in sigs}, sigs, make_cfg(name, kw), B["full"], B["ivs"], costs(B["full"]), *P)
    df = R.replay(tr, factor)
    R.CACHE.write_text(json.dumps(R.cache))
    st = stats(df)
    und = np.mean([t.direction * (t.exit_spot / t.entry_spot - 1) for t in tr]) * 100
    L.append(f"| {name} | {kw.get('min_days')} days | {kw.get('delta')} | {st['n']} | {fmt(st['exp'], True)} | {fmt(st['vw'], True)} | {fmt(st['win'])} | {fmt(st['t'])} | {fmt(st['model'], True)} | {und:+.2f}% |")
    out[(name, json.dumps(kw))] = df
    print(L[-1], flush=True)
(OUT / "REAL_DTE.md").write_text("\n".join(L), encoding="utf-8")
pd.to_pickle(out, OUT / "real_dte.pkl")
