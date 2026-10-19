"""Bottom-up evidence: count every COMPLETED leg of a candidate scenario from the inside.
A leg that subdivides best as a complete 5-wave motive supports a motive label (1, 3, 5, A/C of a zigzag, C of a
flat); a leg that subdivides best as a complete 3-wave / triangle / combination supports a corrective label
(2, 4, B, A/B of a flat, triangle legs, W/X/Y).  This is the decisive Elliott test that ratios alone cannot give,
and it is what lets children correct their parents (e.g. a rise to a new high that is a 3 -> it is a B, not a 5)."""
from __future__ import annotations
from functools import lru_cache
import numpy as np
from . import pivots as PV, count as C, patterns as PT

MOT = ("IMPULSE", "LEADING_DIAG", "ENDING_DIAG")
COR = ("ZIGZAG", "FLAT", "TRIANGLE")


def expected(pat, j):
    """+1 motive, -1 corrective, 0 = either (diagonal legs)."""
    if pat == "IMPULSE": return 1 if j % 2 == 0 else -1
    if pat in ("LEADING_DIAG", "ENDING_DIAG"): return 0 if j % 2 == 0 else -1
    if pat == "ZIGZAG": return 1 if j != 1 else -1
    if pat == "FLAT": return 1 if j == 2 else -1
    return -1


def leg_evidence(b, i0, i1, up, cache):
    key = (i0, i1)
    if key in cache: return cache[key]
    sub = b.iloc[i0:i1 + 1]
    best = {1: -9.0, -1: -9.0}
    if len(sub) >= 12:
        from .gen import adaptive_ks
        for k in adaptive_ks(sub, "", lo=6, hi=17, n=2):
            pv = PV.zigzag(sub, k)
            T, P, K, tent = C._points(pv)
            if len(P) < 4: continue
            s = 0
            if K[0] != (-1 if up else 1): continue
            d = 1 if up else -1
            BX = np.r_[pv.i, [pv.tent[3]] if tent else []].astype(float)
            for seg, irr in C.segmentations(P, K, s, len(P) - 1, 5, max_irregular=1):
                y = d * P[list(seg)]; x = BX[list(seg)]; sb = np.diff(seg); n = len(seg) - 1
                for pat in MOT + COR:
                    if n == PT.LEGS[pat]:
                        ok, f = PT.check(pat, y, x, sb, False)
                        if ok:
                            t = 1 if pat in MOT else -1
                            best[t] = max(best[t], PT.score(pat, f) - C.IRR_PEN * irr)
    ev = float(np.clip(best[1] - best[-1], -2.0, 2.0)) if max(best.values()) > -9 else 0.0
    cache[key] = ev
    return ev


def rescore(scen, b, w=0.6, top=15):
    """adds bottom-up evidence to the best `top` scenarios (bars `b` = the scenario's own timeframe bars)."""
    cache = {}
    for z in scen[:top]:
        tot, m = 0.0, 0
        for pat, idx in z.parts:
            n = len(idx) - 1
            for j in range(n):
                last = (pat, idx) == z.parts[-1] and j == n - 1
                if last and z.tentative: continue                      # the running leg has no complete structure yet
                e = expected(pat, j)
                if e == 0: continue
                i0, i1 = int(z.bx[idx[j]]), int(z.bx[idx[j + 1]])
                up = z.pts_p[idx[j + 1]] > z.pts_p[idx[j]]
                tot += e * leg_evidence(b, i0, i1, up, cache); m += 1
        z.feats["bottom_up"] = tot / m if m else 0.0
        z.score += w * z.feats["bottom_up"] * min(m, 6) / 3
    scen[:top] = sorted(scen[:top], key=lambda z: -z.score)
    return scen
