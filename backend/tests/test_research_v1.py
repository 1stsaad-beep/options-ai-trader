"""Behavioral and adversarial tests for isolated V1 shadow research engines."""
from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone
import json
import math

import pytest

from app.engines import Bar
from app.research import (
    AdaptiveEntryEngine, AutonomousSafetySupervisor, ContractQualityPolicy,
    CounterfactualReplay, DecisionMemory, EntrySetup, EntryTimingOptimizer,
    LiquidityTrapDetector, MomentumCandidate, OptionContract, OptionTwin,
    PortfolioCorrelationGuard, ResearchPoint, SafetyState, ShadowScenarioBattle,
    StrategyTournament, SystemTrustScore, assess_contract, synthetic_research_demo,
)

NOW = datetime(2026, 1, 5, 15, tzinfo=timezone.utc)


def contract(**changes):
    base = OptionContract("synthetic-aapl-call", "AAPL", "CALL", 100,
                          NOW+timedelta(days=30), NOW, 100, 4.9, 5.1,
                          .5, .04, -.04, .12, .3, 500, 1000)
    return replace(base, **changes)


def bar(index, close=101, low=100, high=102, open_price=100.5, volume=1000):
    return Bar(NOW+timedelta(minutes=index), open_price, high, low, close, volume)


def setup(**changes):
    return replace(EntrySetup("CALL", 100, 95, NOW, NOW+timedelta(hours=4), "wave-1"), **changes)


def series(length=60, kind="rising", offset=0, scale=1):
    prices = []
    for i in range(length):
        change = i*.02 if kind == "rising" else 0 if kind == "flat" else math.sin(i*.8)*.2+i*.005
        price = (4+change)*scale
        prices.append(ResearchPoint(NOW+timedelta(minutes=i+offset), price-.01*scale, price+.01*scale))
    return tuple(prices)


def recorded(memory=None, account="a", key="one", at=NOW, evidence=None):
    memory = memory or DecisionMemory()
    return memory.record(account, key, at, at, "synthetic-aapl-call", ("quantitative breakout",),
                         evidence or {"activation": 100, "invalidated": False})


@pytest.mark.parametrize("changes", [
    {"bid": float("nan")}, {"ask": float("inf")}, {"spot": True}, {"strike": 0},
    {"delta": -0.5}, {"gamma": -1}, {"theta_per_day": float("nan")}, {"iv": 0},
    {"volume": True}, {"open_interest": -1}, {"multiplier": 0}, {"bid": 6},
    {"symbol": "aapl"}, {"right": "SELL"}, {"instrument_type": "STOCK"},
    {"source": "IBKR_VERIFIED"}, {"observed_at": NOW.replace(tzinfo=None)},
])
def test_contract_rejects_malformed_inputs(changes):
    with pytest.raises(ValueError):
        contract(**changes)


@pytest.mark.parametrize("changes,reason", [
    ({"observed_at": NOW+timedelta(seconds=1)}, "FUTURE_QUOTE"),
    ({"observed_at": NOW-timedelta(seconds=61)}, "STALE_QUOTE"),
    ({"expiry": NOW}, "EXPIRED"),
    ({"expiry": NOW+timedelta(hours=2)}, "NEAR_EXPIRY"),
    ({"multiplier": 10}, "NONSTANDARD_MULTIPLIER"),
    ({"currency": "EUR"}, "UNSUPPORTED_CURRENCY"),
    ({"source": "unverified"}, "UNVERIFIED_DATA"),
    ({"bid": 0}, "NO_EXECUTABLE_BID"),
    ({"volume": 1}, "LOW_VOLUME"),
    ({"open_interest": 1}, "LOW_OPEN_INTEREST"),
    ({"ask": 7}, "WIDE_SPREAD"),
    ({"commission_per_contract": 200}, "HIGH_ROUND_TRIP_COST"),
    ({"delta": .95}, "DELTA_OUTSIDE_POLICY"),
])
def test_contract_hard_quality_failures(changes, reason):
    result = assess_contract(contract(**changes), NOW)
    assert not result["accepted_for_research"]
    assert reason in result["reasons"]
    assert not result["broker_verified"]


