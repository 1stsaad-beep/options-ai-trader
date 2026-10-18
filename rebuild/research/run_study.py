"""Full study on REAL daily data.

Usage:
    python run_study.py <folder_with_csvs> [--out results] [--split 2020]

Put one CSV per symbol in the folder (Yahoo or Stooq format, file name = symbol,
e.g. AAPL.csv, SPY.csv, VIX.csv). SPY is used as the market regime filter; VIX
(optional) as SPY's implied vol.

Phases
  A  Signal quality on the underlying (in-sample <= split-1, out-of-sample >= split)
  B  Option backtest of every engine with default rules (same costs for all)
  C  Walk-forward (3y train / 1y test, rolling) for the candidate strategies
  D  Robustness: per year, per symbol, cost sensitivity, parameter neighbourhood
"""
from __future__ import annotations

import argparse
import json
import time
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd

from oat_research import backtest as bt
from oat_research import baseline as B
from oat_research import data as D
from oat_research import engines_v2 as E
from oat_research import options_model as om
from oat_research import study as S

ETFS = {"SPY", "QQQ", "IWM", "DIA"}


def fmt(x, p=3):
    return "—" if x is None or (isinstance(x, float) and not np.isfinite(x)) else (f"{x:.{p}f}" if isinstance(x, float) else str(x))


def build_signals(data, spy):
    """All engines for all symbols -> {engine: {sym: frame}}."""
    out = {}
    for sym, df in data.items():
        if sym == "VIX":
            continue
        ctx = E.Ctx(df, spy if sym != "SPY" else None)
        per_bar = B.engine_signals(df)
        eng = {"baseline_composite": B.composite(df, per_bar)}
        for name in ("divergence", "harmonic", "elliott", "classical", "trend", "momentum"):
            raw = B.single_engine(df, per_bar, name)
            eng[f"raw_{name}"] = raw
            eng[f"gated_{name}"] = E.quality_gate(ctx, raw)
        eng["gated_composite"] = E.quality_gate(ctx, eng["baseline_composite"])
        eng["rcb"] = E.compression_breakout(ctx)
        eng["tpb"] = E.trend_pullback(ctx)
        eng["rcb_calls"] = E.compression_breakout(ctx, E.RCBParams(allow_puts=False))
        eng["tpb_calls"] = E.trend_pullback(ctx, E.TPBParams(allow_puts=False))
        eng["rcb+tpb"] = E.combine(eng["rcb"], eng["tpb"])
        for k, v in eng.items():
            out.setdefault(k, {})[sym] = v
    return out


