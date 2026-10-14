"""Causal, completed-bar indicators. Warm-up values are None, never backfilled."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from math import isfinite, log, sqrt
from statistics import fmean, pstdev
from typing import Iterable, Sequence

from ..engines import Bar, aware, validate_bars

INDICATOR_CONTRACT_VERSION = 'completed-bar-indicators-v1'


def checked_bars(bars: Iterable[Bar], *, as_of: datetime | None = None,
                 max_age: timedelta | None = None,
                 expected_interval: timedelta | None = None) -> tuple[Bar, ...]:
    result = tuple(bars)
    if any(not isinstance(b, Bar) for b in result):
        raise ValueError("Analysis accepts validated Bar objects only")
    if any(isinstance(value, bool) for b in result for value in (b.open, b.high, b.low, b.close, b.volume)):
        raise ValueError("Boolean OHLCV fields are not prices or volume")
    result = validate_bars(result)
    if not result:
        raise ValueError("At least one completed bar required")
    if as_of is not None:
        aware(as_of)
        if result[-1].timestamp > as_of:
            raise ValueError("Future bar cannot enter a historical analysis")
    if max_age is not None:
        if as_of is None or max_age.total_seconds() < 0:
            raise ValueError("Freshness requires as_of and nonnegative max_age")
        if as_of - result[-1].timestamp > max_age:
            raise ValueError("Market data is stale")
    if expected_interval is not None:
        if expected_interval.total_seconds() <= 0:
            raise ValueError("Expected interval must be positive")
        if any(b.timestamp - a.timestamp != expected_interval for a, b in zip(result, result[1:])):
            raise ValueError("Market data has gaps or an unexpected interval")
    return result


def _values(values: Sequence[float], period: int) -> None:
    if isinstance(period, bool) or not isinstance(period, int) or period < 1:
        raise ValueError("Period must be a positive integer")
    if any(isinstance(v, bool) or not isfinite(v) for v in values):
        raise ValueError("Values must be finite numbers")


def sma(values: Sequence[float], period: int) -> list[float | None]:
    _values(values, period)
    return [None if i + 1 < period else fmean(values[i + 1 - period:i + 1])
            for i in range(len(values))]


def ema(values: Sequence[float], period: int) -> list[float | None]:
    _values(values, period)
    result: list[float | None] = [None] * len(values)
    if len(values) < period:
        return result
    result[period - 1] = value = fmean(values[:period])
    alpha = 2 / (period + 1)
    for i in range(period, len(values)):
        value = values[i] * alpha + value * (1 - alpha)
        result[i] = value
    return result


def rsi(values: Sequence[float], period: int = 14) -> list[float | None]:
    _values(values, period)
    result: list[float | None] = [None] * len(values)
    if len(values) <= period:
        return result
    changes = [b - a for a, b in zip(values, values[1:])]
    gain = fmean(max(change, 0) for change in changes[:period])
    loss = fmean(max(-change, 0) for change in changes[:period])

    def value() -> float:
        return 50.0 if gain == loss == 0 else 100.0 if loss == 0 else 100 - 100 / (1 + gain / loss)

    result[period] = value()
    for i in range(period + 1, len(values)):
        gain = (gain * (period - 1) + max(changes[i - 1], 0)) / period
        loss = (loss * (period - 1) + max(-changes[i - 1], 0)) / period
        result[i] = value()
    return result


def macd(values: Sequence[float], fast: int = 12, slow: int = 26,
         signal: int = 9) -> dict[str, list[float | None]]:
    _values(values, signal)
    if fast >= slow:
        raise ValueError("MACD fast period must be less than slow period")
    fast_values, slow_values = ema(values, fast), ema(values, slow)
    line = [None if a is None or b is None else a - b for a, b in zip(fast_values, slow_values)]
    start = min(slow - 1, len(values))
    signal_values = [None] * start + ema([v for v in line[start:] if v is not None], signal)
    histogram = [None if a is None or b is None else a - b for a, b in zip(line, signal_values)]
    return {"line": line, "signal": signal_values, "histogram": histogram}


def atr(bars: Iterable[Bar], period: int = 14) -> list[float | None]:
    data = checked_bars(bars)
    ranges = [b.high - b.low if i == 0 else max(b.high - b.low, abs(b.high - data[i - 1].close),
              abs(b.low - data[i - 1].close)) for i, b in enumerate(data)]
    _values(ranges, period)
    result: list[float | None] = [None] * len(data)
    if len(data) >= period:
        result[period - 1] = value = fmean(ranges[:period])
        for i in range(period, len(data)):
            value = (value * (period - 1) + ranges[i]) / period
            result[i] = value
    return result


def bollinger(values: Sequence[float], period: int = 20, deviations: float = 2.0) -> dict:
    _values(values, period)
    if not isfinite(deviations) or deviations <= 0:
        raise ValueError("Band multiplier must be positive")
    middle = sma(values, period)
    spread = [None if i + 1 < period else deviations * pstdev(values[i + 1 - period:i + 1])
              for i in range(len(values))]
    return {"middle": middle,
            "upper": [None if m is None else m + s for m, s in zip(middle, spread)],
            "lower": [None if m is None else m - s for m, s in zip(middle, spread)]}


def vwap(bars: Iterable[Bar]) -> list[float | None]:
    """Resets at UTC calendar date; caller must supply a chosen session's bars for exchange VWAP."""
    data = checked_bars(bars)
    day, total, volume, result = None, 0.0, 0.0, []
    for b in data:
        current = b.timestamp.astimezone(timezone.utc).date()
        if current != day:
            day, total, volume = current, 0.0, 0.0
        total += (b.high + b.low + b.close) / 3 * b.volume
        volume += b.volume
        result.append(total / volume if volume else None)
    return result