def test_contract_quality_and_twin_preserve_provenance_and_costs():
    c = contract()
    result = OptionTwin().simulate(c, NOW, [{"spot": 100, "elapsed_days": 0, "iv": .3}])
    assert result["source"] == "synthetic_fixture"
    assert not result["execution_authority"]
    assert not result["profitability_evidence"]
    # Unchanged mid still loses the full bid/ask spread, two slippages and fees.
    assert result["scenarios"][0]["scenario_pnl"] == pytest.approx(-23.3)
    assert result["contract_quality"]["round_trip_cost"] == pytest.approx(23.3)


def test_twin_time_decay_and_vega_have_explicit_units():
    c = contract()
    cases = [{"spot": 100, "elapsed_days": 0, "iv": .3},
             {"spot": 100, "elapsed_days": 2, "iv": .3},
             {"spot": 100, "elapsed_days": 0, "iv": .31}]
    result = OptionTwin().simulate(c, NOW, cases)["scenarios"]
    assert result[1]["estimated_option_value"]-result[0]["estimated_option_value"] == pytest.approx(-.08)
    assert result[2]["estimated_option_value"]-result[0]["estimated_option_value"] == pytest.approx(.12)


def test_twin_put_direction_and_expiry_are_explicit_scenarios():
    c = contract(right="PUT", delta=-.5)
    result = OptionTwin().simulate(c, NOW, [{"spot": 95, "elapsed_days": 1, "iv": .3},
                                         {"spot": 105, "elapsed_days": 1, "iv": .3},
                                         {"spot": 90, "elapsed_days": 30, "iv": .3}])["scenarios"]
    assert result[0]["scenario_pnl"] > result[1]["scenario_pnl"]
    assert result[2]["expiry_intrinsic_scenario"]
    assert result[2]["estimated_option_value"] == 10
    assert result[2]["outside_local_approximation"]


def test_twin_rejects_stale_contract_and_scenario_extra_authority():
    with pytest.raises(ValueError, match="STALE_QUOTE"):
        OptionTwin().simulate(contract(), NOW+timedelta(minutes=2), [{"spot": 100, "elapsed_days": 0, "iv": .3}])
    with pytest.raises(ValueError, match="requires"):
        OptionTwin().simulate(contract(), NOW, [{"spot": 100, "elapsed_days": 0, "iv": .3, "execute": True}])


@pytest.mark.parametrize("scenario", [{"spot": 0, "elapsed_days": 1, "iv": .3},
                                      {"spot": 100, "elapsed_days": -1, "iv": .3},
                                      {"spot": 100, "elapsed_days": 1, "iv": float("nan")}])
def test_twin_malformed_shocks_rejected(scenario):
    with pytest.raises(ValueError):
        OptionTwin().simulate(contract(), NOW, [scenario])


def test_entry_profiles_adjust_signal_rule_not_risk_quantity():
    data = (bar(0),)
    engine = AdaptiveEntryEngine()
    assert engine.evaluate(setup(), data, NOW, profile="balanced")["entry_candidate"]
    assert not engine.evaluate(setup(), data, NOW, profile="conservative", strength=.8)["entry_candidate"]
    accepted = engine.evaluate(setup(), (bar(0), bar(1)), NOW+timedelta(minutes=1),
                               profile="conservative", strength=.8)
    assert accepted["entry_candidate"]
    assert not accepted["risk_sizing_included"]
    assert "quantity" not in accepted


def test_early_confirmed_and_pullback_are_distinct_causal_rules():
    first = bar(0, close=99.5, low=99, high=101, open_price=99.2)
    engine = AdaptiveEntryEngine()
    assert engine.evaluate(setup(), [first], NOW, method="early")["entry_candidate"]
    assert not engine.evaluate(setup(), [first], NOW, method="confirmed")["entry_candidate"]
    assert not engine.evaluate(setup(), [bar(0)], NOW, method="pullback")["entry_candidate"]
    pullback = bar(1, close=100.5, low=99.5, high=101, open_price=99.7)
    result = engine.evaluate(setup(), [bar(0), pullback], pullback.timestamp, method="pullback")
    assert result["entry_candidate"]


def test_entry_invalidated_same_bar_cannot_claim_beneficial_intrabar_order():
    ambiguous = bar(0, low=94, high=102)
    result = AdaptiveEntryEngine().evaluate(setup(), [ambiguous], NOW, method="early")
    assert not result["entry_candidate"]
    assert result["reason"] == "SCENARIO_INVALIDATED"


