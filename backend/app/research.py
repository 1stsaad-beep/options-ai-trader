"""Pure V1 research engines. Every result is SHADOW and has no execution authority.

Money in this module is research-only decimal dollars, never the integer-cent
execution ledger. No network, model provider, broker or repository is imported.
"""
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from math import isfinite, sqrt
import json
import re
from typing import Iterable, Mapping

from .engines import Bar, aware, validate_bars


def number(value, name, minimum=None, maximum=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value):
        raise ValueError(f"{name} must be finite numeric data")
    if minimum is not None and value < minimum or maximum is not None and value > maximum:
        raise ValueError(f"{name} outside permitted range")
    return value


def integer(value, name, minimum=0, maximum=1_000_000_000):
    if type(value) is not int or value < minimum or value > maximum:
        raise ValueError(f"Invalid {name}")
    return value


def timestamp(value):
    if not isinstance(value, datetime):
        raise ValueError("Datetime required")
    aware(value)
    return value


@dataclass(frozen=True)
class OptionContract:
    contract_id: str
    symbol: str
    right: str
    strike: float
    expiry: datetime
    observed_at: datetime
    spot: float
    bid: float
    ask: float
    delta: float
    gamma: float
    theta_per_day: float
    vega_per_vol_point: float
    iv: float
    volume: int
    open_interest: int
    multiplier: int = 100
    commission_per_contract: float = .65
    slippage_per_share: float = .01
    currency: str = "USD"
    exchange: str = "SYNTHETIC"
    instrument_type: str = "OPTION"
    source: str = "synthetic_fixture"

    def __post_init__(self):
        timestamp(self.expiry)
        timestamp(self.observed_at)
        if not isinstance(self.contract_id, str) or not self.contract_id.strip():
            raise ValueError("Contract identifier required")
        if not isinstance(self.symbol, str) or not re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,11}", self.symbol):
            raise ValueError("Invalid symbol")
        if self.right not in ("CALL", "PUT") or self.instrument_type != "OPTION":
            raise ValueError("Only single-leg long calls and puts are modeled")
        for name in ("strike", "spot", "ask"):
            number(getattr(self, name), name, 1e-12, 1e9)
        for name in ("bid", "gamma", "vega_per_vol_point", "commission_per_contract", "slippage_per_share"):
            number(getattr(self, name), name, 0, 1e9)
        number(self.theta_per_day, "theta_per_day", -1e9, 1e9)
        number(self.delta, "delta", 0 if self.right == "CALL" else -1, 1 if self.right == "CALL" else 0)
        number(self.iv, "iv", .000001, 10)
        integer(self.volume, "volume")
        integer(self.open_interest, "open_interest")
        integer(self.multiplier, "multiplier", 1)
        if self.bid > self.ask:
            raise ValueError("Crossed option quote")
        if self.source not in ("synthetic_fixture", "provided_history", "unverified"):
            raise ValueError("Unknown data provenance")
        if not all(isinstance(v, str) and v.strip() for v in (self.currency, self.exchange)):
            raise ValueError("Currency and exchange required")


@dataclass(frozen=True)
class ContractQualityPolicy:
    max_age_seconds: float = 60
    min_days_to_expiry: float = 2
    max_spread_fraction: float = .15
    min_volume: int = 10
    min_open_interest: int = 100
    max_round_trip_cost_fraction: float = .25
    min_abs_delta: float = .2
    max_abs_delta: float = .8

    def __post_init__(self):
        number(self.max_age_seconds, "max_age_seconds", 0)
        number(self.min_days_to_expiry, "min_days_to_expiry", 0)
        number(self.max_spread_fraction, "max_spread_fraction", 0, 2)
        number(self.max_round_trip_cost_fraction, "max_round_trip_cost_fraction", 0)
        number(self.min_abs_delta, "min_abs_delta", 0, 1)
        number(self.max_abs_delta, "max_abs_delta", self.min_abs_delta, 1)
        integer(self.min_volume, "min_volume")
        integer(self.min_open_interest, "min_open_interest")


