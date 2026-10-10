"""Confirmed extrema retain both extremum time and first knowable time."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from math import isfinite
from typing import Iterable

from ..engines import Bar, aware
from .indicators import checked_bars


@dataclass(frozen=True)
class Pivot:
    index: int
    price: float
    kind: str
    timestamp: datetime
    confirmed_at: datetime
    confirmed_index: int

    def __post_init__(self):
        aware(self.timestamp)
        aware(self.confirmed_at)
        if (self.kind not in ("HIGH", "LOW") or isinstance(self.price, bool) or not isfinite(self.price) or self.price <= 0
                or type(self.index) is not int or type(self.confirmed_index) is not int
                or self.index < 0 or self.confirmed_index <= self.index
                or self.confirmed_at <= self.timestamp):
            raise ValueError("Invalid confirmed pivot")

    def to_dict(self) -> dict:
        return {**asdict(self), "timestamp": self.timestamp.isoformat(),
                "confirmed_at": self.confirmed_at.isoformat()}


def validate_pivots(pivots: Iterable[Pivot]) -> tuple[Pivot, ...]:
    result = tuple(pivots)
    if any(a.index >= b.index or a.timestamp >= b.timestamp or a.confirmed_at >= b.confirmed_at
           for a, b in zip(result, result[1:])):
        raise ValueError("Pivots must be strictly chronological and unique")
    return result


def confirmed_pivots(bars: Iterable[Bar], left: int = 2, right: int = 2) -> tuple[Pivot, ...]:
    data = checked_bars(bars)
    if any(isinstance(n, bool) or not isinstance(n, int) or n < 1 for n in (left, right)):
        raise ValueError("Pivot confirmation spans must be positive integers")
    result = []
    for i in range(left, len(data) - right):
        current = data[i]
        neighbours = data[i - left:i] + data[i + 1:i + right + 1]
        high = all(current.high > b.high for b in neighbours)
        low = all(current.low < b.low for b in neighbours)
        # Outside bars can contain both extremes; OHLC does not reveal their order.
        if high == low:
            continue
        result.append(Pivot(i, current.high if high else current.low, "HIGH" if high else "LOW",
                            current.timestamp, data[i + right].timestamp, i + right))
    return tuple(result)


def alternating(pivots: Iterable[Pivot]) -> bool:
    points = validate_pivots(pivots)
    return all(a.kind != b.kind for a, b in zip(points, points[1:]))


def market_structure(pivots: Iterable[Pivot], close: float) -> dict:
    points = validate_pivots(pivots)
    if isinstance(close, bool) or not isfinite(close) or close <= 0:
        raise ValueError("Valid observed price required")
    highs = [p for p in points if p.kind == "HIGH"]
    lows = [p for p in points if p.kind == "LOW"]
    state = "INSUFFICIENT_CONFIRMED_PIVOTS"
    if len(highs) >= 2 and len(lows) >= 2:
        state = ("HIGHER_HIGHS_HIGHER_LOWS" if highs[-1].price > highs[-2].price and lows[-1].price > lows[-2].price
                 else "LOWER_HIGHS_LOWER_LOWS" if highs[-1].price < highs[-2].price and lows[-1].price < lows[-2].price
                 else "MIXED")
    return {"structure": state, "support": max((p.price for p in lows if p.price <= close), default=None),
            "resistance": min((p.price for p in highs if p.price >= close), default=None)}


def classic_patterns(pivots: Iterable[Pivot], *, close: float, as_of: datetime) -> list[dict]:
    aware(as_of)
    points = validate_pivots(pivots)
    if any(p.confirmed_at > as_of for p in points) or isinstance(close, bool) or not isfinite(close) or close <= 0:
        raise ValueError("Invalid pattern observation")
    result = []
    for length in (3, 5):
        if len(points) < length:
            continue
        window = points[-length:]
        if not alternating(window):
            continue
        direction = -1 if window[0].kind == "HIGH" else 1
        prices = [p.price * -direction for p in window]
        if length == 3 and abs(prices[0] - prices[2]) / abs(prices[0]) <= .02:
            neckline = window[1].price
            result.append({"kind": "DOUBLE_TOP" if direction == -1 else "DOUBLE_BOTTOM",
                           "points": [p.to_dict() for p in window], "neckline": neckline,
                           "confirmed": (close - neckline) * direction > 0, "observed_at": as_of.isoformat()})
        if length == 5 and prices[2] > max(prices[0], prices[4]) and abs(prices[0] - prices[4]) / abs(prices[0]) <= .03:
            # Conservative neckline: price must cross both shoulder troughs/peaks.
            neckline = min(window[1].price, window[3].price) if direction == -1 else max(window[1].price, window[3].price)
            result.append({"kind": "HEAD_AND_SHOULDERS" if direction == -1 else "INVERSE_HEAD_AND_SHOULDERS",
                           "points": [p.to_dict() for p in window], "neckline": neckline,
                           "confirmed": (close - neckline) * direction > 0, "observed_at": as_of.isoformat()})
    if len(points) >= 6 and alternating(points[-6:]):
        highs = [p.price for p in points[-6:] if p.kind == "HIGH"]
        lows = [p.price for p in points[-6:] if p.kind == "LOW"]
        if len(highs) == len(lows) == 3 and highs[0] > highs[1] > highs[2] > lows[2] > lows[1] > lows[0]:
            result.append({"kind": "CONVERGING_TRIANGLE", "upper": highs[-1], "lower": lows[-1],
                           "confirmed": close > highs[-1] or close < lows[-1], "observed_at": as_of.isoformat()})
    return result
