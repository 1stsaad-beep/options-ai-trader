"""Stage 5b / T2 — do indicator confirmations rescue the wave forecasts?  (pre-registered in PREREG_STAGE5B.json)
Filters evaluated at the as-of bar, on data known then:
  htf  : previous DAILY close vs daily SMA50 agrees with the forecast direction
  macd : MACD line (12,26) on the forecast timeframe on the forecast's side of zero
  ema  : EMA50 on the forecast timeframe rising (up forecast) / falling (down) vs 5 bars ago
Pass: edge >= +0.03 and exp_R > 0 with day-clustered t >= 2 in BOTH original-15 and new-30, for UP and DOWN separately."""
import numpy as np
import pandas as pd
import r7_lib as L7
from . import bars as B
from .walk_eval import summ


def add_filters(D):
    out = []
    for (sym, tf), g in D.groupby(["sym", "tf"]):
        b = B.bars(sym, tf); c = b["close"]
        macd = c.ewm(span=12, adjust=False).mean() - c.ewm(span=26, adjust=False).mean()
        ema = c.ewm(span=50, adjust=False).mean(); slope = ema - ema.shift(5)
        d = B.bars(sym, "D")["close"]; dtrend = (d > d.rolling(50).mean()).shift(1)     # previous session
        g = g.copy()
        g["macd"] = macd.reindex(g.t).to_numpy(); g["slope"] = slope.reindex(g.t).to_numpy()
        day = g.t.dt.normalize() if tf != "D" else g.t
        g["dup"] = dtrend.reindex(day).to_numpy() if tf != "D" else dtrend.shift(0).reindex(g.t).to_numpy()
        out.append(g)
    D = pd.concat(out)
    sg = np.where(D.up, 1, -1)
    D["f_htf"] = (D.dup == D.up)
    D["f_macd"] = np.sign(D.macd) == sg
    D["f_ema"] = np.sign(D.slope) == sg
    D["f_all"] = D.f_htf & D.f_macd & D.f_ema
    D["grp"] = np.where(D.sym.isin(L7.ORIG), "orig15", "new30")
    return D


def verdict(D):
    rows = []
    W = D[D.who == "wave1"]
    for tf in sorted(W.tf.unique()):
        for f in ("none", "f_htf", "f_macd", "f_ema", "f_all"):
            x = W[W.tf == tf] if f == "none" else W[(W.tf == tf) & W[f]]
            cells = {}
            for (g, up), y in x.groupby(["grp", "up"]):
                s = summ(y); cells[f"{g}_{'up' if up else 'dn'}"] = s
            ok = all(c["edge"] >= 0.03 and c["exp_R"] > 0 and c["t"] >= 2 for c in cells.values()) and len(cells) == 4
            r = dict(tf=tf, filter=f, n=len(x), PASS=ok)
            for k, c in cells.items():
                r[f"{k}_edge"] = round(c["edge"], 3); r[f"{k}_expR"] = round(c["exp_R"], 3); r[f"{k}_t"] = round(c["t"], 2); r[f"{k}_n"] = int(c["n"])
            rows.append(r)
    return pd.DataFrame(rows)
