"""Synthetic Elliott-wave price series with KNOWN labels (benchmark for the counter itself).

gen(pattern, ...) builds a fractal path: every leg of the top pattern is itself a pattern one degree lower
(motive legs -> impulse, corrective legs -> zigzag / flat / triangle), down to `depth` 0 where a leg is a noisy
straight walk.  Ratios are drawn from the usual Elliott ranges, with the awkward cases switched on on purpose:
expanded flats (B beyond the start of A = beyond the prior top), running flats, truncated fifths, triangles,
double threes.  Returns daily-like OHLC bars + the truth (top-degree boundary bar indices and labels)."""
from __future__ import annotations
import numpy as np
import pandas as pd


class G:
    def __init__(self, seed=0, noise=0.25):
        self.r = np.random.default_rng(seed); self.noise = noise

    # ---------------------------------------------------------------- leg size rules (fractions of first leg)
    def impulse(self, L, trunc=False):
        r = self.r
        w1 = L; w2 = r.uniform(0.382, 0.786) * w1
        w3 = w1 * r.choice([1.618, 2.0, 2.618, 1.272], p=[0.45, 0.2, 0.2, 0.15]) * r.uniform(0.95, 1.05)
        w4 = w3 * r.uniform(0.236, 0.5)
        if w4 >= (w1 - w2) + w3 - w1: w4 = 0.9 * ((w1 - w2) + w3 - w1)        # no overlap with 1
        w5 = (r.uniform(0.75, 0.95) * w4) if trunc else max(w1 * r.uniform(0.618, 1.1), w4 * r.uniform(1.15, 1.4))
        return [w1, -w2, w3, -w4, w5]

    def zigzag(self, L):
        a = L; b = self.r.uniform(0.382, 0.786) * a; c = a * self.r.choice([1.0, 0.618, 1.272, 1.618]) * self.r.uniform(0.95, 1.05)
        return [a, -b, c]

    def flat(self, L, kind="regular"):
        a = L
        b = a * {"regular": self.r.uniform(0.9, 1.0), "expanded": self.r.uniform(1.1, 1.38), "running": self.r.uniform(1.1, 1.3)}[kind]
        c = {"regular": self.r.uniform(1.0, 1.1) * a, "expanded": self.r.uniform(1.272, 1.618) * a, "running": self.r.uniform(0.8, 0.95) * b}[kind]
        return [a, -b, c]

    def triangle(self, L):
        legs = [L]; s = -1
        for _ in range(4):
            legs.append(s * abs(legs[-1]) * self.r.uniform(0.618, 0.85)); s = -s
        return legs

    # ---------------------------------------------------------------- fractal builder
    def build(self, pat, L, depth, kind=None):
        """returns list of (signed leg moves) at the finest level + the top-level leg grouping."""
        legs = {"IMPULSE": lambda: self.impulse(L, kind == "trunc"), "ZIGZAG": lambda: self.zigzag(L),
                "FLAT": lambda: self.flat(L, kind or "regular"), "TRIANGLE": lambda: self.triangle(L)}[pat]()
        if depth == 0:
            return [[x] for x in legs]
        out = []
        for j, mv in enumerate(legs):
            sgn = 1 if mv > 0 else -1
            if pat == "IMPULSE":
                child = "IMPULSE" if j % 2 == 0 else ("ZIGZAG" if j == 1 else self.r.choice(["FLAT", "TRIANGLE", "ZIGZAG"], p=[0.5, 0.2, 0.3]))
            elif pat == "ZIGZAG":
                child = "IMPULSE" if j != 1 else self.r.choice(["ZIGZAG", "FLAT"])
            elif pat == "FLAT":
                child = "IMPULSE" if j == 2 else "ZIGZAG"
            else:
                child = "ZIGZAG"
            if child == "TRIANGLE" and depth - 1 == 0: child = "ZIGZAG"
            sub = self.build(child, abs(mv), depth - 1)
            flat = [x for g in sub for x in g]
            # scale the child so its net move equals mv exactly
            net = sum(flat); flat = [x * (mv / net) for x in flat] if abs(net) > 1e-12 else flat
            out.append(flat)
        return out

    def path(self, groups, p0=100.0, bars_per_unit=40.0, log=False):
        """turn finest moves into OHLC bars; returns bars + top boundary bar indices."""
        prices, bounds, p = [p0], [0], p0
        for g in groups:
            for mv in g:
                n = max(2, int(abs(mv) / p0 * bars_per_unit * self.r.uniform(0.7, 1.3) * 10))
                tgt = p + mv
                steps = np.linspace(p, tgt, n + 1)[1:]
                vol = abs(mv) / n * self.noise
                steps = steps + self.r.normal(0, vol, n) * np.r_[np.ones(n - 1), 0]
                prices.extend(steps.tolist()); p = tgt
            bounds.append(len(prices) - 1)
        c = np.array(prices)
        o = np.r_[c[0], c[:-1]]
        rng = np.abs(np.diff(np.r_[c[0], c])) * 0.5 + c * 0.0005
        h = np.maximum(o, c) + rng * self.r.uniform(0, 0.6, len(c)); l = np.minimum(o, c) - rng * self.r.uniform(0, 0.6, len(c))
        # boundary bars carry the exact extreme
        idx = pd.bdate_range("2000-01-03", periods=len(c))
        df = pd.DataFrame({"open": o, "high": h, "low": l, "close": c, "volume": 1.0}, index=idx)
        df["t_end"] = df.index
        for k, bi in enumerate(bounds):
            if k == 0: continue
            up = groups[k - 1] and sum(groups[k - 1]) > 0
            if up: df.iloc[bi, df.columns.get_loc("high")] = max(df["high"].iloc[max(0, bi - 2):bi + 3].max(), c[bi]) + 1e-9
            else: df.iloc[bi, df.columns.get_loc("low")] = min(df["low"].iloc[max(0, bi - 2):bi + 3].min(), c[bi]) - 1e-9
        return df, bounds


