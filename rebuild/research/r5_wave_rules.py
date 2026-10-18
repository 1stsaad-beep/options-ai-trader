"""Round 5 — MTF Elliott: the literal rule (as specified) and the developed rule.
Feature selection uses DISCOVERY only, keeping features whose lift is positive in BOTH halves
of discovery (2016-18, 2019-20); max 3 features, greedy by discovery lift.
python r5_wave_rules.py [tf] -> results/r5/WAVE_RULES_{tf}.md, results/r5/wave_rules_{tf}.json"""
import json, sys
import numpy as np, pandas as pd
from r5_common import DISC, VALID, HOLD

tf = int(sys.argv[1]) if len(sys.argv) > 1 else 15
df = pd.read_pickle(f"results/r5/wave_cand_{tf}.pkl")
df["date"] = pd.to_datetime(df["date"])
df["per"] = np.where(df.date <= DISC[1], "DISC", np.where(df.date <= VALID[1], "VALID", "HOLD"))
df["half"] = np.where(df.date <= pd.Timestamp("2018-12-31"), 1, 2)
df["p05_d2"] = (df["hit0.5"] < 2).astype(float)
for c in ["div_any","trend200","above_e200","e50_gt_e200","ema_stack","ema50_slope","macd_above_signal","macd_zero_side","engulf_or_hammer",
          "leg1_fast","fib_golden","fib_deep","fib_time","ma_touch20","ma_touch50","sr_polarity","sr_prev_day","vol_dryup","avwap_hold","rs",
          "double_extreme","w2_lt_w1_time","bb_tag","div_rsi","div_macd"]:
    df[c] = df[c].astype(float).fillna(0).astype(bool)

def literal(side):
    if side == 1:   # daily impulse up (wave 1/3/5 in progress), hourly up wave 3, grandchild W2 with bullish divergence
        return (df.dir == 1) & (df.d_dir == 1) & df.d_wave.isin(["1", "3", "5"]) & (df.h_dir == 1) & (df.h_wave == "3") & df.div_any
    # daily in correction or down impulse, hourly in a C (of an up count) or a down impulse leg, grandchild B->C with bearish divergence
    dctx = ((df.d_dir == 1) & df.d_wave.isin(["2", "4", "A", "B", "C"])) | ((df.d_dir == -1) & df.d_wave.isin(["1", "3", "5"]))
    hctx = ((df.h_dir == 1) & (df.h_wave == "C")) | ((df.h_dir == -1) & df.h_wave.isin(["1", "3", "5", "C"]))
    return (df.dir == -1) & dctx & hctx & df.div_any

def stat(m, per):
    x = df[m & (df.per == per)]
    if len(x) < 3: return dict(n=len(x))
    return dict(n=len(x), ret2=x.ret2.mean(), ret1=x.ret1.mean(), p05=x.p05_d2.mean(), t=x.ret2.mean() / x.ret2.std(ddof=1) * np.sqrt(len(x)))

FEATS = ["trend200","above_e200","e50_gt_e200","ema_stack","ema50_slope","macd_above_signal","macd_zero_side","engulf_or_hammer","leg1_fast",
         "fib_golden","fib_deep","fib_time","ma_touch20","ma_touch50","sr_polarity","sr_prev_day","vol_dryup","avwap_hold","rs","div_any",
         "double_extreme","w2_lt_w1_time","div_rsi","div_macd"]
L = [f"# MTF Elliott — rules ({tf}-minute grandchildren)", ""]
out = {}
for side, name in ((1, "CALL"), (-1, "PUT")):
    base = (df.dir == side)
    d = df[base & (df.per == "DISC")]
    chosen, cur = [], d
    for _ in range(3):
        best = None
        for f in FEATS:
            if f in chosen: continue
            ok = True; lifts = []
            for h in (1, 2):
                x = cur[cur.half == h]
                a, b = x[x[f]].ret2.mean(), x[~x[f]].ret2.mean()
                if not (np.isfinite(a) and np.isfinite(b)) or a - b <= 0 or x[f].sum() < 40: ok = False
                lifts.append(a - b)
            if ok and (best is None or np.mean(lifts) > best[1]):
                best = (f, np.mean(lifts))
        if best is None: break
        chosen.append(best[0]); cur = cur[cur[best[0]]]
    dev = base.copy()
    for f in chosen: dev &= df[f]
    lit = literal(side)
    out[name] = dict(features=chosen)
    L += [f"## {name}", "", f"Developed rule = grandchild setup ({'bull W2/correction' if side == 1 else 'bear B→C'}) AND " + (" AND ".join(chosen) or "(none passed)"), "",
          "| rule | period | n | ret day1 (ATR) | ret day2 (ATR) | P(+0.5 ATR before stop, 2d) | t |", "|---|---|---|---|---|---|---|"]
    for rn, m in (("all grandchild setups (base)", base), ("literal rule (as specified)", lit), ("developed rule", dev),
                  ("developed + divergence", dev & df.div_any)):
        for per in ("DISC", "VALID", "HOLD"):
            s = stat(m, per)
            if s["n"] < 3:
                L.append(f"| {rn} | {per} | {s['n']} | — | — | — | — |"); continue
            L.append(f"| {rn} | {per} | {s['n']} | {s['ret1']:+.3f} | {s['ret2']:+.3f} | {s['p05']*100:.0f}% | {s['t']:.2f} |")
    L.append("")
open(f"results/r5/WAVE_RULES_{tf}.md", "w").write("\n".join(L))
json.dump(out, open(f"results/r5/wave_rules_{tf}.json", "w"), indent=2)
print("\n".join(L))
