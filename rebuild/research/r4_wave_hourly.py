"""Round 4: wave-2/B exhaustion on 60-minute and 15-minute bars (5-min source 2016+), daily HTF.
python r4_wave_hourly.py -> results/r4/WAVE_INTRADAY.md"""
import itertools, json
import pandas as pd
from oat_research import data as D, engines_v2 as E, intraday4 as I4, setups4 as S4, shortdated as SD
from r4_common import OUT, costs, fmt, load_daily
from r4_intraday import I_DISC, I_VALID
from r4_intraday3 import SYMS

def cfg_for(delta, ex, md, bm):
    tgt, stp, hold = ex
    return SD.SDConfig("wave", SD.SDExit(target_atr=tgt, stop_atr=stp, use_signal_levels=False, max_hold_bars=hold),
                       target_delta=delta, min_days=md, budget=0.02, max_open=5, bar_minutes=bm)

def main():
    d1, vols = load_daily()
    m5 = {s: D.load_csv(f"data/m5a/{s}.csv") for s in SYMS}
    full = {s: I4.daily_asof(df, "16:00", d1[s]) for s, df in m5.items()}
    ivs = SD.iv_table(full, vols)
    c1, c2 = costs(full), costs(full, mult=2.0)
    L = ["# Wave-2/B exhaustion on intraday bars (daily trend as higher timeframe)", "",
         "| bars | variant | period | chosen | n | win | exp/trade | PF | t(week) | 2× spr |", "|---|---|---|---|---|---|---|---|---|---|"]
    for bm in (60, 15):
        bars = {s: S4.resample(m5[s], bm) for s in SYMS}
        ctx = {s: E.Ctx(df, bars["SPY"] if s != "SPY" else None) for s, df in bars.items()}
        htf = {s: S4.daily_trend_for_intraday(bars[s], full[s]).astype(bool) for s in SYMS}
        for vname, kw in (("wave", {}), ("control (no wave)", {"control": True})):
            sigs = {s: S4.wave_exhaustion(ctx[s], htf[s], **kw) for s in SYMS}
            best, scb, grid = None, -9e9, {}
            for delta, ex, md in itertools.product((0.5, 0.7), ((0.5, 1.0, None), (0.75, 1.0, None), (None, None, 7 * 60 // bm * 2)), (2, 5)):
                sm = SD.summarize(*SD.run(bars, sigs, cfg_for(delta, ex, md, bm), full, ivs, c1, *I_DISC))
                grid[(delta, ex, md)] = sm
                sc = sm.get("t_week", -9) if sm["n"] >= 30 else -9
                if sc > scb: best, scb = (delta, ex, md), sc
            sm = grid[best]
            L.append(f"| {bm}m | {vname} | disc | {best} | {sm['n']} | {fmt(sm.get('win'))} | {fmt(sm.get('exp'), True)} | {fmt(sm.get('pf_cash'))} | {fmt(sm.get('t_week'))} | |")
            cfg = cfg_for(*best, bm)
            sv = SD.summarize(*SD.run(bars, sigs, cfg, full, ivs, c1, *I_VALID))
            s2 = SD.summarize(*SD.run(bars, sigs, cfg, full, ivs, c2, *I_VALID))
            L.append(f"| {bm}m | {vname} | valid | | {sv['n']} | {fmt(sv.get('win'))} | {fmt(sv.get('exp'), True)} | {fmt(sv.get('pf_cash'))} | {fmt(sv.get('t_week'))} | {fmt(s2.get('exp'), True)} |")
            print(L[-2], L[-1], sep="\n", flush=True)
    (OUT / "WAVE_INTRADAY.md").write_text("\n".join(L), encoding="utf-8")

if __name__ == "__main__":
    main()
