"""Round 4, step 3: daily signals acted on at 15:50 (same afternoon) and the pre-FOMC
trade exiting before the 14:00 statement - using Alpaca 5-minute bars (2016+).

Intraday periods: discovery 2016-2020, validation 2021 - 2026-04-15, holdout after.
python r4_intraday.py -> results/r4/INTRADAY.md, results/r4/intraday.pkl, PREREG_INTRADAY.json
"""
from __future__ import annotations

import itertools
import json

import numpy as np
import pandas as pd

from oat_research import data as D
from oat_research import engines_v2 as E
from oat_research import intraday4 as I4
from oat_research import setups4 as S4
from oat_research import shortdated as SD
from r4_common import ETFS, OUT, costs, fmt, load_daily

I_DISC = (pd.Timestamp("2016-01-01"), pd.Timestamp("2020-12-31 23:59"))
I_VALID = (pd.Timestamp("2021-01-01"), pd.Timestamp("2026-04-15 23:59"))

GRID_DELTA = (0.5, 0.7)
GRID_EXIT = ((0.5, 1.0, None), (0.75, 1.0, None), (None, None, None))
GRID_MINDAYS = (2, 5)


def load_intraday(syms):
    m5 = {s: D.load_csv(f"data/m5a/{s}.csv") for s in syms}
    return m5


def prepare(m5, d1, vols):
    seg = {s: I4.segment_bars(df) for s, df in m5.items()}
    asof = {s: I4.daily_asof(df, "15:50", d1[s]) for s, df in m5.items()}
    full = {s: I4.daily_asof(df, "16:00", d1[s]) for s, df in m5.items()}   # for ATR (same price scale)
    spy_asof = asof.get("SPY")
    ctx = {s: E.Ctx(df, spy_asof if s != "SPY" else None) for s, df in asof.items()}
    ivs = SD.iv_table(full, vols)
    return seg, asof, full, ctx, ivs


def strategies(seg, asof, ctx, vols, fomc):
    vix = vols["VIX"]
    out = {}
    etfs = [s for s in ETFS if s in seg]
    # pre-FOMC, pure Lucca-Moench window: enter 15:50 the day before, exit 13:55 on the day
    pf = {}
    for s in etfs:
        sg = seg[s]
        idx = sg.index
        day = idx.normalize()
        days = pd.DatetimeIndex(sorted(set(day)))
        pos = {d: i for i, d in enumerate(days)}
        pre = {days[pos[f] - 1] for f in fomc if f in pos and pos[f] >= 1}
        hm = idx.hour * 60 + idx.minute
        sig = day.isin(list(pre)) & (hm == 13 * 60 + 55)
        ex = day.isin(list(fomc)) & (hm == 12 * 60)
        pf[s] = S4.frame(sg, np.where(sig, 1, 0), reason=np.where(sig, "pre-FOMC 15:50 -> 13:55", ""), min_days=1, xsched=ex)
    out["Pre-FOMC 15:50→13:55"] = pf
    pf2 = {}
    for s in etfs:
        f = pf[s].copy()
        sg = seg[s]
        day = sg.index.normalize()
        hm = sg.index.hour * 60 + sg.index.minute
        f["xsched"] = day.isin(list(fomc)) & (hm == 13 * 60 + 55)  # exit 15:50 on the day (after the statement)
        f["reason"] = np.where(f["dir"] != 0, "pre-FOMC 15:50 -> 15:50", "")
        pf2[s] = f
    out["Pre-FOMC 15:50→15:50 (holds through statement)"] = pf2
    out["ETF dip @15:50"] = {s: I4.to_segments(S4.etf_dip(ctx[s], vix), seg[s]) for s in etfs}
    out["ETF bear-rally puts @15:50"] = {s: I4.to_segments(S4.etf_rip_put(ctx[s]), seg[s]) for s in etfs}
    out["VIX spike reversal @15:50"] = {s: I4.to_segments(S4.vix_reversal(ctx[s], vix), seg[s]) for s in etfs}
    return out


def cfg_for(name, delta, ex, md):
    tgt, stp, hold = ex
    return SD.SDConfig(name=name, exits=SD.SDExit(target_atr=tgt, stop_atr=stp, use_signal_levels=False, max_hold_bars=hold),
                       target_delta=delta, min_days=md, budget=0.02, max_open=5)


