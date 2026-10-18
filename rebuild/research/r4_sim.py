"""Round 4, step 2: weekly-option simulation of the candidate setups.

Discovery (1999-2012): small pre-declared grid per setup, choose by week-clustered t
(min 60 trades). The chosen rule is frozen in results/r4/PREREG.json, then run once on
validation (2013 - 2026-04-15). The holdout (2026-04-16 ->) is NOT touched here.

python r4_sim.py -> results/r4/SIM.md, results/r4/sim.pkl, results/r4/PREREG.json
"""
from __future__ import annotations

import itertools
import json
from dataclasses import replace

import numpy as np
import pandas as pd

from oat_research import setups4 as S4
from oat_research import shortdated as SD
from r4_common import DISC, ETFS, OUT, VALID, contexts, costs, fmt, load_daily

GRID_DELTA = (0.5, 0.7)
GRID_EXIT = (  # (underlying target ATR, stop ATR, max hold bars)
    (0.5, 1.0, 2), (0.75, 1.0, 3), (1.0, 1.0, 4), (None, None, None),  # last = rule exits only (+ pre-expiry)
)
GRID_MINDAYS = (2, 5)


def build(data, vols):
    ctxs = contexts(data)
    cal = S4.trading_calendar(data["SPY"].index)
    vix = vols["VIX"]
    fomc = S4.load_fomc()
    waves = {}
    for tag in ("W2", "B"):
        waves[tag] = {s: S4.wave(df, data["SPY"], S4.weekly_trend(df), tag)[0] for s, df in data.items()}
    return {
        "ETF dip": {s: S4.etf_dip(ctxs[s], vix) for s in ETFS},
        "ETF bear-rally puts": {s: S4.etf_rip_put(ctxs[s]) for s in ETFS},
        "Pre-FOMC": {s: S4.pre_fomc(ctxs[s], fomc, cal) for s in ETFS},
        "Turn of month": {s: S4.tom(ctxs[s], cal) for s in ETFS},
        "Turn of month (stocks)": {s: S4.tom(ctxs[s], cal) for s in data if s not in ETFS},
        "Pre-holiday": {s: S4.pre_holiday(ctxs[s], cal) for s in ETFS},
        "Event gap drift": {s: S4.event_gap(ctxs[s]) for s in data},
        "Wave 2->3 daily": waves["W2"],
        "Wave B->C daily": waves["B"],
        "VIX spike reversal": {s: S4.vix_reversal(ctxs[s], vix) for s in ETFS},
        "20-day breakout": {s: S4.breakout20(ctxs[s]) for s in data},
        "Wave-2/B exhaustion (new)": {s: S4.wave_exhaustion(ctxs[s], S4.weekly_trend(df)) for s, df in data.items()},
        "Control: trend + RSI2 (no wave)": {s: S4.wave_exhaustion(ctxs[s], S4.weekly_trend(df), control=True) for s, df in data.items()},
    }


def cfg_for(name, delta, ex, md):
    tgt, stp, hold = ex
    exits = SD.SDExit(target_atr=tgt, stop_atr=stp, use_signal_levels=False, max_hold_bars=hold)
    return SD.SDConfig(name=name, exits=exits, target_delta=delta, min_days=md, budget=0.02, max_open=5)


def run_one(data, ivs, sigs, cfg, c, period):
    sub = {s: data[s] for s in sigs}
    tr, nav = SD.run(sub, sigs, cfg, data, ivs, c, start=period[0], end=period[1])
    return tr, nav, SD.summarize(tr, nav)


