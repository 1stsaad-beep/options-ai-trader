"""Strict confirmed-pivot XABCD geometry. Research candidates only."""
from __future__ import annotations

from hashlib import sha256
from math import isfinite
from typing import Iterable

from .pivots import Pivot, alternating, validate_pivots


def _between(value: float, lower: float, upper: float, tolerance: float) -> bool:
    return lower - tolerance <= value <= upper + tolerance


def harmonic_candidates(pivots: Iterable[Pivot], ratio_tolerance: float = .03) -> list[dict]:
    points = validate_pivots(pivots)
    if not isfinite(ratio_tolerance) or not 0 <= ratio_tolerance <= .05:
        raise ValueError("Harmonic ratio tolerance must be 0..0.05")
    result = []
    for start in range(max(0, len(points) - 64), len(points) - 4):
        p = points[start:start + 5]
        if not alternating(p):
            continue
        sign = 1 if p[0].kind == "LOW" else -1
        x, a, b, c, d = [v.price * sign for v in p]
        xa, ab, bc, cd = a - x, a - b, c - b, c - d
        # All legs must alternate in price as well as in pivot labels.
        if min(xa, ab, bc, cd) <= 0 or not x < b < a or d >= b:
            continue
        ratios = {"AB_XA": ab / xa, "BC_AB": bc / ab, "CD_BC": cd / bc,
                  "AD_XA": (a - d) / xa, "XC_XA": (c - x) / xa,
                  "CD_XC": cd / (c - x) if c > x else 0}
        definitions = {
            "GARTLEY": ((.618, .618), (1.272, 1.618), (.786, .786), True),
            "BAT": ((.382, .5), (1.618, 2.618), (.886, .886), True),
            "BUTTERFLY": ((.786, .786), (1.618, 2.618), (1.272, 1.618), False),
            "CRAB": ((.382, .618), (2.24, 3.618), (1.618, 1.618), False),
        }
        for name, (b_range, cd_range, ad_range, internal_d) in definitions.items():
            if not (b < c < a and (d > x if internal_d else d < x)):
                continue
            if not all((_between(ratios["AB_XA"], *b_range, ratio_tolerance),
                        _between(ratios["BC_AB"], .382, .886, ratio_tolerance),
                        _between(ratios["CD_BC"], *cd_range, ratio_tolerance),
                        _between(ratios["AD_XA"], *ad_range, ratio_tolerance))):
                continue
            # PRZ is the intersection of independent XA and BC-derived D zones.
            xa_zone = (a - (ad_range[1] + ratio_tolerance) * xa, a - (ad_range[0] - ratio_tolerance) * xa)
            bc_zone = (c - (cd_range[1] + ratio_tolerance) * bc, c - (cd_range[0] - ratio_tolerance) * bc)
            zone = max(xa_zone[0], bc_zone[0]), min(xa_zone[1], bc_zone[1])
            if zone[0] <= d <= zone[1]:
                result.append(_pattern(name, p, ratios, zone, sign, xa, cd))
        if (c > a and x < d < b
                and _between(ratios["AB_XA"], .382, .618, ratio_tolerance)
                and _between(ratios["XC_XA"], 1.272, 1.414, ratio_tolerance)
                and _between(ratios["CD_XC"], .786, .786, ratio_tolerance)):
            xc = c - x
            zone = c - (.786 + ratio_tolerance) * xc, c - (.786 - ratio_tolerance) * xc
            result.append(_pattern("CYPHER", p, ratios, zone, sign, xa, cd))
    return result


def _pattern(name: str, points: tuple[Pivot, ...], ratios: dict, zone: tuple[float, float],
             sign: int, xa: float, cd: float) -> dict:
    actual_zone = sorted(z * sign for z in zone)
    d = points[-1].price
    identity = f"{name}:" + ":".join(p.timestamp.isoformat() + str(p.price) for p in points)
    return {"pattern_id": sha256(identity.encode()).hexdigest()[:24], "kind": name,
            "direction": "BULLISH" if sign == 1 else "BEARISH", "mode": "SHADOW", "executable": False,
            "points": {label: p.to_dict() for label, p in zip("XABCD", points)}, "ratios": ratios,
            "prz": {"low": actual_zone[0], "high": actual_zone[1]},
            "activation": d + sign * cd * .236, "invalidation": d - sign * xa * .05,
            "targets": [d + sign * cd * .382, d + sign * cd * .618],
            "observed_at": max(p.confirmed_at for p in points).isoformat()}
