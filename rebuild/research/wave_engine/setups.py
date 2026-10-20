"""Decision-point test (pre-registered in results/wave/PREREG_SETUPS.json).

Events = confirmations of new pivots (causal zigzag).  At each event the engine counts the last 30 known pivots
plus the running leg; if the best scenario is an early wave 3 (just after a confirmed 1-2) or an early wave 5
(just after a confirmed 4) a trade is defined (entry = confirmation-bar close, stop = end of 2 / 4, target = Fib).
For every setup the parent and grandparent counts (coarser timeframes) and the inner structure of wave 1 are
recorded, then the trade is resolved on the following bars.
python -m wave_engine.setups <tf> <symbols...>  -> results/wave/setups_<tf>_<sym>.pkl"""
from __future__ import annotations
import sys, time
from pathlib import Path
import numpy as np
import pandas as pd
from . import bars as B, pivots as PV, count as C, patterns as PT, gen as G, bottomup as BU

OUT = Path(__file__).resolve().parents[1] / "results/wave"
K = 2.5
NWIN = 20
FAST_PATS = ["IMPULSE", "LEADING_DIAG", "ENDING_DIAG", "ZIGZAG", "FLAT", "TRIANGLE", "DOUBLE_THREE"]
PARENT = {"5": "60", "60": "D", "D": "W"}
GRAND = {"5": "D", "60": "W", "D": "M"}
PWIN = {"60": pd.Timedelta(days=40), "D": pd.Timedelta(days=500), "W": pd.Timedelta(days=2200), "M": None}
START = {"5": "2025-07-01", "60": "2023-03-01", "D": "2008-01-01"}


def window_pivots(pv, j, b, n=30):
    """pivots known when pivot j was confirmed (j and earlier, last n) + the running leg up to that bar."""
    lo = max(0, j - n + 1)
    conf_t = pv.conf[j]
    ci = int(np.searchsorted(b["t_end"].to_numpy(), conf_t))       # confirmation bar index
    ci = min(ci, len(b) - 1)
    seg = b.iloc[pv.i[j] + 1:ci + 1]
    if len(seg) == 0: return None, ci
    if pv.kind[j] == 1:   # after a high the running leg is down
        k = int(np.argmin(seg["low"].to_numpy())); tent = (seg.index[k], float(seg["low"].iloc[k]), -1, pv.i[j] + 1 + k)
    else:
        k = int(np.argmax(seg["high"].to_numpy())); tent = (seg.index[k], float(seg["high"].iloc[k]), 1, pv.i[j] + 1 + k)
    w = PV.Pivots(pv.t[lo:j + 1], pv.p[lo:j + 1], pv.kind[lo:j + 1], pv.i[lo:j + 1], pv.conf[lo:j + 1], tent, K, "")
    return w, ci


_PC = {}
FLOOR = {"60": "h", "D": "D", "W": "W-FRI", "M": "M"}


def parent_state(sym, ptf, asof, up):
    """the parent count can only change when a parent bar closes -> cached per (symbol, timeframe, completed bar)."""
    if ptf is None: return None
    ts = pd.Timestamp(asof)
    key_t = ts.floor("h") if ptf == "60" else (ts.normalize() if ptf == "D" else ts.to_period(FLOOR[ptf]).start_time)
    key = (sym, ptf, key_t)
    if key not in _PC:
        _PC[key] = _parent_raw(sym, ptf, asof)
    c = _PC[key]
    if c is None: return None
    return dict(motive=c["motive"], up=c["up"], agree=bool(c["motive"] and c["up"] == up), state=c["state"])


def _parent_raw(sym, ptf, asof):
    try:
        t0 = (pd.Timestamp(asof) - PWIN[ptf]) if PWIN.get(ptf) is not None else None
        sc = G.counts_for(sym, ptf, t0, asof, top=5)
    except Exception:
        return None
    if not sc: return None
    c = sc[0].current()
    return dict(motive=bool(c["motive_leg"]), up=bool(c["leg_up"]), state=f"{c['pattern']}:{c['leg']}")