def test_entry_expiry_stale_future_incomplete_and_weak_signal_fail_closed():
    engine = AdaptiveEntryEngine()
    assert engine.evaluate(setup(), [bar(0)], NOW+timedelta(hours=4))["reason"] == "SETUP_EXPIRED"
    assert engine.evaluate(setup(), [bar(0)], NOW+timedelta(minutes=16))["reason"] == "STALE_OBSERVATION"
    assert not engine.evaluate(setup(), [bar(0)], NOW, strength=.2)["entry_candidate"]
    with pytest.raises(ValueError, match="Future"):
        engine.evaluate(setup(), [bar(1)], NOW)
    with pytest.raises(ValueError, match="Incomplete"):
        engine.evaluate(setup(), [replace(bar(0), completed=False)], NOW)


def test_put_entry_and_timing_comparison_never_use_later_returns():
    bearish = setup(right="PUT", invalidation=105)
    data = [bar(0, close=99, low=98, high=100, open_price=99.5)]
    output = EntryTimingOptimizer().compare(bearish, data, NOW)
    assert output["methods"][1]["entry_candidate"]
    assert not output["optimized_on_future_outcomes"]


def test_scenario_battle_retains_conflict_and_excludes_invalidated_high_score():
    candidates = [{"id": "bull", "direction": "bullish", "score": .8, "known_at": NOW, "invalidated": False},
                  {"id": "bear", "direction": "bearish", "score": .75, "known_at": NOW, "invalidated": False},
                  {"id": "invalid", "direction": "bullish", "score": 1, "known_at": NOW, "invalidated": True}]
    result = ShadowScenarioBattle().compare(candidates, NOW)
    assert result["directional_conflict"] and result["preferred_id"] is None
    assert [row["id"] for row in result["rejected"]] == ["invalid"]
    assert result["ranked"][0]["id"] == "bull"


def test_future_scenario_and_nonboolean_invalidation_rejected():
    scenario = {"id": "bull", "direction": "bullish", "score": .8, "known_at": NOW, "invalidated": False}
    with pytest.raises(ValueError):
        ShadowScenarioBattle().compare([{**scenario, "known_at": NOW+timedelta(seconds=1)}], NOW)
    with pytest.raises(ValueError):
        ShadowScenarioBattle().compare([{**scenario, "invalidated": "false"}], NOW)


def test_liquidity_trap_uses_prior_range_not_future_or_hidden_order_book():
    data = [bar(i, close=100, low=99, high=101, open_price=100) for i in range(20)]
    data.append(bar(20, close=100.5, low=100, high=103, open_price=101, volume=2000))
    output = LiquidityTrapDetector().assess(data, data[-1].timestamp)
    assert output["flags"] == ["FAILED_UPSIDE_BREAKOUT", "ELEVATED_VOLUME_REJECTION"]
    assert output["prior_high"] == 101
    assert not output["execution_authority"]
    with pytest.raises(ValueError):
        LiquidityTrapDetector().assess(data, NOW)


def test_correlation_guard_accounts_for_related_exposure_and_missing_data():
    a = series(30, "wave")
    b = series(30, "wave", scale=2)
    guard = PortfolioCorrelationGuard()
    result = guard.assess({"A": a, "B": b}, {"A": 600, "B": 500}, a[-1].timestamp, 1000)
    assert not result["passes_guard"]
    assert result["pairs"][0]["correlation"] == pytest.approx(1)
    assert result["exposure_input_must_include_pending_orders"]
    insufficient = guard.assess({"A": a}, {"A": 600, "B": 500}, a[-1].timestamp, 1000)
    assert any("INSUFFICIENT" in reason for reason in insufficient["failures"])


def test_zero_variance_and_future_correlation_are_not_silently_safe():
    a = series(30, "flat")
    guard = PortfolioCorrelationGuard()
    result = guard.assess({"A": a, "B": a}, {"A": 1, "B": 1}, a[-1].timestamp, 1000)
    assert not result["passes_guard"]
    assert any("UNDEFINED" in reason for reason in result["failures"])
    with pytest.raises(ValueError, match="Future"):
        guard.assess({"A": a}, {"A": 1}, NOW, 1000)