def regression_channel(values: Sequence[float], period: int = 20) -> dict:
    _values(values, period)
    if period < 2 or len(values) < period:
        raise ValueError("Channel requires at least two observations and a full window")
    ys = values[-period:]
    center_x, center_y = (period - 1) / 2, fmean(ys)
    slope = sum((i - center_x) * (y - center_y) for i, y in enumerate(ys)) / sum((i - center_x) ** 2 for i in range(period))
    intercept = center_y - slope * center_x
    residual = [y - (intercept + slope * i) for i, y in enumerate(ys)]
    width = 2 * sqrt(fmean(r * r for r in residual))
    variance = sum((y - center_y) ** 2 for y in ys)
    return {"period": period, "slope_per_bar": slope, "start": intercept,
            "end": intercept + slope * (period - 1), "half_width": width,
            "r_squared": max(0.0, 1 - sum(r * r for r in residual) / variance) if variance else 0.0}


def fibonacci(start: float, end: float) -> dict:
    if not all(isfinite(v) and v > 0 for v in (start, end)) or start == end:
        raise ValueError("Distinct positive Fibonacci anchors required")
    move = end - start
    return {"start": start, "end": end,
            "retracements": {str(r): end - move * r for r in (.236, .382, .5, .618, .786)},
            "extensions": {str(r): start + move * r for r in (1.272, 1.618, 2.618)}}


def candle_patterns(bars: Iterable[Bar]) -> list[str]:
    data = checked_bars(bars)
    b = data[-1]
    body, span = abs(b.close - b.open), b.high - b.low
    upper, lower = b.high - max(b.open, b.close), min(b.open, b.close) - b.low
    result = []
    if span > 0 and body <= span * .1:
        result.append("DOJI")
    if body > 0 and lower >= body * 2 and upper <= body:
        result.append("HAMMER_SHAPE")
    if body > 0 and upper >= body * 2 and lower <= body:
        result.append("SHOOTING_STAR_SHAPE")
    if len(data) >= 2:
        a = data[-2]
        if a.close < a.open and b.close > b.open and b.open <= a.close and b.close >= a.open:
            result.append("BULLISH_ENGULFING")
        if a.close > a.open and b.close < b.open and b.open >= a.close and b.close <= a.open:
            result.append("BEARISH_ENGULFING")
    return result


def indicator_series(bars: Iterable[Bar]) -> dict:
    data = checked_bars(bars)
    closes = [b.close for b in data]
    return {"sma20": sma(closes, 20), "ema20": ema(closes, 20), "ema50": ema(closes, 50),
            "rsi14": rsi(closes), "macd": macd(closes), "atr14": atr(data),
            "vwap_utc_day": vwap(data), "bollinger20": bollinger(closes)}


def summarize(bars: Iterable[Bar]) -> dict:
    data = checked_bars(bars)
    if len(data) < 35:
        raise ValueError("At least 35 completed bars required")
    series = indicator_series(data)
    latest = {k: {sub: vals[-1] for sub, vals in v.items()} if isinstance(v, dict) else v[-1]
              for k, v in series.items()}
    channel = regression_channel([b.close for b in data])
    last, previous = data[-1], data[-21:-1]
    avg_volume = fmean(b.volume for b in previous)
    returns = [log(b.close / a.close) for a, b in zip(data[-21:-1], data[-20:])]
    atr_value = latest["atr14"]
    slope = channel["slope_per_bar"]
    regime = ("HIGH_VOLATILITY" if atr_value / last.close >= .06 else
              "UPTREND" if slope > atr_value * .05 and last.close > latest["sma20"] else
              "DOWNTREND" if slope < -atr_value * .05 and last.close < latest["sma20"] else "RANGE")
    technical_signals = []
    if avg_volume > 0 and last.volume >= avg_volume * 1.2:
        if regime == "UPTREND" and last.close > max(b.high for b in previous):
            technical_signals.append({"rule": "BREAKOUT", "direction": "BULLISH"})
        if regime == "DOWNTREND" and last.close < min(b.low for b in previous):
            technical_signals.append({"rule": "BREAKOUT", "direction": "BEARISH"})
    if atr_value > 0:
        if regime == "UPTREND" and abs(last.low - latest["sma20"]) <= atr_value * .5 and last.close > data[-2].close:
            technical_signals.append({"rule": "PULLBACK", "direction": "BULLISH"})
        if regime == "DOWNTREND" and abs(last.high - latest["sma20"]) <= atr_value * .5 and last.close < data[-2].close:
            technical_signals.append({"rule": "PULLBACK", "direction": "BEARISH"})
    return {"latest": latest, "channel": channel, "regime": regime,
            "realized_log_return_volatility_per_bar": pstdev(returns),
            "volume_ratio_to_prior20": last.volume / avg_volume if avg_volume else None,
            "candles": candle_patterns(data), "quantitative_shadow_signals": technical_signals}
