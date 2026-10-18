"""Round 5: deterministic, causal Elliott wave numbering on any timeframe.

Swings: confirmed fractal pivots (3/2) filtered by an ATR zig-zag (k x ATR). At every bar
the numbering uses only swings confirmed by that bar plus the bar's own close.

Impulse rules (up; down is the mirror):
  W1: s0 (low) -> s1 (high)
  W2: s2 low  > s0                        (wave 2 never retraces all of wave 1)
  W3: s3 high > s1                        (wave 3 goes beyond wave 1)
  W4: s4 low  > s1  (strict) or > s2 (relaxed=True)     (no overlap with wave 1)
  W5: s5 high > s3
  |W3| is not the shortest of W1, W3, W5 (checked once W5 is complete)
After a completed 5-wave impulse the next legs are A, B, C (correction).
The count starts at the most recent swing extreme that has not been broken since
(the lowest low for an up count, the highest high for a down count) inside a window of
the last `window` swings; when both directions give a valid count the larger structure
(older origin) wins.

label(t) returns (direction, wave) where wave in {"1","2","3","4","5","A","B","C", ""} is
the wave IN PROGRESS at bar t.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import indicators as ind


class ZZ:
    def __init__(self, atr, k):
        self.atr, self.k, self.out = atr, k, []

    def add(self, p):
        if not self.out:
            self.out.append(p); return
        last = self.out[-1]
        if last[3] == p[3]:
            if (p[2] > last[2]) if p[3] else (p[2] < last[2]):
                self.out[-1] = p
            return
        a = self.atr[p[0]]
        if np.isfinite(a) and abs(p[2] - last[2]) < self.k * a:
            return
        self.out.append(p)


def _count(sw, price, up, relaxed=True):
    """sw: swings starting at the count origin (a low for up). Returns wave in progress."""
    sgn = 1 if up else -1
    v = [sgn * q[2] for q in sw]           # in 'up' space
    p = sgn * price
    n = len(v)
    if p < v[0]:
        return None                          # origin broken -> count invalid
    # validate completed waves
    if n >= 3 and not v[2] > v[0]:
        return None
    if n >= 4 and not v[3] > v[1]:
        return None
    if n >= 5 and not (v[4] > (v[2] if relaxed else v[1])):
        return None
    if n >= 6:
        w1, w3, w5 = v[1] - v[0], v[3] - v[2], v[5] - v[4]
        if not v[5] > v[3] or (w3 < w1 and w3 < w5):
            return None
    labels = {1: "1", 2: "2", 3: "3", 4: "4", 5: "5", 6: "A", 7: "B", 8: "C"}
    # swings confirmed after the origin: n-1 -> wave in progress index = n
    k = n
    if k > 8:
        return None
    # live invalidations of the wave in progress
    if k == 2 and p <= v[0]:
        return None
    if k == 4 and p <= (v[2] if relaxed else v[1]):
        return None
    return labels[k]


def label_series(df: pd.DataFrame, k_atr: float = 1.5, window: int = 10, left=3, right=2, relaxed=True):
    """Per-bar (direction, wave, origin_index, swings) — direction +1 up count, -1 down count, 0 none."""
    atr = ind.atr(df).to_numpy()
    c = df["close"].to_numpy()
    piv = ind.pivots(df, left, right)
    zz = ZZ(atr, k_atr)
    j = 0
    dirs = np.zeros(len(df), int)
    waves = np.array([""] * len(df), dtype=object)
    for t in range(len(df)):
        while j < len(piv) and piv[j][1] <= t:
            zz.add(piv[j]); j += 1
        sw = zz.out[-window:]
        if len(sw) < 2:
            continue
        best = None
        for up in (True, False):
            # origin = extreme (lowest low for up) among swings of the right type in the window, not broken since
            cand = [i for i, q in enumerate(sw) if q[3] == (not up)]
            if not cand:
                continue
            i0 = min(cand, key=lambda i: sw[i][2]) if up else max(cand, key=lambda i: sw[i][2])
            w = _count(sw[i0:], c[t], up, relaxed)
            if w is None:
                continue
            if best is None or i0 < best[0]:   # the larger structure (older origin) wins
                best = (i0, up, w)
        if best:
            dirs[t] = 1 if best[1] else -1
            waves[t] = best[2]
    return pd.DataFrame({"wdir": dirs, "wave": waves}, index=df.index)