def main(syms=ETFS):
    d1, vols = load_daily()
    m5 = load_intraday(syms)
    seg, asof, full, ctx, ivs = prepare(m5, d1, vols)
    c1 = costs(full)
    c2 = costs(full, mult=2.0)
    ch = costs(full, mult=0.5)
    fomc = S4.load_fomc()
    strat = strategies(seg, asof, ctx, vols, fomc)
    prereg, store = {}, {}
    L = ["# Round 4 — act at 15:50 (5-minute data, 2016–2026)", "",
         "Signals are computed on a daily series whose close is the 15:50 price, so the trade is placed the same afternoon.", "",
         "## Discovery 2016–2020 → chosen rule", "",
         "| strategy | chosen delta / exit / min days | n | win | exp/trade | PF | t(week) |", "|---|---|---|---|---|---|---|"]
    for name, sigs in strat.items():
        best, best_sc, rows = None, -9e9, []
        for delta, ex, md in itertools.product(GRID_DELTA, GRID_EXIT, GRID_MINDAYS):
            tr, nav = SD.run({s: seg[s] for s in sigs}, sigs, cfg_for(name, delta, ex, md), full, ivs, c1, *I_DISC)
            sm = SD.summarize(tr, nav)
            rows.append(((delta, ex, md), sm))
            sc = sm.get("t_week", -9) if sm["n"] >= 30 else -9
            if sc > best_sc:
                best, best_sc = (delta, ex, md), sc
        sm = dict(rows)[best]
        prereg[name] = dict(delta=best[0], exit=best[1], min_days=best[2], disc_n=sm["n"], disc_exp=sm.get("exp"))
        store[name] = dict(grid=rows)
        L.append(f"| {name} | {best[0]} / {best[1]} / {best[2]} | {sm['n']} | {fmt(sm.get('win'))} | {fmt(sm.get('exp'), True)} | "
                 f"{fmt(sm.get('pf_cash'))} | {fmt(sm.get('t_week'))} |")
        print(name, best, sm["n"], fmt(sm.get("exp"), True), flush=True)
    (OUT / "PREREG_INTRADAY.json").write_text(json.dumps(dict(written="before validation", disc=I_DISC, valid=I_VALID, rules=prereg),
                                                         indent=2, default=str), encoding="utf-8")
    L += ["", "## Validation 2021 – 2026-04-15 (frozen rules)", "",
          "| strategy | n | win | avg win | avg loss | exp/trade | PF | t(week) | ½ spreads | 2× spreads | maxDD* | median hours |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for name, sigs in strat.items():
        r = prereg[name]
        cfg = cfg_for(name, r["delta"], r["exit"], r["min_days"])
        b = {s: seg[s] for s in sigs}
        tr, nav = SD.run(b, sigs, cfg, full, ivs, c1, *I_VALID)
        sm = SD.summarize(tr, nav)
        sm2 = SD.summarize(*SD.run(b, sigs, cfg, full, ivs, c2, *I_VALID))
        smh = SD.summarize(*SD.run(b, sigs, cfg, full, ivs, ch, *I_VALID))
        store[name].update(valid=sm, trades=tr, nav=nav)
        L.append(f"| {name} | {sm['n']} | {fmt(sm.get('win'))} | {fmt(sm.get('avg_win'), True)} | {fmt(sm.get('avg_loss'), True)} | "
                 f"{fmt(sm.get('exp'), True)} | {fmt(sm.get('pf_cash'))} | {fmt(sm.get('t_week'))} | {fmt(smh.get('exp'), True)} | "
                 f"{fmt(sm2.get('exp'), True)} | {fmt(sm.get('max_dd'), True)} | {fmt(sm.get('hours_median'), p=0)} |")
        print("VALID", name, sm["n"], fmt(sm.get("exp"), True), fmt(sm.get("t_week")), flush=True)
    (OUT / "INTRADAY.md").write_text("\n".join(L), encoding="utf-8")
    pd.to_pickle(store, OUT / "intraday.pkl")
    print("\n".join(L))


if __name__ == "__main__":
    main()
