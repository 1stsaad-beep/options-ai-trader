"""Stage 3b — generations: parent scenario -> its CURRENT leg is re-counted on a finer timeframe (chosen
automatically so the leg has enough bars), with the child constrained by the parent (direction of the leg;
motive leg -> motive pattern in progress, corrective leg -> corrective pattern in progress).
Beam search keeps the best CHAINS (sum of scores), so every generation is consistent with its parents."""
from __future__ import annotations
from dataclasses import dataclass, field
import numpy as np
import pandas as pd
from . import bars as B, pivots as PV, count as C, patterns as PT

TF_NEXT = ["M", "W", "D", "60", "5"]
CORRECTIVE = [p for p in PT.LEGS if p not in PT.MOTIVE]


@dataclass
class Chain:
    score: float
    gens: list = field(default_factory=list)      # list of Scenario

    @property
    def last(self):
        return self.gens[-1]


def adaptive_ks(b, tf, lo=7, hi=41, n=4):
    """ATR multiples that give between lo and hi pivots on these bars (the pivot density adapts to the leg,
    so a 17-year leg on daily bars and a 2-day leg on 5-minute bars are both counted on ~10-40 swings)."""
    grid = [0.75 * 1.35 ** j for j in range(30)]
    good = []
    for k in grid:
        m = len(PV.zigzag(b, k, tf=tf))
        if m < lo: break
        if m <= hi: good.append(k)
    if len(good) > n:
        idx = np.linspace(0, len(good) - 1, n).round().astype(int); good = [good[i] for i in idx]
    return good


def counts_for(sym, tf, t0, asof, direction=None, patterns=None, ks=None, top=12, anchor_p=None):
    b = B.bars(sym, tf, t0, asof)
    if len(b) < 15: return []
    out, seen = [], set()
    for k in (ks or adaptive_ks(b, tf)):
        pv = PV.zigzag(b, k, tf=tf)
        T, P, K, tent = C._points(pv)
        # start = the extreme point at the beginning of the interval with the right kind
        if direction is None:
            s = None                                     # top generation: start at the global extremes
        else:
            cand = [j for j in range(min(3, len(K))) if K[j] == -direction]
            if not cand: continue
            s = cand[0]
        anc = None
        if anchor_p is not None and direction is not None:
            # bar where the parent's leg-start extreme actually printed on this finer timeframe
            col = b["low"].to_numpy() if direction == 1 else b["high"].to_numpy()
            hit = np.flatnonzero(np.abs(col - anchor_p) <= 1e-6 * max(1.0, abs(anchor_p)))
            abx = int(hit[0]) if len(hit) else int(np.argmin(col) if direction == 1 else np.argmax(col[:max(1, len(col) // 4)]))
            anc = (np.datetime64(b.index[abx]), anchor_p, -direction, abx)
        sc = C.count(pv, start=s, direction=direction, log=tf in ("M", "W"), top=top, first_parts=patterns, anchor=anc)
        for z in sc:
            key = (tuple(z.pts_t[i] for _, idx in z.parts for i in idx), tuple(p for p, _ in z.parts))
            if key in seen: continue
            seen.add(key); out.append(z)
    out.sort(key=lambda z: -z.score)
    return out[:top]


def pick_tf(sym, t0, asof, parent_tf, min_bars=60):
    """coarsest timeframe, not coarser than the parent's, whose data covers the leg start and gives it
    >= min_bars bars.  Degree drives the generations; the timeframe follows the size of the leg."""
    for cand in TF_NEXT[TF_NEXT.index(parent_tf):]:
        try:
            first, _ = B.available(sym, cand)
        except FileNotFoundError:
            continue
        if first is None or first > t0: continue
        if len(B.bars(sym, cand, t0, asof)) >= min_bars:
            return cand
    return None


def run(sym, asof=None, beam=6, top_tf="M", max_gen=9, stop_tf="5", min_bars=60):
    """generations continue until the current leg is counted on the finest timeframe (or max_gen)."""
    asof = pd.Timestamp(asof) if asof is not None else B.available(sym, "5")[1]
    chains = [Chain(z.score, [z]) for z in counts_for(sym, top_tf, None, asof, top=beam * 2)][:beam]
    for g in range(1, max_gen):
        new, grew = [], False
        for ch in chains:
            if ch.last.tf == stop_tf and g > 1 and len(ch.gens) >= 2 and ch.last.tf == ch.gens[-2].tf == stop_tf:
                new.append(ch); continue
            cur = ch.last.current()
            t0 = pd.Timestamp(cur["leg_start_t"])
            tf = pick_tf(sym, t0, asof, ch.last.tf, min_bars)
            if tf is None:
                new.append(ch); continue
            direction = 1 if cur["leg_up"] else -1
            pats = list(PT.MOTIVE) if cur["motive_leg"] else CORRECTIVE
            kids = [z for z in counts_for(sym, tf, t0, asof, direction=direction, patterns=pats, top=beam, anchor_p=cur["leg_start_p"]) if len(z.parts) == 1]
            # a child that just repeats its parent (single leg, same start) adds no information
            kids = [z for z in kids if len(z.parts[0][1]) > 2]
            if not kids:
                new.append(ch); continue
            grew = True
            for z in kids[:3]:
                new.append(Chain(ch.score + z.score, ch.gens + [z]))
        new.sort(key=lambda c: (-len(c.gens), -c.score))
        chains = new[:beam]
        if not grew: break
    return chains


def best_two(chains):
    if not chains: return []
    a = chains[0]; ca = a.last.current()
    for b in chains[1:]:
        cb = b.last.current()
        if (cb["pattern"], cb["leg"], cb["leg_up"], round(cb["leg_start_p"], 6)) != (ca["pattern"], ca["leg"], ca["leg_up"], round(ca["leg_start_p"], 6)):
            return [a, b]
    return [a]


def describe(ch):
    rows = []
    for g, z in enumerate(ch.gens):
        c = z.current()
        rows.append(dict(gen=g + 1, tf=z.tf, k=z.k, pattern=" + ".join(p for p, _ in z.parts), now=f"{c['pattern']} wave {c['leg']}",
                         dir="up" if c["leg_up"] else "down", leg_start=str(pd.Timestamp(c["leg_start_t"])), leg_start_p=round(c["leg_start_p"], 2),
                         invalid=round(z.invalidation(), 2), score=round(z.score, 2),
                         labels=" ".join(f"{l}@{p:.2f}" for t, p, l, _ in z.labels())))
    return pd.DataFrame(rows)
