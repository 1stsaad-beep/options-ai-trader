"""Published (P1-P5) and new (N1-N5) strategies on real data.

Daily: 15 symbols 2012-2026. A = 2013-2019 (selection), B = 2020-2026 (untouched).
5-minute: P5/N5 on 60 sessions (first half / second half).

python run_six.py   ->  results/six/RESULTS_SIX.md
"""
from __future__ import annotations

import itertools
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd

from oat_research import backtest as bt
from oat_research import data as D
from oat_research import engines_v2 as E
from oat_research import intraday as I
from oat_research import options_model as om
from oat_research import published as P
from oat_research import study as S

ETFS = {"SPY", "QQQ", "IWM"}
A = (pd.Timestamp(2013, 1, 1), pd.Timestamp(2019, 12, 31))
B = (pd.Timestamp(2020, 1, 1), pd.Timestamp(2026, 12, 31))


def X(**kw):
    base = dict(option_stop=None, option_target=None, trail_arm=None, time_stop_days=10, min_dte_exit=7,
                use_signal_stop=True, use_signal_target=True, exit_on_opposite=False)
    base.update(kw)
    return bt.ExitRules(**base)


# Pre-declared rules per strategy (set before looking at results).
DAILY = {
    "P1 TSMOM monthly": (lambda c, v, cal: P.tsmom_monthly(c), bt.StrategyConfig("P1", X(time_stop_days=21), dte=60, target_delta=0.60)),
    "P2 Connors RSI2": (lambda c, v, cal: P.connors_rsi2(c), bt.StrategyConfig("P2", X(time_stop_days=10), dte=35, target_delta=0.60)),
    "P3 52-week high": (lambda c, v, cal: P.high_52w(c), bt.StrategyConfig("P3", X(time_stop_days=20), dte=60, target_delta=0.60)),
    "P4 Turtle 20/10": (lambda c, v, cal: P.turtle_20(c), bt.StrategyConfig("P4", X(time_stop_days=30), dte=60, target_delta=0.60)),
    "N1 Trend-dip (RSI2+IBS+VIX)": (lambda c, v, cal: P.trend_dip(c, v),
                                    bt.StrategyConfig("N1", X(time_stop_days=7), dte=45, target_delta=0.75)),
    "N2 52w-high squeeze": (lambda c, v, cal: P.high_squeeze(c),
                            bt.StrategyConfig("N2", X(time_stop_days=15, option_target=1.0, trail_arm=0.5, trail_drop=0.3), dte=60, target_delta=0.60)),
    "N3 Turtle-55 quality": (lambda c, v, cal: P.turtle_quality(c), bt.StrategyConfig("N3", X(time_stop_days=30, trail_arm=0.6, trail_drop=0.3), dte=60, target_delta=0.65)),
    "N4 Turn-of-month trend": (lambda c, v, cal: P.tom_trend(c, cal), bt.StrategyConfig("N4", X(time_stop_days=9), dte=30, target_delta=0.60)),
}

GRID = list(itertools.product([0.6, 0.75], [35, 60], [None, 0.5]))


def costs(data, etf=0.02, stock=0.04, vrp=1.10):
    return om.OptionCosts(spread_pct=stock, vrp=vrp), {s: om.OptionCosts(spread_pct=etf, vrp=vrp) for s in data if s in ETFS}


def f(x, p=3, pct=False):
    if x is None or (isinstance(x, float) and not np.isfinite(x)):
        return "—"
    return f"{x * 100:+.1f}%" if pct else f"{x:+.{p}f}"


def line(name, st, extra=""):
    return (f"| {name} | {st['trades']} | {f(st.get('win_rate'), 2)} | {f(st.get('avg_win'), pct=True)} | {f(st.get('avg_loss'), pct=True)} | "
            f"{f(st.get('expectancy'), pct=True)} | {f(st.get('profit_factor'), 2)} | {f(st.get('t_stat'), 2)} | {extra}")