def test_correlation_alignment_handles_different_timestamps():
    a = series(30, "wave")
    b = series(30, "wave", offset=100)
    output = PortfolioCorrelationGuard().assess({"A": a, "B": b}, {"A": 1, "B": 1},
                                               b[-1].timestamp, 1000)
    assert not output["passes_guard"]
    assert "INSUFFICIENT_ALIGNED_HISTORY:A:B" in output["failures"]


def test_walk_forward_strict_order_costs_and_nonoverlapping_oos_folds():
    data = series(55)
    output = StrategyTournament().walk_forward(data, [MomentumCandidate("enter", 3, 0)],
                                               train_size=20, test_size=10, purge=2)
    assert len(output["folds"]) == 3
    previous_end = None
    for fold in output["folds"]:
        assert fold["selection_at"] == fold["train_end"] < fold["test_start"]
        assert not previous_end or previous_end < fold["test_start"]
        previous_end = fold["test_end"]
        for trade in fold["testing"]["trades"]:
            assert trade["decision_at"] < trade["entry_at"] < trade["exit_at"]
            assert fold["test_start"] <= trade["entry_at"] <= trade["exit_at"] <= fold["test_end"]
            assert trade["commission"] == 1.3 and trade["modeled_cost"] > 1.3
    assert not output["profitability_evidence"]


def test_walk_forward_selection_does_not_look_at_test_outcomes():
    # A train-only rising fixture exceeds all modeled costs and selects the
    # trading candidate; changing its later test outcomes must not change selection.
    data = tuple(replace(p, bid=p.bid+i*.08, ask=p.ask+i*.08) for i, p in enumerate(series(42)))
    candidates = [MomentumCandidate("enter", 3, 0), MomentumCandidate("flat", 3, 1)]
    normal = StrategyTournament().walk_forward(data, candidates, train_size=20, test_size=10)
    changed = tuple(p if i < 21 else replace(p, bid=1, ask=1.1) for i, p in enumerate(data))
    shocked = StrategyTournament().walk_forward(changed, candidates, train_size=20, test_size=10)
    assert normal["folds"][0]["selected"] == shocked["folds"][0]["selected"]
    assert normal["folds"][0]["training"] == shocked["folds"][0]["training"]
    assert normal["folds"][0]["testing"] != shocked["folds"][0]["testing"]


def test_walk_forward_appending_future_does_not_repaint_completed_folds():
    tournament = StrategyTournament()
    candidates = [MomentumCandidate("enter", 3, 0), MomentumCandidate("flat", 3, 1)]
    first = tournament.walk_forward(series(31), candidates, train_size=20, test_size=10)
    extended = tournament.walk_forward(series(61), candidates, train_size=20, test_size=10)
    assert extended["folds"][:1] == first["folds"]


def test_walk_forward_flat_series_loses_money_to_costs():
    output = StrategyTournament().walk_forward(series(31, "flat"), [MomentumCandidate("enter", 3, 0)],
                                               train_size=20, test_size=10)
    assert output["out_of_sample_pnl"] < 0


@pytest.mark.parametrize("options", [{"purge": 0}, {"train_size": 2}, {"test_size": 1},
                                     {"commission": -1}, {"slippage": float("nan")}, {"multiplier": 10}])
def test_walk_forward_rejects_invalid_validation_configuration(options):
    with pytest.raises(ValueError):
        StrategyTournament().walk_forward(series(), [MomentumCandidate("enter", 3, 0)], **options)


def test_walk_forward_rejects_duplicate_timestamps_and_arbitrary_callbacks():
    with pytest.raises(ValueError, match="chronological"):
        StrategyTournament().walk_forward((series()[0],)*60, [MomentumCandidate("enter", 3, 0)])
    with pytest.raises(ValueError, match="Declarative"):
        StrategyTournament().walk_forward(series(), [lambda prefix: True])


def test_decision_memory_is_immutable_account_scoped_and_hash_chained():
    memory = DecisionMemory()
    evidence = {"indicators": {"rsi": 61}}
    first = recorded(memory, evidence=evidence)
    evidence["indicators"]["rsi"] = 2
    assert json.loads(first.evidence_json)["indicators"]["rsi"] == 61
    with pytest.raises(FrozenInstanceError):
        first.contract_id = "other"
    second = recorded(memory, key="two", at=NOW+timedelta(minutes=1))
    other = recorded(memory, account="b")
    assert second.previous_digest == first.digest
    assert other.previous_digest == ""
    assert len(memory.observations("a")) == 2 and len(memory.observations("b")) == 1
    assert memory.observations("unknown") == ()


