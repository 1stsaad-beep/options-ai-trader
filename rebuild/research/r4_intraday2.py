"""Round 4, step 4: same-day option trades on 5-minute bars (0-DTE where it exists).

  * Noise-area momentum (Zarattini-Aziz-Barbon 2024) on SPY / QQQ
  * 5-minute ORB on 'stocks in play' (Zarattini-Barbon-Aziz 2024) on all symbols

Expiry: SPY/QQQ same-day expiry from 2022-11-15 (daily expiries), otherwise the nearest
Friday. Flat at the close. Discovery 2016-2020, validation 2021 - 2026-04-15.
python r4_intraday2.py [SYMS...]
"""
from __future__ import annotations

import itertools
import json
import sys

import pandas as pd

from oat_research import data as D
from oat_research import intraday4 as I4
from oat_research import setups4 as S4
from oat_research import shortdated as SD
from r4_common import OUT, costs, fmt, load_daily
from r4_intraday import I_DISC, I_VALID


def cfg_for(name, delta, opt_stop):
    return SD.SDConfig(name=name, exits=SD.SDExit(target_atr=None, stop_atr=None, use_signal_levels=True, opt_stop=opt_stop,
                                                  cutoff_hours_before_expiry=0.0),
                       target_delta=delta, min_days=0, budget=0.01, max_open=5, bar_minutes=5, daily_expiry_syms=("SPY", "QQQ"))


def main(syms):
    d1, vols = load_daily()
    m5 = {s: D.load_csv(f"data/m5a/{s}.csv") for s in syms}
    full = {s: I4.daily_asof(df, "16:00", d1[s]) for s, df in m5.items()}
    ivs = SD.iv_table(full, vols)
    c1, c2, ch = costs(full), costs(full, mult=2.0), costs(full, mult=0.5)
    strat = {
        "Noise-area momentum (SPY/QQQ)": {s: S4.noise_momentum(m5[s]) for s in ("SPY", "QQQ") if s in m5},
        "ORB 5-min, in play (all)": {s: S4.orb5(m5[s], daily=full[s]) for s in m5},
    }
    L = ["# Round 4 — same-day option trades (5-minute bars)", "", "| strategy | period | delta / option stop | n | win | avg win | avg loss | exp/trade | PF | t(week) | ½ spr | 2× spr |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    store, prereg = {}, {}
    for name, sigs in strat.items():
        bars = {s: m5[s] for s in sigs}
        best, sc_best, grid = None, -9e9, {}
        for delta, ost in itertools.product((0.5, 0.7), (None, 0.5)):
            sm = SD.summarize(*SD.run(bars, sigs, cfg_for(name, delta, ost), full, ivs, c1, *I_DISC))
            grid[(delta, ost)] = sm
            sc = sm.get("t_week", -9) if sm["n"] >= 30 else -9
            if sc > sc_best:
                best, sc_best = (delta, ost), sc
            print(name, delta, ost, sm["n"], fmt(sm.get("exp"), True), flush=True)
        sm = grid[best]
        L.append(f"| {name} | disc 2016–20 | {best[0]} / {best[1]} | {sm['n']} | {fmt(sm.get('win'))} | {fmt(sm.get('avg_win'), True)} | "
                 f"{fmt(sm.get('avg_loss'), True)} | {fmt(sm.get('exp'), True)} | {fmt(sm.get('pf_cash'))} | {fmt(sm.get('t_week'))} | | |")
        prereg[name] = dict(delta=best[0], opt_stop=best[1])
        cfg = cfg_for(name, *best)
        tr, nav = SD.run(bars, sigs, cfg, full, ivs, c1, *I_VALID)
        sv = SD.summarize(tr, nav)
        s2 = SD.summarize(*SD.run(bars, sigs, cfg, full, ivs, c2, *I_VALID))
        sh = SD.summarize(*SD.run(bars, sigs, cfg, full, ivs, ch, *I_VALID))
        L.append(f"| {name} | valid 2021–26 | | {sv['n']} | {fmt(sv.get('win'))} | {fmt(sv.get('avg_win'), True)} | {fmt(sv.get('avg_loss'), True)} | "
                 f"{fmt(sv.get('exp'), True)} | {fmt(sv.get('pf_cash'))} | {fmt(sv.get('t_week'))} | {fmt(sh.get('exp'), True)} | {fmt(s2.get('exp'), True)} |")
        store[name] = dict(grid=grid, valid=sv, trades=tr, nav=nav)
        print("VALID", name, sv["n"], fmt(sv.get("exp"), True), flush=True)
    (OUT / "PREREG_SAMEDAY.json").write_text(json.dumps(prereg, indent=2, default=str))
    (OUT / "SAMEDAY.md").write_text("\n".join(L), encoding="utf-8")
    pd.to_pickle(store, OUT / "sameday.pkl")
    print("\n".join(L))


if __name__ == "__main__":
    main(sys.argv[1:] or ["SPY", "QQQ", "IWM", "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "AMD", "JPM", "XOM", "UNH", "COST"])
