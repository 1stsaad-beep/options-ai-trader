"""Round 5 — the LITERAL MTF Elliott call rule on 5-minute grandchildren: options (model + real).
python r5_wave_literal_opt.py -> results/r5/WAVE_LITERAL_OPT.md"""
import json
from dataclasses import replace
import numpy as np, pandas as pd
import r4_real_options as R
from oat_research import setups4 as S4, shortdated as SD, indicators as ind
from r4_common import costs, fmt
from r5_common import DISC, VALID, HOLD, SYMS, load
from r5_options import cfg_for, implied_vol, RDEV, RTEST

m5, full, vols = load()
ivs = SD.iv_table(full, vols)
c1 = costs(full)
cand = pd.read_pickle("results/r5/wave_cand_5.pkl")
cand["div_any"] = cand.div_any.astype(bool)
lit = cand[(cand.dir == 1) & (cand.d_dir == 1) & cand.d_wave.isin(["1", "3", "5"]) & (cand.h_dir == 1) & (cand.h_wave == "3") & cand.div_any]
sigs = {}
for s in SYMS:
    c = lit[lit.sym == s]
    d = np.zeros(len(m5[s]), int); d[c.t.astype(int).to_numpy()] = 1
    sigs[s] = S4.frame(m5[s], d, reason=np.where(d != 0, "MTF Elliott literal", ""))
L = ["# MTF Elliott literal Call rule (5-min grandchildren) — options", "", "| config | period | n | win | exp/trade (model) | t(week) |", "|---|---|---|---|---|---|"]
for cfg in [(0.5, 2, (0.75, 1.0, 52)), (0.5, 5, (1.0, 1.0, 104)), (0.7, 2, (0.75, 1.0, 52))]:
    c = cfg_for(*cfg)
    c = replace(c, bar_minutes=5, exits=replace(c.exits, max_hold_bars=cfg[2][2] * 3))
    for pn, per in (("DISC", DISC), ("VALID", VALID), ("HOLD", HOLD)):
        sm = SD.summarize(*SD.run(m5, sigs, c, full, ivs, c1, *per))
        L.append(f"| {cfg} | {pn} | {sm['n']} | {fmt(sm.get('win'))} | {fmt(sm.get('exp'), True)} | {fmt(sm.get('t_week'))} |")
        print(L[-1], flush=True)
factor = {s: (R.stock_daily(s, "raw") / R.stock_daily(s, "all")).dropna() for s in SYMS}
c = cfg_for(0.5, 2, (0.75, 1.0, 52)); c = replace(c, bar_minutes=5, exits=replace(c.exits, max_hold_bars=156))
tr, _ = SD.run(m5, sigs, c, full, ivs, c1, RDEV[0], RTEST[1])
df = R.replay(tr, factor); R.CACHE.write_text(json.dumps(R.cache))
ok = df[df.status == "ok"]
L += ["", f"Real option prices 2024-02 → 2026-10 (delta 0.5, min 2 days, +0.75/−1 ATR, 2 days): n {len(ok)}, REAL exp {fmt(ok.real.mean(), True)}, "
      f"@VWAP {fmt(ok.real_vwap.mean(), True)}, win {fmt((ok.real > 0).mean())}, model {fmt(ok.model.mean(), True)}"]
open("results/r5/WAVE_LITERAL_OPT.md", "w").write("\n".join(L)); print(L[-1])
