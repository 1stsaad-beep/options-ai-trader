from dataclasses import replace
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from math import sin

import pytest

from app.engines import Bar
from app.intelligence import WaveScenarioTracker, analyze_shadow, analyze_timeframes
from app.intelligence.divergence import divergences
from app.intelligence.harmonics import harmonic_candidates
from app.intelligence.indicators import (
    atr, bollinger, candle_patterns, checked_bars, ema, fibonacci, indicator_series,
    macd, regression_channel, rsi, sma, summarize, vwap,
)
from app.intelligence.pivots import Pivot, classic_patterns, confirmed_pivots, market_structure
from app.intelligence.waves import nested_third_candidates, rank_scenarios, wave_candidates


START = datetime(2026, 1, 5, 14, 30, tzinfo=timezone.utc)


def bars(count=120, slope=.04, phase=0):
    values = [100 + slope * i + 5 * sin((i + phase) / 4) for i in range(count)]
    return tuple(Bar(START + timedelta(minutes=i), value - .1, value + .5,
                     value - .5, value, 1000 + i * 3) for i, value in enumerate(values))


def points(prices, first="LOW", spacing=10, offset=0):
    return tuple(Pivot(offset + i * spacing, price,
                       first if i % 2 == 0 else "HIGH" if first == "LOW" else "LOW",
                       START + timedelta(minutes=offset + i * spacing),
                       START + timedelta(minutes=offset + i * spacing + 2),
                       offset + i * spacing + 2) for i, price in enumerate(prices))


@pytest.mark.parametrize("period", [0, -1, True, 1.5])
def test_indicator_rejects_bad_period(period):
    with pytest.raises(ValueError):
        sma([1, 2, 3], period)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), True])
def test_indicator_rejects_nonfinite_and_bool(value):
    with pytest.raises(ValueError):
        ema([1, value], 2)


def test_known_sma_ema_and_rsi_values():
    assert sma([1, 2, 3, 4], 3) == [None, None, 2, 3]
    assert ema([1, 2, 3, 4], 3) == [None, None, 2, 3]
    assert rsi([10] * 20)[-1] == 50
    assert rsi(list(range(1, 21)))[-1] == 100
    assert rsi(list(range(20, 0, -1)))[-1] == 0


def test_macd_warmup_and_known_linear_series():
    result = macd(list(range(1, 61)))
    assert all(v is None for v in result["line"][:25])
    assert all(v is None for v in result["signal"][:33])
    assert result["line"][-1] == pytest.approx(7)
    assert result["signal"][-1] == pytest.approx(7)
    assert result["histogram"][-1] == pytest.approx(0)
    with pytest.raises(ValueError):
        macd([1, 2, 3], fast=26, slow=12)


def test_atr_bollinger_channel_fibonacci_exact_fixtures():
    data = tuple(Bar(START + timedelta(minutes=i), 100, 102, 98, 100, 1) for i in range(30))
    assert atr(data)[-1] == 4
    assert bollinger([100] * 30)["upper"][-1] == 100
    channel = regression_channel(list(range(1, 31)))
    assert channel["slope_per_bar"] == 1
    assert channel["half_width"] == 0
    assert channel["r_squared"] == 1
    assert fibonacci(100, 200)["retracements"]["0.618"] == pytest.approx(138.2)
    assert fibonacci(200, 100)["extensions"]["1.618"] == pytest.approx(38.2)


def test_vwap_zero_volume_and_utc_session_reset():
    data = [Bar(START, 100, 100, 100, 100, 0),
            Bar(START + timedelta(minutes=1), 110, 110, 110, 110, 2),
            Bar(START + timedelta(minutes=2), 120, 120, 120, 120, 2),
            Bar(START + timedelta(days=1), 150, 150, 150, 150, 1)]
    assert vwap(data) == [None, 110, 115, 150]


def test_engulfing_and_shape_are_descriptive_not_orders():
    data = [Bar(START, 102, 103, 99, 100, 1),
            Bar(START + timedelta(minutes=1), 99, 104, 98, 103, 1)]
    assert "BULLISH_ENGULFING" in candle_patterns(data)


@pytest.mark.parametrize("prefix", [35, 50, 75, 99])
def test_indicator_series_prefix_invariant_no_backfill(prefix):
    full, short = indicator_series(bars()), indicator_series(bars()[:prefix])
    for name, value in full.items():
        if isinstance(value, dict):
            for key in value:
                assert value[key][:prefix] == short[name][key]
        else:
            assert value[:prefix] == short[name]


