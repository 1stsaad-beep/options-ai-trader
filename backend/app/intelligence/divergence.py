"""Momentum divergence evidence aligned to confirmed price pivots; never orders."""
from __future__ import annotations

from math import isfinite
from typing import Iterable, Sequence

from .pivots import Pivot, validate_pivots

DIVERGENCE_CONTRACT_VERSION = 'confirmed-divergence-v1'


def divergences(pivots: Iterable[Pivot], oscillator: Sequence[float | None], *,
                name: str = "RSI", min_distance: int = 3, max_distance: int = 60,
                minimum_momentum_change: float = 1e-9) -> list[dict]:
    points = validate_pivots(pivots)
    if (name not in ("RSI", "MACD") or type(min_distance) is not int or type(max_distance) is not int
            or min_distance < 1 or max_distance < min_distance
            or isinstance(minimum_momentum_change, bool) or not isfinite(minimum_momentum_change) or minimum_momentum_change < 0
            or any(v is not None and (isinstance(v, bool) or not isfinite(v)) for v in oscillator)):
        raise ValueError("Invalid divergence configuration or oscillator")
    if any(p.confirmed_index >= len(oscillator) for p in points):
        raise ValueError("Oscillator must cover the confirmation bar")
    result = []
    for kind in ("LOW", "HIGH"):
        same = [p for p in points if p.kind == kind]
        for a, b in zip(same, same[1:]):
            old, new = oscillator[a.index], oscillator[b.index]
            if old is None or new is None or not min_distance <= b.index - a.index <= max_distance:
                continue
            price_change, momentum_change = b.price - a.price, new - old
            if abs(momentum_change) <= minimum_momentum_change or abs(price_change) <= max(a.price, b.price) * 1e-9:
                continue
            pattern = ("REGULAR_BULLISH" if kind == "LOW" and price_change < 0 < momentum_change else
                       "HIDDEN_BULLISH" if kind == "LOW" and momentum_change < 0 < price_change else
                       "REGULAR_BEARISH" if kind == "HIGH" and momentum_change < 0 < price_change else
                       "HIDDEN_BEARISH" if kind == "HIGH" and price_change < 0 < momentum_change else None)
            if pattern:
                result.append({"kind": pattern, "oscillator": name, "from": a.to_dict(), "to": b.to_dict(),
                               "momentum_from": old, "momentum_to": new,
                               "observed_at": b.confirmed_at.isoformat(), "mode": "SHADOW", "executable": False,
                               "requires_independent_strategy_confirmation": True})
    return result
