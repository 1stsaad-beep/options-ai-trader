"""Stage 4 — projections for the CURRENT leg of a scenario: Fibonacci price targets, time windows, invalidation.

Price targets use the classic relationships (wave 3 = 1.0/1.618/2.618 x wave 1, wave 5 = 0.618/1.0 x wave 1 or
0.618 x (0->3), C = 0.618/1.0/1.618 x A, corrections 0.236-0.786 ...).  Time windows use the same ratios on the
durations of the corresponding legs (in bars of the scenario's timeframe).  Everything is measured from the
CONFIRMED start of the current leg, so nothing depends on the still-moving tentative extreme."""
from __future__ import annotations
import numpy as np
import pandas as pd
from . import patterns as PT

BAR_MIN = {"M": 21 * 390, "W": 5 * 390, "D": 390, "60": 60, "5": 5}


def _rel(a, b):
    return b - a


def targets(z):
    """returns dict(direction, start_p, levels=[(name, price)], minimum, invalid, time=[(name, bars)], bars_so_far)."""
    pat, idx = z.parts[-1]
    P = z.pts_p; n = len(idx) - 1
    pts = [float(P[i]) for i in idx]
    # bar positions of the boundaries (pivot ordinal -> bar index of that timeframe)
    lv, tm, minimum = [], [], None
    s = pts[-2] if n >= 1 else pts[0]          # start of current leg
    up = pts[-1] > s if n >= 1 else True
    sg = 1 if up else -1
    leg = lambda j: abs(pts[j + 1] - pts[j])   # length of leg j (0-based)
    dur = lambda j: float(z.bx[idx[j + 1]] - z.bx[idx[j]]) if z.bx is not None else np.nan
    if pat in PT.MOTIVE:
        if n == 1:
            pass
        elif n == 2:   # wave 2 in progress (moving against 1): retracements of wave 1
            w1 = leg(0); d = -1 if pts[1] > pts[0] else 1
            lv = [(f"2 = {r} x 1", pts[1] + d * r * w1) for r in (0.382, 0.5, 0.618, 0.786)]
            tm = [(f"t2 = {r} x t1", r * dur(0)) for r in (0.382, 0.618, 1.0)]
        elif n == 3:
            w1 = leg(0); d = 1 if pts[1] > pts[0] else -1
            lv = [(f"3 = {r} x 1", pts[2] + d * r * w1) for r in (1.0, 1.618, 2.618)]
            minimum = pts[1]
            tm = [(f"t3 = {r} x t1", r * dur(0)) for r in (1.0, 1.618, 2.618)]
        elif n == 4:
            w3 = leg(2); d = -1 if pts[3] > pts[2] else 1
            lv = [(f"4 = {r} x 3", pts[3] + d * r * w3) for r in (0.236, 0.382, 0.5)]
            tm = [(f"t4 = {r} x t2", r * dur(1)) for r in (1.0, 1.618, 2.618)]
        elif n == 5:
            w1 = leg(0); d = 1 if pts[1] > pts[0] else -1
            lv = sorted([(f"5 = {r} x 1", pts[4] + d * r * w1) for r in (0.618, 1.0, 1.618)] +
                        [("5 = 0.618 x (0-3)", pts[4] + d * 0.618 * abs(pts[3] - pts[0]))], key=lambda x: d * x[1])
            minimum = pts[3]
            tm = [(f"t5 = {r} x t1", r * dur(0)) for r in (0.618, 1.0, 1.618)]
    elif pat in ("ZIGZAG", "FLAT") or pat.startswith("DOUBLE") or pat == "TRIPLE_THREE":
        k = n if pat in ("ZIGZAG", "FLAT") else ((n - 1) % 4) + 1   # position inside the current three
        base = n - k
        a = leg(base) if n > base else None
        dA = 1 if pts[base + 1] > pts[base] else -1
        if k == 2:
            rs = (0.382, 0.5, 0.618, 0.786) if pat == "ZIGZAG" else (0.9, 1.0, 1.236, 1.382)
            lv = [(f"B = {r} x A", pts[base + 1] - dA * r * a) for r in rs]
            tm = [(f"tB = {r} x tA", r * dur(base)) for r in (0.618, 1.0, 1.618, 2.618)]
        elif k == 3:
            rs = (0.618, 1.0, 1.618) if pat != "FLAT" else (1.0, 1.272, 1.618)
            lv = [(f"C = {r} x A", pts[base + 2] + dA * r * a) for r in rs]
            minimum = pts[base + 1] if pat != "FLAT" else None
            tm = [(f"tC = {r} x tA", r * dur(base)) for r in (0.618, 1.0, 1.618)]
    elif pat == "TRIANGLE" and n >= 2:
        prev = leg(n - 2); d = 1 if pts[n] > pts[n - 1] else -1
        lv = [(f"{PT.labels(pat)[n - 1]} = {r} x prev", pts[n - 1] + d * r * prev) for r in (0.618, 0.786)]
        tm = [(f"t = {r} x prev", r * dur(n - 2)) for r in (0.618, 1.0)]
    so_far = float(z.bx[idx[-1]] - z.bx[idx[-2]]) if z.bx is not None and n >= 1 else np.nan
    return dict(pattern=pat, leg=PT.labels(pat)[n - 1] if n else "", up=up, start_p=s, levels=lv, minimum=minimum,
                invalid=z.invalidation(), time=tm, bars_so_far=so_far, tf=z.tf)


def to_time(start_t, bars, tf):
    """approximate calendar time after `bars` bars of timeframe tf from start_t (6.5-hour sessions, 5-day weeks)."""
    mins = bars * BAR_MIN[tf]
    days = mins / 390
    return pd.Timestamp(start_t) + pd.offsets.BDay(int(days)) + pd.Timedelta(minutes=(days % 1) * 390)
