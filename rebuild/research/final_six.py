"""Final validation of the six proposed strategies (fixed rules, no further tuning).
Reports: all symbols, ETFs only, ex the 4 biggest winners, A/B halves, 2x spreads,
positive years, max drawdown of the portfolio simulation."""
import numpy as np, pandas as pd
from dataclasses import replace
from oat_research import data as D, engines_v2 as E, published as P, intraday as I, backtest as bt, study as S, options_model as om, wave_lab as W
from run_six import DAILY, costs, X
from wave_study import score, lift_table

data = {s: df for s, df in D.load_folder("data/d1").items() if s != "VIX"}
vix = D.load_csv("data/d1/VIX.csv")["close"]; spy = data["SPY"]; cal = spy.index
ctxs = {s: E.Ctx(df, spy if s != "SPY" else None) for s, df in data.items()}
calls_only = lambda f: f.assign(dir=f["dir"].clip(lower=0))
c = pd.read_pickle("results/wave_d1.pkl")
lt = lift_table(c, pd.Timestamp(2020, 1, 1))
top4 = [r.feature for r in lt.itertuples() if r.A_n >= 0.15 * (c.date < pd.Timestamp(2020, 1, 1)).sum()][:4]
wsel = c[(score(c, top4) >= 3) & (c.dir > 0)]
ETF = ["SPY", "QQQ", "IWM"]
FINAL = {
    "S0 Wave-2/B confluence (calls)": ({s: W.to_signals(df, wsel[wsel.sym == s]) for s, df in data.items()},
        bt.StrategyConfig("w", X(option_target=1.0, trail_arm=0.5, trail_drop=0.3, time_stop_days=20), dte=45, target_delta=0.75), None),
    "S1 TSMOM monthly calls": ({s: calls_only(P.tsmom_monthly(ctxs[s])) for s in data},
        bt.StrategyConfig("s1", X(time_stop_days=21), dte=35, target_delta=0.75), None),
    "S2 Index trend-dip (ETFs)": ({s: P.trend_dip(ctxs[s], vix) for s in data},
        bt.StrategyConfig("s2", X(time_stop_days=7), dte=35, target_delta=0.60), ETF),
    "S3 Turtle-55 quality calls": ({s: calls_only(P.turtle_quality(ctxs[s])) for s in data},
        bt.StrategyConfig("s3", X(time_stop_days=30, trail_arm=0.6, trail_drop=0.3), dte=60, target_delta=0.75), None),
    "S4 52-week-high calls": ({s: calls_only(P.high_52w(ctxs[s])) for s in data},
        bt.StrategyConfig("s4", X(time_stop_days=20), dte=35, target_delta=0.75), None),
}
rows = []
for name, (sigs, cfg, only) in FINAL.items():
    syms_main = only or list(data)
    res = {}
    for u, syms in (("main", syms_main), ("etf", ETF), ("exw", [s for s in syms_main if s not in ("NVDA", "META", "AMD", "TSLA")])):
        d = {s: data[s] for s in syms}; sg = {s: sigs[s] for s in syms}
        base, ov = costs(d); base2, ov2 = costs(d, 0.04, 0.08)
        tr, cv = bt.run(d, sg, cfg, base, pd.Timestamp(2013, 1, 1), vix=vix, cost_overrides=ov)
        res[u] = (tr, cv)
        if u == "main":
            tr2, _ = bt.run(d, sg, cfg, base2, pd.Timestamp(2013, 1, 1), vix=vix, cost_overrides=ov2)
            res["2x"] = S.trade_stats(tr2)
    tr, cv = res["main"]; st = S.trade_stats(tr); m = bt.metrics(tr, cv)
    a = S.trade_stats([t for t in tr if t.entry_date.year < 2020]); b = S.trade_stats([t for t in tr if t.entry_date.year >= 2020])
    e = S.trade_stats(res["etf"][0]); x = S.trade_stats(res["exw"][0])
    rows.append(dict(name=name, n=st["trades"], win=st.get("win_rate"), aw=st.get("avg_win"), al=st.get("avg_loss"),
                     exp=st.get("expectancy"), pf=st.get("profit_factor"), t=st.get("t_stat"), A=a.get("expectancy"), B=b.get("expectancy"),
                     x2=res["2x"].get("expectancy"), etf=e.get("expectancy"), etf_n=e["trades"], exw=x.get("expectancy"), exw_t=x.get("t_stat"),
                     yrs=f"{st.get('positive_years')}/{st.get('years')}", cagr=m.get("cagr"), dd=m.get("max_dd"), sharpe=m.get("sharpe"),
                     by_year=st.get("by_year")))
    print(name, f"n={st['trades']} exp={st.get('expectancy',0):+.1%} t={st.get('t_stat',0):+.2f} A={a.get('expectancy',0):+.1%} B={b.get('expectancy',0):+.1%} "
          f"2x={res['2x'].get('expectancy',0):+.1%} ETF={e.get('expectancy',0):+.1%}({e['trades']}) exW={x.get('expectancy',0):+.1%} t={x.get('t_stat',0):+.1f} "
          f"yrs={st.get('positive_years')}/{st.get('years')} CAGR={m.get('cagr',0):+.1%} DD={m.get('max_dd',0):+.1%} Sharpe={m.get('sharpe',0):.2f}", flush=True)
pd.to_pickle(rows, "results/final_six.pkl")
