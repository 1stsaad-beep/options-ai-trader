"""Pre-registered ORB variants (5m, 60 sessions): relative-volume 'stock in play' filter
and the R-target, each reported on both halves. No other variants were tried."""
import numpy as np
from oat_research import data as D, intraday as I, backtest as bt, study as S, options_model as om
from run_intraday import TF_CFG, ETFS

data = {s: df for s, df in D.load_folder("data/m5").items()}
cfg = TF_CFG["m5"]
base = om.OptionCosts(spread_pct=cfg["spread"][1]); ov = {s: om.OptionCosts(spread_pct=cfg["spread"][0]) for s in data if s in ETFS}
start = min(df.index[0] for df in data.values()); end = max(df.index[-1] for df in data.values()); mid = start + (end - start) / 2
for label, p in [("ORB base rvol>=1.0", I.ORBParams()), ("ORB rvol>=1.5", I.ORBParams(rvol_min=1.5)),
                 ("ORB rvol>=2.0", I.ORBParams(rvol_min=2.0)), ("ORB rvol>=1.0 target 2R", I.ORBParams(target_r=2.0)),
                 ("ORB calls only", I.ORBParams(allow_puts=False))]:
    sigs = {s: I.orb(df, p) for s, df in data.items()}
    tr, _ = bt.run(data, sigs, cfg["cfg"], base, cost_overrides=ov)
    st = S.trade_stats(tr); a = S.trade_stats([t for t in tr if t.entry_date < mid]); b = S.trade_stats([t for t in tr if t.entry_date >= mid])
    print(f"{label:26s} n={st['trades']:4d} win={st.get('win_rate',0):.2f} avgW={st.get('avg_win',0):+.3f} avgL={st.get('avg_loss',0):+.3f} "
          f"exp={st.get('expectancy',0):+.3f} t={st.get('t_stat',0):+.2f} A={a.get('expectancy',0):+.3f} B={b.get('expectancy',0):+.3f}")
