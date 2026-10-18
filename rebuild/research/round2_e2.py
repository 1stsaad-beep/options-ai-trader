"""Round 2b (criterion declared before looking at B):
E2 = base strategy + every filter whose lift is > +1 pt in BOTH A1 and A2 (coverage >= 35%),
no greedy/t-stat step, round-1 contract kept. Then an equal-weight portfolio of the
strategies, compared with each strategy alone (daily equity curves summed)."""
import json
import numpy as np, pandas as pd
from round2 import STRATS, apply_filters, run, A, B, BIG, data
from oat_research import backtest as bt, study as S

def e2_filters(key):
    j = json.load(open(f"results/round2/{key}.json"))
    return [c for c, a, b, cov in j["lifts"] if a is not None and b is not None and a > 1 and b > 1]

curves = {}
for key in ("S0_wave", "S1_tsmom", "S2_dip_etf", "S3_52wh", "S4_turtle55", "S6_dualmom"):
    maker, cfg, only = STRATS[key]
    syms = only or list(data)
    sigs = maker()
    fl = e2_filters(key)
    fs = apply_filters(sigs, fl)
    out = []
    for lab, sg in (("base", sigs), ("E2", fs)):
        for per_lab, per in (("A", A), ("B", B)):
            tr, cv = run(sg, cfg, syms, per)
            st = S.trade_stats(tr); m = bt.metrics(tr, cv)
            out.append(f"{lab}-{per_lab}: n={st['trades']} win={st.get('win_rate',0):.2f} exp={st.get('expectancy',0):+.1%} t={st.get('t_stat',0):+.2f} DD={m.get('max_dd',0):+.1%}")
        if lab == "base":
            tr, cv = run(sg, cfg, syms, (A[0], B[1]))
            curves[key] = cv["equity"]
    print(f"{key} E2 filters={fl}\n   " + "\n   ".join(out), flush=True)

# equal-weight portfolio of the four robust/useful strategies (each its own 100k book)
def summarize(eq):
    eq = eq.dropna()
    r = eq.pct_change().dropna()
    yrs = (eq.index[-1] - eq.index[0]).days / 365.25
    return dict(cagr=(eq.iloc[-1] / eq.iloc[0]) ** (1 / yrs) - 1, dd=(eq / eq.cummax() - 1).min(),
                sharpe=r.mean() / r.std() * np.sqrt(252) if r.std() > 0 else 0)
for combo in (("S1_tsmom",), ("S1_tsmom", "S2_dip_etf"), ("S1_tsmom", "S2_dip_etf", "S3_52wh", "S4_turtle55"),
              ("S0_wave", "S1_tsmom", "S2_dip_etf", "S3_52wh", "S4_turtle55")):
    eq = sum(curves[k].reindex(curves["S1_tsmom"].index).ffill() for k in combo) / len(combo)
    for lab, per in (("A", A), ("B", B), ("ALL", (A[0], B[1]))):
        s = summarize(eq[(eq.index >= per[0]) & (eq.index <= per[1])])
        print(f"PORTFOLIO {'+'.join(combo):45s} {lab}: CAGR={s['cagr']:+.1%} maxDD={s['dd']:+.1%} Sharpe={s['sharpe']:.2f}", flush=True)
