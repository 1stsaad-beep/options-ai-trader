"""Small real-data check on the repo's AAPL/SPY daily fixtures (2024-10 -> 2026-10).
~500 bars per symbol; after indicator warm-up only ~250-300 bars produce signals.
This is a sanity check of direction, NOT a statistically meaningful backtest."""
import numpy as np
import pandas as pd
from oat_research import data as D, baseline as B, engines_v2 as E, backtest as bt, study as S, options_model as om
from run_study import build_signals, costs_for

data = {s.upper(): D.load_csv(f"../trader_core/test/fixtures/{s}_d1.csv") for s in ("aapl", "spy")}
sigs = build_signals(data, data["SPY"])
base_cost, ov = costs_for(data)
app_cfg = bt.StrategyConfig("app_rules", bt.ExitRules(option_stop=0.35, option_target=0.90, trail_arm=0.30, trail_drop=0.20,
                                                     time_stop_days=10, min_dte_exit=2), dte=30, target_delta=0.45, risk_per_trade=0.01)
default_cfg = bt.StrategyConfig("default")
print(f"{'engine':22s} {'sig':>4s} {'fwd10':>7s} {'hit':>5s} | {'trades':>6s} {'win':>5s} {'avgW':>6s} {'avgL':>6s} {'exp':>7s} {'PF':>5s} {'ret':>7s} {'maxDD':>7s}")
rows = []
for eng, per in sigs.items():
    sq = S.signal_quality(data, per)
    for cfgname, cfg in (("app", app_cfg), ("v2", default_cfg)):
        if eng != "baseline_composite" and cfgname == "app":
            continue
        tr, cv = bt.run(data, per, cfg, base_cost, cost_overrides=ov)
        m = bt.metrics(tr, cv)
        name = eng + ("[app exits]" if cfgname == "app" else "")
        print(f"{name:22s} {sq['n']:4d} {sq.get('fwd10', np.nan):+7.2f} {sq.get('hit', np.nan):5.2f} | {m['trades']:6d} "
              f"{m.get('win_rate', np.nan):5.2f} {m.get('avg_win', np.nan):+6.2f} {m.get('avg_loss', np.nan):+6.2f} "
              f"{m.get('expectancy', np.nan):+7.3f} {m.get('profit_factor', np.nan):5.2f} {m.get('total_return', np.nan):+7.3f} {m.get('max_dd', np.nan):+7.3f}")