def test_decision_memory_retries_idempotent_and_reasons_cannot_be_rewritten():
    memory = DecisionMemory()
    first = recorded(memory)
    assert recorded(memory) is first
    with pytest.raises(ValueError, match="immutable"):
        memory.record("a", "one", NOW, NOW, "synthetic-aapl-call", ["invented after outcome"], {"activation": 100})
    assert len(memory.observations("a")) == 1


def test_decision_memory_rejects_future_observation_backdating_and_nan():
    memory = DecisionMemory()
    with pytest.raises(ValueError, match="after a decision"):
        memory.record("a", "one", NOW, NOW+timedelta(seconds=1), "c", ["reason"], {})
    recorded(memory, at=NOW+timedelta(minutes=2))
    with pytest.raises(ValueError, match="backdated"):
        recorded(memory, key="two")
    with pytest.raises(ValueError):
        recorded(DecisionMemory(), evidence={"score": float("nan")})


def test_counterfactual_replay_uses_next_quote_costs_and_retains_original_reasons():
    decision = recorded()
    data = series(4, "flat")
    outcome = CounterfactualReplay().replay(decision, data, data[-1].timestamp,
                                          contract_id=decision.contract_id)
    assert outcome["entry_at"] == data[1].timestamp.isoformat()
    assert outcome["exit_at"] == data[2].timestamp.isoformat()
    assert outcome["pnl"] == pytest.approx(-5.3)
    assert outcome["decision_digest"] == decision.digest
    assert outcome["decision_reasons"] == list(decision.reasons)


def test_counterfactual_cannot_see_future_outcomes_or_mix_contracts():
    decision = recorded()
    data = series(4)
    result = CounterfactualReplay().replay(decision, data, data[1].timestamp, contract_id=decision.contract_id)
    assert result["status"] == "INSUFFICIENT_OBSERVED_OUTCOME" and result["pnl"] is None
    with pytest.raises(ValueError, match="identity"):
        CounterfactualReplay().replay(decision, data, data[-1].timestamp, contract_id="wrong-contract")


@pytest.mark.parametrize("field", ["account_known", "balances_fresh", "orders_reconciled",
                                  "market_fresh", "contract_qualified", "live_locked"])
def test_perfect_trust_score_never_overrides_any_hard_safety_failure(field):
    state = SafetyState(True, True, True, True, True, True, False, True)
    result = AutonomousSafetySupervisor().assess(replace(state, **{field: False}), {"ai": 1, "signals": 1})
    assert result["trust"]["score"] == 1
    assert not result["new_entry_gate_passes"]
    assert not result["owned_close_gate_passes"]
    assert field.upper() in result["hard_failures"]
    assert not result["execution_authority"]


def test_emergency_allows_only_verified_owned_reduction_candidate():
    state = SafetyState(True, True, True, True, True, True, True, True)
    output = AutonomousSafetySupervisor().assess(state)
    assert not output["new_entry_gate_passes"]
    assert output["owned_close_gate_passes"]
    assert not AutonomousSafetySupervisor().assess(replace(state, owned_close_quantity_known=False))["owned_close_gate_passes"]


def test_safety_unknown_defaults_and_truthy_strings_cannot_pass():
    result = AutonomousSafetySupervisor().assess(SafetyState(), {"ai": 1})
    assert not result["new_entry_gate_passes"] and not result["owned_close_gate_passes"]
    with pytest.raises(ValueError):
        SafetyState(account_known="true")
    with pytest.raises(ValueError):
        SystemTrustScore().assess({"ai": 1.01})


def test_json_facade_is_reproducible_synthetic_and_has_no_execution_authority():
    result = synthetic_research_demo()
    assert json.loads(json.dumps(result, allow_nan=False)) == result
    assert result == synthetic_research_demo()
    assert result["source"] == "synthetic_fixture"
    assert not result["external_connections"]
    assert not result["safety_example"]["new_entry_gate_passes"]


def test_quality_policy_rejects_nonfinite_and_inverted_delta_bounds():
    with pytest.raises(ValueError):
        ContractQualityPolicy(max_age_seconds=float("nan"))
    with pytest.raises(ValueError):
        ContractQualityPolicy(min_abs_delta=.9, max_abs_delta=.5)