def test_future_stale_incomplete_duplicate_and_gap_rejected():
    data = bars(40)
    with pytest.raises(ValueError, match="Future"):
        checked_bars(data, as_of=data[-2].timestamp)
    with pytest.raises(ValueError, match="stale"):
        analyze_shadow(data, as_of=data[-1].timestamp + timedelta(minutes=16))
    with pytest.raises(ValueError, match="Incomplete"):
        checked_bars(data[:-1] + (replace(data[-1], completed=False),))
    with pytest.raises(ValueError, match="chronological"):
        checked_bars(data + (data[-1],))
    with pytest.raises(ValueError, match="gaps"):
        checked_bars(data[:20] + data[21:], expected_interval=timedelta(minutes=1))
    with pytest.raises(ValueError, match="validated Bar"):
        checked_bars([{"close": 100}])
    with pytest.raises(ValueError, match="Boolean"):
        checked_bars([Bar(START, 1, 1, 1, True, 0)])


@pytest.mark.parametrize("prefix", [10, 20, 35, 58, 92])
def test_confirmed_pivots_never_repaint_and_respect_confirmation_time(prefix):
    data = bars()
    full = confirmed_pivots(data, left=2, right=3)
    expected = tuple(p for p in full if p.confirmed_index < prefix)
    observed = confirmed_pivots(data[:prefix], left=2, right=3)
    assert observed == expected
    assert all(p.confirmed_at == data[p.index + 3].timestamp for p in observed)
    assert all(p.timestamp < p.confirmed_at <= data[prefix - 1].timestamp for p in observed)


def test_outside_bar_and_equal_extrema_are_not_fabricated_ordered_pivots():
    data = [Bar(START, 100, 101, 99, 100, 1),
            Bar(START + timedelta(minutes=1), 100, 105, 95, 100, 1),
            Bar(START + timedelta(minutes=2), 100, 101, 99, 100, 1)]
    assert confirmed_pivots(data, 1, 1) == ()
    equal = [replace(b, high=105, low=95) for b in data]
    assert confirmed_pivots(equal, 1, 1) == ()


def test_standard_impulse_and_fifth_scenario_rules():
    p = points([100, 120, 110, 150, 130, 160])
    candidates = wave_candidates(p)
    complete = [s for s in candidates if s.kind == "IMPULSE_1_5_COMPLETED"]
    assert len(complete) == 1
    assert complete[0].labels == ("0", "1", "2", "3", "4", "5")
    assert complete[0].observed_at == p[-1].confirmed_at
    assert any(s.kind == "WAVE_5_PENDING" for s in candidates)
    assert any(s.kind == "ABC_ZIGZAG_CANDIDATE" for s in candidates)
    assert all(not s.to_dict()["executable"] for s in candidates)


@pytest.mark.parametrize("prices", [
    [100, 120, 99, 150, 130, 160],   # W2 erases W1.
    [100, 120, 110, 150, 119, 160],  # W4 overlaps W1.
    [100, 130, 120, 140, 135, 165],  # W3 is shortest.
    [100, 120, 110, 150, 130, 149],  # Strict standard model excludes truncated W5.
])
def test_invalid_impulse_geometry_rejected(prices):
    assert not any(s.kind == "IMPULSE_1_5_COMPLETED" for s in wave_candidates(points(prices)))


def test_bearish_impulse_symmetry_and_confirmed_wave_prefix_invariance():
    p = points([300, 280, 290, 250, 270, 240], first="HIGH")
    full = wave_candidates(p)
    assert any(s.kind == "IMPULSE_1_5_COMPLETED" and s.direction == "BEARISH" for s in full)
    for count in range(1, len(p) + 1):
        short = wave_candidates(p[:count])
        assert short == tuple(s for s in full if s.observed_at <= p[count - 1].confirmed_at)


def test_third_of_third_waits_for_parent_confirmation():
    outer = [s for s in wave_candidates(points([100, 120, 110, 160], spacing=20)) if s.kind == "WAVE_3_CANDIDATE"]
    inner = [s for s in wave_candidates(points([110, 125, 118, 145], spacing=5, offset=40), "internal") if s.kind == "WAVE_3_CANDIDATE"]
    nested = nested_third_candidates(outer, inner)
    assert len(nested) == 1
    assert nested[0].parent_id == outer[0].scenario_id
    assert nested[0].observed_at == outer[0].observed_at


