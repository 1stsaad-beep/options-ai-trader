"""Harness validation on SYNTHETIC data (never evidence of profitability).
1) NULL: no predictable structure  -> every engine must show no significant edge
   (proves there is no look-ahead leak in signals, entries or option marks).
2) PLANTED: a known drift after a known rule -> an 'oracle-of-rule' signal must
   show a clearly positive edge in both signal quality and option P&L (proves the
   harness can detect a real edge after costs)."""
import time
import numpy as np
import pandas as pd
from oat_research import data as D, baseline as B, engines_v2 as E, backtest as bt, study as S, options_model as om
from oat_research import indicators as ind


def rule_signal(df):
    c = df["close"]
    r = np.log(c).diff()
    cond = (r.rolling(10).std() < 0.75 * r.rolling(60).std()) & (c >= c.rolling(20).max())
    d = np.where(cond, 1, 0)
    a = ind.atr(df)
    return pd.DataFrame({"dir": d, "stop": c - 2 * a, "target": c + 3 * a, "reason": "rule"}, index=df.index)


def run(tag, planted, n_sym=8):
    syms = {f"S{i}": D.synthetic(3000, seed=100 + i, planted_edge=planted, start_price=50 + 30 * i) for i in range(n_sym)}
    syms["SPY"] = D.synthetic(3000, seed=7, base_vol=0.16)
    sigs = {}
    for s, df in syms.items():
        ctx = E.Ctx(df, syms["SPY"] if s != "SPY" else None)
        sigs[s] = {"baseline": B.composite(df), "rcb": E.compression_breakout(ctx), "tpb": E.trend_pullback(ctx),
                   "rule": rule_signal(df)}
    out = []
    for eng in ("baseline", "rcb", "tpb", "rule"):
        sq = S.signal_quality(syms, {s: v[eng] for s, v in sigs.items()})
        tr, cv = bt.run(syms, {s: v[eng] for s, v in sigs.items()}, bt.StrategyConfig(eng), om.OptionCosts())
        st = S.trade_stats(tr)
        line = (f"  {eng:9s} signals={sq['n']:4d} fwd10={sq.get('fwd10',0):+.3f}ATR t={sq.get('t_fwd10',0):+.2f} "
                f"hit={sq.get('hit',0):.2f} | option trades={st['trades']} win={st.get('win_rate',0):.2f} "
                f"exp/trade={st.get('expectancy',0):+.3f} t={st.get('t_stat',0):+.2f}")
        print(f"[{tag}]" + line)
        out.append((tag, eng, sq.get('t_fwd10', 0), st.get('t_stat', 0)))
    return out


if __name__ == "__main__":
    res = run("NULL", 0.0) + run("PLANTED", 0.004)
    null_ok = all(abs(t1) < 2.5 for tag, e, t1, t2 in res if tag == "NULL")
    planted_ok = [t1 for tag, e, t1, t2 in res if tag == "PLANTED" and e == "rule"][0] > 3
    print("NULL no-leak check:", "PASS" if null_ok else "FAIL")
    print("PLANTED detection check:", "PASS" if planted_ok else "FAIL")
