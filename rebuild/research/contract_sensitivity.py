"""Same signals, different contract/exit choices (real AAPL/SPY fixtures, small sample)."""
import numpy as np
from oat_research import data as D, backtest as bt, study as S
from run_study import build_signals, costs_for

data = {s.upper(): D.load_csv(f"../trader_core/test/fixtures/{s}_d1.csv") for s in ("aapl", "spy")}
sigs = build_signals(data, data["SPY"])
bc, ov = costs_for(data)
variants = {
    "app: d0.45 30DTE stop35 hold10": bt.StrategyConfig("a", bt.ExitRules(option_stop=0.35, option_target=0.90, trail_arm=0.30, trail_drop=0.20, time_stop_days=10, min_dte_exit=2), dte=30, target_delta=0.45),
    "v2: d0.60 35DTE stop50 hold10": bt.StrategyConfig("b"),
    "v2: d0.70 45DTE stop50 hold5": bt.StrategyConfig("c", bt.ExitRules(time_stop_days=5), dte=45, target_delta=0.70),
}
print(f"{'engine':20s}" + "".join(f" | {k:32s}" for k in variants))
for eng in ("baseline_composite", "gated_composite", "gated_trend", "gated_classical", "raw_divergence", "raw_elliott", "rcb+tpb"):
    cells = []
    for cfg in variants.values():
        tr, _ = bt.run(data, sigs[eng], cfg, bc, cost_overrides=ov)
        st = S.trade_stats(tr)
        cells.append(f"n={st['trades']:3d} win={st.get('win_rate', 0):.2f} exp={st.get('expectancy', 0):+.3f}")
    print(f"{eng:20s}" + "".join(f" | {c:32s}" for c in cells))
