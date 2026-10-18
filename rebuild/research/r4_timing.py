"""Round 4, step 1: time-to-target study on the DISCOVERY period only.

python r4_timing.py -> results/r4/TIMING.md, results/r4/timing.pkl
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from oat_research import indicators as ind
from oat_research import setups4 as S4
from oat_research import timing as T
from r4_common import DISC, ETFS, H_DISC, OUT, contexts, fmt, load_daily, load_hourly


def entries(sig: pd.DataFrame, start, end):
    m = (sig["dir"] != 0) & (sig.index >= start) & (sig.index <= end)
    idx = np.flatnonzero(m.to_numpy())
    return [(int(i), int(sig["dir"].iloc[i])) for i in idx]


def main():
    data, vols = load_daily()
    ctxs = contexts(data)
    cal = S4.trading_calendar(data["SPY"].index)
    vix = vols["VIX"]
    setups = {
        "ETF dip (calls)": {s: S4.etf_dip(ctxs[s], vix) for s in ETFS},
        "ETF bear-rally (puts)": {s: S4.etf_rip_put(ctxs[s]) for s in ETFS},
        "VIX spike reversal (calls)": {s: S4.vix_reversal(ctxs[s], vix) for s in ETFS},
        "Gap & go (both)": {s: S4.gap_go(ctxs[s]) for s in data},
        "Turn of month (calls)": {s: S4.tom(ctxs[s], cal) for s in data},
        "20-day breakout (calls)": {s: S4.breakout20(ctxs[s]) for s in data},
        "Pre-FOMC (calls, ETFs)": {s: S4.pre_fomc(ctxs[s], S4.load_fomc(), cal) for s in ETFS},
        "Event gap drift (both)": {s: S4.event_gap(ctxs[s]) for s in data},
        "Pre-holiday (calls, ETFs)": {s: S4.pre_holiday(ctxs[s], cal) for s in ETFS},
    }
    waves_w2, waves_b = {}, {}
    for s, df in data.items():
        htf = S4.weekly_trend(df)
        waves_w2[s] = S4.wave(df, data["SPY"], htf, "W2")[0]
        waves_b[s] = S4.wave(df, data["SPY"], htf, "B")[0]
    setups["Wave 2->3 daily (HTF)"] = waves_w2
    setups["Wave B->C daily (HTF)"] = waves_b
    # baselines: every day in the regime
    base_c, base_p = {}, {}
    for s, cx in ctxs.items():
        c = cx.df["close"]
        up = (c > cx.sma200) & cx.mkt_up
        dn = (c < cx.sma200) & cx.mkt_dn
        base_c[s] = pd.DataFrame({"dir": np.where(up, 1, 0)}, index=c.index)
        base_p[s] = pd.DataFrame({"dir": np.where(dn, -1, 0)}, index=c.index)
    setups["BASELINE calls: any day above SMA200"] = base_c
    setups["BASELINE puts: any day below SMA200"] = base_p

    store, lines = {}, []
    lines += ["# Round 4 — time-to-target study (discovery 1999–2012, daily bars)", "",
              "Entry = next open. Units = daily ATR(14) at the signal. Stop = −1 ATR (a bar touching both counts as stop first).",
              "pX_dN = share of setups that touched +X ATR **before the stop** within N trading days (day 1 = entry day).", "",
              "| setup | n | +0.5 d1 | +0.5 d2 | +0.75 d2 | +1 d1 | +1 d2 | +1 d3 | +1 d5 | +1.5 d5 | median days to +1 | stop ≤5d | MFE d1 | MFE d2 | close d1 | close d2 | close d5 |",
              "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for name, sigs in setups.items():
        frames = []
        for s, sig in sigs.items():
            df = data[s]
            datr = ind.atr(df)
            w = T.walk(df, entries(sig, *DISC), datr)
            if not w.empty:
                w["sym"] = s
                frames.append(w)
        w = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
        sm = T.summarize(w)
        store[name] = w
        if sm["n"] == 0:
            lines.append(f"| {name} | 0 |" + " — |" * 15)
            continue
        pc = lambda k: f"{sm[k] * 100:.0f}%"
        lines.append(f"| {name} | {sm['n']} | {pc('p0.5_d1')} | {pc('p0.5_d2')} | {pc('p0.75_d2')} | {pc('p1.0_d1')} | {pc('p1.0_d2')} | "
                     f"{pc('p1.0_d3')} | {pc('p1.0_d5')} | {pc('p1.5_d5')} | {fmt(sm['med_days1.0'], p=1)} | {pc('p_stop_d5')} | "
                     f"{fmt(sm['mfe1'])} | {fmt(sm['mfe2'])} | {fmt(sm['ret1'])} | {fmt(sm['ret2'])} | {fmt(sm['ret5'])} |")
        print(name, sm["n"], flush=True)

    # weekday of entry (all non-baseline setups pooled)
    pool = pd.concat([w for n, w in store.items() if not n.startswith("BASELINE") and not w.empty])
    lines += ["", "## Entry weekday (all setups pooled)", "", "| weekday | n | +0.5 within 2d | +1 within 2d | mean close d2 (ATR) |", "|---|---|---|---|---|"]
    for wd, g in pool.groupby("weekday"):
        lines.append(f"| {['Mon','Tue','Wed','Thu','Fri'][wd]} | {len(g)} | {(g['hit0.5'] < 2).mean()*100:.0f}% | {(g['hit1.0'] < 2).mean()*100:.0f}% | {g['ret2'].mean():+.2f} |")

    # ---------------- hourly
    hd = load_hourly()
    daily = data
    hl = ["", f"## Hourly bars, discovery {H_DISC[0]:%Y-%m-%d} → {H_DISC[1]:%Y-%m-%d} (horizon in trading days, 7 bars/day)", "",
          "| setup | n | +0.5 same day | +0.5 d2 | +1 same day | +1 d2 | stop ≤5d | close same day | close d2 |", "|---|---|---|---|---|---|---|---|---|"]
    hsets = {"First-hour breakout (in play)": {s: S4.orb_hour(df, daily[s]) for s, df in hd.items() if s in daily}}
    hw2, hb = {}, {}
    for s, df in hd.items():
        if s not in daily:
            continue
        htf = S4.daily_trend_for_intraday(df, daily[s])
        hw2[s] = S4.wave(df, None, htf, "W2")[0]
        hb[s] = S4.wave(df, None, htf, "B")[0]
    hsets["Wave 2->3 hourly (daily HTF)"] = hw2
    hsets["Wave B->C hourly (daily HTF)"] = hb
    for name, sigs in hsets.items():
        frames = []
        for s, sig in sigs.items():
            datr = ind.atr(daily[s])
            datr_prev = datr.shift(1)
            datr_prev.index = datr_prev.index.normalize()
            dh = pd.Series(datr_prev.reindex(hd[s].index.normalize()).to_numpy(), index=hd[s].index)
            w = T.walk(hd[s], entries(sig, *H_DISC), dh, bars_per_day=7)
            if not w.empty:
                w["sym"] = s
                frames.append(w)
        w = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
        store["H " + name] = w
        sm = T.summarize(w)
        if sm["n"] == 0:
            hl.append(f"| {name} | 0 |" + " — |" * 7)
            continue
        pc = lambda k: f"{sm[k] * 100:.0f}%"
        hl.append(f"| {name} | {sm['n']} | {pc('p0.5_d1')} | {pc('p0.5_d2')} | {pc('p1.0_d1')} | {pc('p1.0_d2')} | {pc('p_stop_d5')} | "
                  f"{fmt(sm['ret1'])} | {fmt(sm['ret2'])} |")
        print(name, sm["n"], flush=True)
    lines += hl
    (OUT / "TIMING.md").write_text("\n".join(lines), encoding="utf-8")
    pd.to_pickle(store, OUT / "timing.pkl")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
