"""Stage 2 — Elliott pattern library: hard rules (reject) + guideline features (score).

A pattern instance is described by its boundary points y0..yn (direction-normalised so the FIRST leg goes UP:
y = d * price, d = +1 for an up-start, -1 for a down-start), their bar positions x0..xn, the number of
lower-level swings inside every leg (`sub`), and whether the last point is still tentative (`open_end`).
n may be smaller than the full leg count -> the pattern is IN PROGRESS.

Patterns (legs):  IMPULSE 5, LEADING_DIAG 5, ENDING_DIAG 5, ZIGZAG 3, FLAT 3, TRIANGLE 5 (contracting / barrier /
expanding), DOUBLE_THREE 7 (W-X-Y, W/Y = zigzag or flat), DOUBLE_THREE_T 9 (Y = triangle), TRIPLE_THREE 11 (W-X-Y-X-Z).
Motive patterns: IMPULSE, LEADING_DIAG, ENDING_DIAG.  Everything else is corrective.
Rules on an OPEN last leg: only violations that can only get worse as the leg extends are enforced.
"""
from __future__ import annotations
import math
import numpy as np

MOTIVE = ("IMPULSE", "LEADING_DIAG", "ENDING_DIAG")
LEGS = {"IMPULSE": 5, "LEADING_DIAG": 5, "ENDING_DIAG": 5, "ZIGZAG": 3, "FLAT": 3, "TRIANGLE": 5,
        "DOUBLE_THREE": 7, "DOUBLE_THREE_T": 9, "TRIPLE_THREE": 11}


def labels(pat):
    if pat in MOTIVE: return ["1", "2", "3", "4", "5"]
    if pat == "TRIANGLE": return ["A", "B", "C", "D", "E"]
    if pat in ("ZIGZAG", "FLAT"): return ["A", "B", "C"]
    if pat == "DOUBLE_THREE": return ["w.a", "w.b", "w.c", "X", "y.a", "y.b", "y.c"]
    if pat == "DOUBLE_THREE_T": return ["w.a", "w.b", "w.c", "X", "y.a", "y.b", "y.c", "y.d", "y.e"]
    if pat == "TRIPLE_THREE": return ["w.a", "w.b", "w.c", "X", "y.a", "y.b", "y.c", "X", "z.a", "z.b", "z.c"]
    raise KeyError(pat)


def fib_close(r, levels, tol=0.08):
    """1.0 exactly at a Fibonacci level, falling linearly to 0 at a log-distance of `tol` (~8 %)."""
    if not np.isfinite(r) or r <= 0: return 0.0
    best = min(abs(math.log(r / f)) for f in levels)
    return max(0.0, 1.0 - best / tol)