def assess_contract(contract: OptionContract, as_of: datetime,
                    policy: ContractQualityPolicy = ContractQualityPolicy()) -> dict:
    timestamp(as_of)
    reasons = []
    age = (as_of - contract.observed_at).total_seconds()
    days = (contract.expiry - as_of).total_seconds() / 86400
    mid = (contract.bid + contract.ask) / 2
    spread = (contract.ask - contract.bid) / mid
    cost = ((contract.ask - contract.bid + 2 * contract.slippage_per_share) * contract.multiplier
            + 2 * contract.commission_per_contract)
    cost_fraction = cost / (mid * contract.multiplier)
    for failed, reason in (
        (age < 0, "FUTURE_QUOTE"), (age > policy.max_age_seconds, "STALE_QUOTE"),
        (days <= 0, "EXPIRED"), (0 < days < policy.min_days_to_expiry, "NEAR_EXPIRY"),
        (contract.multiplier != 100, "NONSTANDARD_MULTIPLIER"),
        (contract.currency != "USD", "UNSUPPORTED_CURRENCY"),
        (contract.source == "unverified", "UNVERIFIED_DATA"),
        (contract.bid <= 0, "NO_EXECUTABLE_BID"),
        (contract.volume < policy.min_volume, "LOW_VOLUME"),
        (contract.open_interest < policy.min_open_interest, "LOW_OPEN_INTEREST"),
        (spread > policy.max_spread_fraction, "WIDE_SPREAD"),
        (cost_fraction > policy.max_round_trip_cost_fraction, "HIGH_ROUND_TRIP_COST"),
        (not policy.min_abs_delta <= abs(contract.delta) <= policy.max_abs_delta, "DELTA_OUTSIDE_POLICY"),
    ):
        if failed:
            reasons.append(reason)
    return {"mode": "SHADOW", "source": contract.source, "contract_id": contract.contract_id,
            "accepted_for_research": not reasons, "reasons": reasons,
            "spread_fraction": spread, "round_trip_cost": cost,
            "round_trip_cost_fraction": cost_fraction, "days_to_expiry": days,
            "broker_verified": False, "execution_authority": False,
            "exercise_risk": "Early exercise, assignment, dividends and settlement are not simulated"}


class OptionTwin:
    """Local Greek-Taylor sensitivity, not an option pricing or fill guarantee.

    Theta uses dollars/share/calendar day; vega uses dollars/share/one IV
    percentage point. Greeks are held fixed and large shocks are flagged.
    """
    def simulate(self, contract: OptionContract, as_of: datetime, scenarios: Iterable[Mapping],
                 quantity: int = 1, policy: ContractQualityPolicy = ContractQualityPolicy()) -> dict:
        integer(quantity, "quantity", 1, 1_000_000)
        quality = assess_contract(contract, as_of, policy)
        if not quality["accepted_for_research"]:
            raise ValueError("Contract rejected: " + ",".join(quality["reasons"]))
        scenarios = tuple(scenarios)
        if not scenarios or len(scenarios) > 250:
            raise ValueError("Provide 1 to 250 explicit scenarios")
        entry = ((contract.ask + contract.slippage_per_share) * contract.multiplier
                 + contract.commission_per_contract) * quantity
        results = []
        for scenario in scenarios:
            if not isinstance(scenario, Mapping) or set(scenario) != {"spot", "elapsed_days", "iv"}:
                raise ValueError("Scenario requires spot, elapsed_days, iv only")
            spot = number(scenario["spot"], "spot", 1e-12, 1e9)
            elapsed = number(scenario["elapsed_days"], "elapsed_days", 0, 36600)
            iv = number(scenario["iv"], "iv", .000001, 10)
            delta_spot = spot - contract.spot
            intrinsic = max(0, spot-contract.strike if contract.right == "CALL" else contract.strike-spot)
            expired = elapsed * 86400 >= (contract.expiry-as_of).total_seconds()
            estimate = ((contract.bid + contract.ask) / 2 + contract.delta * delta_spot
                        + .5 * contract.gamma * delta_spot ** 2
                        + contract.theta_per_day * elapsed
                        + contract.vega_per_vol_point * (iv-contract.iv) * 100)
            # Bounds are a conservative numerical constraint, not American exercise modeling.
            theoretical = intrinsic if expired else min(spot if contract.right == "CALL" else contract.strike,
                                                         max(intrinsic, estimate))
            exit_value = max(0, theoretical - (contract.ask-contract.bid)/2 - contract.slippage_per_share)
            fees = 0 if expired else contract.commission_per_contract * quantity
            proceeds = (intrinsic if expired else exit_value) * contract.multiplier * quantity - fees
            results.append({"spot": spot, "elapsed_days": elapsed, "iv": iv,
                            "estimated_option_value": theoretical, "scenario_pnl": proceeds-entry,
                            "entry_outlay": entry, "exit_value_after_modeled_costs": proceeds,
                            "expiry_intrinsic_scenario": expired,
                            "outside_local_approximation": abs(delta_spot/contract.spot) > .1 or
                            abs(iv-contract.iv) > .1 or elapsed > 7})
        return {"mode": "SHADOW", "source": contract.source, "model": "fixed_greek_taylor_sensitivity",
                "scenarios": results, "contract_quality": quality, "execution_authority": False,
                "profitability_evidence": False,
                "limitations": ["Fixed Greeks; no IV surface or rate/dividend model",
                                "Expiry intrinsic is hypothetical economic value, not a broker fill or exercise instruction",
                                "Modeled spread and slippage can understate actual losses"]}


