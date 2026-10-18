"""Round 4, step 5: wave-2/B exhaustion vs. plain trend-dip, acted on at 15:50, all 15 symbols.
Same protocol as r4_intraday.py (discovery 2016-2020 grid -> frozen -> validation 2021 - 2026-04-15).
python r4_intraday3.py -> results/r4/INTRADAY3.md
"""
from __future__ import annotations

import itertools
import json

import pandas as pd

from oat_research import intraday4 as I4
from oat_research import setups4 as S4
from oat_research import shortdated as SD
from r4_common import ETFS, OUT, costs, fmt, load_daily
from r4_intraday import GRID_DELTA, GRID_EXIT, GRID_MINDAYS, I_DISC, I_VALID, cfg_for, load_intraday, prepare

SYMS = ["SPY", "QQQ", "IWM", "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "AMD", "JPM", "XOM", "UNH", "COST"]


def main():
    d1, vols = load_daily()
    m5 = load_intraday(SYMS)
    seg, asof, full, ctx, ivs = prepare(m5, d1, vols)
    htf = {s: S4.weekly_trend(asof[s]) for s in SYMS}
    strat = {
        "Wave-2/B exhaustion @15:50": {s: I4.to_segments(S4.wave_exhaustion(ctx[s], htf[s]), seg[s]) for s in SYMS},
        "Wave-2 exhaustion calls only @15:50": {s: I4.to_segments(S4.wave_exhaustion(ctx[s], htf[s], allow_puts=False), seg[s]) for s in SYMS},
        "Control: trend + RSI2 @15:50 (no wave)": {s: I4.to_segments(S4.wave_exhaustion(ctx[s], htf[s], control=True), seg[s]) for s in SYMS},
        "Trend dip stocks @15:50 (calls)": {s: I4.to_segments(S4.etf_dip(ctx[s], vols["VIX"]), seg[s]) for s in SYMS if s not in ETFS},
    }
    c1, c2, ch = costs(full), costs(full, mult=2.0), costs(full, mult=0.5)
    L = ["# Round 4 — waves vs. trend-dip at 15:50 (15 symbols, 5-minute data)", "",
         "| strategy | period | chosen delta / exit / min days | n | win | avg win | avg loss | exp/trade | PF | t(week) | ½ spr | 2× spr | maxDD* |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    prereg, store = {}, {}
    for name, sigs in strat.items():
        bars = {s: seg[s] for s in sigs}
        best, sc_best, grid = None, -9e9, {}
        for delta, ex, md in itertools.product(GRID_DELTA, GRID_EXIT, GRID_MINDAYS):
            sm = SD.summarize(*SD.run(bars, sigs, cfg_for(name, delta, ex, md), full, ivs, c1, *I_DISC))
            grid[(delta, ex, md)] = sm
            sc = sm.get("t_week", -9) if sm["n"] >= 30 else -9
            if sc > sc_best:
                best, sc_best = (delta, ex, md), sc
        sm = grid[best]
        prereg[name] = dict(delta=best[0], exit=best[1], min_days=best[2])
        L.append(f"| {name} | disc 2016–20 | {best[0]} / {best[1]} / {best[2]} | {sm['n']} | {fmt(sm.get('win'))} | {fmt(sm.get('avg_win'), True)} | "
                 f"{fmt(sm.get('avg_loss'), True)} | {fmt(sm.get('exp'), True)} | {fmt(sm.get('pf_cash'))} | {fmt(sm.get('t_week'))} | | | |")
        cfg = cfg_for(name, *best)
        tr, nav = SD.run(bars, sigs, cfg, full, ivs, c1, *I_VALID)
        sv = SD.summarize(tr, nav)
        s2 = SD.summarize(*SD.run(bars, sigs, cfg, full, ivs, c2, *I_VALID))
        sh = SD.summarize(*SD.run(bars, sigs, cfg, full, ivs, ch, *I_VALID))
        L.append(f"| {name} | valid 2021–26 | | {sv['n']} | {fmt(sv.get('win'))} | {fmt(sv.get('avg_win'), True)} | {fmt(sv.get('avg_loss'), True)} | "
                 f"{fmt(sv.get('exp'), True)} | {fmt(sv.get('pf_cash'))} | {fmt(sv.get('t_week'))} | {fmt(sh.get('exp'), True)} | "
                 f"{fmt(s2.get('exp'), True)} | {fmt(sv.get('max_dd'), True)} |")
        store[name] = dict(grid=grid, valid=sv, trades=tr, nav=nav)
        print(L[-2], L[-1], sep="\n", flush=True)
    (OUT / "PREREG_INTRADAY3.json").write_text(json.dumps(prereg, indent=2, default=str))
    (OUT / "INTRADAY3.md").write_text("\n".join(L), encoding="utf-8")
    pd.to_pickle(store, OUT / "intraday3.pkl")


if __name__ == "__main__":
    main()
