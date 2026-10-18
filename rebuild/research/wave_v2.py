"""Wave-2/B v2 on daily data: confirmations chosen on A only (top-3 and top-4 by
A lift), contract/exit chosen on A only, tested on B."""
import itertools
from dataclasses import replace
import numpy as np, pandas as pd
from oat_research import data as D, wave_lab as W, backtest as bt, study as S, options_model as om
from wave_study import FEATURES, mask_for, score, lift_table

ETFS = {"SPY", "QQQ", "IWM"}
split = pd.Timestamp(2020, 1, 1)
c = pd.read_pickle("results/wave_d1.pkl")
data = {s: df for s, df in D.load_folder("data/d1").items() if s != "VIX"}
lt = lift_table(c, split)
ranked = [r.feature for r in lt.itertuples() if r.A_n >= 0.15 * (c.date < split).sum()]
top3, top4 = ranked[:3], ranked[:4]
print("top by A lift:", ranked[:6])
variants = {
    "W-v2a: all of top-3": mask_for(c, top3),
    "W-v2b: >=3 of top-4": score(c, top4) >= 3,
    "W-v2c: top-3 + W2 only": mask_for(c, top3) & mask_for(c, ["W2->3 (structure break)"]),
    "W-v2d: top-3 + RSI divergence": mask_for(c, top3) & mask_for(c, ["div RSI (any)"]),
}
base = om.OptionCosts(spread_pct=0.04); ov = {s: om.OptionCosts(spread_pct=0.02) for s in data if s in ETFS}
base2 = om.OptionCosts(spread_pct=0.08); ov2 = {s: om.OptionCosts(spread_pct=0.04) for s in data if s in ETFS}
grid = list(itertools.product([0.6, 0.75], [45, 90], [10, 20], [None, 0.5]))
for name, m in variants.items():
    sel = c[m]
    A, B = sel[sel.date < split], sel[sel.date >= split]
    sigs = {s: W.to_signals(df, sel[sel.sym == s]) for s, df in data.items()}
    best, bsc = None, -9
    for delta, dte, hold, stop in grid:
        cfg = bt.StrategyConfig(name, bt.ExitRules(option_stop=stop, option_target=1.0, trail_arm=0.5, trail_drop=0.3,
                                                   time_stop_days=hold, min_dte_exit=7), dte=dte, target_delta=delta)
        tr, _ = bt.run(data, sigs, cfg, base, pd.Timestamp(2013, 1, 1), split - pd.Timedelta(days=1), cost_overrides=ov)
        st = S.trade_stats(tr)
        sc = st.get("t_stat", -9) if st["trades"] >= 30 else -9
        if sc > bsc: best, bsc = (delta, dte, hold, stop), sc
    delta, dte, hold, stop = best
    cfg = bt.StrategyConfig(name, bt.ExitRules(option_stop=stop, option_target=1.0, trail_arm=0.5, trail_drop=0.3,
                                               time_stop_days=hold, min_dte_exit=7), dte=dte, target_delta=delta)
    ta, _ = bt.run(data, sigs, cfg, base, pd.Timestamp(2013, 1, 1), split - pd.Timedelta(days=1), cost_overrides=ov)
    tb, cb = bt.run(data, sigs, cfg, base, split, pd.Timestamp(2026, 12, 31), cost_overrides=ov)
    tb2, _ = bt.run(data, sigs, cfg, base2, split, pd.Timestamp(2026, 12, 31), cost_overrides=ov2)
    a, b, m = S.trade_stats(ta), S.trade_stats(tb), bt.metrics(tb, cb)
    yrs = S.trade_stats(ta + tb)
    print(f"{name}: setups A {len(A)} fwd {A.fwd10.mean():+.2f} hit {A.hit.mean():.2f} | B {len(B)} fwd {B.fwd10.mean():+.2f} hit {B.hit.mean():.2f} "
          f"| chosen {best} | opt A n={a['trades']} exp={a.get('expectancy',0):+.1%} | B n={b['trades']} win={b.get('win_rate',0):.2f} "
          f"avgW={b.get('avg_win',0):+.1%} avgL={b.get('avg_loss',0):+.1%} exp={b.get('expectancy',0):+.1%} t={b.get('t_stat',0):+.2f} "
          f"PF={b.get('profit_factor',0):.2f} CAGR={m.get('cagr',0):+.1%} DD={m.get('max_dd',0):+.1%} | 2x spread B exp={S.trade_stats(tb2).get('expectancy',0):+.1%} "
          f"| years+ {yrs.get('positive_years')}/{yrs.get('years')}", flush=True)