def test_wave_journal_append_only_idempotent_and_invalidation_survives_recovery():
    scenario = wave_candidates(points([100, 120, 110, 150]))[0]
    tracker = WaveScenarioTracker()
    now = scenario.observed_at
    first = tracker.observe([scenario], as_of=now, close=150)
    snapshot = first[0].snapshot_json
    assert tracker.observe([scenario], as_of=now, close=150) == ()
    second = tracker.observe([scenario], as_of=now + timedelta(minutes=1), close=90)
    assert second[0].event == "INVALIDATED"
    assert tracker.observe([scenario], as_of=now + timedelta(minutes=2), close=160) == ()
    assert tracker.events[0].snapshot_json == snapshot
    assert [e.sequence for e in tracker.events] == [1, 2]
    with pytest.raises(ValueError, match="rewritten"):
        tracker.observe([scenario], as_of=now, close=100)
    with pytest.raises(ValueError, match="same-time"):
        tracker.observe([scenario], as_of=now + timedelta(minutes=2), close=170)
    with pytest.raises(ValueError, match="silently rewritten"):
        tracker.observe([replace(scenario, invalidation=10)], as_of=now + timedelta(minutes=3), close=170)


def test_future_scenario_not_ranked_or_recorded():
    s = wave_candidates(points([100, 120, 110, 150]))[0]
    before = s.observed_at - timedelta(seconds=1)
    with pytest.raises(ValueError, match="Future"):
        rank_scenarios([s], before, 150)
    with pytest.raises(ValueError, match="future"):
        WaveScenarioTracker().observe([s], as_of=before, close=150)


def test_invalidated_scenario_not_resurrected_when_price_recovers():
    s = wave_candidates(points([100, 120, 110, 150]))[0]
    result = rank_scenarios([s], s.observed_at, 150, invalidated_ids=[s.scenario_id])
    assert result["primary"] is None
    assert result["active_count"] == 0


def test_target_rank_and_journal_never_treat_future_bar_as_confirmation():
    full = bars(100)
    truncated = full[:75]
    at_time = truncated[-1].timestamp
    expected = analyze_shadow(truncated, as_of=at_time)
    changed_future = truncated + tuple(replace(b, open=b.open + 100, high=b.high + 100,
                                              low=b.low + 100, close=b.close + 100) for b in full[75:])
    with pytest.raises(ValueError, match="Future"):
        analyze_shadow(changed_future, as_of=at_time)
    assert analyze_shadow(changed_future[:75], as_of=at_time) == expected


HARMONICS = {
    "GARTLEY": [100, 200, 138.2, 176.3924, 121.4],
    "BAT": [100, 200, 150, 175, 111.4],
    "BUTTERFLY": [100, 200, 121.4, 160.7, 72.8],
    "CRAB": [100, 200, 150, 194.3, 38.2],
    "CYPHER": [100, 200, 150, 230, 127.82],
}


@pytest.mark.parametrize("name", list(HARMONICS))
@pytest.mark.parametrize("bearish", [False, True])
def test_all_harmonic_definitions_geometry_prz_and_mirror(name, bearish):
    prices = [400 - p for p in HARMONICS[name]] if bearish else HARMONICS[name]
    p = points(prices, first="HIGH" if bearish else "LOW")
    results = [r for r in harmonic_candidates(p) if r["kind"] == name]
    assert len(results) == 1
    result = results[0]
    assert result["direction"] == ("BEARISH" if bearish else "BULLISH")
    assert result["prz"]["low"] <= prices[-1] <= result["prz"]["high"]
    assert result["observed_at"] == p[-1].confirmed_at.isoformat()
    assert not result["executable"]
    assert harmonic_candidates(p[:-1]) == []


@pytest.mark.parametrize("prices", [
    [100, 200, 138.2, 176.3924, 180],  # CD moves wrong way.
    [100, 200, 250, 270, 150],        # B is outside XA.
    [100, 200, 101, 102, 99],         # Fibonacci ratios fail.
])
def test_harmonics_reject_invalid_geometry_and_ratios(prices):
    assert harmonic_candidates(points(prices)) == []


