"""Independent causal research facade. This package has no broker or order interface."""
from __future__ import annotations

from datetime import datetime, timedelta
from hashlib import sha256
import json
from typing import Iterable, Mapping

from ..engines import Bar, aware
from .divergence import divergences
from .harmonics import harmonic_candidates
from .indicators import checked_bars, fibonacci, indicator_series, summarize
from .pivots import classic_patterns, confirmed_pivots, market_structure
from .waves import WaveScenarioTracker, nested_third_candidates, rank_scenarios, wave_candidates


def analyze_shadow(bars: Iterable[Bar], *, as_of: datetime,
                   max_age: timedelta = timedelta(minutes=15),
                   expected_interval: timedelta | None = None,
                   tracker: WaveScenarioTracker | None = None) -> dict:
    """JSON-serializable observation at as_of, using only already-completed input bars.

    The caller sets freshness/session interval appropriate to its timeframe. Missing
    sessions are not inferred. The tracker must be scoped to account/symbol/timeframe
    by its owning service. All outputs remain non-executable Shadow evidence.
    """
    data = checked_bars(bars, as_of=as_of, max_age=max_age, expected_interval=expected_interval)
    technical = summarize(data)
    series = indicator_series(data)
    main_pivots = confirmed_pivots(data, left=3, right=3)
    internal_pivots = confirmed_pivots(data, left=1, right=1)
    main_waves = wave_candidates(main_pivots)
    internal_waves = wave_candidates(internal_pivots, degree="internal")
    scenarios = main_waves + internal_waves + nested_third_candidates(main_waves, internal_waves)
    source_history = {b.timestamp.isoformat(): sha256(json.dumps(
        [b.open, b.high, b.low, b.close, b.volume, b.completed], separators=(",", ":"), allow_nan=False
    ).encode()).hexdigest() for b in data}
    events = tracker.observe(scenarios, as_of=as_of, close=data[-1].close,
                             source_history=source_history) if tracker else ()
    # A breached count cannot become primary again merely because price recovered.
    # Evaluate only observations on/after the count's first knowable confirmation.
    invalidated = {s.scenario_id for s in scenarios
                   if any((b.close <= s.invalidation if s.direction == "BULLISH" else b.close >= s.invalidation)
                          for b in data if b.timestamp >= s.observed_at)}
    if tracker:
        invalidated.update(tracker.invalidated_ids)
    ranking = rank_scenarios(scenarios, as_of, data[-1].close, invalidated)
    fib = None
    if len(main_pivots) >= 2 and main_pivots[-1].price != main_pivots[-2].price:
        fib = fibonacci(main_pivots[-2].price, main_pivots[-1].price)
    divergence = divergences(main_pivots, series["rsi14"], name="RSI")
    divergence += divergences(main_pivots, series["macd"]["line"], name="MACD")
    return {"schema_version": 1, "mode": "SHADOW", "executable": False,
            "as_of": as_of.isoformat(), "last_bar_at": data[-1].timestamp.isoformat(),
            "source": "CALLER_SUPPLIED_COMPLETED_BARS", "bar_count": len(data),
            "technical": technical, "series": series,
            "timestamps": [b.timestamp.isoformat() for b in data],
            "pivots": [p.to_dict() for p in main_pivots],
            "internal_pivots": [p.to_dict() for p in internal_pivots],
            "market_structure": market_structure(main_pivots, data[-1].close),
            "fibonacci": fib, "waves": {**ranking, "candidates": [s.to_dict() for s in scenarios],
                                        "invalidated_ids": sorted(invalidated)},
            "wave_events": [e.to_dict() for e in events],
            "harmonics": harmonic_candidates(main_pivots),
            "divergences": divergence,
            "classical_patterns": classic_patterns(main_pivots, close=data[-1].close, as_of=as_of),
            "limitations": ["Quantitative pattern candidates are not verified forecasts or trade instructions.",
                            "Elliott implementation covers standard impulses and zigzags; diagonals and complex corrections are not inferred.",
                            "Pivot labels become available only at confirmed_at; never draw them as known at timestamp.",
                            "VWAP resets at UTC dates; exchange-session VWAP requires a supplied session convention.",
                            "No market-feed entitlement, live broker validation, or profitability claim is implied."]}


def analyze_timeframes(frames: Mapping[str, Iterable[Bar]], *, as_of: datetime,
                       max_age_by_frame: Mapping[str, timedelta]) -> dict:
    aware(as_of)
    if not frames or set(frames) != set(max_age_by_frame) or any(not name for name in frames):
        raise ValueError("Every named timeframe requires an explicit freshness policy")
    analyses = {name: analyze_shadow(bars, as_of=as_of, max_age=max_age_by_frame[name])
                for name, bars in sorted(frames.items())}
    regimes = {name: result["technical"]["regime"] for name, result in analyses.items()}
    wave_directions = {name: result["waves"]["primary"]["direction"] if result["waves"]["primary"] else None
                       for name, result in analyses.items()}
    directions = {d for d in wave_directions.values() if d is not None}
    divergence_directions = {name: sorted({"BULLISH" if "BULLISH" in d["kind"] else "BEARISH"
                                         for d in result["divergences"]}) for name, result in analyses.items()}
    return {"mode": "SHADOW", "executable": False, "as_of": as_of.isoformat(), "frames": analyses,
            "regimes": regimes, "wave_directions": wave_directions,
            "wave_alignment": "CONFLICT" if len(directions) > 1 else "ALIGNED" if len(directions) == 1 else "INSUFFICIENT",
            "divergence_directions": divergence_directions,
            "trend_conflict": "UPTREND" in regimes.values() and "DOWNTREND" in regimes.values()}


__all__ = ["analyze_shadow", "analyze_timeframes", "WaveScenarioTracker"]
