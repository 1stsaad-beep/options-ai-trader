"""Test 5 — end-of-wave-5 reversal (PREREG_ROUND_W2.json): the just-confirmed pivot is the end of wave 5 of an
impulse; trade the correction toward the end of wave 4; variant DIV requires RSI divergence 3 -> 5."""
from __future__ import annotations
import sys, time
import numpy as np
import pandas as pd
from . import bars as B, pivots as PV, count as C, personality as PS
from .setups import window_pivots, resolve, K, NWIN, FAST_PATS, START, OUT


def scan(sym, tf):
    b = B.bars(sym, tf); pv = PV.zigzag(b, K, tf=tf)
    rsi = PS.frames(sym, tf)[0]["rsi"].to_numpy()
    start = np.datetime64(pd.Timestamp(START[tf])); rows = []
    for j in np.flatnonzero(pv.conf >= start):
        if j < 8: continue
        w, ci = window_pivots(pv, j, b, n=NWIN)
        if w is None or ci >= len(b) - 2: continue
        sc = C.count(w, top=8, first_parts=FAST_PATS, max_irregular=1)
        if not sc: continue
        z = sc[0]
        if len(z.parts) != 2 or z.parts[0][0] != "IMPULSE" or len(z.parts[1][1]) - 1 != 1: continue
        idx = z.parts[0][1]
        if pd.Timestamp(z.pts_t[idx[5]]) != pd.Timestamp(pv.t[j]): continue
        P = z.pts_p; up5 = P[idx[5]] > P[idx[4]]
        trade_up = not up5
        entry = float(b["close"].iloc[ci]); stop = float(P[idx[5]]); tgt = float(P[idx[4]])
        if (trade_up and (tgt <= entry or stop >= entry)) or ((not trade_up) and (tgt >= entry or stop <= entry)): continue
        bx = z.bx; i3, i5 = int(bx[idx[3]]), int(bx[idx[5]])
        div = (rsi[i5] < rsi[i3]) if up5 else (rsi[i5] > rsi[i3])
        H = int(np.clip(3 * (bx[idx[5]] - bx[idx[4]]), 20, 400))
        hit, r, nb = resolve(b, ci, trade_up, entry, tgt, stop, H)
        rows.append(dict(sym=sym, tf=tf, t=b.index[ci], setup="S5_end", up=bool(trade_up), entry=entry, stop=stop, target=tgt, H=H,
                         hit=hit, r=r, bars=nb, div=bool(div), inner=0.0, p_agree=None, g_agree=None))
    return pd.DataFrame(rows)


if __name__ == "__main__":
    tf = sys.argv[1]
    for s in sys.argv[2:]:
        p = OUT / f"end5_{tf}_{s}.pkl"
        if p.exists(): continue
        t0 = time.time(); df = scan(s, tf); df.to_pickle(p); print(s, tf, len(df), f"{time.time() - t0:.0f}s", flush=True)