@dataclass(frozen=True)
class EntrySetup:
    right: str
    activation: float
    invalidation: float
    known_at: datetime
    expires_at: datetime
    scenario_id: str

    def __post_init__(self):
        timestamp(self.known_at)
        timestamp(self.expires_at)
        number(self.activation, "activation", 1e-12)
        number(self.invalidation, "invalidation", 1e-12)
        if self.right not in ("CALL", "PUT") or self.expires_at <= self.known_at or not self.scenario_id:
            raise ValueError("Invalid entry setup")
        if (self.right == "CALL" and self.invalidation >= self.activation or
                self.right == "PUT" and self.invalidation <= self.activation):
            raise ValueError("Invalidation must be adverse to activation")


class AdaptiveEntryEngine:
    PROFILES = {"conservative": (.75, 2), "balanced": (.6, 1), "opportunistic": (.45, 1)}

    def evaluate(self, setup: EntrySetup, bars: Iterable[Bar], as_of: datetime,
                 method: str = "confirmed", profile: str = "balanced", strength: float = .6,
                 max_observation_age: timedelta = timedelta(minutes=15)) -> dict:
        timestamp(as_of)
        number(strength, "strength", 0, 1)
        if not isinstance(max_observation_age, timedelta) or max_observation_age < timedelta(0):
            raise ValueError("Invalid maximum observation age")
        if method not in ("early", "confirmed", "pullback") or profile not in self.PROFILES:
            raise ValueError("Unknown entry method or profile")
        bars = validate_bars(bars)
        if bars and bars[-1].timestamp > as_of:
            raise ValueError("Future bar cannot influence entry")
        eligible = tuple(b for b in bars if b.timestamp >= setup.known_at)
        threshold, confirmations = self.PROFILES[profile]
        reason = "WAITING_FOR_TRIGGER"
        accepted = False
        sign = 1 if setup.right == "CALL" else -1
        invalidated = any((b.low <= setup.invalidation if sign == 1 else b.high >= setup.invalidation) for b in eligible)
        if as_of < setup.known_at:
            reason = "SETUP_NOT_YET_KNOWN"
        elif as_of >= setup.expires_at:
            reason = "SETUP_EXPIRED"
        elif invalidated:
            reason = "SCENARIO_INVALIDATED"
        elif eligible and as_of-eligible[-1].timestamp > max_observation_age:
            reason = "STALE_OBSERVATION"
        elif strength < threshold:
            reason = "INSUFFICIENT_QUANTITATIVE_STRENGTH"
        elif eligible:
            last = eligible[-1]
            if method == "early":
                accepted = last.high >= setup.activation if sign == 1 else last.low <= setup.activation
            elif method == "confirmed":
                accepted = len(eligible) >= confirmations and all(sign * (b.close-setup.activation) > 0
                                                                  for b in eligible[-confirmations:])
            else:
                prior_activation = any(sign*(b.close-setup.activation) > 0 for b in eligible[:-1])
                touched = last.low <= setup.activation <= last.high
                rejection = sign*(last.close-setup.activation) > 0 and sign*(last.close-last.open) > 0
                accepted = prior_activation and touched and rejection
            if accepted:
                reason = "QUANTITATIVE_ENTRY_CANDIDATE"
        return {"mode": "SHADOW", "entry_candidate": accepted, "reason": reason,
                "method": method, "profile": profile, "signal_strength": strength,
                "activation": setup.activation, "invalidation": setup.invalidation,
                "expires_at": setup.expires_at.isoformat(), "scenario_id": setup.scenario_id,
                "risk_sizing_included": False, "execution_authority": False}


