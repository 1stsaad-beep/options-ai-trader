"""Round 4 — the four selected strategies with FROZEN rules.

  A  Trend-dip @15:50          RSI2 < 10, close > SMA200, VIX < 35 (all 15 symbols), weekly Calls
  B  Wave-2/B exhaustion @15:50 (the wave strategy), weekly Calls/Puts
  C  ORB-5 'in play'           5-minute opening range, RVOL >= 2, same-day exit (0-DTE on SPY/QQQ)
  D  Noise-area momentum       SPY/QQQ intraday, same-day exit (0-DTE)

python r4_final.py robust   -> results/r4/FINAL_ROBUST.md  (validation period only)
python r4_final.py holdout  -> results/r4/HOLDOUT.md       (run ONCE, after FINAL_PREREG.json is written)
"""
from __future__ import annotations

import json
import sys

import numpy as np
import pandas as pd

from oat_research import data as D
from oat_research import engines_v2 as E
from oat_research import intraday4 as I4
from oat_research import setups4 as S4
from oat_research import shortdated as SD
from r4_common import HOLD, OUT, costs, fmt, load_daily

SYMS = ["SPY", "QQQ", "IWM", "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "AMD", "JPM", "XOM", "UNH", "COST"]
VALID = (pd.Timestamp("2021-01-01"), pd.Timestamp("2026-04-15 23:59"))
BIG_MOVERS = {"NVDA", "TSLA", "AMD", "META"}

RULES = {
    "A Trend-dip @15:50": dict(bars="segments", delta=0.5, target_atr=0.75, stop_atr=1.0, min_days=2, budget=0.02,
                               entry="15:50 when RSI2(15:50 close) < 10, close > SMA200, VIX(prev) < 35",
                               exit="close >= entry + 0.75 ATR or <= entry - 1 ATR or close > SMA5 or RSI2 > 70 (decided 15:50, filled 15:50 next segment); sell by the close before expiry day"),
    "B Wave-2/B exhaustion @15:50": dict(bars="segments", delta=0.5, target_atr=0.5, stop_atr=1.0, min_days=2, budget=0.02,
                                         entry="15:50; confirmed zig-zag (1.5 ATR) wave-1 >= 3 ATR breaking prior swing, retracement 38.2-78.6%, close above wave start and its anchored VWAP, weekly trend up, SMA200, RSI2 < 10 (mirror for Puts)",
                                         exit="+0.5 ATR target / -1 ATR stop at 15:50 checks; sell by the close before expiry day"),
    "C ORB-5 in play": dict(bars="m5", delta=0.5, opt_stop=None, min_days=0, budget=0.01,
                            entry="09:35 open; first 5-min bar volume >= 2x its 14-day average; direction = first bar body",
                            exit="stop = first-bar extreme or 10% daily ATR (nearer), else 15:55 bar close"),
    "D Noise-area momentum": dict(bars="m5", delta=0.7, opt_stop=None, min_days=0, budget=0.01,
                                  entry="half-hour marks 10:00-15:00: close beyond max/min(open, prev close) x (1 +/- 14-day avg |move| at that time)",
                                  exit="half-hour close back inside max(UB, VWAP)/min(LB, VWAP), else the close"),
}


def build():
    d1, vols = load_daily()
    m5 = {s: D.load_csv(f"data/m5a/{s}.csv") for s in SYMS}
    seg = {s: I4.segment_bars(df) for s, df in m5.items()}
    asof = {s: I4.daily_asof(df, "15:50", d1[s]) for s, df in m5.items()}
    full = {s: I4.daily_asof(df, "16:00", d1[s]) for s, df in m5.items()}
    ctx = {s: E.Ctx(df, asof["SPY"] if s != "SPY" else None) for s, df in asof.items()}
    ivs = SD.iv_table(full, vols)
    vix = vols["VIX"]
    sigs = {
        "A Trend-dip @15:50": {s: I4.to_segments(S4.etf_dip(ctx[s], vix), seg[s]) for s in SYMS},
        "B Wave-2/B exhaustion @15:50": {s: I4.to_segments(S4.wave_exhaustion(ctx[s], S4.weekly_trend(asof[s])), seg[s]) for s in SYMS},
        "C ORB-5 in play": {s: S4.orb5(m5[s], daily=full[s]) for s in SYMS},
        "D Noise-area momentum": {s: S4.noise_momentum(m5[s]) for s in ("SPY", "QQQ")},
    }
    bars = {"segments": seg, "m5": m5}
    return dict(d1=d1, vols=vols, m5=m5, seg=seg, full=full, ivs=ivs, sigs=sigs, bars=bars)


def cfg(name):
    r = RULES[name]
    if r["bars"] == "segments":
        ex = SD.SDExit(target_atr=r["target_atr"], stop_atr=r["stop_atr"], use_signal_levels=False)
        return SD.SDConfig(name, ex, target_delta=r["delta"], min_days=r["min_days"], budget=r["budget"], max_open=5)
    ex = SD.SDExit(target_atr=None, stop_atr=None, use_signal_levels=True, opt_stop=r["opt_stop"], cutoff_hours_before_expiry=0.0)
    return SD.SDConfig(name, ex, target_delta=r["delta"], min_days=r["min_days"], budget=r["budget"], max_open=5, bar_minutes=5,
                       daily_expiry_syms=("SPY", "QQQ"))


def run(B, name, period, cost_mult=1.0, iv_mult=1.0, syms=None):
    sigs = B["sigs"][name]
    if syms is not None:
        sigs = {s: v for s, v in sigs.items() if s in syms}
    bars = {s: B["bars"][RULES[name]["bars"]][s] for s in sigs}
    ivs = B["ivs"] if iv_mult == 1.0 else {s: v * iv_mult for s, v in B["ivs"].items()}
    return SD.run(bars, sigs, cfg(name), B["full"], ivs, costs(B["full"], mult=cost_mult), *period)


def row(label, tr, nav=None):
    sm = SD.summarize(tr, nav)
    und = [t.direction * (t.exit_spot / t.entry_spot - 1) for t in tr]
    return (f"| {label} | {sm['n']} | {fmt(sm.get('win'))} | {fmt(sm.get('avg_win'), True)} | {fmt(sm.get('avg_loss'), True)} | "
            f"{fmt(sm.get('exp'), True)} | {fmt(sm.get('pf_cash'))} | {fmt(sm.get('t_week'))} | "
            f"{(np.mean(und) * 100 if und else float('nan')):+.2f}% |"), sm


HDR = ["| variant | n | win | avg win | avg loss | exp/trade | PF | t(week) | underlying move/trade |", "|---|---|---|---|---|---|---|---|---|"]


def robust():
    B = build()
    L = ["# Round 4 — final four: robustness on validation (2021 – 2026-04-15)", ""]
    for name in RULES:
        L += [f"## {name}", ""] + HDR
        tr, nav = run(B, name, VALID)
        L.append(row("base", tr, nav)[0])
        L.append(row("2× spreads", *run(B, name, VALID, cost_mult=2.0))[0])
        L.append(row("½ spreads", *run(B, name, VALID, cost_mult=0.5))[0])
        L.append(row("IV × 1.25", *run(B, name, VALID, iv_mult=1.25))[0])
        L.append(row("IV × 0.8", *run(B, name, VALID, iv_mult=0.8))[0])
        if len(B["sigs"][name]) > 2:
            L.append(row("without NVDA/TSLA/AMD/META", *run(B, name, VALID, syms=set(SYMS) - BIG_MOVERS))[0])
            L.append(row("ETFs only", *run(B, name, VALID, syms={"SPY", "QQQ", "IWM"}))[0])
        L.append(row("Calls only", [t for t in tr if t.direction > 0])[0])
        L.append(row("Puts only", [t for t in tr if t.direction < 0])[0])
        top = sorted(tr, key=lambda t: t.pnl, reverse=True)[:5]
        L.append(row("without the 5 best trades", [t for t in tr if t not in top])[0])
        for y in range(2021, 2027):
            L.append(row(f"year {y}", [t for t in tr if t.entry_time.year == y])[0])
        ex = pd.Series([t.exit_reason for t in tr]).value_counts()
        L += ["", "Exit reasons: " + ", ".join(f"{k} {v}" for k, v in ex.items()), ""]
        print(name, "done", flush=True)
    (OUT / "FINAL_ROBUST.md").write_text("\n".join(L), encoding="utf-8")
    print("\n".join(L))


def holdout():
    pre = OUT / "FINAL_PREREG.json"
    assert pre.exists(), "write FINAL_PREREG.json first"
    B = build()
    L = [f"# Round 4 — HOLDOUT {HOLD[0]:%Y-%m-%d} → {HOLD[1]:%Y-%m-%d} (run once, rules from FINAL_PREREG.json)", ""] + HDR
    allt = []
    for name in RULES:
        tr, nav = run(B, name, HOLD)
        allt += tr
        L.append(row(name, tr, nav)[0])
        L.append(row(f"{name} — 2× spreads", *run(B, name, HOLD, cost_mult=2.0))[0])
    L.append(row("ALL FOUR pooled", allt)[0])
    (OUT / "HOLDOUT.md").write_text("\n".join(L), encoding="utf-8")
    pd.to_pickle(allt, OUT / "holdout_trades.pkl")
    print("\n".join(L))


if __name__ == "__main__":
    {"robust": robust, "holdout": holdout}[sys.argv[1]]()