def costs_for(data, spread_etf=0.02, spread_stock=0.04, vrp=1.10):
    base = om.OptionCosts(spread_pct=spread_stock, vrp=vrp)
    return base, {s: om.OptionCosts(spread_pct=spread_etf, vrp=vrp) for s in data if s in ETFS}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("folder")
    ap.add_argument("--out", default="results")
    ap.add_argument("--split", type=int, default=2020)
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    data = D.load_folder(args.folder)
    vix = data.pop("VIX", None)
    spy = data.get("SPY")
    tradable = {s: df for s, df in data.items()}
    print(f"symbols: {sorted(tradable)}; VIX={'yes' if vix is not None else 'no'}")
    t0 = time.time()
    sigs = build_signals(tradable, spy)
    print(f"signals built in {time.time() - t0:.0f}s")
    split = pd.Timestamp(args.split, 1, 1)
    base_cost, overrides = costs_for(tradable)
    vix_close = vix["close"] if vix is not None else None
    lines = ["# Study results (real data)", "", f"Symbols: {', '.join(sorted(tradable))}",
             f"Period: {min(df.index[0] for df in tradable.values()).date()} → {max(df.index[-1] for df in tradable.values()).date()}",
             f"In-sample < {args.split} ≤ out-of-sample", ""]

    # ---- Phase A ----
    lines += ["## A. Signal quality on the underlying (entry next open, ATR units)", "",
              "| engine | IS n | IS fwd10 | IS hit | OOS n | OOS fwd10 | OOS t | OOS hit |", "|---|---|---|---|---|---|---|---|"]
    for eng, per_sym in sigs.items():
        a = S.signal_quality(tradable, per_sym, end=split - pd.Timedelta(days=1))
        b = S.signal_quality(tradable, per_sym, start=split)
        lines.append(f"| {eng} | {a['n']} | {fmt(a.get('fwd10'))} | {fmt(a.get('hit'), 2)} | {b['n']} | "
                     f"{fmt(b.get('fwd10'))} | {fmt(b.get('t_fwd10'), 2)} | {fmt(b.get('hit'), 2)} |")
    print("phase A done")

    # ---- Phase B ----
    lines += ["", "## B. Option backtest, default rules, full period", "",
              "| engine | trades | win | avg win | avg loss | exp/trade | PF | CAGR | maxDD | Sharpe |",
              "|---|---|---|---|---|---|---|---|---|---|"]
    default_cfg = bt.StrategyConfig("default")
    app_cfg = bt.StrategyConfig("app_rules", bt.ExitRules(option_stop=0.35, option_target=0.90, trail_arm=0.30,
                                                         trail_drop=0.20, time_stop_days=10, min_dte_exit=2),
                                dte=30, target_delta=0.45, risk_per_trade=0.01)
    phase_b = {}
    for eng, per_sym in sigs.items():
        cfg = app_cfg if eng == "baseline_composite" else default_cfg
        tr, cv = bt.run(tradable, per_sym, cfg, base_cost, vix=vix_close, cost_overrides=overrides)
        m = bt.metrics(tr, cv)
        phase_b[eng] = m
        lines.append(f"| {eng} | {m['trades']} | {fmt(m.get('win_rate'), 2)} | {fmt(m.get('avg_win'))} | {fmt(m.get('avg_loss'))} | "
                     f"{fmt(m.get('expectancy'))} | {fmt(m.get('profit_factor'), 2)} | {fmt(m.get('cagr'))} | {fmt(m.get('max_dd'))} | {fmt(m.get('sharpe'), 2)} |")
    print("phase B done")

    # ---- Phase C: walk-forward ----
    lines += ["", "## C. Walk-forward (3y train → 1y test, parameters chosen on train only)", ""]
    candidates = {
        "rcb": (lambda p: {s: E.compression_breakout(E.Ctx(df, spy if s != "SPY" else None),
                                                     E.RCBParams(lookback=p["lookback"], squeeze_pct=p["squeeze_pct"],
                                                                 vol_mult=p["vol_mult"], target_atr=p["target_atr"]))
                           for s, df in tradable.items()},
                {"lookback": [20, 55], "squeeze_pct": [0.2, 0.35], "vol_mult": [1.2, 1.5], "target_atr": [2.5, 4.0],
                 "c_target_delta": [0.5, 0.7], "x_time_stop_days": [8, 15]}),
        "tpb": (lambda p: {s: E.trend_pullback(E.Ctx(df, spy if s != "SPY" else None),
                                               E.TPBParams(rsi2_max=p["rsi2_max"], adx_min=p["adx_min"], target_atr=p["target_atr"]))
                           for s, df in tradable.items()},
                {"rsi2_max": [5, 10, 20], "adx_min": [15, 25], "target_atr": [2.0, 3.0],
                 "c_target_delta": [0.6, 0.75], "x_time_stop_days": [5, 10]}),
        "gated_composite": (lambda p: {s: E.quality_gate(E.Ctx(df, spy if s != "SPY" else None), sigs["baseline_composite"][s],
                                                         E.GateParams(vol_mult=p["vol_mult"], rv_pct_max=p["rv_pct_max"]))
                                       for s, df in tradable.items()},
                            {"vol_mult": [1.0, 1.3], "rv_pct_max": [0.6, 0.9], "c_target_delta": [0.5, 0.7],
                             "x_time_stop_days": [8, 15]}),
    }
    wf_results = {}
    for name, (maker, grid) in candidates.items():
        print(f"walk-forward {name}")
        trades, log = S.walk_forward(tradable, maker, grid, default_cfg, base_cost, cost_overrides=overrides)
        st = S.trade_stats(trades)
        curve = S.oos_equity(trades)
        wf_results[name] = (st, log, trades)
        lines += [f"### {name}", "",
                  f"OOS trades {st['trades']}, win {fmt(st.get('win_rate'), 2)}, avg win {fmt(st.get('avg_win'))}, "
                  f"avg loss {fmt(st.get('avg_loss'))}, expectancy/trade {fmt(st.get('expectancy'))} (t={fmt(st.get('t_stat'), 2)}), "
                  f"PF {fmt(st.get('profit_factor'), 2)}, positive years {st.get('positive_years')}/{st.get('years')}, "
                  f"approx. max DD (4% premium per trade) {fmt(S.curve_dd(curve))}", "",
                  "| test year | params | trades | win | exp | PF | return | maxDD |", "|---|---|---|---|---|---|---|---|"]
        for r in log:
            lines.append(f"| {r['test']} | `{json.dumps(r['params'])}` | {r['trades']} | {fmt(r.get('win_rate'), 2)} | "
                         f"{fmt(r.get('expectancy'))} | {fmt(r.get('profit_factor'), 2)} | {fmt(r.get('total_return'))} | {fmt(r.get('max_dd'))} |")
        lines.append("")
    print("phase C done")

    # ---- Phase D: robustness of fixed default strategies ----
    lines += ["## D. Robustness (default parameters, no fitting)", "", "### Cost sensitivity (expectancy per trade)", "",
              "| engine | spread 2/4% vrp1.1 | spread 4/8% vrp1.1 | spread 2/4% vrp1.25 |", "|---|---|---|---|"]
    for eng in ("rcb", "tpb", "rcb+tpb", "gated_composite", "baseline_composite"):
        row = [eng]
        for se, ss, vrp in ((0.02, 0.04, 1.10), (0.04, 0.08, 1.10), (0.02, 0.04, 1.25)):
            bc, ov = costs_for(tradable, se, ss, vrp)
            tr, cv = bt.run(tradable, sigs[eng], default_cfg, bc, vix=vix_close, cost_overrides=ov)
            row.append(fmt(S.trade_stats(tr).get("expectancy")))
        lines.append("| " + " | ".join(row) + " |")
    lines += ["", "### Per symbol (rcb+tpb, default rules)", "", "| symbol | trades | win | exp |", "|---|---|---|---|"]
    tr, _ = bt.run(tradable, sigs["rcb+tpb"], default_cfg, base_cost, vix=vix_close, cost_overrides=overrides)
    for s in sorted(tradable):
        ts = [t for t in tr if t.symbol == s]
        st = S.trade_stats(ts)
        lines.append(f"| {s} | {st['trades']} | {fmt(st.get('win_rate'), 2)} | {fmt(st.get('expectancy'))} |")
    lines += ["", "### Exit reasons (rcb+tpb)", "", "```\n" + bt.exit_breakdown(tr).to_string() + "\n```" if tr else "none", ""]
    (out / "RESULTS.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {out / 'RESULTS.md'}")


if __name__ == "__main__":
    main()