class EntryTimingOptimizer:
    """Compares rules on the same known prefix; never selects using later P&L."""
    def compare(self, setup, bars, as_of, profile="balanced", strength=.6):
        bars = tuple(bars)
        return {"mode": "SHADOW", "optimized_on_future_outcomes": False,
                "methods": [AdaptiveEntryEngine().evaluate(setup, bars, as_of, method, profile, strength)
                            for method in ("early", "confirmed", "pullback")]}


class ShadowScenarioBattle:
    def compare(self, scenarios: Iterable[Mapping], as_of: datetime) -> dict:
        timestamp(as_of)
        candidates = []
        ids = set()
        for scenario in scenarios:
            if set(scenario) != {"id", "direction", "score", "known_at", "invalidated"}:
                raise ValueError("Unexpected scenario fields")
            if not isinstance(scenario["id"], str) or not scenario["id"] or scenario["id"] in ids:
                raise ValueError("Unique scenario IDs required")
            ids.add(scenario["id"])
            timestamp(scenario["known_at"])
            number(scenario["score"], "score", 0, 1)
            if scenario["known_at"] > as_of or scenario["direction"] not in ("bullish", "bearish", "neutral"):
                raise ValueError("Unknown or future scenario")
            if type(scenario["invalidated"]) is not bool:
                raise ValueError("Invalidation is a mandatory boolean")
            candidates.append({**scenario, "known_at": scenario["known_at"].isoformat()})
        eligible = sorted((s for s in candidates if not s["invalidated"]), key=lambda s: (-s["score"], s["id"]))
        conflict = bool(eligible and any(s["direction"] != eligible[0]["direction"] and
                                       abs(s["score"]-eligible[0]["score"]) < .1 for s in eligible[1:]))
        return {"mode": "SHADOW", "ranked": eligible, "rejected": [s for s in candidates if s["invalidated"]],
                "directional_conflict": conflict, "preferred_id": None if not eligible or conflict else eligible[0]["id"],
                "execution_authority": False}


class LiquidityTrapDetector:
    def assess(self, bars: Iterable[Bar], as_of: datetime, lookback: int = 20) -> dict:
        timestamp(as_of)
        integer(lookback, "lookback", 2)
        bars = validate_bars(bars)
        if bars and bars[-1].timestamp > as_of:
            raise ValueError("Future bar")
        if len(bars) < lookback+1:
            return {"mode": "SHADOW", "status": "INSUFFICIENT_DATA", "flags": []}
        prior, last = bars[-lookback-1:-1], bars[-1]
        high, low = max(b.high for b in prior), min(b.low for b in prior)
        avg_volume = sum(b.volume for b in prior)/lookback
        flags = []
        if last.high > high and last.close <= high:
            flags.append("FAILED_UPSIDE_BREAKOUT")
        if last.low < low and last.close >= low:
            flags.append("FAILED_DOWNSIDE_BREAKOUT")
        if flags and avg_volume > 0 and last.volume >= 1.5*avg_volume:
            flags.append("ELEVATED_VOLUME_REJECTION")
        return {"mode": "SHADOW", "status": "ASSESSED", "flags": flags,
                "prior_high": high, "prior_low": low, "execution_authority": False,
                "interpretation": "Price/volume rejection proxy; no claim to observe hidden liquidity"}


@dataclass(frozen=True)
class ResearchPoint:
    timestamp: datetime
    bid: float
    ask: float

    def __post_init__(self):
        timestamp(self.timestamp)
        number(self.bid, "bid", 0, 1e9)
        number(self.ask, "ask", 1e-12, 1e9)
        if self.ask < self.bid:
            raise ValueError("Crossed quote")

    @property
    def mid(self):
        return (self.bid+self.ask)/2


