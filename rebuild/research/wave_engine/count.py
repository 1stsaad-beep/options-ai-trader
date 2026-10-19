"""Stage 3a — count ONE degree: all labelings of a pivot sequence from a start pivot to 'now'.

Boundaries are chosen by a monotone segmentation (each wave ends at the extreme of its own segment, and no later
price exceeds it before the next boundary) — the property every valid Elliott count has; it prunes the search
from combinatorial to small.  Each boundary sequence is then interpreted as
   (a) one pattern in progress, or
   (b) one complete pattern followed by a second pattern in progress,
and checked/scored by patterns.py."""
from __future__ import annotations
from dataclasses import dataclass, field
import math
import numpy as np
from . import patterns as PT
from .pivots import Pivots

MAX_LEGS = 11


@dataclass
class Scenario:
    score: float
    parts: list                    # [(pattern, idx_list)] idx into the point arrays
    d: int                         # +1 first leg up
    pts_t: np.ndarray
    pts_p: np.ndarray
    tentative: bool
    feats: dict = field(default_factory=dict)
    k: float = 0.0
    tf: str = ""
    bx: np.ndarray | None = None       # bar index (in the scenario's timeframe) of every point

    # ----------------------------------------------------------------- description of 'now'
    def current(self):
        pat, idx = self.parts[-1]
        n = len(idx) - 1
        lab = PT.labels(pat)
        complete = n == PT.LEGS[pat] and not self.tentative
        cur = lab[n - 1] if n >= 1 else lab[0]
        # direction of the current leg in price terms
        leg_up = (self.pts_p[idx[-1]] > self.pts_p[idx[-2]]) if n >= 1 else None
        return dict(pattern=pat, leg=cur, leg_index=n, legs_total=PT.LEGS[pat], complete=complete,
                    leg_start_t=self.pts_t[idx[-2]] if n >= 1 else self.pts_t[idx[0]],
                    leg_start_p=float(self.pts_p[idx[-2]]) if n >= 1 else float(self.pts_p[idx[0]]),
                    leg_up=bool(leg_up), motive_leg=(pat in PT.MOTIVE and n % 2 == 1) or
                    (pat in ("ZIGZAG",) and n in (1, 3)) or (pat == "FLAT" and n == 3))

    def invalidation(self):
        """price beyond which this count is wrong (Elliott hard rules)."""
        pat, idx = self.parts[-1]; p = self.pts_p; n = len(idx) - 1
        if pat in PT.MOTIVE:
            if n == 1: return float(p[idx[0]])                  # 1 in progress -> start of 1
            if n == 2: return float(p[idx[0]])                  # 2 must not pass start of 1
            if n == 3: return float(p[idx[2]])                  # 3 must not fall back below end of 2
            if n == 4: return float(p[idx[1]]) if pat == "IMPULSE" else float(p[idx[2]])   # 4 vs end of 1
            if n == 5: return float(p[idx[4]])
        if pat in ("ZIGZAG",):
            if n <= 2: return float(p[idx[0]])
            return float(p[idx[2]])
        if pat == "FLAT":
            return float(p[idx[0]] + 0.618 * (p[idx[0]] - p[idx[1]])) if n == 2 else float(p[idx[min(n, 2)]])
        return float(p[idx[0]])

    def labels(self):
        out = [(self.pts_t[self.parts[0][1][0]], float(self.pts_p[self.parts[0][1][0]]), "0", self.parts[0][0])]
        for pat, idx in self.parts:
            for j, lab in enumerate(PT.labels(pat)[:len(idx) - 1]):
                out.append((self.pts_t[idx[j + 1]], float(self.pts_p[idx[j + 1]]), lab, pat))
        return out


def _points(pv: Pivots):
    t, p, k = list(pv.t), list(pv.p), list(pv.kind)
    tent = False
    if pv.tent is not None and (len(k) == 0 or pv.tent[2] != k[-1]):
        t.append(pv.tent[0]); p.append(pv.tent[1]); k.append(pv.tent[2]); tent = True
    return np.array(t), np.array(p, float), np.array(k, int), tent