def main():
    data, vols = load_daily()
    ivs = SD.iv_table(data, vols)
    c1 = costs(data)
    c2 = costs(data, mult=2.0)
    setups = build(data, vols)
    prereg, store = {}, {}
    lines = ["# Round 4 — weekly options simulation", "",
             "Contracts expire ≤ 7 calendar days after entry (first Friday ≥ entry + min_days). Spreads: ETF 3%, stocks 6% of mid.",
             "Conditional exits are decided at a close and filled at the next open. Budget 2% of NAV per trade, max 5 open.", "",
             "## Discovery 1999–2012: grid (delta × exit × expiry) → chosen rule", "",
             "| setup | chosen: delta / (target ATR, stop ATR, max days) / min days | n | win | avg win | avg loss | exp/trade | PF | t(week) |",
             "|---|---|---|---|---|---|---|---|---|"]
    for name, sigs in setups.items():
        best, best_sc, grid_rows = None, -9e9, []
        for delta, ex, md in itertools.product(GRID_DELTA, GRID_EXIT, GRID_MINDAYS):
            cfg = cfg_for(name, delta, ex, md)
            tr, nav, sm = run_one(data, ivs, sigs, cfg, c1, DISC)
            sc = sm.get("t_week", -9) if sm["n"] >= 60 else -9
            grid_rows.append((delta, ex, md, sm))
            if sc > best_sc:
                best, best_sc = (delta, ex, md), sc
        delta, ex, md = best
        sm = [g[3] for g in grid_rows if g[:3] == best][0]
        prereg[name] = dict(delta=delta, target_atr=ex[0], stop_atr=ex[1], max_hold_days=ex[2], min_days=md,
                            discovery=dict(n=sm["n"], exp=sm.get("exp"), t_week=sm.get("t_week")))
        store[name] = dict(grid=grid_rows)
        lines.append(f"| {name} | {delta} / {ex} / {md} | {sm['n']} | {fmt(sm.get('win'))} | {fmt(sm.get('avg_win'), True)} | "
                     f"{fmt(sm.get('avg_loss'), True)} | {fmt(sm.get('exp'), True)} | {fmt(sm.get('pf_cash'))} | {fmt(sm.get('t_week'))} |")
        print(name, best, sm["n"], fmt(sm.get("exp"), True), fmt(sm.get("t_week")), flush=True)
    (OUT / "PREREG.json").write_text(json.dumps(dict(
        written="before validation", periods=dict(discovery=DISC, validation=VALID), rules=prereg), indent=2, default=str), encoding="utf-8")

    lines += ["", "## Validation 2013 – 2026-04-15 (rules frozen above, run once)", "",
              "| setup | n | win | avg win | avg loss | exp/trade | PF | t(week) | 2× spreads exp | CAGR* | maxDD* | median hours held |",
              "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for name, sigs in setups.items():
        r = prereg[name]
        cfg = cfg_for(name, r["delta"], (r["target_atr"], r["stop_atr"], r["max_hold_days"]), r["min_days"])
        tr, nav, sm = run_one(data, ivs, sigs, cfg, c1, VALID)
        tr2, nav2, sm2 = run_one(data, ivs, sigs, cfg, c2, VALID)
        store[name].update(valid=sm, valid_trades=tr, valid_nav=nav, valid2=sm2)
        lines.append(f"| {name} | {sm['n']} | {fmt(sm.get('win'))} | {fmt(sm.get('avg_win'), True)} | {fmt(sm.get('avg_loss'), True)} | "
                     f"{fmt(sm.get('exp'), True)} | {fmt(sm.get('pf_cash'))} | {fmt(sm.get('t_week'))} | {fmt(sm2.get('exp'), True)} | "
                     f"{fmt(sm.get('cagr'), True)} | {fmt(sm.get('max_dd'), True)} | {fmt(sm.get('hours_median'), p=0)} |")
        print("VALID", name, sm["n"], fmt(sm.get("exp"), True), fmt(sm.get("t_week")), flush=True)
    lines += ["", "*Each setup alone, 2% of NAV premium per trade."]
    (OUT / "SIM.md").write_text("\n".join(lines), encoding="utf-8")
    pd.to_pickle(store, OUT / "sim.pkl")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