def check(pat: str, y, x, sub, open_end: bool):
    """returns (ok, features) for pattern `pat` with points y (n+1), x (n+1), sub (n), open_end."""
    y = np.asarray(y, float); x = np.asarray(x, float); n = len(y) - 1
    if n < 1 or n > LEGS[pat]: return False, {}
    if y[1] <= y[0]: return False, {}
    L = np.abs(np.diff(y)); D = np.diff(x)
    f = {"complete": float(n == LEGS[pat] and not open_end)}
    last_open = open_end

    def sub_ok(j, motive):        # lower-degree swings inside leg j: motive 1/5/9.., corrective 3/5/7/11
        s = sub[j]
        if s <= 1: return 0.0
        if motive: return 1.0 if s % 4 == 1 else -1.0
        return 1.0 if s in (3, 5, 7, 11) else -0.5

    if pat in MOTIVE:
        diag = pat != "IMPULSE"
        if n >= 2 and y[2] <= y[0]: return False, {}                                  # 2 beyond the start of 1
        if n >= 3 and not (last_open and n == 3) and y[3] <= y[1]: return False, {}   # 3 must pass the end of 1
        if n >= 4:
            if not diag and y[4] <= y[1]: return False, {}                              # 4 into 1 territory
            if diag and y[4] > y[1]: return False, {}                                    # diagonal: 4 overlaps 1
        if n >= 5 and L[2] < L[0] and L[4] > L[2]: return False, {}                       # 3 the shortest (open 5 can only grow)
        # an OPEN impulsive leg already far beyond any normal proportion is implausible (stops the
        # 'tiny 1-2, endless 3' counts): penalise each doubling beyond the largest usual ratio, in price and time
        if last_open and n in (3, 5):
            ref = 4.236 if n == 3 else 2.618
            r = L[n - 1] / L[0]; rt = max(D[n - 1], 1) / max(D[0], 1)
            f["open_prop"] = -max(0.0, math.log(r / ref) / math.log(2)) - max(0.0, math.log(rt / 6) / math.log(2))
        if last_open and n in (2, 4):          # time-based weakening of an open correction that drags on
            ref = D[0] if n == 2 else D[1]
            f["open_time"] = -max(0.0, math.log(max(D[n - 1], 1) / max(ref, 1) / 3) / math.log(2))
        if n >= 5 and not last_open:
            if y[5] <= y[3]: f["truncated5"] = 1.0
        if diag and n >= 4:
            contracting = L[2] < L[0] and L[3] < L[1]
            expanding = L[2] > L[0] and L[3] > L[1]
            if not (contracting or expanding): return False, {}
            if n >= 5 and contracting and L[4] >= L[2]: return False, {}             # open 5 already too long
            f["diag_contracting"] = float(contracting)
        if n >= 2: f["w2_fib"] = fib_close(L[1] / L[0], (0.382, 0.5, 0.618, 0.786))
        if n >= 3 and not (last_open and n == 3): f["w3_ext"] = fib_close(L[2] / L[0], (1.618, 2.618, 1.0, 1.272))
        if n >= 4 and not (last_open and n == 4):
            f["w4_fib"] = fib_close(L[3] / L[2], (0.236, 0.382, 0.5))
            f["alternation"] = min(1.0, abs(L[1] / L[0] - L[3] / L[2]) * 2)
        if n >= 5 and not last_open:
            f["w5_eq1"] = max(fib_close(L[4] / L[0], (1.0, 0.618, 1.618)), fib_close(L[4] / (y[3] - y[0]), (0.618, 0.382)))
            e = sorted([L[0], L[2], L[4]]); f["has_extension"] = float(e[2] >= 1.5 * e[1])
        # proportion ("right look"): corrective legs must be a real fraction of the move, 2 and 4 of similar time
        if n >= 2 and not (last_open and n == 2):
            f["prop"] = -float(L[1] / L[0] < 0.2)
        if n >= 4 and not (last_open and n == 4):
            f["prop"] = f.get("prop", 0.0) - float(L[3] / L[2] < 0.12) - min(1.0, abs(math.log(max(D[3], 1) / max(D[1], 1))) / math.log(6))
        mot = [sub_ok(j, not diag) for j in range(0, n - (1 if last_open else 0), 2)]
        cor = [sub_ok(j, False) for j in range(1, n - (1 if last_open else 0), 2)]
        if mot: f["sub_motive"] = float(np.mean(mot))
        if cor: f["sub_corr"] = float(np.mean(cor))
        return True, f

    if pat == "ZIGZAG":
        if n >= 2:
            r = L[1] / L[0]
            if r >= 0.9: return False, {}                                                # B too deep
            if not (last_open and n == 2): f["b_fib"] = fib_close(r, (0.382, 0.5, 0.618, 0.786))
        if n == 3 and last_open:
            f["open_prop"] = -max(0.0, math.log(L[2] / L[0] / 2.618) / math.log(2)) - max(0.0, math.log(max(D[2], 1) / max(D[0], 1) / 6) / math.log(2))
        if n >= 3 and not last_open:
            if y[3] <= y[1]: return False, {}                                           # C must pass A
            f["c_eq_a"] = fib_close(L[2] / L[0], (1.0, 0.618, 1.618))
        if n >= 2 or not last_open: f["sub_motive"] = sub_ok(0, True)
        return True, f

    if pat == "FLAT":
        if n >= 2:
            r = L[1] / L[0]
            if r > 1.618: return False, {}                                              # B up to ~138-162 % of A
            if r < 0.9 and not (last_open and n == 2): return False, {}                 # B must reach 90 % of A
            if not (last_open and n == 2): f["expanded"] = float(r > 1.05)
        if n >= 3 and not last_open:
            f["c_fib"] = fib_close(L[2] / L[0], (1.0, 1.272, 1.618, 0.618))
            f["running"] = float(L[1] / L[0] > 1.05 and y[3] < y[1])
        if n >= 2 or not last_open: f["sub_corr"] = sub_ok(0, False)
        return True, f

    if pat == "TRIANGLE":
        # contracting: each leg shorter than the previous (an OPEN leg already longer is final);
        # expanding: each leg longer but <= 1.8x the previous
        if n >= 2:
            closed = n - 1 if last_open else n
            sh = all(L[j + 1] < L[j] for j in range(n - 1))
            lg = all(1.0 < L[j + 1] / L[j] <= 1.8 for j in range(closed - 1)) and L[n - 1] / L[n - 2] <= 1.8
            if last_open:   # open leg may still grow: for 'contracting' it must already be shorter
                sh = all(L[j + 1] < L[j] for j in range(n - 1))
            if not (sh or lg): return False, {}
            f["tri_contracting"] = float(sh)
            if closed >= 2: f["tri_fib"] = float(np.mean([fib_close(L[j + 1] / L[j], (0.618, 0.786, 0.5)) for j in range(closed - 1)]))
        cs = [sub_ok(j, False) for j in range(n - (1 if last_open else 0))]
        if cs: f["sub_corr"] = float(np.mean(cs))
        f["is_triangle"] = 1.0
        return True, f

    if pat in ("DOUBLE_THREE", "DOUBLE_THREE_T", "TRIPLE_THREE"):
        w_open = last_open and n <= 3
        okW, _ = check("ZIGZAG", y[:min(n, 3) + 1], x[:min(n, 3) + 1], sub[:3], w_open)
        if not okW:
            okW, _ = check("FLAT", y[:min(n, 3) + 1], x[:min(n, 3) + 1], sub[:3], w_open)
        if not okW: return False, {}
        if n >= 4 and y[4] <= y[0]: return False, {}                                     # X beyond the start of W
        if n >= 5:
            ylen = 5 if pat == "DOUBLE_THREE_T" else 3
            m = min(n - 4, ylen)
            ypart = y[4:4 + m + 1]; xpart = x[4:4 + m + 1]; sp = sub[4:4 + m]
            y_open = last_open and n <= 4 + ylen
            if pat == "DOUBLE_THREE_T":
                okY, _ = check("TRIANGLE", ypart, xpart, sp, y_open)
            else:
                okY, _ = check("ZIGZAG", ypart, xpart, sp, y_open)
                if not okY: okY, _ = check("FLAT", ypart, xpart, sp, y_open)
            if not okY: return False, {}
        if pat == "TRIPLE_THREE":
            if n >= 8 and y[8] <= y[4]: return False, {}
            if n >= 9:
                okZ, _ = check("ZIGZAG", y[8:], x[8:], sub[8:], last_open)
                if not okZ: okZ, _ = check("FLAT", y[8:], x[8:], sub[8:], last_open)
                if not okZ: return False, {}
        f["combo"] = 1.0 if pat == "DOUBLE_THREE" else 1.5
        return True, f
    raise KeyError(pat)


