"""Faithful Python port of the app's current engines (trader_core/lib/src/analysis)
and its composite score. Used as the BASELINE in the study.

Evaluated bar by bar with only the pivots confirmed by that bar (causal).
Returns per-bar engine signals (bias, strength, invalidation, target).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

from . import indicators as ind


@dataclass
class Sig:
    engine: str
    bias: int          # +1 / -1
    strength: float
    pattern: str
    inval: float | None = None
    target: float | None = None


def _clamp(x, lo=0.0, hi=1.0):
    return max(lo, min(hi, x))


class _Pre:
    """Pre-computed causal series for one symbol."""

    def __init__(self, df: pd.DataFrame):
        c = df["close"]
        self.df = df
        self.close = c.to_numpy()
        self.high = df["high"].to_numpy()
        self.low = df["low"].to_numpy()
        self.e20 = ind.ema(c, 20).to_numpy()
        self.e50 = ind.ema(c, 50).to_numpy()
        self.e200 = ind.ema(c, 200).to_numpy()
        self.atr = ind.atr(df).to_numpy()
        self.adx = ind.adx(df).to_numpy()
        self.rsi = ind.rsi(c).to_numpy()
        self.hist = ind.macd_hist(c).to_numpy()
        k = ind.stoch_k(df)
        self.k = k.to_numpy()
        self.d = k.rolling(3).mean().to_numpy()
        self.piv = ind.pivots(df)


def _trend(p: _Pre, t: int):
    if t < 59 or not np.isfinite(p.e50[t]) or not np.isfinite(p.atr[t]) or p.atr[t] <= 0:
        return []
    c = p.close[t]
    long_ok = not np.isfinite(p.e200[t]) or c > p.e200[t]
    short_ok = not np.isfinite(p.e200[t]) or c < p.e200[t]
    b = 0
    if c > p.e20[t] > p.e50[t] and long_ok:
        b = 1
    if c < p.e20[t] < p.e50[t] and short_ok:
        b = -1
    if b == 0:
        return []
    slope = 0.0 if not np.isfinite(p.e20[t - 5]) else (p.e20[t] - p.e20[t - 5]) / (p.atr[t] * 5) * b
    a = p.adx[t] if np.isfinite(p.adx[t]) else 0
    return [Sig("trend", b, 0.4 + 0.3 * min(a / 40, 1) + 0.3 * _clamp(slope), "EMA", p.e50[t])]


def _momentum(p: _Pre, t: int):
    if t < 39:
        return []
    r, h, hp, k, d = p.rsi[t], p.hist[t], p.hist[t - 1], p.k[t], p.d[t]
    if not all(np.isfinite(x) for x in (r, h, hp, k, d)):
        return []
    v = 0
    v += 1 if r > 55 else -1 if r < 45 else 0
    v += 1 if (h > 0 and h >= hp) else -1 if (h < 0 and h <= hp) else 0
    v += 1 if (k > d and k < 80) else -1 if (k < d and k > 20) else 0
    if abs(v) < 2:
        return []
    b = 1 if v > 0 else -1
    s = abs(v) / 3
    if (b > 0 and r > 75) or (b < 0 and r < 25):
        s *= 0.6
    return [Sig("momentum", b, s, "MOM")]


def _divergence(p: _Pre, t: int, piv, recency=8):
    if t < 49:
        return []
    out = []
    for is_high in (False, True):
        same = [q for q in piv if q[3] == is_high]
        if len(same) < 2:
            continue
        p1, p2 = same[-2], same[-1]
        gap = p2[0] - p1[0]
        if gap < 5 or gap > 60 or p2[1] < t - recency:
            continue
        r1, r2 = p.rsi[p1[0]], p.rsi[p2[0]]
        h1, h2 = p.hist[p1[0]], p.hist[p2[0]]
        if not (np.isfinite(r1) and np.isfinite(r2)):
            continue
        kind = None
        if not is_high:
            if p2[2] < p1[2] and r2 > r1:
                kind = "REGULAR_BULL"
            if p2[2] > p1[2] and r2 < r1:
                kind = "HIDDEN_BULL"
            b = 1
        else:
            if p2[2] > p1[2] and r2 < r1:
                kind = "REGULAR_BEAR"
            if p2[2] < p1[2] and r2 > r1:
                kind = "HIDDEN_BEAR"
            b = -1
        if kind is None:
            continue
        agree = np.isfinite(h1) and np.isfinite(h2) and ((r2 > r1) == (h2 > h1))
        s = 0.5 + (0.25 if agree else 0) + 0.25 * min(abs(r2 - r1) / 10, 1)
        if kind == "REGULAR_BULL" and r2 < 40:
            s += 0.1
        if kind == "REGULAR_BEAR" and r2 > 60:
            s += 0.1
        between = [q[2] for q in piv if q[3] != is_high and p1[0] < q[0] < p2[0]]
        tgt = (min(between) if is_high else max(between)) if between else None
        c = p.close[t]
        if (b > 0 and c < p2[2]) or (b < 0 and c > p2[2]):
            continue
        out.append(Sig("divergence", b, min(s, 1.0), kind, p2[2], tgt))
    return out


def _within(v, lo, hi, tol):
    return lo - tol <= v <= hi + tol


_HDEFS = [("GARTLEY", .618, .618, 1.272, 1.618, .786, .786, True),
          ("BAT", .382, .5, 1.618, 2.618, .886, .886, True),
          ("BUTTERFLY", .786, .786, 1.618, 2.618, 1.272, 1.618, False),
          ("CRAB", .382, .618, 2.24, 3.618, 1.618, 1.618, False)]


def harmonic_at(close_t: float, zz, t: int, tol=0.04, recency=6):
    if len(zz) < 5:
        return []
    pts = zz[-5:]
    if pts[4][1] < t - recency:
        return []
    sign = -1.0 if pts[0][3] else 1.0
    x, a, b, c, d = [q[2] * sign for q in pts]
    xa, ab, bc, cd = a - x, a - b, c - b, c - d
    if min(xa, ab, bc, cd) <= 0:
        return []
    abxa, bcab, cdbc, adxa = ab / xa, bc / ab, cd / bc, (a - d) / xa
    cl = close_t * sign
    out = []

    def emit(name, fit, details=None):
        inval = d - xa * 0.08
        ad = a - d
        t1, t2 = d + ad * 0.382, d + ad * 0.618
        if cl <= inval or cl >= t1:
            return
        out.append(Sig("harmonic", 1 if sign > 0 else -1, 0.45 + 0.55 * fit, name, inval * sign, t1 * sign))

    if x < b < a and b < c < a and d < b:
        for name, bmin, bmax, cdmin, cdmax, admin, admax, inside in _HDEFS:
            if inside and not d > x:
                continue
            if not inside and not d < x:
                continue
            if not (_within(abxa, bmin, bmax, tol) and _within(bcab, .382, .886, tol)
                    and _within(cdbc, cdmin, cdmax, tol * 2) and _within(adxa, admin, admax, tol)):
                continue
            lo = max(a - (admax + tol) * xa, c - (cdmax + tol * 2) * bc)
            hi = min(a - (admin - tol) * xa, c - (cdmin - tol * 2) * bc)
            if lo > hi or d < lo or d > hi:
                continue
            ideal = (admin + admax) / 2
            emit(name, 1 - min(1.0, abs(adxa - ideal) / (tol * 3)))
    xc = c - x
    if c > a and x < d < b and xc > 0:
        if _within(abxa, .382, .618, tol) and _within(xc / xa, 1.272, 1.414, tol) and _within(cd / xc, .786, .786, tol):
            emit("CYPHER", 1 - min(1.0, abs(cd / xc - .786) / (tol * 2)))
    return out


def _fit(v, ideal, w):
    return 1 - min(1.0, abs(v - ideal) / w)


def elliott_at(close_t: float, zz, t: int, recency=20):
    if len(zz) < 3:
        return []
    out = []
    n = len(zz)
    for sign in (1.0, -1.0):
        b = 1 if sign > 0 else -1
        cl = close_t * sign
        s = [q[2] * sign for q in zz]
        is_low = (lambda k: not zz[k][3]) if sign > 0 else (lambda k: zz[k][3])
        recent = zz[-1][1] >= t - recency
        if not recent:
            continue
        if n >= 3 and is_low(n - 3):
            p0, p1, p2 = s[-3], s[-2], s[-1]
            w1 = p1 - p0
            if w1 > 0:
                retr = (p1 - p2) / w1
                if p2 > p0 and 0.36 <= retr <= 0.80 and cl > p2 and cl < p2 + 1.618 * w1:
                    broke = cl > p1
                    out.append(Sig("elliott", b, 0.45 + (0.25 if broke else 0) + 0.3 * _fit(retr, 0.59, 0.25),
                                   "WAVE3", p0 * sign, (p1 + 0.618 * w1) * sign))
        if n >= 5 and is_low(n - 5):
            p = s[-5:]
            w1, w3 = p[1] - p[0], p[3] - p[2]
            if w1 > 0 and w3 > 0:
                r2, r4 = (p[1] - p[2]) / w1, (p[3] - p[4]) / w3
                if p[2] > p[0] and p[3] > p[1] and p[4] > p[1] and w3 >= w1 and 0.2 <= r4 <= 0.62 and p[4] < cl < p[4] + w1:
                    st = 0.4 + 0.2 * _fit(r4, .382, .2) + 0.2 * _fit(w3 / w1, 1.618, .8) + 0.2 * _fit(r2, .59, .3)
                    out.append(Sig("elliott", b, st, "WAVE5", p[1] * sign, (p[4] + 0.618 * w1) * sign))

        def impulse(fr):
            if fr < 0 or fr + 5 >= n or not is_low(fr):
                return False
            p = s[fr:fr + 6]
            w1, w3, w5 = p[1] - p[0], p[3] - p[2], p[5] - p[4]
            if min(w1, w3, w5) <= 0:
                return False
            if not (p[2] > p[0] and p[3] > p[1] and p[4] > p[1] and p[5] > p[3]):
                return False
            return not (w3 < w1 and w3 < w5)

        if impulse(n - 6):
            p = s[-6:]
            tot = p[5] - p[0]
            t1 = p[5] - 0.382 * tot
            if t1 < cl < p[5]:
                out.append(Sig("elliott", -b, 0.5, "IMPULSE_DONE", p[5] * sign, t1 * sign))
        if impulse(n - 8):
            top, a_, b_ = s[-3], s[-2], s[-1]
            la = top - a_
            if la > 0:
                rb = (b_ - a_) / la
                if 0.38 <= rb <= 0.89 and b_ < top and b_ - la < cl < b_:
                    out.append(Sig("elliott", -b, 0.45 + 0.3 * _fit(rb, .618, .3), "WAVE_C", top * sign,
                                   (b_ - 0.618 * la) * sign))
    return out


def classical_at(p: _Pre, t: int, zz, tol=0.015, recency=6):
    out = []
    c, h, l, cl = p.close, p.high, p.low, p.close[t]
    n = len(zz)

    def brk(frm, level, above):
        for i in range(frm + 1, t + 1):
            if (c[i] > level) if above else (c[i] < level):
                return i
        return -1

    def fresh(i):
        return i >= 0 and i >= t - recency

    if n >= 3:
        p1, mid, p2 = zz[-3], zz[-2], zz[-1]
        sim = abs(p1[2] - p2[2]) / p1[2] <= tol
        depth = abs(p1[2] - mid[2]) / p1[2]
        if sim and depth >= 0.02 and p2[0] - p1[0] >= 8:
            top = p1[3]
            neck = mid[2]
            at = brk(p2[1], neck, not top)
            height = abs((p1[2] + p2[2]) / 2 - neck)
            tgt = neck - height if top else neck + height
            if fresh(at) and ((cl > tgt) if top else (cl < tgt)):
                st = 0.55 + 0.25 * (1 - abs(p1[2] - p2[2]) / p1[2] / tol) + min(0.2, depth)
                out.append(Sig("classical", -1 if top else 1, min(st, 1), "DOUBLE",
                               max(p1[2], p2[2]) if top else min(p1[2], p2[2]),
                               neck - 0.618 * height if top else neck + 0.618 * height))
    if n >= 5:
        ls, t1, hd, t2, rs = zz[-5:]
        top = ls[3]
        sg = 1 if top else -1
        if hd[2] * sg > ls[2] * sg and hd[2] * sg > rs[2] * sg and abs(ls[2] - rs[2]) / ls[2] <= tol * 2:
            slope = (t2[2] - t1[2]) / (t2[0] - t1[0])

            def neck(i):
                return t1[2] + slope * (i - t1[0])
            at = -1
            for i in range(rs[1] + 1, t + 1):
                if (c[i] < neck(i)) if top else (c[i] > neck(i)):
                    at = i
                    break
            height = abs(hd[2] - neck(hd[0]))
            nn = neck(t)
            tgt = nn - height if top else nn + height
            if fresh(at) and ((cl > tgt) if top else (cl < tgt)):
                out.append(Sig("classical", -1 if top else 1,
                               min(1, 0.7 + 0.3 * (1 - abs(ls[2] - rs[2]) / ls[2] / (tol * 2))), "HS", rs[2],
                               nn - 0.618 * height if top else nn + 0.618 * height))
    if n >= 4:
        w = zz[-4:]
        hi = [q for q in w if q[3]]
        lo = [q for q in w if not q[3]]
        if len(hi) == 2 and len(lo) == 2:
            hs = (hi[1][2] - hi[0][2]) / (hi[1][0] - hi[0][0])
            lsl = (lo[1][2] - lo[0][2]) / (lo[1][0] - lo[0][0])
            ref = (hi[0][2] + lo[0][2]) / 2
            flat = ref * 0.0005
            kind = None
            if abs(hs) <= flat and lsl > flat:
                kind = "ASC"
            if abs(lsl) <= flat and hs < -flat:
                kind = "DESC"
            if hs < -flat and lsl > flat:
                kind = "SYM"
            if kind:
                def up_at(i):
                    return hi[1][2] + hs * (i - hi[1][0])

                def lo_at(i):
                    return lo[1][2] + lsl * (i - lo[1][0])
                at, up = -1, False
                for i in range(w[-1][1] + 1, t + 1):
                    if c[i] > up_at(i):
                        at, up = i, True
                        break
                    if c[i] < lo_at(i):
                        at = i
                        break
                height = hi[0][2] - lo[0][2]
                if fresh(at) and height > 0:
                    base = up_at(at) if up else lo_at(at)
                    tgt = base + height if up else base - height
                    if (cl < tgt) if up else (cl > tgt):
                        natural = (kind == "ASC" and up) or (kind == "DESC" and not up) or kind == "SYM"
                        out.append(Sig("classical", 1 if up else -1, 0.7 if natural else 0.5, "TRI",
                                       lo_at(t) if up else up_at(t), base + (0.618 if up else -0.618) * height))
    if t >= 21:
        hh, ll = h[t - 20:t].max(), l[t - 20:t].min()
        rng = hh - ll
        if rng > 0 and rng / cl < 0.12:
            if cl > hh:
                out.append(Sig("classical", 1, 0.45, "RANGE_UP", (hh + ll) / 2, hh + 0.618 * rng))
            elif cl < ll:
                out.append(Sig("classical", -1, 0.45, "RANGE_DN", (hh + ll) / 2, ll - 0.618 * rng))
    return out


DEFAULT_WEIGHTS = {"trend": 1.5, "momentum": 1.0, "divergence": 1.0, "harmonic": 0.8, "elliott": 0.8, "classical": 1.0}


class _ZZ:
    """Incremental zig-zag over confirmed pivots (equals batch zigzag on the prefix)."""

    def __init__(self, min_move):
        self.mm = min_move
        self.out = []

    def add(self, p):
        if not self.out:
            self.out.append(p)
            return
        last = self.out[-1]
        if last[3] == p[3]:
            if (p[2] > last[2]) if p[3] else (p[2] < last[2]):
                self.out[-1] = p
            return
        if self.mm > 0 and abs(p[2] - last[2]) / last[2] < self.mm:
            return
        self.out.append(p)


def engine_signals(df: pd.DataFrame) -> list[dict[str, Sig]]:
    """Per bar: strongest non-conflicting signal of every engine (analyzer rule)."""
    p = _Pre(df)
    n = len(df)
    zz_h, zz_e, zz_c = _ZZ(0.004), _ZZ(0.006), _ZZ(0.005)
    piv_known = []
    j = 0
    res = []
    for t in range(n):
        while j < len(p.piv) and p.piv[j][1] <= t:
            q = p.piv[j]
            piv_known.append(q)
            zz_h.add(q)
            zz_e.add(q)
            zz_c.add(q)
            j += 1
        found = {
            "trend": _trend(p, t),
            "momentum": _momentum(p, t),
            "divergence": _divergence(p, t, piv_known[-80:]),
            "harmonic": harmonic_at(p.close[t], zz_h.out, t) if t >= 39 else [],
            "elliott": elliott_at(p.close[t], zz_e.out, t) if t >= 59 else [],
            "classical": classical_at(p, t, zz_c.out) if t >= 39 else [],
        }
        best = {}
        for k, sigs in found.items():
            if not sigs:
                continue
            top = max(sigs, key=lambda s: s.strength)
            if any(s.bias == -top.bias and s.strength >= top.strength - 0.1 for s in sigs):
                continue
            best[k] = top
        res.append(best)
    return res


def composite(df: pd.DataFrame, per_bar=None, weights=None, min_score=35.0, min_agree=2,
              trend_align=True) -> pd.DataFrame:
    """The app's current entry rule -> signal frame (dir/stop/target/reason/score)."""
    weights = weights or DEFAULT_WEIGHTS
    per_bar = per_bar if per_bar is not None else engine_signals(df)
    den = sum(w for w in weights.values() if w > 0)
    rows = []
    close = df["close"].to_numpy()
    for t, best in enumerate(per_bar):
        num = sum(weights.get(k, 0) * s.strength * s.bias for k, s in best.items())
        score = 100 * num / den if den else 0
        d = 0
        if abs(score) >= min_score:
            b = 1 if score > 0 else -1
            agree = [s for s in best.values() if s.bias == b]
            tr = best.get("trend")
            if len(agree) >= min_agree and not (trend_align and tr is not None and tr.bias != b):
                d = b
        stop = tgt = np.nan
        if d:
            invs = [s.inval for s in best.values() if s.bias == d and s.inval is not None
                    and ((s.inval < close[t]) if d > 0 else (s.inval > close[t]))]
            tgts = [s.target for s in best.values() if s.bias == d and s.target is not None
                    and ((s.target > close[t]) if d > 0 else (s.target < close[t]))]
            if invs:
                stop = max(invs) if d > 0 else min(invs)
            if tgts:
                tgt = min(tgts) if d > 0 else max(tgts)
        rows.append((d, stop, tgt, "+".join(f"{k}:{s.pattern}" for k, s in best.items() if s.bias == d), score))
    return pd.DataFrame(rows, index=df.index, columns=["dir", "stop", "target", "reason", "score"])


def single_engine(df: pd.DataFrame, per_bar, engine: str, min_strength: float = 0.0) -> pd.DataFrame:
    """Raw signal of one engine (no composite) for the signal-quality study."""
    rows = []
    for best in per_bar:
        s = best.get(engine)
        if s is None or s.strength < min_strength:
            rows.append((0, np.nan, np.nan, ""))
        else:
            rows.append((s.bias, s.inval if s.inval is not None else np.nan,
                         s.target if s.target is not None else np.nan, f"{engine}:{s.pattern}"))
    return pd.DataFrame(rows, index=df.index, columns=["dir", "stop", "target", "reason"])