def segmentations(P, K, s, end, max_legs=MAX_LEGS):
    """monotone boundary sequences s=b0<b1<...<bm=end with alternating kinds."""
    out = []

    def rec(seq):
        a = seq[-1]
        if a == end:
            out.append(tuple(seq)); return
        if len(seq) - 1 >= max_legs: return
        ka = K[a]; best = None
        for j in range(a + 1, end + 1):
            if K[j] == ka:                          # same-kind point beyond a -> a no longer the extreme
                if (ka == 1 and P[j] > P[a]) or (ka == -1 and P[j] < P[a]): break
                continue
            if best is None or (ka == 1 and P[j] < best) or (ka == -1 and P[j] > best):
                best = P[j]
                # j is a running extreme after a -> candidate boundary (must also be extreme until next boundary;
                # checked in the next recursion by the 'break' above)
                rec(seq + [j])
    rec([s])
    return out


def count(pv: Pivots, start=None, direction=None, log=False, top=40, max_legs=MAX_LEGS, first_parts=None, anchor=None):
    """all scenarios from a start pivot to now.  start: index into the point list (default: global extremes)."""
    T, P, K, tent = _points(pv)
    BX0 = np.r_[pv.i, [pv.tent[3]] if tent else []].astype(float)
    if anchor is not None:      # force the parent's leg start as the first point (child must start where the parent leg starts)
        at, ap, ak, abx = anchor
        j0 = int(np.argmax(K == -ak)) if (K == -ak).any() else None   # first point of the opposite kind
        if j0 is None: return []
        T = np.r_[[np.datetime64(at)], T[j0:]]; P = np.r_[[ap], P[j0:]]; K = np.r_[[ak], K[j0:]]
        BX0 = np.r_[[float(abx)], BX0[j0:]]
        start = 0
    N = len(P)
    if N < 3: return []
    Y = np.log(P) if log else P
    X = np.arange(N, dtype=float)          # pivot ordinal; real bar positions below
    BX = BX0
    starts = [start] if start is not None else sorted({int(np.argmin(P)), int(np.argmax(P))})
    res = []
    for s in starts:
        if direction is not None and K[s] != -direction: continue
        d = -K[s]
        for seg in segmentations(P, K, s, N - 1, max_legs):
            m = len(seg) - 1
            y = d * Y[list(seg)]; x = BX[list(seg)]; sub = np.diff(seg)
            pats1 = first_parts or list(PT.LEGS)
            # (a) one pattern in progress
            for pat in pats1:
                if m <= PT.LEGS[pat]:
                    ok, f = PT.check(pat, y, x, sub, tent)
                    if ok:
                        res.append(Scenario(PT.score(pat, f), [(pat, list(seg))], d, T, P, tent, f, pv.k, pv.tf))
            # (b) complete pattern + next pattern in progress
            for pat in pats1:
                L = PT.LEGS[pat]
                if L < m:
                    ok, f = PT.check(pat, y[:L + 1], x[:L + 1], sub[:L], False)
                    if not ok: continue
                    seg2 = seg[L:]; y2 = -y[L:] if True else None
                    # second pattern's first leg is opposite to the last leg of the first pattern
                    y2 = (y[L:] * (1 if y[L + 1] > y[L] else -1))
                    nexts = [q for q in PT.LEGS if (pat not in PT.MOTIVE or q not in PT.MOTIVE)]
                    for q in nexts:
                        if len(seg2) - 1 <= PT.LEGS[q]:
                            ok2, f2 = PT.check(q, y2, x[L:], sub[L:], tent)
                            if ok2:
                                sc = PT.score(pat, f) + PT.score(q, f2) - 0.3
                                res.append(Scenario(sc, [(pat, list(seg[:L + 1])), (q, list(seg2))],
                                                    d, T, P, tent, {**f, **{"2_" + k: v for k, v in f2.items()}}, pv.k, pv.tf))
    for z in res: z.bx = BX
    res.sort(key=lambda z: -z.score)
    return res[:top] if top else res


def best_two(scen, min_gap=0.0):
    """best scenario + the best one that is genuinely different (different current leg/pattern, or the
    invalidation level on the other side / >1 ATR apart is handled by the caller)."""
    if not scen: return []
    a = scen[0]; ca = a.current()
    for b in scen[1:]:
        cb = b.current()
        if (cb["pattern"], cb["leg"], cb["leg_up"]) != (ca["pattern"], ca["leg"], ca["leg_up"]) or \
           abs(cb["leg_start_p"] - ca["leg_start_p"]) > 1e-9:
            return [a, b]
    return [a]
