"""Round 5 — MTF-RSI Calls on REAL option prices: neighbours and robustness (2024-02 -> 2026-10).
python r5_rsi_robust.py -> results/r5/RSI_REAL_ROBUST.md"""
import json
import numpy as np, pandas as pd
import r4_real_options as R
from oat_research import mtf, setups4 as S4, shortdated as SD
from r4_common import costs, fmt
from r5_common import SYMS, load
from r5_options import cfg_for, implied_vol, RDEV, RTEST
from dataclasses import replace

m5, full, vols = load()
ivs = SD.iv_table(full, vols)
bars = {s: S4.resample(m5[s], 15) for s in SYMS}
factor = {s: (R.stock_daily(s, "raw") / R.stock_daily(s, "all")).dropna() for s in SYMS}
c1 = costs(full)
BASE_CFG = (0.5, 2, (0.75, 1.0, 52))


def run_variant(n, ob, os_, trig, cfg=BASE_CFG, ltf=15):
    b = bars if ltf == 15 else {s: S4.resample(m5[s], ltf) for s in SYMS}
    sigs = {s: mtf.mtf_rsi(m5[s], n, ob, os_, trig, ltf=ltf) for s in SYMS}
    sigs = {s: f.assign(dir=np.where(f["dir"] > 0, 1, 0)) for s, f in sigs.items()}
    c = cfg_for(*cfg)
    if ltf != 15:
        c = replace(c, bar_minutes=ltf, exits=replace(c.exits, max_hold_bars=cfg[2][2] * 15 // ltf))
    tr, _ = SD.run(b, sigs, c, full, ivs, c1, RDEV[0], RTEST[1])
    df = R.replay(tr, factor)
    R.CACHE.write_text(json.dumps(R.cache))
    return df[df.status == "ok"].copy(), tr


def st(x):
    if len(x) < 3:
        return f"{len(x)} | — | — | — | —"
    t = x.real.mean() / x.real.std(ddof=1) * np.sqrt(len(x))
    return f"{len(x)} | {fmt(x.real.mean(), True)} | {fmt(x.real_vwap.mean(), True)} | {fmt((x.real > 0).mean())} | {t:.2f}"


L = ["# MTF-RSI Calls — real option prices, neighbours and robustness (2024-02 → 2026-10)", "",
     "## Neighbouring parameters (same contract/exit rule)", "", "| variant | n | REAL exp | @VWAP | win | t |", "|---|---|---|---|---|---|"]
for n, ob, os_, trig, ltf in [(14, 75, 25, "reentry", 15), (14, 70, 30, "reentry", 15), (14, 80, 20, "reentry", 15), (9, 75, 25, "reentry", 15),
                               (14, 75, 25, "fail", 15), (14, 70, 30, "div", 15), (9, 70, 30, "reentry", 15), (14, 70, 30, "reentry", 5)]:
    ok, tr = run_variant(n, ob, os_, trig, ltf=ltf)
    L.append(f"| RSI{n} {os_} {trig} {ltf}m | {st(ok)} |")
    print(L[-1], flush=True)
    if (n, ob, os_, trig, ltf) == (14, 75, 25, "reentry", 15):
        base = ok
L += ["", "## Contract / exit neighbours (signal RSI14 25 re-entry, 15m)", "", "| delta / min days / (target, stop, bars) | n | REAL exp | @VWAP | win | t |", "|---|---|---|---|---|---|"]
for cfg in [(0.5, 5, (0.75, 1.0, 52)), (0.7, 2, (0.75, 1.0, 52)), (0.5, 2, (0.5, 1.0, 26)), (0.5, 2, (1.0, 1.0, 104))]:
    ok, _ = run_variant(14, 75, 25, "reentry", cfg)
    L.append(f"| {cfg} | {st(ok)} |"); print(L[-1], flush=True)
b = base
b["year"] = b.entry.dt.year
hs2 = lambda r: (100 * r.real_exit_px * (1 - 2 * h(r)) - 0.65 - (100 * r.real_px * (1 + 2 * h(r)) + 0.65)) / (100 * r.real_px * (1 + 2 * h(r)) + 0.65)
h = lambda r: 0.015 if r.sym in ("SPY", "QQQ", "IWM") else 0.03
b["real_2x"] = [hs2(r) for r in b.itertuples()]
top = b.real.nlargest(5).index
L += ["", "## Robustness of the base variant", "", "| cut | n | REAL exp | @VWAP | win | t |", "|---|---|---|---|---|---|",
      f"| all | {st(b)} |",
      f"| double half-spread (3% ETF / 6% stock) | {len(b)} | {fmt(b.real_2x.mean(), True)} | | | |",
      f"| without the 5 best trades | {st(b.drop(top))} |",
      f"| ETFs only | {st(b[b.sym.isin(['SPY','QQQ','IWM'])])} |",
      f"| stocks only | {st(b[~b.sym.isin(['SPY','QQQ','IWM'])])} |",
      f"| without NVDA/TSLA/AMD/META | {st(b[~b.sym.isin(['NVDA','TSLA','AMD','META'])])} |"]
for y, g in b.groupby("year"):
    L.append(f"| year {y} | {st(g)} |")
L += ["", "Trades per symbol: " + ", ".join(f"{s} {n}" for s, n in b.sym.value_counts().items())]
b.to_pickle("results/r5/rsi_real_base.pkl")
open("results/r5/RSI_REAL_ROBUST.md", "w").write("\n".join(L))
print("\n".join(L))
