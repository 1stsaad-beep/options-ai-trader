"""Round 4 harness check for the weekly-option engine: null data must not show an edge,
a planted edge must be detected. python r4_validate.py -> results/r4/VALIDATE.md"""
import numpy as np, pandas as pd
from oat_research import data as D, indicators as ind, setups4 as S4, shortdated as SD, options_model as om
from r4_common import OUT, fmt

def rule(df):
    r = np.log(df["close"]).diff()
    comp = r.rolling(10).std() < 0.75 * r.rolling(60).std()
    hi = df["close"] >= df["close"].rolling(20).max()
    sig = comp & hi
    return S4.frame(df, np.where(sig, 1, 0), reason=np.where(sig, "planted rule", ""))

def rand(df, seed):
    rng = np.random.default_rng(seed)
    d = np.where(rng.random(len(df)) < 0.03, rng.choice([-1, 1], len(df)), 0)
    return S4.frame(df, d)

L = ["# Weekly-option engine — harness validation (synthetic data, 10 series × 3000 days)", "",
     "| data | signal | n | exp/trade | t(week) | underlying move 3d (ATR) |", "|---|---|---|---|---|---|"]
for edge in (0.0, 0.004):
    data = {f"S{i}": D.synthetic(3000, seed=i, planted_edge=edge) for i in range(10)}
    vols = {}
    ivs = {s: (1.10 * (0.5 * ind.realized_vol(df["close"], 20) + 0.5 * ind.realized_vol(df["close"], 60))).clip(lower=0.08) for s, df in data.items()}
    costs = {s: om.OptionCosts(spread_pct=0.03) for s in data}
    for name, mk in (("planted rule", rule), ("random 3%", lambda df: rand(df, 7))):
        sigs = {s: mk(df) for s, df in data.items()}
        cfg = SD.SDConfig("v", SD.SDExit(target_atr=None, stop_atr=None, max_hold_bars=3), target_delta=0.6, min_days=5, max_open=10)
        tr, nav = SD.run(data, sigs, cfg, data, ivs, costs)
        sm = SD.summarize(tr, nav)
        mv = []
        for s, df in data.items():
            a = ind.atr(df).to_numpy(); o, c = df["open"].to_numpy(), df["close"].to_numpy()
            for i in np.flatnonzero(sigs[s]["dir"].to_numpy() != 0):
                if i + 3 < len(df): mv.append(sigs[s]["dir"].iloc[i] * (c[i + 3] - o[i + 1]) / a[i])
        L.append(f"| {'planted edge' if edge else 'null (no edge)'} | {name} | {sm['n']} | {fmt(sm.get('exp'), True)} | {fmt(sm.get('t_week'))} | {np.mean(mv):+.2f} |")
        print(L[-1], flush=True)
(OUT / "VALIDATE.md").write_text("\n".join(L), encoding="utf-8")