def points(values):
    values = tuple(values)
    if any(not isinstance(p, ResearchPoint) for p in values):
        raise ValueError("ResearchPoint sequence required")
    if any(a.timestamp >= b.timestamp for a, b in zip(values, values[1:])):
        raise ValueError("Observations must be unique and chronological")
    return values


class PortfolioCorrelationGuard:
    """Conservative delta-exposure proxy; not a full nonlinear options stress model."""
    def assess(self, histories: Mapping[str, Iterable[ResearchPoint]], exposures: Mapping[str, float],
               as_of: datetime, pair_limit: float, correlation_threshold: float = .8,
               min_observations: int = 20) -> dict:
        timestamp(as_of)
        number(pair_limit, "pair_limit", 0, 1e15)
        number(correlation_threshold, "correlation_threshold", 0, 1)
        integer(min_observations, "min_observations", 3)
        series, failures, pairs = {}, [], []
        for symbol, exposure in exposures.items():
            number(exposure, "signed_delta_exposure", -1e15, 1e15)
            history = points(histories.get(symbol, ()))
            if history and history[-1].timestamp > as_of:
                raise ValueError("Future correlation observation")
            series[symbol] = {p.timestamp: p.mid for p in history}
            if exposure != 0 and len(history) < min_observations:
                failures.append(f"INSUFFICIENT_HISTORY:{symbol}")
        symbols = sorted(s for s, e in exposures.items() if e != 0)
        for index, first in enumerate(symbols):
            for second in symbols[index+1:]:
                times = sorted(set(series[first]) & set(series[second]))
                if len(times) < min_observations:
                    failures.append(f"INSUFFICIENT_ALIGNED_HISTORY:{first}:{second}")
                    continue
                returns = [[series[s][b]/series[s][a]-1 for a, b in zip(times, times[1:])] for s in (first, second)]
                centered = [[v-sum(row)/len(row) for v in row] for row in returns]
                denominator = sqrt(sum(v*v for v in centered[0])*sum(v*v for v in centered[1]))
                if denominator < 1e-15:
                    failures.append(f"UNDEFINED_CORRELATION:{first}:{second}")
                    continue
                correlation = max(-1., min(1., sum(a*b for a, b in zip(*centered))/denominator))
                # Absolute correlation is conservative even when directional hedge benefits are claimed.
                combined = abs(exposures[first])+abs(exposures[second])
                blocked = abs(correlation) >= correlation_threshold and combined > pair_limit
                if blocked:
                    failures.append(f"CORRELATED_EXPOSURE_LIMIT:{first}:{second}")
                pairs.append({"symbols": [first, second], "correlation": correlation,
                              "combined_absolute_exposure": combined, "blocked": blocked})
        return {"mode": "SHADOW", "passes_guard": not failures, "failures": failures, "pairs": pairs,
                "exposure_input_must_include_pending_orders": True, "execution_authority": False}


@dataclass(frozen=True)
class MomentumCandidate:
    name: str
    lookback: int
    threshold: float

    def __post_init__(self):
        if not self.name:
            raise ValueError("Candidate name required")
        integer(self.lookback, "lookback", 2)
        number(self.threshold, "threshold", -1, 10)

    def wants_long(self, history: tuple[ResearchPoint, ...]) -> bool:
        return len(history) >= self.lookback and history[-1].mid/history[-self.lookback].mid-1 >= self.threshold


