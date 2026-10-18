"""Survivorship / concentration checks for the candidate strategies (fixed rules).
The 15-symbol universe was chosen in 2026, so long-trend strategies may profit
from hindsight (NVDA, META, AMD, TSLA). Re-run on ETFs only and without the four
biggest winners; split Calls / Puts."""
import numpy as np, pandas as pd
from oat_research import data as D, engines_v2 as E, published as P, backtest as bt, study as S, options_model as om, wave_lab as W
from run_six import DAILY, costs
from wave_study import mask_for, score, lift_table

data = {s: df for s, df in D.load_folder("data/d1").items() if s != "VIX"}
vix = D.load_csv("data/d1/VIX.csv")["close"]; spy = data["SPY"]; cal = spy.index
ctxs = {s: E.Ctx(df, spy if s != "SPY" else None) for s, df in data.items()}
c = pd.read_pickle("results/wave_d1.pkl")
lt = lift_table(c, pd.Timestamp(2020, 1, 1))
top4 = [r.feature for r in lt.itertuples() if r.A_n >= 0.15 * (c.date < pd.Timestamp(2020, 1, 1)).sum()][:4]
wsel = c[score(c, top4) >= 3]
strategies = {k: DAILY[k] for k in ("P1 TSMOM monthly", "P2 Connors RSI2", "P3 52-week high", "N1 Trend-dip (RSI2+IBS+VIX)",
                                    "N2 52w-high squeeze", "N3 Turtle-55 quality", "N4 Turn-of-month trend")}
universes = {"all 15": list(data), "ETFs only": ["SPY", "QQQ", "IWM"],
             "ex NVDA/META/AMD/TSLA": [s for s in data if s not in ("NVDA", "META", "AMD", "TSLA")]}
print(f"{'strategy':30s} | " + " | ".join(f"{u:24s}" for u in universes) + " | calls / puts (all)")
for name, (maker, cfg) in list(strategies.items()) + [("W-v2b wave confluence", (None, bt.StrategyConfig("w", bt.ExitRules(option_stop=None, option_target=1.0, trail_arm=0.5, trail_drop=0.3, time_stop_days=20, min_dte_exit=7), dte=45, target_delta=0.75)))]:
    if maker is None:
        sigs_all = {s: W.to_signals(df, wsel[wsel.sym == s]) for s, df in data.items()}
    else:
        sigs_all = {s: maker(ctxs[s], vix, cal) for s in data}
    cells, trades_all = [], None
    for u, syms in universes.items():
        d = {s: data[s] for s in syms}; sg = {s: sigs_all[s] for s in syms}
        base, ov = costs(d)
        tr, _ = bt.run(d, sg, cfg, base, pd.Timestamp(2013, 1, 1), vix=vix, cost_overrides=ov)
        st = S.trade_stats(tr)
        a = S.trade_stats([t for t in tr if t.entry_date.year < 2020]); b = S.trade_stats([t for t in tr if t.entry_date.year >= 2020])
        cells.append(f"n={st['trades']:4d} {st.get('expectancy', 0):+6.1%} t={st.get('t_stat', 0):+.1f} ({a.get('expectancy', 0):+.0%}/{b.get('expectancy', 0):+.0%})")
        if u == "all 15":
            trades_all = tr
    calls = S.trade_stats([t for t in trades_all if t.direction > 0]); puts = S.trade_stats([t for t in trades_all if t.direction < 0])
    print(f"{name:30s} | " + " | ".join(f"{x:24s}" for x in cells) +
          f" | {calls['trades']} {calls.get('expectancy', 0):+.1%} / {puts['trades']} {puts.get('expectancy', 0):+.1%}", flush=True)