def main():
    data = {s: df for s, df in D.load_folder("data/d1").items() if s != "VIX"}
    vix = D.load_csv("data/d1/VIX.csv")["close"]
    spy = data["SPY"]
    cal = spy.index
    ctxs = {s: E.Ctx(df, spy if s != "SPY" else None) for s, df in data.items()}
    base, ov = costs(data)
    base2, ov2 = costs(data, 0.04, 0.08)
    out = ["# Published vs. new strategies — real data", "",
           "Daily: 15 symbols. A = 2013–2019, B = 2020–2026. Returns are per trade on option premium (modelled).", "",
           "## 1. Daily, fixed pre-declared rules", "",
           "| strategy | trades | win | avg win | avg loss | exp/trade | PF | t | A / B exp | 2× spreads | fwd10 ATR A / B | maxDD* |",
           "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    sel = ["", "## 2. Contract selection on A only, tested on B", "",
           "| strategy | chosen (delta, DTE, premium stop) | B trades | B win | B avg win | B avg loss | B exp/trade | B PF | B t | B CAGR | B maxDD | positive years (A+B) |",
           "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    store = {}
    for name, (maker, cfg) in DAILY.items():
        sigs = {s: maker(ctxs[s], vix, cal) for s in data}
        tr, cv = bt.run(data, sigs, cfg, base, A[0], B[1], vix=vix, cost_overrides=ov)
        st = S.trade_stats(tr)
        ta = S.trade_stats([t for t in tr if t.entry_date <= A[1]])
        tb = S.trade_stats([t for t in tr if t.entry_date >= B[0]])
        tr2, _ = bt.run(data, sigs, cfg, base2, A[0], B[1], vix=vix, cost_overrides=ov2)
        qa = S.signal_quality(data, sigs, start=A[0], end=A[1])
        qb = S.signal_quality(data, sigs, start=B[0], end=B[1])
        dd = S.curve_dd(S.oos_equity(tr))
        out.append(line(name, st, f"{f(ta.get('expectancy'), pct=True)} / {f(tb.get('expectancy'), pct=True)} | "
                                  f"{f(S.trade_stats(tr2).get('expectancy'), pct=True)} | {f(qa.get('fwd10'), 2)} / {f(qb.get('fwd10'), 2)} | {f(dd, pct=True)} |"))
        print(name, st["trades"], f(st.get("expectancy"), pct=True), flush=True)
        # train/test contract selection
        best, best_sc = None, -np.inf
        for delta, dte, stop in GRID:
            c2 = replace(cfg, target_delta=delta, dte=dte, exits=replace(cfg.exits, option_stop=stop))
            t_a, _ = bt.run(data, sigs, c2, base, A[0], A[1], vix=vix, cost_overrides=ov)
            sa = S.trade_stats(t_a)
            sc = sa.get("t_stat", -9) if sa["trades"] >= 30 else -9
            if sc > best_sc:
                best, best_sc = (delta, dte, stop), sc
        delta, dte, stop = best
        c2 = replace(cfg, target_delta=delta, dte=dte, exits=replace(cfg.exits, option_stop=stop))
        t_a, _ = bt.run(data, sigs, c2, base, A[0], A[1], vix=vix, cost_overrides=ov)
        t_b, cv_b = bt.run(data, sigs, c2, base, B[0], B[1], vix=vix, cost_overrides=ov)
        sb = S.trade_stats(t_b)
        mb = bt.metrics(t_b, cv_b)
        yrs = S.trade_stats(t_a + t_b)
        sel.append(f"| {name} | {delta}, {dte}, {stop} | {sb['trades']} | {f(sb.get('win_rate'), 2)} | {f(sb.get('avg_win'), pct=True)} | "
                   f"{f(sb.get('avg_loss'), pct=True)} | {f(sb.get('expectancy'), pct=True)} | {f(sb.get('profit_factor'), 2)} | "
                   f"{f(sb.get('t_stat'), 2)} | {f(mb.get('cagr'), pct=True)} | {f(mb.get('max_dd'), pct=True)} | "
                   f"{yrs.get('positive_years')}/{yrs.get('years')} |")
        store[name] = dict(fixed=st, A=ta, B=tb, chosen=best, B_sel=sb, mB=mb, by_year=yrs.get("by_year"))
    out += ["", "*maxDD = sequential curve, 4% of equity in premium per trade. fwd10 = underlying move 10 days after entry (ATR)."]
    out += sel

    # ---- 5-minute: P5 / N5 ----
    m5 = {s: df for s, df in D.load_folder("data/m5").items()}
    mb5, ov5 = costs(m5, 0.03, 0.06)
    cfg5 = bt.StrategyConfig("m5", bt.ExitRules(option_stop=None, option_target=None, trail_arm=None, time_stop_days=999,
                                                min_dte_exit=-1, flat_time="15:50", no_entry_after="15:00",
                                                exit_on_opposite=False), dte=1, target_delta=0.50)
    start = min(df.index[0] for df in m5.values()); end = max(df.index[-1] for df in m5.values()); mid = start + (end - start) / 2
    out += ["", f"## 3. 5-minute ({start:%Y-%m-%d} → {end:%Y-%m-%d}, 15 symbols)", "",
            "| strategy | trades | win | avg win | avg loss | exp/trade | PF | t | first / second half |", "|---|---|---|---|---|---|---|---|---|"]
    for name, maker in (("P5 ORB (published)", I.orb_published), ("N5 ORB in-play + VWAP exit", I.orb_inplay_vwap)):
        sigs = {s: maker(df) for s, df in m5.items()}
        tr, _ = bt.run(m5, sigs, cfg5, mb5, cost_overrides=ov5)
        st = S.trade_stats(tr)
        a = S.trade_stats([t for t in tr if t.entry_date < mid]); b = S.trade_stats([t for t in tr if t.entry_date >= mid])
        out.append(line(name, st, f"{f(a.get('expectancy'), pct=True)} / {f(b.get('expectancy'), pct=True)} |"))
        print(name, st["trades"], f(st.get("expectancy"), pct=True), flush=True)
    Path("results/six").mkdir(parents=True, exist_ok=True)
    Path("results/six/RESULTS_SIX.md").write_text("\n".join(out), encoding="utf-8")
    pd.to_pickle(store, "results/six/store.pkl")
    print("wrote results/six/RESULTS_SIX.md")


if __name__ == "__main__":
    main()
