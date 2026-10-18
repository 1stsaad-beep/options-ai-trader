"""Round 2: systematic enhancement of every strategy.

Protocol (fixed before running):
  A1 = 2013-2016 (discover)  A2 = 2017-2019 (confirm)  B = 2020-2026 (final, untouched)
  1. Base trades with the round-1 configuration.
  2. Filter lift: mean premium return of trades that pass a filter minus all trades,
     in A1 and A2 separately. Candidate = lift > +1.0 pt in BOTH, and keeps >= 35% of A trades.
  3. Greedy combination (max 3 filters) in order of min(lift A1, lift A2); a filter is
     added only if the A t-stat improves and >= 25% of base A trades remain.
  4. Exit / contract grid on A only (delta x DTE x exit style), choose by A t-stat (>= 25 trades).
  5. Report base vs enhanced on A and on B, plus B with 2x spreads and B without the
     four biggest winners. Nothing is chosen on B.

python round2.py <strategy keys...>   (writes results/round2/<key>.json)
"""
from __future__ import annotations

import itertools
import json
import sys
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd

from oat_research import backtest as bt
from oat_research import data as D
from oat_research import engines_v2 as E
from oat_research import features as F
from oat_research import published as P
from oat_research import study as S
from oat_research import wave_lab as W
from run_six import X, costs
from wave_study import lift_table, score

A1 = (pd.Timestamp(2013, 1, 1), pd.Timestamp(2016, 12, 31))
A2 = (pd.Timestamp(2017, 1, 1), pd.Timestamp(2019, 12, 31))
A = (A1[0], A2[1])
B = (pd.Timestamp(2020, 1, 1), pd.Timestamp(2026, 12, 31))
ETF = ["SPY", "QQQ", "IWM"]
BIG = ("NVDA", "META", "AMD", "TSLA")

data = {s: df for s, df in D.load_folder("data/d1").items() if s != "VIX"}
vix = D.load_csv("data/d1/VIX.csv")["close"]
spy = data["SPY"]
ctxs = {s: E.Ctx(df, spy if s != "SPY" else None) for s, df in data.items()}
FEAT = F.build(data, vix)
calls_only = lambda f: f.assign(dir=f["dir"].clip(lower=0))


def wave_signals():
    c = pd.read_pickle("results/wave_d1.pkl")
    lt = lift_table(c, pd.Timestamp(2020, 1, 1))
    top4 = [r.feature for r in lt.itertuples() if r.A_n >= 0.15 * (c.date < pd.Timestamp(2020, 1, 1)).sum()][:4]
    sel = c[(score(c, top4) >= 3) & (c.dir > 0)]
    return {s: W.to_signals(df, sel[sel.sym == s]) for s, df in data.items()}


STRATS = {
    "S0_wave": (wave_signals, bt.StrategyConfig("S0", X(option_target=1.0, trail_arm=0.5, trail_drop=0.3, time_stop_days=20), dte=45, target_delta=0.75), None),
    "S1_tsmom": (lambda: {s: calls_only(P.tsmom_monthly(ctxs[s])) for s in data}, bt.StrategyConfig("S1", X(time_stop_days=21), dte=35, target_delta=0.75), None),
    "S2_dip_etf": (lambda: {s: P.trend_dip(ctxs[s], vix) for s in data}, bt.StrategyConfig("S2", X(time_stop_days=7), dte=35, target_delta=0.60), ETF),
    "S3_52wh": (lambda: {s: calls_only(P.high_52w(ctxs[s])) for s in data}, bt.StrategyConfig("S3", X(time_stop_days=20), dte=35, target_delta=0.75), None),
    "S4_turtle55": (lambda: {s: calls_only(P.turtle_quality(ctxs[s])) for s in data}, bt.StrategyConfig("S4", X(time_stop_days=30, trail_arm=0.6, trail_drop=0.3), dte=60, target_delta=0.75), None),
    "S6_dualmom": (lambda: P.dual_momentum(ctxs, data), bt.StrategyConfig("S6", X(time_stop_days=21), dte=35, target_delta=0.75), None),
    "S7_nr7": (lambda: {s: P.nr7_trend(ctxs[s]) for s in data}, bt.StrategyConfig("S7", X(time_stop_days=7), dte=35, target_delta=0.60), None),
}

EXIT_STYLES = {
    "base": {},
    "chandelier 3ATR": {"chandelier_atr": 3.0},
    "chandelier 2ATR": {"chandelier_atr": 2.0},
    "breakeven after 1ATR": {"breakeven_after_atr": 1.0},
    "breakeven 1ATR + chandelier 3ATR": {"breakeven_after_atr": 1.0, "chandelier_atr": 3.0},
}


def feats_at_signal(trades):
    rows = []
    for t in trades:
        f = FEAT[t.symbol]
        i = f.index.get_loc(t.entry_date) - 1
        rows.append(f.iloc[i].to_dict())
    return pd.DataFrame(rows)


def stats(tr):
    st = S.trade_stats(tr)
    return {k: (float(v) if isinstance(v, (int, float, np.floating, np.integer)) and v is not None else v)
            for k, v in st.items() if k != "by_year"}


def apply_filters(sigs, names):
    out = {}
    for s, sg in sigs.items():
        if not names:
            out[s] = sg
            continue
        ok = np.logical_and.reduce([FEAT[s][n].reindex(sg.index).fillna(False).to_numpy() for n in names])
        out[s] = sg.assign(dir=np.where(ok, sg["dir"], 0))
    return out