@pytest.mark.parametrize("kind,prices,values,expected", [
    ("LOW", [100, 95], [30, 40], "REGULAR_BULLISH"),
    ("LOW", [100, 105], [40, 30], "HIDDEN_BULLISH"),
    ("HIGH", [100, 105], [70, 60], "REGULAR_BEARISH"),
    ("HIGH", [100, 95], [60, 70], "HIDDEN_BEARISH"),
])
@pytest.mark.parametrize("name", ["RSI", "MACD"])
def test_four_divergence_types_on_two_momentum_series(kind, prices, values, expected, name):
    p = (points([prices[0]], first=kind)[0], points([prices[1]], first=kind, offset=10)[0])
    oscillator = [None] * 13
    oscillator[0], oscillator[10] = values
    result = divergences(p, oscillator, name=name)
    assert result[0]["kind"] == expected
    assert result[0]["observed_at"] == p[-1].confirmed_at.isoformat()
    assert result[0]["requires_independent_strategy_confirmation"]
    assert not result[0]["executable"]


def test_divergence_requires_confirmation_adequate_distance_and_warmup():
    p = (points([100])[0], points([95], offset=10)[0])
    oscillator = [None] * 13
    oscillator[0], oscillator[10] = 30, 40
    with pytest.raises(ValueError, match="confirmation"):
        divergences(p, oscillator[:11])
    assert divergences(p, oscillator, min_distance=11) == []
    assert divergences(p, oscillator, max_distance=9) == []
    oscillator[0] = None
    assert divergences(p, oscillator) == []


def test_market_structure_and_classical_double_top_neckline_confirmation():
    p = points([120, 100, 121], first="HIGH")
    result = classic_patterns(p, close=99, as_of=p[-1].confirmed_at)
    assert result[0]["kind"] == "DOUBLE_TOP"
    assert result[0]["confirmed"]
    assert not classic_patterns(p, close=110, as_of=p[-1].confirmed_at)[0]["confirmed"]
    trend = market_structure(points([100, 120, 110, 130]), close=125)
    assert trend["structure"] == "HIGHER_HIGHS_HIGHER_LOWS"
    assert trend["support"] == 110
    assert trend["resistance"] == 130


def test_facade_json_serializable_and_explicitly_shadow():
    data = bars()
    result = analyze_shadow(data, as_of=data[-1].timestamp, expected_interval=timedelta(minutes=1))
    json.dumps(result, allow_nan=False)
    assert result["mode"] == "SHADOW" and result["executable"] is False
    assert len(result["series"]["rsi14"]) == len(data)
    assert "quantitative_shadow_signals" in result["technical"]
    assert result["limitations"]


def test_multi_timeframe_requires_fresh_completed_bars_for_every_frame():
    data = bars(50)
    result = analyze_timeframes({"1m": data, "5m": data}, as_of=data[-1].timestamp,
                                max_age_by_frame={"1m": timedelta(minutes=1), "5m": timedelta(minutes=5)})
    assert set(result["frames"]) == {"1m", "5m"}
    assert not result["executable"]
    with pytest.raises(ValueError, match="freshness"):
        analyze_timeframes({"1m": data}, as_of=data[-1].timestamp, max_age_by_frame={})
    with pytest.raises(ValueError, match="stale"):
        analyze_timeframes({"1m": data}, as_of=data[-1].timestamp + timedelta(minutes=10),
                           max_age_by_frame={"1m": timedelta(minutes=1)})


def test_replay_stream_keeps_historical_wave_events_unchanged():
    data = bars(130, slope=.2)
    tracker = WaveScenarioTracker()
    historical = ()
    for end in range(35, len(data) + 1):
        analyze_shadow(data[:end], as_of=data[end - 1].timestamp, tracker=tracker)
        assert tracker.events[:len(historical)] == historical
        assert all(e.observed_at <= data[end - 1].timestamp for e in tracker.events)
        historical = tracker.events
    assert historical


def test_wave_checkpoint_restart_preserves_history_invalidations_and_idempotency():
    scenarios = wave_candidates(points([100, 120, 110, 150]))
    tracker = WaveScenarioTracker()
    now = max(s.observed_at for s in scenarios)
    tracker.observe(scenarios, as_of=now, close=150)
    first_state = tracker.to_state()
    tracker.observe(scenarios, as_of=now + timedelta(minutes=1), close=90)
    state = json.loads(json.dumps(tracker.to_state(), allow_nan=False))
    restored = WaveScenarioTracker.from_state(state)
    assert restored.events == tracker.events
    assert restored.invalidated_ids == tracker.invalidated_ids
    assert restored.to_state() == state
    assert restored.observe(scenarios, as_of=now + timedelta(minutes=1), close=90) == ()
    assert restored.observe(scenarios, as_of=now + timedelta(minutes=2), close=160) == ()
    assert restored.events == tracker.events
    assert state["events"][:len(first_state["events"])] == first_state["events"]
    with pytest.raises(ValueError, match="same-time"):
        restored.observe(scenarios, as_of=now + timedelta(minutes=2), close=170)
    with pytest.raises(ValueError, match="rewritten"):
        restored.observe(scenarios, as_of=now, close=150)


