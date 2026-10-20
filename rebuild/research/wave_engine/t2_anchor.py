"""Test 2 — engine 2 with a typical user's drawing (see PREREG_ROUND_W2.json, T2_anchor)."""
from __future__ import annotations
import sys, time
import numpy as np
import pandas as pd
from . import bars as B, pivots as PV, count as C, bottomup as BU
from .setups import resolve, K, START, OUT

PARENT = {"60": "D", "D": "W"}
CORR = ["ZIGZAG", "FLAT", "DOUBLE_THREE"]


def scan(sym, tf):
    b = B.bars(sym, tf); pb = B.bars(sym, PARENT[tf])
    pv = PV.zigzag(b, K, tf=tf); ppv = PV.zigzag(pb, K, tf=PARENT[tf])
    start = np.datetime64(pd.Timestamp(START[tf])); rows = []; cache = {}; done = set()
    bt = b.index.to_numpy(); te = b["t_end"].to_numpy()
    for j in np.flatnonzero(pv.conf >= start):
        conf = pv.conf[j]
        known = np.flatnonzero(ppv.conf <= conf)
        if len(known) < 12: continue
        kk = known[-31:]
        legs = [(abs(ppv.p[kk[a + 1]] - ppv.p[kk[a]]), kk[a], kk[a + 1]) for a in range(len(kk) - 1)]
        mag, a0, a1 = max(legs)
        if a1 < known[-10]: continue                                   # the drawn wave must be recent
        t0, t1 = pd.Timestamp(ppv.t[a0]), pd.Timestamp(ppv.t[a1]); p0, p1 = ppv.p[a0], ppv.p[a1]
        up = p1 > p0
        # child bars from the end of the drawn wave to this confirmation; anchor = the drawn wave's end extreme
        ci = int(np.searchsorted(te, conf)); ci = min(ci, len(b) - 1)
        i1 = int(np.searchsorted(bt, np.datetime64(t1)))
        seg = b.iloc[i1:ci + 1]
        if len(seg) < 15: continue
        col = seg["high"].to_numpy() if up else seg["low"].to_numpy()
        k = int(np.argmax(col) if up else np.argmin(col)); anchor_i = i1 + k
        sub = b.iloc[anchor_i:ci + 1]
        if len(sub) < 10: continue
        cpv = PV.zigzag(sub, K)
        sc = C.count(cpv, direction=-1 if up else 1, top=6, first_parts=CORR, max_irregular=1,
                     anchor=(np.datetime64(sub.index[0]), float(col[k]), 1 if up else -1, 0))
        if not sc: continue
        z = sc[0]; pat, idx = z.parts[0]
        # the correction must be COMPLETE: either it is followed by the start of the next move (2 parts) or it is
        # the whole count and its last point is the just-confirmed pivot
        if len(idx) - 1 != {"ZIGZAG": 3, "FLAT": 3, "DOUBLE_THREE": 7}[pat]: continue
        end_t = pd.Timestamp(z.pts_t[idx[-1]])
        if end_t != pd.Timestamp(pv.t[j]) or (a1, j) in done: continue
        cend = float(z.pts_p[idx[-1]]); retr = abs(float(col[k]) - cend) / mag
        if not (0.382 <= retr <= 0.886): continue
        entry = float(b["close"].iloc[ci])
        if (up and entry >= col[k]) or ((not up) and entry <= col[k]): continue
        stop = cend; tgt = cend + (mag if up else -mag)
        if (up and stop >= entry) or ((not up) and stop <= entry): continue
        dur = max(1, int(np.searchsorted(bt, np.datetime64(t1)) - np.searchsorted(bt, np.datetime64(t0))))
        H = int(np.clip(3 * dur, 20, 400))
        hit, r, nb = resolve(b, ci, up, entry, tgt, stop, H)
        ia, ib = int(np.searchsorted(pb.index.to_numpy(), np.datetime64(t0))), int(np.searchsorted(pb.index.to_numpy(), np.datetime64(t1)))
        inner = BU.leg_evidence(pb, ia, ib, up, cache)
        done.add((a1, j))
        rows.append(dict(sym=sym, tf=tf, t=b.index[ci], setup="T2_anchor", up=bool(up), entry=entry, stop=stop, target=tgt, H=H,
                         hit=hit, r=r, bars=nb, inner=inner, retr=retr, pattern=pat, p_agree=None, g_agree=None))
    return pd.DataFrame(rows)


if __name__ == "__main__":
    tf = sys.argv[1]
    for s in sys.argv[2:]:
        p = OUT / f"t2_{tf}_{s}.pkl"
        if p.exists(): continue
        t0 = time.time(); df = scan(s, tf); df.to_pickle(p); print(s, tf, len(df), f"{time.time() - t0:.0f}s", flush=True)