class StrategyTournament:
    """Expanding/rolling chronological selection for one fixed option quote series.

    Candidates are declarative, not arbitrary callbacks with access to future data.
    One contract per non-overlapping one-bar trade; entry is the next ask after
    a decision, exit the subsequent bid. Does not model capital or option rolls.
    """
    def walk_forward(self, quotes: Iterable[ResearchPoint], candidates: Iterable[MomentumCandidate],
                     train_size: int = 40, test_size: int = 10, purge: int = 1,
                     commission: float = .65, slippage: float = .01, multiplier: int = 100) -> dict:
        quotes, candidates = points(quotes), tuple(candidates)
        integer(train_size, "train_size", 4)
        integer(test_size, "test_size", 2)
        integer(purge, "purge", 1)
        number(commission, "commission", 0)
        number(slippage, "slippage", 0)
        if type(multiplier) is not int or multiplier != 100:
            raise ValueError("Only standard option contracts supported")
        if not candidates or any(not isinstance(c, MomentumCandidate) for c in candidates):
            raise ValueError("Declarative candidates required")
        if len({c.name for c in candidates}) != len(candidates):
            raise ValueError("Duplicate candidate names")
        if max(c.lookback for c in candidates) > train_size-2:
            raise ValueError("Insufficient training history for candidate")
        if len(quotes) < train_size+purge+test_size:
            raise ValueError("Insufficient train/purge/test observations")

        def evaluate(candidate, history_start, start, end):
            pnl, cost, trades = 0., 0., []
            index = max(start, history_start+candidate.lookback)
            while index+1 < end:
                prefix = quotes[history_start:index]  # Decision sees only the earlier quote.
                if candidate.wants_long(prefix):
                    entry, exit_quote = quotes[index], quotes[index+1]
                    entry_price, exit_price = entry.ask+slippage, max(0, exit_quote.bid-slippage)
                    trade_pnl = (exit_price-entry_price)*multiplier-2*commission
                    trade_cost = ((entry.ask-entry.mid)+(exit_quote.mid-exit_quote.bid)
                                  + slippage + min(slippage, exit_quote.bid))*multiplier+2*commission
                    pnl += trade_pnl
                    cost += trade_cost
                    trades.append({"decision_at": prefix[-1].timestamp.isoformat(),
                                   "entry_at": entry.timestamp.isoformat(), "exit_at": exit_quote.timestamp.isoformat(),
                                   "pnl": trade_pnl, "commission": 2*commission, "modeled_cost": trade_cost})
                    index += 2
                else:
                    index += 1
            return {"pnl": pnl, "modeled_cost": cost, "trades": trades}

        folds = []
        train_end = train_size
        while train_end+purge+test_size <= len(quotes):
            train_start = train_end-train_size
            ranked = [(candidate, evaluate(candidate, train_start, train_start, train_end)) for candidate in candidates]
            selected, training = sorted(ranked, key=lambda row: (-row[1]["pnl"], row[0].name))[0]
            test_start, test_end = train_end+purge, train_end+purge+test_size
            testing = evaluate(selected, train_start, test_start, test_end)
            folds.append({"selected": selected.name, "selection_at": quotes[train_end-1].timestamp.isoformat(),
                          "train_start": quotes[train_start].timestamp.isoformat(),
                          "train_end": quotes[train_end-1].timestamp.isoformat(),
                          "test_start": quotes[test_start].timestamp.isoformat(),
                          "test_end": quotes[test_end-1].timestamp.isoformat(),
                          "training": training, "testing": testing})
            train_end += test_size
        return {"mode": "SHADOW", "folds": folds, "purge_observations": purge,
                "out_of_sample_pnl": sum(f["testing"]["pnl"] for f in folds),
                "profitability_evidence": False,
                "limitations": ["Single provided option series; synthetic data is not market evidence",
                                "No capital sizing, assignment, overnight liquidity or contract rolling",
                                "Multiple-comparison bias and statistical significance not estimated"]}


@dataclass(frozen=True)
class DecisionObservation:
    account_id: str
    decision_id: str
    decided_at: datetime
    observed_at: datetime
    contract_id: str
    reasons: tuple[str, ...]
    evidence_json: str
    previous_digest: str
    digest: str


