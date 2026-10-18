"""Train/test selection of contract + exit rules (daily, 15 symbols).
Choose on A = 2013-2019 (by t-stat of premium returns, >= 40 trades), then report
the untouched B = 2020-2026 result. Signals are fixed (no signal tuning here)."""
import itertools, sys
import numpy as np, pandas as pd
from oat_research import data as D, engines_v2 as E, intraday as I, baseline as B, backtest as bt, study as S, options_model as om

ETFS = {"SPY", "QQQ", "IWM"}
data = {s: df for s, df in D.load_folder("data/d1").items() if s != "VIX"}
vix = D.load_csv("data/d1/VIX.csv")["close"]
spy = data["SPY"]
sig = {}
for s, df in data.items():
    ctx = E.Ctx(df, spy if s != "SPY" else None)
    comp = B.composite(df, B.engine_signals(df))
    sig.setdefault("RCB", {})[s] = E.compression_breakout(ctx)
    sig.setdefault("TPB", {})[s] = E.trend_pullback(ctx)
    sig.setdefault("GATED", {})[s] = E.quality_gate(ctx, comp)
    sig.setdefault("WD_RSI", {})[s] = I.wave_divergence(df, I.WDParams(divergence="rsi"))
base = om.OptionCosts(spread_pct=0.04); ov = {s: om.OptionCosts(spread_pct=0.02) for s in data if s in ETFS}
A = (pd.Timestamp(2013, 1, 1), pd.Timestamp(2019, 12, 31)); Bp = (pd.Timestamp(2020, 1, 1), pd.Timestamp(2026, 12, 31))
grid = list(itertools.product([0.6, 0.75], [35, 60], [5, 10, 20], [0.5, None]))
rows = []
for name, sg in sig.items():
    best, best_sc, res = None, -np.inf, []
    for delta, dte, hold, stop in grid:
        cfg = bt.StrategyConfig(name, bt.ExitRules(option_stop=stop, time_stop_days=hold, min_dte_exit=7), dte=dte, target_delta=delta)
        tr, _ = bt.run(data, sg, cfg, base, A[0], A[1], vix=vix, cost_overrides=ov)
        st = S.trade_stats(tr)
        sc = st.get("t_stat", -9) if st["trades"] >= 40 else -9
        res.append(((delta, dte, hold, stop), st.get("expectancy", np.nan), st["trades"]))
        if sc > best_sc:
            best, best_sc = (delta, dte, hold, stop), sc
    delta, dte, hold, stop = best
    cfg = bt.StrategyConfig(name, bt.ExitRules(option_stop=stop, time_stop_days=hold, min_dte_exit=7), dte=dte, target_delta=delta)
    trA, cA = bt.run(data, sg, cfg, base, A[0], A[1], vix=vix, cost_overrides=ov)
    trB, cB = bt.run(data, sg, cfg, base, Bp[0], Bp[1], vix=vix, cost_overrides=ov)
    a, b = S.trade_stats(trA), S.trade_stats(trB)
    mB = bt.metrics(trB, cB)
    pos = sum(1 for _, e, n in res if e > 0)
    print(f"{name}: chosen delta={delta} dte={dte} hold={hold} stop={stop} | A n={a['trades']} exp={a['expectancy']:+.3f} t={a['t_stat']:+.2f} "
          f"| B n={b['trades']} win={b.get('win_rate',0):.2f} avgW={b.get('avg_win',0):+.3f} avgL={b.get('avg_loss',0):+.3f} exp={b.get('expectancy',0):+.3f} "
          f"t={b.get('t_stat',0):+.2f} PF={b.get('profit_factor',0):.2f} B-portfolio CAGR={mB.get('cagr',0):+.3f} maxDD={mB.get('max_dd',0):+.3f} "
          f"| grid cells positive on A: {pos}/{len(res)}", flush=True)
    rows.append(dict(name=name, delta=delta, dte=dte, hold=hold, stop=stop, A=a, B=b, mB=mB, grid=res, byyearB=b.get("by_year")))
pd.to_pickle(rows, "results/contract_selection.pkl")