CASES = {
    # name: (list of (pattern, kind) at top degree in sequence, how many legs of the LAST pattern are shown)
    "impulse_in_3": ([("IMPULSE", None)], 3),
    "impulse_in_5": ([("IMPULSE", None)], 5),
    "impulse_then_zigzag_B": ([("IMPULSE", None), ("ZIGZAG", None)], 2),
    "impulse_then_expanded_flat_B": ([("IMPULSE", None), ("FLAT", "expanded")], 2),   # B above the top of 5
    "impulse_then_expanded_flat_C": ([("IMPULSE", None), ("FLAT", "expanded")], 3),
    "truncated_5_then_zigzag": ([("IMPULSE", "trunc"), ("ZIGZAG", None)], 2),
    "impulse_then_running_flat_C": ([("IMPULSE", None), ("FLAT", "running")], 3),
    "impulse_then_triangle_D": ([("IMPULSE", None), ("TRIANGLE", None)], 4),
}
LBL = {"IMPULSE": ["1", "2", "3", "4", "5"], "ZIGZAG": ["A", "B", "C"], "FLAT": ["A", "B", "C"], "TRIANGLE": ["A", "B", "C", "D", "E"]}


def make(case, seed=0, depth=2, noise=0.25):
    seq, shown = CASES[case]
    g = G(seed, noise); groups, labels = [], []
    L = 30.0; d = 1
    for j, (pat, kind) in enumerate(seq):
        gg = g.build(pat, L, depth - 1, kind)
        if j > 0:                       # second pattern runs against the first (a correction of it)
            gg = [[-x for x in grp] for grp in gg]
        if j == len(seq) - 1: gg = gg[:shown]
        groups += gg; labels += [(pat, LBL[pat][i]) for i in range(len(gg))]
        L = abs(sum(sum(x) for x in gg)) * 0.6
    df, bounds = g.path(groups)
    return df, dict(bounds=bounds, labels=labels, case=case, seed=seed)
