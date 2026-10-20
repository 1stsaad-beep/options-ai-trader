"""Stage 5 — walk-forward test of the LAST generation (hourly and 5-minute), no look-ahead.

At each as-of time the engine counts the recent window of the timeframe (only data known at that time), takes
the two best scenarios and turns each into a testable forecast:
   direction = the current leg's direction, TARGET = the first Fibonacci projection beyond the current price in
   that direction, STOP = the scenario's invalidation level.
Outcome = which is touched first in the following bars (horizon = 3x the bars the current leg has run, 10..300).
Benchmarks:
   * random walk: P(target before stop) = stop_dist / (target_dist + stop_dist)   (driftless gambler's ruin)
   * a simple non-Elliott forecaster on the same pivots: continue the last swing, target = 1.0x the previous
     swing in that direction, stop = start of the current swing.
python -m wave_engine.walk <tf> <symbols...>  -> results/wave/walk_<tf>_<sym>.pkl"""
from __future__ import annotations
import sys, time
from pathlib import Path
import numpy as np
import pandas as pd
from . import bars as B, gen as G, project as PJ, pivots as PV, count as C

OUT = Path(__file__).resolve().parents[1] / "results/wave"
WINDOW = {"60": 420, "5": 700, "D": 500}
STEP = {"60": 35, "5": 480, "D": 21}             # as-of spacing in bars (hourly ~ every 5 sessions; 5-min ~ every 3 sessions)


def first_touch(fut, up, target, stop, price):
    """returns (hit 1/0/0.5/nan, bars, outcome in R): +R at target, -1 at stop, else the mark-to-market at the
    horizon in units of the stop distance (so a driftless random walk has expectancy ~0)."""
    hi, lo, cl = fut["high"].to_numpy(), fut["low"].to_numpy(), fut["close"].to_numpy()
    ds = abs(price - stop); R = abs(target - price) / ds
    for j in range(len(hi)):
        th = hi[j] >= target if up else lo[j] <= target
        ts = lo[j] <= stop if up else hi[j] >= stop
        if th and ts: return 0.5, j, (R - 1) / 2
        if th: return 1.0, j, R
        if ts: return 0.0, j, -1.0
    if not len(cl): return np.nan, 0, np.nan
    return np.nan, len(hi), ((cl[-1] - price) if up else (price - cl[-1])) / ds


def forecast_from(z, price):
    r = PJ.targets(z)
    up = bool(r["up"])
    lv = [p for _, p in r["levels"] if (p > price if up else p < price)]
    if not lv: return None
    tgt = min(lv) if up else max(lv)
    stop = r["invalid"]
    if (up and stop >= price) or ((not up) and stop <= price): return None
    return dict(up=up, target=tgt, stop=stop, leg=f"{r['pattern']}:{r['leg']}", so_far=r["bars_so_far"])


def naive_from(b):
    pv = PV.zigzag(b, 2.0)
    T, P, K, tent = C._points(pv)
    if len(P) < 4: return None
    price = float(b["close"].iloc[-1]); up = P[-1] > P[-2]
    prev = abs(P[-3] - P[-4]) if len(P) >= 4 else abs(P[-2] - P[-3])
    tgt = P[-2] + (prev if up else -prev); stop = P[-2]
    if (up and (tgt <= price or stop >= price)) or ((not up) and (tgt >= price or stop <= price)): return None
    return dict(up=bool(up), target=float(tgt), stop=float(stop))


def run_symbol(sym, tf, start=None, end="2026-09-30"):
    start = start or ("2008-01-01" if tf == "D" else "2023-03-01")
    full = B.bars(sym, tf)
    full = full[(full.index >= start) & (full.index <= end)]
    allb = B.bars(sym, tf)
    rows = []
    idx_all = {t: i for i, t in enumerate(allb.index)}
    for k in range(WINDOW[tf], len(full) - 50, STEP[tf]):
        t_asof = full.index[k]; i = idx_all[t_asof]
        win = allb.iloc[max(0, i - WINDOW[tf]):i + 1]
        asof = win["t_end"].iloc[-1]
        price = float(win["close"].iloc[-1])
        try:
            sc = G.counts_for(sym, tf, win.index[0], asof, top=12)
        except Exception as e:
            continue
        two = C.best_two(sc)
        p = np.exp([z.score for z in sc]); p = p / p.sum() if len(p) else p
        fut = allb.iloc[i + 1:i + 1 + 300]
        base = dict(sym=sym, tf=tf, t=t_asof, price=price, n_scen=len(sc))
        for rank, z in enumerate(two):
            f = forecast_from(z, price)
            if not f: continue
            hz = int(np.clip(3 * (f["so_far"] if np.isfinite(f["so_far"]) else 20), 30, 300))
            out, nb, ro = first_touch(fut.iloc[:hz], f["up"], f["target"], f["stop"], price)
            dt, ds = abs(f["target"] - price), abs(price - f["stop"])
            rows.append({**base, "who": f"wave{rank + 1}", "prob": float(p[sc.index(z)]), "leg": f["leg"], "up": f["up"],
                         "target": f["target"], "stop": f["stop"], "hit": out, "bars": nb, "p_rw": ds / (dt + ds),
                         "R": dt / ds, "r_out": ro, "cur": f"{z.current()['pattern']}:{z.current()['leg']}"})
        nf = naive_from(win)
        if nf:
            out, nb, ro = first_touch(fut.iloc[:100], nf["up"], nf["target"], nf["stop"], price)
            dt, ds = abs(nf["target"] - price), abs(price - nf["stop"])
            rows.append({**base, "who": "naive", "prob": np.nan, "leg": "", "up": nf["up"], "target": nf["target"], "stop": nf["stop"],
                         "hit": out, "bars": nb, "p_rw": ds / (dt + ds), "R": dt / ds, "r_out": ro, "cur": ""})
    return pd.DataFrame(rows)


if __name__ == "__main__":
    tf = sys.argv[1]
    for s in sys.argv[2:]:
        t0 = time.time()
        p = OUT / f"walk_{tf}_{s}.pkl"
        if p.exists(): continue
        df = run_symbol(s, tf)
        df.to_pickle(p)
        print(s, tf, len(df), f"{time.time() - t0:.0f}s", flush=True)
