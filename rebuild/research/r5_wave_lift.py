"""Round 5 — MTF Elliott: context and enhancement lift (discovery only), then validation of the
chosen rule. python r5_wave_lift.py [tf] -> results/r5/WAVE_LIFT_{tf}.md"""
import sys
import numpy as np, pandas as pd
from r5_common import DISC, VALID, fmt

tf = int(sys.argv[1]) if len(sys.argv) > 1 else 15
df = pd.read_pickle(f"results/r5/wave_cand_{tf}.pkl")
df["date"] = pd.to_datetime(df["date"])
df["per"] = np.where(df.date <= DISC[1], "DISC", np.where(df.date <= VALID[1], "VALID", "HOLD"))
df["p05_d2"] = (df["hit0.5"] < 2).astype(float)
L = [f"# MTF Elliott — {tf}-minute grandchildren: lift study", "", "Outcome: close of day 2 after entry (ret2, daily ATR, direction-adjusted) and P(+0.5 ATR before −1 ATR within 2 days).", ""]

def stat(x):
    return f"{len(x)} | {x.ret2.mean():+.3f} | {x.p05_d2.mean()*100:.0f}%" if len(x) else "0 | — | —"

for side, sname in ((1, "CALL setups (grandchild wave 2 / bull correction)"), (-1, "PUT setups (grandchild wave B → C)")):
    d = df[(df.dir == side) & (df.per == "DISC")]
    v = df[(df.dir == side) & (df.per == "VALID")]
    L += [f"## {sname}", "", "| group | DISC n | DISC ret2 | DISC p0.5 | VALID n | VALID ret2 | VALID p0.5 |", "|---|---|---|---|---|---|---|"]
    L.append(f"| all | {stat(d)} | {stat(v)} |")
    for tag in ("W2", "B"):
        L.append(f"| tag {tag} | {stat(d[d.tag == tag])} | {stat(v[v.tag == tag])} |")
    # contexts
    L += ["", "**Context (daily / hourly wave labels):**", "", "| context | DISC n | DISC ret2 | DISC p0.5 | VALID n | VALID ret2 | VALID p0.5 |", "|---|---|---|---|---|---|---|"]
    for col in ("d", "h"):
        for (dr, wv), g in d.groupby([f"{col}_dir", f"{col}_wave"]):
            if len(g) < 60: continue
            gv = v[(v[f"{col}_dir"] == dr) & (v[f"{col}_wave"] == wv)]
            L.append(f"| {'daily' if col == 'd' else 'hourly'} {'up' if dr == 1 else 'down' if dr == -1 else 'none'} wave {wv or '—'} | {stat(g)} | {stat(gv)} |")
    # binary features
    feats = ["div_any", "div_rsi", "div_macd", "div_rsi_hidden", "div_rsi_regular", "div_macd_hidden", "div_macd_regular", "golden", "fib_golden", "fib_deep",
             "fib_time", "w2_lt_w1_time", "leg1_fast", "ma_touch20", "ma_touch50", "above_e200", "e50_gt_e200", "trend200", "above_ema50", "ema_stack",
             "ema50_slope", "macd_hist_rising", "macd_above_signal", "macd_zero_side", "avwap_hold", "vol_dryup", "bb_tag", "sr_polarity", "sr_prev_day",
             "double_extreme", "engulf_or_hammer", "rs", "d_up50", "d_above200"]
    L += ["", "**Single features (True vs False):**", "", "| feature | DISC True n / ret2 | DISC False ret2 | lift DISC | VALID True n / ret2 | VALID False ret2 | lift VALID |", "|---|---|---|---|---|---|---|"]
    rows = []
    for f in feats:
        if f not in d: continue
        dd = d[f].astype(float) == (1.0 if not (f.startswith("d_") and side < 0) else 0.0)
        vv = v[f].astype(float) == (1.0 if not (f.startswith("d_") and side < 0) else 0.0)
        a, b = d[dd].ret2.mean(), d[~dd].ret2.mean()
        a2, b2 = v[vv].ret2.mean(), v[~vv].ret2.mean()
        rows.append((a - b, f, dd.sum(), a, b, vv.sum(), a2, b2))
    for lift, f, n1, a, b, n2, a2, b2 in sorted(rows, reverse=True):
        L.append(f"| {f} | {n1} / {a:+.3f} | {b:+.3f} | **{lift:+.3f}** | {n2} / {a2:+.3f} | {b2:+.3f} | **{a2 - b2:+.3f}** |")
    L.append("")
open(f"results/r5/WAVE_LIFT_{tf}.md", "w").write("\n".join(L))
print("\n".join(L))