@pytest.mark.parametrize("corruption", ["snapshot", "truncate", "reorder", "clock", "observation", "head"])
def test_wave_checkpoint_rejects_corruption(corruption):
    tracker = WaveScenarioTracker()
    scenarios = wave_candidates(points([100, 120, 110, 150]))
    now = max(s.observed_at for s in scenarios)
    tracker.observe(scenarios, as_of=now, close=150)
    tracker.observe(scenarios, as_of=now + timedelta(minutes=1), close=90)
    state = deepcopy(tracker.to_state())
    if corruption == "snapshot":
        state["events"][0]["snapshot_json"] = state["events"][0]["snapshot_json"].replace('"SHADOW"', '"LIVE"')
    elif corruption == "truncate":
        state["events"].pop()
    elif corruption == "reorder":
        state["events"].reverse()
    elif corruption == "clock":
        state["last_as_of"] = START.isoformat()
    elif corruption == "observation":
        state["last_observation"] = "[]"
    else:
        state["chain_head"] = "0" * 64
    with pytest.raises(ValueError, match="integrity"):
        WaveScenarioTracker.from_state(state)


def test_wave_checkpoint_validates_chain_beyond_outer_checksum():
    from app.intelligence.waves import _digest
    tracker = WaveScenarioTracker()
    scenarios = wave_candidates(points([100, 120, 110, 150]))
    tracker.observe(scenarios, as_of=max(s.observed_at for s in scenarios), close=150)
    state = tracker.to_state()
    state["events"][0]["price"] = 160
    state["state_hash"] = _digest({k: v for k, v in state.items() if k != "state_hash"})
    with pytest.raises(ValueError, match="chain"):
        WaveScenarioTracker.from_state(state)


def test_empty_wave_checkpoint_and_observation_without_candidates_restore():
    tracker = WaveScenarioTracker()
    assert WaveScenarioTracker.from_state(tracker.to_state()).events == ()
    tracker.observe([], as_of=START, close=100)
    restored = WaveScenarioTracker.from_state(tracker.to_state())
    assert restored.observe([], as_of=START, close=100) == ()
    with pytest.raises(ValueError, match="same-time"):
        restored.observe([], as_of=START, close=101)


def test_wave_facade_rejects_retroactive_bar_edits_even_if_price_and_count_match():
    data = bars(60)
    tracker = WaveScenarioTracker()
    analyze_shadow(data, as_of=data[-1].timestamp, tracker=tracker)
    restored = WaveScenarioTracker.from_state(tracker.to_state())
    changed = list(data)
    changed[10] = replace(changed[10], volume=changed[10].volume + 1)
    before = restored.to_state()
    with pytest.raises(ValueError, match="source bars cannot be rewritten"):
        analyze_shadow(changed, as_of=data[-1].timestamp, tracker=restored)
    assert restored.to_state() == before
    with pytest.raises(ValueError, match="source bars cannot be rewritten"):
        analyze_shadow(changed, as_of=data[-1].timestamp + timedelta(minutes=1), tracker=restored)


def test_wave_journal_rejects_silent_backfill_into_previously_observed_prefix():
    tracker = WaveScenarioTracker()
    tracker.observe([], as_of=START + timedelta(minutes=2), close=100,
                    source_history={START.isoformat(): "1" * 64,
                                    (START + timedelta(minutes=2)).isoformat(): "2" * 64})
    restored = WaveScenarioTracker.from_state(tracker.to_state())
    with pytest.raises(ValueError, match="cannot be inserted"):
        restored.observe([], as_of=START + timedelta(minutes=3), close=100,
                         source_history={(START + timedelta(minutes=1)).isoformat(): "3" * 64})


def test_facade_checkpoint_continues_the_same_cumulative_history_after_restart():
    data = bars(80)
    original = WaveScenarioTracker()
    analyze_shadow(data[:60], as_of=data[59].timestamp, tracker=original)
    resumed = WaveScenarioTracker.from_state(json.loads(json.dumps(original.to_state())))
    expected = analyze_shadow(data, as_of=data[-1].timestamp, tracker=original)
    actual = analyze_shadow(data, as_of=data[-1].timestamp, tracker=resumed)
    assert actual == expected
    assert resumed.to_state() == original.to_state()
