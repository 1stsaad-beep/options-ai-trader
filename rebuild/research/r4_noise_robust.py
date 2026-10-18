"""Robustness of noise-area momentum (SPY/QQQ, 5-min): instrument regime, IV level, side, year."""
import numpy as np, pandas as pd
from oat_research import data as D, intraday4 as I4, setups4 as S4, shortdated as SD
from r4_common import costs, fmt, load_daily, OUT
from r4_intraday2 import cfg_for

d1, vols = load_daily()
syms = ("SPY", "QQQ")
m5 = {s: D.load_csv(f"data/m5a/{s}.csv") for s in syms}
full = {s: I4.daily_asof(df, "16:00", d1[s]) for s, df in m5.items()}
ivs = SD.iv_table(full, vols)
v1 = vols["VIX1D"] / 100
ivs_1d = {}
for s in syms:
    base = ivs[s].copy()
    alt = v1.reindex(base.index).ffill(limit=3)
    if s == "QQQ":
        alt = alt * (vols["VXN"] / vols["VIX"]).reindex(base.index).ffill()
    ivs_1d[s] = alt.fillna(base).clip(lower=0.08)
c1 = costs(full)
sigs = {s: S4.noise_momentum(m5[s]) for s in syms}
cfg = cfg_for("noise", 0.7, None)
L = ["# Noise-area momentum — robustness", "", "| variant | n | win | exp/trade | PF | t(week) |", "|---|---|---|---|---|---|"]
def row(name, tr, nav=None):
    sm = SD.summarize(tr, nav)
    L.append(f"| {name} | {sm['n']} | {fmt(sm.get('win'))} | {fmt(sm.get('exp'), True)} | {fmt(sm.get('pf_cash'))} | {fmt(sm.get('t_week'))} |")
    print(L[-1], flush=True)
P0 = pd.Timestamp("2021-01-01"); P1 = pd.Timestamp("2022-11-15"); P2 = pd.Timestamp("2026-04-15 23:59")
tr, nav = SD.run(m5, sigs, cfg, full, ivs, c1, P0, P2)
row("validation, base", tr, nav)
row("2021-01 → 2022-11 (weekly expiries)", [t for t in tr if t.entry_time < P1])
row("2022-11 → 2026-04 (0-DTE)", [t for t in tr if t.entry_time >= P1])
row("calls only", [t for t in tr if t.direction > 0]); row("puts only", [t for t in tr if t.direction < 0])
row("SPY only", [t for t in tr if t.symbol == "SPY"]); row("QQQ only", [t for t in tr if t.symbol == "QQQ"])
for y in range(2021, 2027):
    row(f"year {y}", [t for t in tr if t.entry_time.year == y])
tr2, nav2 = SD.run(m5, sigs, cfg, full, ivs_1d, c1, P1, P2); row("0-DTE period, IV = VIX1D-based", tr2, nav2)
ivb = {s: v * 1.25 for s, v in ivs.items()}
tr3, nav3 = SD.run(m5, sigs, cfg, full, ivb, c1, P1, P2); row("0-DTE period, IV x1.25", tr3, nav3)
cfg05 = cfg_for("noise", 0.5, None)
tr4, nav4 = SD.run(m5, sigs, cfg05, full, ivs, c1, P1, P2); row("0-DTE period, delta 0.5", tr4, nav4)
# underlying-only check (does the signal move price, independent of option model?)
und = np.array([t.direction * (t.exit_spot / t.entry_spot - 1) for t in tr])
L += ["", f"Underlying move per trade (validation): mean {und.mean()*100:+.3f}%, win {(und>0).mean():.2f}, n {len(und)}"]
(OUT / "NOISE_ROBUST.md").write_text("\n".join(L), encoding="utf-8")
print(L[-1])