def resolve(b, ci, up, entry, target, stop, H):
    hi, lo, cl = b["high"].to_numpy(), b["low"].to_numpy(), b["close"].to_numpy()
    ds = abs(entry - stop); R = abs(target - entry) / ds
    for j in range(ci + 1, min(len(b), ci + 1 + H)):
        th = hi[j] >= target if up else lo[j] <= target
        ts = lo[j] <= stop if up else hi[j] >= stop
        if th and ts: return 0.5, (R - 1) / 2, j - ci
        if th: return 1.0, R, j - ci
        if ts: return 0.0, -1.0, j - ci
    end = min(len(b) - 1, ci + H)
    return np.nan, ((cl[end] - entry) if up else (entry - cl[end])) / ds, end - ci


def scan(sym, tf):
    b = B.bars(sym, tf)
    pv = PV.zigzag(b, K, tf=tf)
    start = np.datetime64(pd.Timestamp(START[tf]))
    rows, cache = [], {}
    js = np.flatnonzero(pv.conf >= start)
    for j in js:
        if j < 8: continue
        w, ci = window_pivots(pv, j, b, n=NWIN)
        if w is None or ci >= len(b) - 2: continue
        sc = C.count(w, top=8, first_parts=FAST_PATS, max_irregular=1)
        if not sc: continue
        z = sc[0]
        pat, idx = z.parts[-1]
        n = len(idx) - 1
        if pat not in ("IMPULSE", "LEADING_DIAG") or n not in (3, 5): continue
        P = z.pts_p
        # the just-confirmed pivot must be the end of wave 2 (n=3) / wave 4 (n=5)
        if pd.Timestamp(z.pts_t[idx[n - 1]]) != pd.Timestamp(pv.t[j]): continue
        up = P[idx[1]] > P[idx[0]]
        entry = float(b["close"].iloc[ci])
        w1 = abs(P[idx[1]] - P[idx[0]])
        if n == 3:
            if (up and entry >= P[idx[1]]) or ((not up) and entry <= P[idx[1]]): continue   # 3 already past 1
            stop = float(P[idx[2]]); tgt = stop + (w1 if up else -w1); tgt2 = stop + (1.618 * w1 if up else -1.618 * w1)
            setup = "S12_early3"
        else:
            if (up and entry >= P[idx[3]]) or ((not up) and entry <= P[idx[3]]): continue
            stop = float(P[idx[4]]); tgt = stop + (0.618 * w1 if up else -0.618 * w1); tgt2 = stop + (w1 if up else -w1)
            setup = "S45_early5"
        if (up and (tgt <= entry or stop >= entry)) or ((not up) and (tgt >= entry or stop <= entry)): continue
        bx = z.bx
        d1 = int(bx[idx[1]] - bx[idx[0]]) if bx is not None else 50
        H = int(np.clip(3 * d1, 20, 400))
        hit, r, nb = resolve(b, ci, up, entry, tgt, stop, H)
        hit2, r2, _ = resolve(b, ci, up, entry, tgt2, stop, H)
        i0, i1 = int(bx[idx[0]]), int(bx[idx[1]])
        inner = BU.leg_evidence(b, i0, i1, up, cache)
        asof = b["t_end"].iloc[ci]
        par = parent_state(sym, PARENT[tf], asof, up)
        gra = parent_state(sym, GRAND[tf], asof, up)
        rows.append(dict(sym=sym, tf=tf, t=b.index[ci], setup=setup, up=bool(up), entry=entry, stop=stop, target=tgt, target2=tgt2,
                         H=H, hit=hit, r=r, hit2=hit2, r2=r2, bars=nb, inner=inner,
                         p_agree=None if par is None else par["agree"], p_state=None if par is None else par["state"],
                         g_agree=None if gra is None else gra["agree"], g_state=None if gra is None else gra["state"],
                         prob_gap=float(sc[0].score - sc[1].score) if len(sc) > 1 else np.nan))
    return pd.DataFrame(rows)


if __name__ == "__main__":
    tf = sys.argv[1]
    for s in sys.argv[2:]:
        p = OUT / f"setups_{tf}_{s}.pkl"
        if p.exists(): continue
        t0 = time.time(); df = scan(s, tf); df.to_pickle(p)
        print(s, tf, len(df), f"{time.time() - t0:.0f}s", flush=True)