def run(sigs, cfg, syms, period, spread=(0.02, 0.04)):
    d = {s: data[s] for s in syms}
    base, ov = costs(d, *spread)
    tr, cv = bt.run(d, {s: sigs[s] for s in syms}, cfg, base, period[0], period[1], vix=vix, cost_overrides=ov)
    return tr, cv


def tstat(tr, min_n):
    st = S.trade_stats(tr)
    return st.get("t_stat", -9) if st["trades"] >= min_n else -9


def process(key):
    maker, cfg, only = STRATS[key]
    syms = only or list(data)
    sigs = maker()
    log = {"key": key}
    base_tr, _ = run(sigs, cfg, syms, (A[0], B[1]))
    trA = [t for t in base_tr if t.entry_date <= A[1]]
    f = feats_at_signal(trA)
    r = np.array([t.ret for t in trA])
    in1 = np.array([t.entry_date <= A1[1] for t in trA])
    lifts = []
    for col in f.columns:
        m = f[col].to_numpy()
        if m.mean() < 0.35 or m.all():
            continue
        l1 = r[in1 & m].mean() - r[in1].mean() if (in1 & m).sum() >= 8 else np.nan
        l2 = r[~in1 & m].mean() - r[~in1].mean() if (~in1 & m).sum() >= 8 else np.nan
        lifts.append((col, l1, l2, float(m.mean())))
    log["lifts"] = [(c_, None if np.isnan(a) else round(a * 100, 2), None if np.isnan(b) else round(b * 100, 2), round(cov, 2))
                    for c_, a, b, cov in sorted(lifts, key=lambda x: -np.nan_to_num(min(x[1], x[2]), nan=-9))]
    cands = [c_ for c_, a, b, _ in sorted(lifts, key=lambda x: -np.nan_to_num(min(x[1], x[2]), nan=-9))
             if np.isfinite(a) and np.isfinite(b) and a > 0.01 and b > 0.01]
    chosen, best_t = [], tstat(trA, 10)
    nA = len(trA)
    for c_ in cands:
        if len(chosen) == 3:
            break
        trial = chosen + [c_]
        tr, _ = run(apply_filters(sigs, trial), cfg, syms, A)
        if len(tr) >= 0.25 * nA and tstat(tr, 10) > best_t:
            chosen, best_t = trial, tstat(tr, 10)
    log["filters"] = chosen
    fsigs = apply_filters(sigs, chosen)
    best, bsc = None, -9
    for (delta, dte, style) in itertools.product([0.6, 0.75, 0.85], [35, 60], list(EXIT_STYLES)):
        c2 = replace(cfg, target_delta=delta, dte=dte, exits=replace(cfg.exits, **EXIT_STYLES[style]))
        tr, _ = run(fsigs, c2, syms, A)
        sc = tstat(tr, 25)
        if sc > bsc:
            best, bsc = (delta, dte, style), sc
    if best is None:
        best = (cfg.target_delta, cfg.dte, "base")
    delta, dte, style = best
    ecfg = replace(cfg, target_delta=delta, dte=dte, exits=replace(cfg.exits, **EXIT_STYLES[style]))
    log["contract"] = {"delta": delta, "dte": dte, "exit": style}
    res = {}
    for lab, s_, c_, period, syms_, spread in (
            ("base_A", sigs, cfg, A, syms, (0.02, 0.04)), ("base_B", sigs, cfg, B, syms, (0.02, 0.04)),
            ("enh_A", fsigs, ecfg, A, syms, (0.02, 0.04)), ("enh_B", fsigs, ecfg, B, syms, (0.02, 0.04)),
            ("enh_B_2x", fsigs, ecfg, B, syms, (0.04, 0.08)),
            ("enh_B_exbig", fsigs, ecfg, B, [s for s in syms if s not in BIG], (0.02, 0.04)),
            ("enh_ALL", fsigs, ecfg, (A[0], B[1]), syms, (0.02, 0.04))):
        tr, cv = run(s_, c_, syms_, period, spread)
        st = stats(tr)
        m = bt.metrics(tr, cv)
        st.update(cagr=m.get("cagr"), max_dd=m.get("max_dd"), sharpe=m.get("sharpe"))
        if lab == "enh_ALL":
            st["by_year"] = {int(y): [n, round(e, 4)] for y, (n, e) in S.trade_stats(tr).get("by_year", {}).items()}
        res[lab] = st
    log["results"] = res
    Path("results/round2").mkdir(parents=True, exist_ok=True)
    Path(f"results/round2/{key}.json").write_text(json.dumps(log, indent=1, default=float), encoding="utf-8")
    b, e = res["base_B"], res["enh_B"]
    print(f"{key}: filters={chosen} contract={best} | B base n={b['trades']} win={b.get('win_rate', 0):.2f} exp={b.get('expectancy', 0):+.1%} "
          f"-> enh n={e['trades']} win={e.get('win_rate', 0):.2f} exp={e.get('expectancy', 0):+.1%} t={e.get('t_stat', 0):+.2f} PF={e.get('profit_factor', 0):.2f} "
          f"| A base {res['base_A'].get('expectancy', 0):+.1%} -> {res['enh_A'].get('expectancy', 0):+.1%} | 2x {res['enh_B_2x'].get('expectancy', 0):+.1%} "
          f"exBig {res['enh_B_exbig'].get('expectancy', 0):+.1%}", flush=True)


if __name__ == "__main__":
    for k in sys.argv[1:] or list(STRATS):
        process(k)
