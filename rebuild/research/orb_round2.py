"""ORB round 2 on 2 years of hourly data (first-hour opening range, ~500 sessions)
plus the 60-day 5-minute set. Variants are selected on the first half only and
reported on the second half.

Filters tested (all known at entry):
  rvol>=1.5 / >=2       opening-range volume vs its 14-session average
  spy_agree             SPY's opening-range candle points the same way
  daily_trend           prior daily close above (calls) / below (puts) its 20-day SMA
  gap_agree             overnight gap in the same direction as the opening candle
  vwap_exit             exit when price closes back across session VWAP
"""
import itertools
import numpy as np
import pandas as pd
from oat_research import data as D, intraday as I, backtest as bt, study as S, options_model as om, indicators as ind

ETFS = {"SPY", "QQQ", "IWM"}


def build(tf, rvol, spy_agree, daily_trend, gap_agree, vwap_exit, data, d1):
    spy_dir = None
    if spy_agree:
        sp = I.orb(data["SPY"], I.ORBParams(rvol_min=0.0, target_r=1e9))
        spy_dir = sp["dir"]
    out = {}
    for s, df in data.items():
        sig = I.orb(df, I.ORBParams(rvol_min=rvol, target_r=1e9))
        d = sig["dir"].copy()
        day = df.index.normalize()
        if spy_agree and s != "SPY":
            sd = spy_dir.reindex(df.index).fillna(0)
            d = d.where(np.sign(sd) == np.sign(d), 0)
        if daily_trend:
            dd = d1[s]
            up = (dd["close"] > ind.sma(dd["close"], 20)).shift(1)
            u = pd.Series(up.reindex(day).to_numpy(), index=df.index)
            d = d.where(((d > 0) & (u == True)) | ((d < 0) & (u == False)), 0)  # noqa: E712
        if gap_agree:
            first_open = df["open"].groupby(day).transform("first")
            prev_close = df["close"].groupby(day).last().shift(1).reindex(day).to_numpy()
            gap = np.sign(first_open.to_numpy() - prev_close)
            d = d.where(np.sign(d.to_numpy()) == gap, 0)
        sig["dir"] = d
        if vwap_exit:
            vw = I.session_vwap(df)
            sig["xl"] = (df["close"] < vw).to_numpy()
            sig["xs"] = (df["close"] > vw).to_numpy()
        out[s] = sig
    return out


def evaluate(tf):
    data = {s: df for s, df in D.load_folder(f"data/{tf}").items() if s != "VIX"}
    d1 = {s: df for s, df in D.load_folder("data/d1").items() if s != "VIX"}
    cfg = bt.StrategyConfig("orb", bt.ExitRules(option_stop=None, option_target=None, trail_arm=None, time_stop_days=999,
                                                min_dte_exit=-1, flat_time="15:50" if tf == "m5" else "15:30",
                                                no_entry_after="15:00", exit_on_opposite=False), dte=1, target_delta=0.5)
    base = om.OptionCosts(spread_pct=0.06); ov = {s: om.OptionCosts(spread_pct=0.03) for s in data if s in ETFS}
    start = min(df.index[0] for df in data.values()); end = max(df.index[-1] for df in data.values())
    mid = start + (end - start) / 2
    grid = list(itertools.product([1.0, 1.5, 2.0], [False, True], [False, True], [False, True], [False, True]))
    rows = []
    for g in grid:
        sigs = build(tf, *g, data, d1)
        tr, _ = bt.run(data, sigs, cfg, base, cost_overrides=ov)
        a = S.trade_stats([t for t in tr if t.entry_date < mid]); b = S.trade_stats([t for t in tr if t.entry_date >= mid])
        rows.append((g, a, b))
    ok = [r for r in rows if r[1]["trades"] >= 40]
    best = max(ok, key=lambda r: r[1].get("t_stat", -9)) if ok else rows[0]
    base_row = rows[0]
    print(f"== {tf} ORB ({start:%Y-%m-%d} -> {end:%Y-%m-%d}, split {mid:%Y-%m-%d}); grid {len(grid)}, cells positive in 1st half: "
          f"{sum(r[1].get('expectancy', -1) > 0 for r in ok)}/{len(ok)}; in 2nd half: {sum(r[2].get('expectancy', -1) > 0 for r in ok)}/{len(ok)}")
    for lab, (g, a, b) in (("base", base_row), ("chosen on 1st half", best)):
        names = ["rvol", "spy_agree", "daily_trend", "gap_agree", "vwap_exit"]
        print(f"  {lab:20s} {dict(zip(names, g))}")
        for nm, st in (("1st half", a), ("2nd half", b)):
            print(f"     {nm}: n={st['trades']} win={st.get('win_rate', 0):.2f} avgW={st.get('avg_win', 0):+.1%} avgL={st.get('avg_loss', 0):+.1%} "
                  f"exp={st.get('expectancy', 0):+.1%} t={st.get('t_stat', 0):+.2f} PF={st.get('profit_factor', 0):.2f}")
    return rows


if __name__ == "__main__":
    import pickle
    res = {tf: evaluate(tf) for tf in ("h1", "m5")}
    pickle.dump(res, open("results/orb_round2.pkl", "wb"))
