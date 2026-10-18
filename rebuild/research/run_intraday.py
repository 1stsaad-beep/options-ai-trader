"""Five-strategy study on 1-minute, 5-minute and hourly data (plus daily from run_study.py).

python run_intraday.py [--tf h1 m5 m1] [--out results]

Every strategy runs with FIXED documented parameters (no fitting) and is reported
for the first half (A) and second half (B) of each dataset separately; a strategy
is only credible if both halves agree. Divergence variants isolate whether the
RSI/MACD divergence condition itself adds value.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from oat_research import backtest as bt
from oat_research import data as D
from oat_research import engines_v2 as E
from oat_research import intraday as I
from oat_research import options_model as om
from oat_research import study as S

ETFS = {"SPY", "QQQ", "IWM", "DIA"}

TF_CFG = {
    "d1": dict(cfg=bt.StrategyConfig("d1", bt.ExitRules(), dte=35, target_delta=0.60), horizon=10, spread=(0.02, 0.04)),
    # options + exits per timeframe
    "h1": dict(cfg=bt.StrategyConfig("h1", bt.ExitRules(option_stop=0.45, option_target=0.80, trail_arm=0.40, trail_drop=0.25,
                                                       time_stop_days=14, min_dte_exit=3), dte=14, target_delta=0.60),
               horizon=14, spread=(0.03, 0.05)),
    "m5": dict(cfg=bt.StrategyConfig("m5", bt.ExitRules(option_stop=0.40, option_target=0.80, trail_arm=0.40, trail_drop=0.25,
                                                       time_stop_days=24, min_dte_exit=-1, flat_time="15:50",
                                                       no_entry_after="15:00"), dte=2, target_delta=0.50),
               horizon=12, spread=(0.03, 0.06)),
    "m1": dict(cfg=bt.StrategyConfig("m1", bt.ExitRules(option_stop=0.35, option_target=0.60, trail_arm=0.30, trail_drop=0.25,
                                                       time_stop_days=45, min_dte_exit=-1, flat_time="15:50",
                                                       no_entry_after="15:20"), dte=1, target_delta=0.50),
               horizon=30, spread=(0.03, 0.06)),
}


def strategies(tf, df, spy):
    out = {}
    for div in ("none", "rsi", "macd", "either", "both"):
        out[f"WD div={div}"] = I.wave_divergence(df, I.WDParams(divergence=div))
    out["WD W2->3 only (either)"] = I.wave_divergence(df, I.WDParams(setups="w2"))
    out["WD B->C only (either)"] = I.wave_divergence(df, I.WDParams(setups="b"))
    if tf in ("h1", "d1"):
        ctx = E.Ctx(df, spy)
        out["RCB"] = E.compression_breakout(ctx)
        out["TPB"] = E.trend_pullback(ctx)
    if tf == "d1":
        from oat_research import baseline as B
        per_bar = B.engine_signals(df)
        comp = B.composite(df, per_bar)
        out["App composite (current)"] = comp
        out["App composite + quality gate"] = E.quality_gate(ctx, comp)
    if tf == "m5":
        out["ORB 5m"] = I.orb(df)
    if tf in ("m5", "m1"):
        out["VWAP pullback"] = I.vwap_pullback(df)
    return out


def fmt(x, p=3):
    if x is None or (isinstance(x, float) and not np.isfinite(x)):
        return "—"
    return f"{x:+.{p}f}" if isinstance(x, float) else str(x)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tf", nargs="*", default=["h1", "m5", "m1"])
    ap.add_argument("--out", default="results")
    args = ap.parse_args()
    lines = ["# Intraday / hourly strategy study (real Yahoo data)", "",
             "Fixed parameters (no fitting). A = first half of the dataset, B = second half. "
             "Option P&L is modelled (Black–Scholes, IV from realised vol, spreads, $0.65/contract/side).", ""]
    for tf in args.tf:
        data = {s: df for s, df in D.load_folder(f"data/{tf}").items() if s != "VIX"}
        spy = data.get("SPY")
        cfgd = TF_CFG[tf]
        start = min(df.index[0] for df in data.values())
        end = max(df.index[-1] for df in data.values())
        mid = start + (end - start) / 2
        base = om.OptionCosts(spread_pct=cfgd["spread"][1], vrp=1.10)
        ov = {s: om.OptionCosts(spread_pct=cfgd["spread"][0], vrp=1.10) for s in data if s in ETFS}
        per = {}
        for s, df in data.items():
            for name, sig in strategies(tf, df, spy if s != "SPY" else None).items():
                per.setdefault(name, {})[s] = sig
        lines += [f"## {tf}: {len(data)} symbols, {start:%Y-%m-%d} → {end:%Y-%m-%d} (split {mid:%Y-%m-%d})", "",
                  "| strategy | signals | fwd (ATR) A / B | hit A / B | trades | win | avg win | avg loss | exp/trade | PF | t | exp A / B | maxDD* |",
                  "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
        for name, sigs in per.items():
            qa = S.signal_quality(data, sigs, horizon=cfgd["horizon"], end=mid)
            qb = S.signal_quality(data, sigs, horizon=cfgd["horizon"], start=mid)
            tr, _ = bt.run(data, sigs, cfgd["cfg"], base, cost_overrides=ov)
            st = S.trade_stats(tr)
            ta = S.trade_stats([t for t in tr if t.entry_date < mid])
            tb = S.trade_stats([t for t in tr if t.entry_date >= mid])
            dd = S.curve_dd(S.oos_equity(tr))
            lines.append(
                f"| {name} | {qa['n'] + qb['n']} | {fmt(qa.get('fwd10'), 2)} / {fmt(qb.get('fwd10'), 2)} | "
                f"{fmt(qa.get('hit'), 2)} / {fmt(qb.get('hit'), 2)} | {st['trades']} | {fmt(st.get('win_rate'), 2)} | "
                f"{fmt(st.get('avg_win'))} | {fmt(st.get('avg_loss'))} | {fmt(st.get('expectancy'))} | "
                f"{fmt(st.get('profit_factor'), 2)} | {fmt(st.get('t_stat'), 2)} | {fmt(ta.get('expectancy'))} / {fmt(tb.get('expectancy'))} | {fmt(dd)} |")
            print(tf, name, st.get("trades"), fmt(st.get("expectancy")), fmt(st.get("t_stat"), 2), flush=True)
        lines += ["", f"fwd = directional move 10 bars after entry (ATR units); hit = +2 ATR before -1 ATR within "
                      f"{cfgd['horizon']} bars; maxDD* = sequential curve with 4% of equity in premium per trade.", ""]
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "RESULTS_INTRADAY.md").write_text("\n".join(lines), encoding="utf-8")
    print("wrote", out / "RESULTS_INTRADAY.md")


if __name__ == "__main__":
    main()