# hand-set PRIOR weights (stage 6 replaces them with weights learned from forecast accuracy)
W = {"w2_fib": 0.6, "w3_ext": 1.0, "w4_fib": 0.6, "w5_eq1": 0.6, "has_extension": 0.5, "alternation": 0.3,
     "w4_channel": 0.3, "sub_motive": 0.8, "sub_corr": 0.4, "truncated5": -1.0, "b_fib": 0.6, "c_eq_a": 0.8,
     "c_fib": 0.6, "expanded": 0.0, "running": -0.4, "tri_fib": 0.4, "tri_contracting": 0.2, "is_triangle": 0.0,
     "combo": 0.0, "diag_contracting": 0.2, "complete": 0.1, "prop": 0.8, "open_prop": 1.0, "open_time": 0.6}
PAT_PRIOR = {"IMPULSE": 0.0, "ZIGZAG": 0.0, "FLAT": -0.2, "LEADING_DIAG": -0.8, "ENDING_DIAG": -0.6,
             "TRIANGLE": -0.7, "DOUBLE_THREE": -0.8, "DOUBLE_THREE_T": -1.2, "TRIPLE_THREE": -1.6}
FIBKEYS = {"w2_fib", "w3_ext", "w4_fib", "w5_eq1", "b_fib", "c_eq_a", "c_fib", "tri_fib", "w4_channel"}
FIB_BASE = 0.2          # mean closeness of a RANDOM ratio -> a leg that fits no better than chance adds nothing


def score(pat, f):
    """prior + evidence; Fibonacci features are centred on their chance level so that adding legs is not
    rewarded by itself (otherwise complex patterns always win)."""
    s = PAT_PRIOR[pat]
    for k, v in f.items():
        w = W.get(k, 0.0)
        s += w * (v - FIB_BASE) if k in FIBKEYS else w * v
    return s