class DecisionMemory:
    """Account-separated in-memory append-only research journal, not durable audit DB."""
    def __init__(self):
        self._records: dict[str, list[DecisionObservation]] = {}

    def record(self, account_id: str, decision_id: str, decided_at: datetime, observed_at: datetime,
               contract_id: str, reasons: Iterable[str], evidence: Mapping) -> DecisionObservation:
        timestamp(decided_at)
        timestamp(observed_at)
        reasons = tuple(reasons)
        if not all(isinstance(v, str) and v.strip() for v in (account_id, decision_id, contract_id)):
            raise ValueError("Account, decision and contract identifiers required")
        if not reasons or any(not isinstance(reason, str) or not reason.strip() for reason in reasons):
            raise ValueError("Decision-time quantitative reasons required")
        if observed_at > decided_at:
            raise ValueError("Evidence cannot be observed after a decision")
        if not isinstance(evidence, Mapping):
            raise ValueError("Evidence mapping required")
        evidence_json = json.dumps(dict(evidence), sort_keys=True, separators=(",", ":"), allow_nan=False)
        if len(evidence_json) > 64000:
            raise ValueError("Evidence too large")
        records = self._records.setdefault(account_id, [])
        base = {"account_id": account_id, "decision_id": decision_id, "decided_at": decided_at.isoformat(),
                "observed_at": observed_at.isoformat(), "contract_id": contract_id,
                "reasons": reasons, "evidence_json": evidence_json}
        existing = next((r for r in records if r.decision_id == decision_id), None)
        if existing:
            comparison = {**asdict(existing), "decided_at": existing.decided_at.isoformat(),
                          "observed_at": existing.observed_at.isoformat()}
            if any(comparison[k] != value for k, value in base.items()):
                raise ValueError("Decision is immutable")
            return existing
        if records and records[-1].decided_at > decided_at:
            raise ValueError("Decision history cannot be backdated")
        previous = records[-1].digest if records else ""
        digest = sha256(json.dumps({**base, "previous_digest": previous}, sort_keys=True).encode()).hexdigest()
        record = DecisionObservation(account_id, decision_id, decided_at, observed_at, contract_id,
                                     reasons, evidence_json, previous, digest)
        records.append(record)
        return record

    def observations(self, account_id: str) -> tuple[DecisionObservation, ...]:
        if not isinstance(account_id, str) or not account_id:
            raise ValueError("Explicit account required")
        return tuple(self._records.get(account_id, ()))

    def to_state(self) -> dict:
        """Export primitive immutable observations, not executable callbacks.

        The owning service must persist this inside its authenticated immutable
        audit store; a hash is an integrity check, not an authentication method.
        """
        return {"schema_version": 1, "records": [
            {**asdict(record), "decided_at": record.decided_at.isoformat(),
             "observed_at": record.observed_at.isoformat(), "reasons": list(record.reasons)}
            for account in sorted(self._records) for record in self._records[account]]}

    @classmethod
    def from_state(cls, state: Mapping) -> "DecisionMemory":
        """Validate every record, account chain, reason and digest on restoration."""
        if (not isinstance(state, Mapping) or set(state) != {"schema_version", "records"}
                or type(state["schema_version"]) is not int or state["schema_version"] != 1
                or not isinstance(state["records"], list) or len(state["records"]) > 10000):
            raise ValueError("Invalid decision memory state")
        memory = cls()
        expected = set(DecisionObservation.__dataclass_fields__)
        seen = set()
        for item in state["records"]:
            if not isinstance(item, Mapping) or set(item) != expected:
                raise ValueError("Invalid decision observation fields")
            if (not isinstance(item["reasons"], list)
                    or not all(isinstance(item[k], str) for k in expected - {"reasons"})):
                raise ValueError("Invalid decision observation types")
            key = (item["account_id"], item["decision_id"])
            if key in seen:
                raise ValueError("Duplicate persisted decision")
            seen.add(key)
            try:
                evidence = json.loads(item["evidence_json"])
                restored = memory.record(item["account_id"], item["decision_id"],
                                         datetime.fromisoformat(item["decided_at"]),
                                         datetime.fromisoformat(item["observed_at"]),
                                         item["contract_id"], item["reasons"], evidence)
            except (ValueError, TypeError, OverflowError) as exc:
                raise ValueError("Invalid persisted decision evidence") from exc
            if any(getattr(restored, key) != item[key]
                   for key in ("digest", "previous_digest", "evidence_json")):
                raise ValueError("Persisted decision integrity mismatch")
        return memory


class CounterfactualReplay:
    def replay(self, decision: DecisionObservation, quotes: Iterable[ResearchPoint], as_of: datetime,
               holding_observations: int = 1, quantity: int = 1, commission: float = .65,
               slippage: float = .01, contract_id: str = "") -> dict:
        timestamp(as_of)
        integer(holding_observations, "holding_observations", 1)
        integer(quantity, "quantity", 1)
        number(commission, "commission", 0)
        number(slippage, "slippage", 0)
        if contract_id != decision.contract_id or as_of < decision.decided_at:
            raise ValueError("Contract identity or replay timestamp mismatch")
        quotes = points(quotes)
        # Later observations are allowed only as explicitly labeled historical outcomes.
        known = tuple(p for p in quotes if decision.decided_at < p.timestamp <= as_of)
        result = {"mode": "SHADOW", "counterfactual": True, "decision_digest": decision.digest,
                  "decision_reasons": list(decision.reasons), "execution_authority": False,
                  "holding_observations": holding_observations, "profitability_evidence": False}
        if len(known) <= holding_observations:
            return {**result, "status": "INSUFFICIENT_OBSERVED_OUTCOME", "pnl": None}
        entry, exit_quote = known[0], known[holding_observations]
        pnl = ((max(0, exit_quote.bid-slippage)-(entry.ask+slippage))*100-2*commission)*quantity
        return {**result, "status": "REPLAYED", "entry_at": entry.timestamp.isoformat(),
                "exit_at": exit_quote.timestamp.isoformat(), "pnl": pnl,
                "commissions": commission*quantity*2,
                "limitations": "Fixed 100 multiplier; hypothetical later quotes; no fill, liquidity or exercise guarantee"}


@dataclass(frozen=True)
class SafetyState:
    account_known: bool = False
    balances_fresh: bool = False
    orders_reconciled: bool = False
    market_fresh: bool = False
    contract_qualified: bool = False
    live_locked: bool = True
    emergency_stop: bool = False
    owned_close_quantity_known: bool = False

    def __post_init__(self):
        if any(type(value) is not bool for value in asdict(self).values()):
            raise ValueError("Safety facts must be explicit booleans")


class SystemTrustScore:
    def assess(self, components: Mapping[str, float]) -> dict:
        if not components:
            return {"score": 0., "status": "NO_OBSERVATIONS", "may_override_hard_gate": False}
        for value in components.values():
            number(value, "trust_component", 0, 1)
        return {"score": sum(components.values())/len(components), "status": "DIAGNOSTIC_ONLY",
                "may_override_hard_gate": False}


class AutonomousSafetySupervisor:
    def assess(self, state: SafetyState, trust_components: Mapping[str, float] | None = None) -> dict:
        required = ("account_known", "balances_fresh", "orders_reconciled", "market_fresh", "contract_qualified", "live_locked")
        failures = [name.upper() for name in required if not getattr(state, name)]
        if state.emergency_stop:
            failures.append("EMERGENCY_STOP")
        close = all((state.account_known, state.balances_fresh, state.orders_reconciled, state.market_fresh,
                     state.contract_qualified, state.live_locked, state.owned_close_quantity_known))
        return {"mode": "SHADOW", "new_entry_gate_passes": not failures, "hard_failures": failures,
                "owned_close_gate_passes": close, "trust": SystemTrustScore().assess(trust_components or {}),
                "execution_authority": False,
                "emergency_policy": "Only reconciled, priced, owned reductions; unknown state blocks sending orders"}


def synthetic_research_demo() -> dict:
    """JSON-friendly deterministic facade for an authenticated read-only UI endpoint."""
    now = datetime(2026, 1, 5, 15, tzinfo=timezone.utc)
    contract = OptionContract("SYNTHETIC-AAPL-CALL-100", "AAPL", "CALL", 100,
                              now+timedelta(days=30), now, 100, 4.9, 5.1, .5,
                              .04, -.04, .12, .3, 500, 1000)
    safety = AutonomousSafetySupervisor().assess(SafetyState(), {"synthetic_feed": 1})
    return {"mode": "SHADOW", "source": "synthetic_fixture", "as_of": now.isoformat(),
            "contract": {**asdict(contract), "expiry": contract.expiry.isoformat(), "observed_at": now.isoformat()},
            "option_twin": OptionTwin().simulate(contract, now, [
                {"spot": 95, "elapsed_days": 1, "iv": .35},
                {"spot": 100, "elapsed_days": 7, "iv": .3},
                {"spot": 105, "elapsed_days": 1, "iv": .25}]),
            "safety_example": safety, "external_connections": False, "profitability_evidence": False}
