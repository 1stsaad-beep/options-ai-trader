"""Rule-constrained Elliott candidates, not an authoritative wave count or forecast."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from hashlib import sha256
import json
from math import isfinite
from typing import Iterable, Mapping

from ..engines import aware
from .pivots import Pivot, alternating, validate_pivots


@dataclass(frozen=True)
class WaveScenario:
    scenario_id: str
    kind: str
    degree: str
    direction: str
    points: tuple[Pivot, ...]
    labels: tuple[str, ...]
    invalidation: float
    activation: float
    targets: tuple[float, ...]
    evidence_score: float
    observed_at: datetime
    parent_id: str | None = None

    def to_dict(self) -> dict:
        return {"scenario_id": self.scenario_id, "kind": self.kind, "degree": self.degree,
                "direction": self.direction, "points": [p.to_dict() for p in self.points],
                "labels": list(self.labels), "invalidation": self.invalidation,
                "activation": self.activation, "targets": list(self.targets),
                "evidence_score": self.evidence_score, "observed_at": self.observed_at.isoformat(),
                "parent_id": self.parent_id, "mode": "SHADOW", "executable": False}


def _scenario(kind: str, degree: str, points: tuple[Pivot, ...], labels: tuple[str, ...],
              invalidation: float, activation: float, targets: tuple[float, ...], score: float,
              parent_id: str | None = None) -> WaveScenario:
    identity = json.dumps([kind, degree, [(p.timestamp.isoformat(), p.kind, p.price) for p in points], parent_id], separators=(",", ":"))
    return WaveScenario(sha256(identity.encode()).hexdigest()[:24], kind, degree,
                        "BULLISH" if points[0].kind == "LOW" else "BEARISH", points, labels,
                        invalidation, activation, tuple(t for t in targets if t > 0), score,
                        max(p.confirmed_at for p in points), parent_id)


def wave_candidates(pivots: Iterable[Pivot], degree: str = "main") -> tuple[WaveScenario, ...]:
    points = validate_pivots(pivots)
    if degree not in ("main", "internal"):
        raise ValueError("Wave degree must be main or internal")
    result: list[WaveScenario] = []
    for length in (4, 5, 6):
        for start in range(max(0, len(points) - 64), len(points) - length + 1):
            p = points[start:start + length]
            if not alternating(p):
                continue
            sign = 1 if p[0].kind == "LOW" else -1
            v = [q.price * sign for q in p]
            first = v[1] - v[0]
            if first <= 0:
                continue
            # Standard non-diagonal impulse: W2 cannot erase W1, W3 exceeds W1.
            impulse_start = v[0] < v[2] < v[1] < v[3]
            if length == 4:
                if impulse_start:
                    third = v[3] - v[2]
                    result.append(_scenario("WAVE_3_CANDIDATE", degree, p, ("0", "1", "2", "3?"),
                                            p[2].price, p[1].price,
                                            (p[2].price + sign * first * 1.618, p[2].price + sign * first * 2.618),
                                            .75 if third >= first * 1.618 else .6))
                # Zigzag ABC candidate. B retraces A; C extends A's endpoint.
                # Both upward and downward corrections use the same signed geometry.
                if v[0] < v[2] < v[1] < v[3] and .5 <= (v[3] - v[2]) / first <= 2.618:
                    result.append(_scenario("ABC_ZIGZAG_CANDIDATE", degree, p, ("0", "A", "B", "C"),
                                            p[0].price, p[1].price,
                                            (p[2].price + sign * first, p[2].price + sign * first * 1.618), .5))
            elif impulse_start and v[1] < v[4] < v[3]:
                if length == 5:
                    result.append(_scenario("WAVE_5_PENDING", degree, p, ("0", "1", "2", "3", "4"),
                                            p[4].price, p[3].price,
                                            (p[4].price + sign * first, p[4].price + sign * first * 1.618), .7))
                elif v[5] > v[3]:
                    third, fifth = v[3] - v[2], v[5] - v[4]
                    if third >= min(first, fifth):
                        # A complete candidate is historical evidence, not a new W5 entry.
                        result.append(_scenario("IMPULSE_1_5_COMPLETED", degree, p, ("0", "1", "2", "3", "4", "5"),
                                                p[4].price, p[5].price,
                                                (p[5].price - sign * (v[5] - v[0]) * .382,
                                                 p[5].price - sign * (v[5] - v[0]) * .618), .85))
    return tuple(sorted(result, key=lambda s: (s.observed_at, s.scenario_id)))


def nested_third_candidates(main: Iterable[WaveScenario], internal: Iterable[WaveScenario]) -> tuple[WaveScenario, ...]:
    """An observed internal W3 candidate inside a larger W3 leg; still provisional."""
    result = []
    for outer in main:
        if outer.kind != "WAVE_3_CANDIDATE":
            continue
        for inner in internal:
            if (inner.kind == "WAVE_3_CANDIDATE" and inner.direction == outer.direction
                    and outer.points[2].timestamp <= inner.points[0].timestamp
                    and inner.points[-1].timestamp <= outer.points[3].timestamp):
                scenario = _scenario("THIRD_OF_THIRD_CANDIDATE", "internal", inner.points,
                                     ("(0)", "(1)", "(2)", "(3)?"), inner.invalidation,
                                     inner.activation, inner.targets, min(inner.evidence_score, outer.evidence_score), outer.scenario_id)
                # Parent information is not knowable until the parent itself is confirmed.
                result.append(WaveScenario(**{**scenario.__dict__, "observed_at": max(inner.observed_at, outer.observed_at)}))
    return tuple(result)


def rank_scenarios(scenarios: Iterable[WaveScenario], as_of: datetime, close: float,
                   invalidated_ids: Iterable[str] = ()) -> dict:
    aware(as_of)
    if isinstance(close, bool) or not isfinite(close) or close <= 0:
        raise ValueError("Valid observed price required")
    candidates = list(scenarios)
    if any(s.observed_at > as_of for s in candidates):
        raise ValueError("Future scenario")
    invalidated = set(invalidated_ids)
    active = [s for s in candidates if s.scenario_id not in invalidated
              and (close > s.invalidation if s.direction == "BULLISH" else close < s.invalidation)]
    active.sort(key=lambda s: (s.observed_at, s.evidence_score, s.scenario_id), reverse=True)
    # Confidence is descriptive evidence only; there is no risk or execution capability.
    return {"primary": active[0].to_dict() if active else None,
            "alternate": active[1].to_dict() if len(active) > 1 else None,
            "candidate_count": len(candidates), "active_count": len(active)}


@dataclass(frozen=True)
class WaveEvent:
    sequence: int
    scenario_id: str
    event: str
    observed_at: datetime
    price: float
    snapshot_json: str

    def to_dict(self) -> dict:
        return {**asdict(self), "observed_at": self.observed_at.isoformat(),
                "snapshot": json.loads(self.snapshot_json)}


class WaveScenarioTracker:
    """Append-only in-memory event journal, exportable for durable storage by the caller.

    No method changes or deletes historical events. Same-time retries are idempotent;
    conflicting retries and time travel are rejected. This object is not a DB store.
    """
    def __init__(self):
        self._events: list[WaveEvent] = []
        self._states: dict[str, tuple[WaveScenario, str]] = {}
        self._as_of: datetime | None = None
        self._observation: str | None = None
        self._source_hashes: dict[str, str] = {}

    @property
    def events(self) -> tuple[WaveEvent, ...]:
        return tuple(self._events)

    @property
    def invalidated_ids(self) -> frozenset[str]:
        return frozenset(key for key, (_, status) in self._states.items() if status == "INVALIDATED")

    def observe(self, scenarios: Iterable[WaveScenario], *, as_of: datetime, close: float,
                source_history: Mapping[str, str] | None = None) -> tuple[WaveEvent, ...]:
        aware(as_of)
        current = tuple(scenarios)
        if isinstance(close, bool) or not isfinite(close) or close <= 0 or any(s.observed_at > as_of for s in current):
            raise ValueError("Invalid or future scenario observation")
        if len({s.scenario_id for s in current}) != len(current):
            raise ValueError("Duplicate scenario identity")
        source = dict(source_history) if source_history is not None else None
        latest_source = max((datetime.fromisoformat(t) for t in self._source_hashes), default=None)
        if source is not None:
            for timestamp, fingerprint in source.items():
                observed_time = datetime.fromisoformat(timestamp)
                aware(observed_time)
                if (observed_time > as_of or not isinstance(fingerprint, str) or len(fingerprint) != 64
                        or any(c not in "0123456789abcdef" for c in fingerprint)):
                    raise ValueError("Invalid or future source observation")
                if timestamp in self._source_hashes and self._source_hashes[timestamp] != fingerprint:
                    raise ValueError("Historical source bars cannot be rewritten")
                if timestamp not in self._source_hashes and latest_source is not None and observed_time <= latest_source:
                    raise ValueError("Historical source bars cannot be inserted after observation")
        observation = json.dumps([close, sorted((s.scenario_id, s.to_dict()) for s in current),
                                  _digest(source) if source is not None else None], sort_keys=True)
        if self._as_of is not None and as_of < self._as_of:
            raise ValueError("Scenario history cannot be rewritten")
        if as_of == self._as_of:
            if observation != self._observation:
                raise ValueError("Conflicting same-time scenario revision")
            return ()
        for s in current:
            if s.scenario_id in self._states and self._states[s.scenario_id][0] != s:
                raise ValueError("Scenario identity cannot be silently rewritten")
        start = len(self._events)
        for s in current:
            if s.scenario_id not in self._states:
                self._states[s.scenario_id] = (s, "ACTIVE")
                self._append(s, "DETECTED", as_of, close)
        for key, (s, status) in list(self._states.items()):
            if status != "ACTIVE":
                continue
            invalid = close <= s.invalidation if s.direction == "BULLISH" else close >= s.invalidation
            if invalid:
                self._states[key] = (s, "INVALIDATED")
                self._append(s, "INVALIDATED", as_of, close)
        self._as_of, self._observation = as_of, observation
        if source is not None:
            self._source_hashes.update(source)
        return tuple(self._events[start:])

    def _append(self, scenario: WaveScenario, event: str, as_of: datetime, price: float) -> None:
        self._events.append(WaveEvent(len(self._events) + 1, scenario.scenario_id, event, as_of,
                                      price, json.dumps(scenario.to_dict(), sort_keys=True)))

    def to_state(self) -> dict:
        """JSON checkpoint with an append hash chain plus whole-checkpoint checksum.

        Hashes detect corruption; they are not signatures. Persist the checkpoint in
        an authenticated, append-only store. Caller controls account/symbol scope.
        """
        previous_hash = "0" * 64
        events = []
        for event in self._events:
            payload = {"sequence": event.sequence, "scenario_id": event.scenario_id,
                       "event": event.event, "observed_at": event.observed_at.isoformat(),
                       "price": event.price, "snapshot_json": event.snapshot_json,
                       "previous_hash": previous_hash}
            previous_hash = _digest(payload)
            events.append({**payload, "event_hash": previous_hash})
        payload = {"schema_version": 1, "events": events, "chain_head": previous_hash,
                   "last_as_of": self._as_of.isoformat() if self._as_of else None,
                   "last_observation": self._observation, "source_hashes": dict(self._source_hashes)}
        return {**payload, "state_hash": _digest(payload)}

    @classmethod
    def from_state(cls, state: dict) -> "WaveScenarioTracker":
        """Verify a checkpoint before restoring; malformed/truncated histories fail closed."""
        try:
            return cls._restore(state)
        except (KeyError, TypeError, AttributeError, OverflowError, json.JSONDecodeError) as exc:
            raise ValueError("Malformed wave journal checkpoint") from exc

    @classmethod
    def _restore(cls, state: dict) -> "WaveScenarioTracker":
        expected = {"schema_version", "events", "chain_head", "last_as_of", "last_observation", "source_hashes", "state_hash"}
        if (not isinstance(state, dict) or set(state) != expected
                or type(state["schema_version"]) is not int or state["schema_version"] != 1):
            raise ValueError("Unsupported wave journal checkpoint")
        payload = {key: value for key, value in state.items() if key != "state_hash"}
        if _digest(payload) != state["state_hash"]:
            raise ValueError("Wave journal checkpoint integrity mismatch")
        if not isinstance(state["events"], list) or len(state["events"]) > 100_000:
            raise ValueError("Invalid wave journal event collection")
        tracker = cls()
        previous_hash, last_event_time = "0" * 64, None
        for item in state["events"]:
            event_keys = {"sequence", "scenario_id", "event", "observed_at", "price", "snapshot_json", "previous_hash", "event_hash"}
            if not isinstance(item, dict) or set(item) != event_keys:
                raise ValueError("Malformed wave journal event")
            event_payload = {key: value for key, value in item.items() if key != "event_hash"}
            if item["previous_hash"] != previous_hash or _digest(event_payload) != item["event_hash"]:
                raise ValueError("Wave journal append chain mismatch")
            previous_hash = item["event_hash"]
            if (type(item["sequence"]) is not int or item["sequence"] != len(tracker._events) + 1
                    or item["event"] not in ("DETECTED", "INVALIDATED")
                    or isinstance(item["price"], bool) or not isfinite(item["price"]) or item["price"] <= 0
                    or not isinstance(item["snapshot_json"], str) or len(item["snapshot_json"]) > 100_000):
                raise ValueError("Invalid wave journal event values")
            observed = datetime.fromisoformat(item["observed_at"])
            aware(observed)
            scenario = _restore_scenario(json.loads(item["snapshot_json"]))
            if (scenario.scenario_id != item["scenario_id"] or observed < scenario.observed_at
                    or last_event_time is not None and observed < last_event_time):
                raise ValueError("Wave journal chronology or identity mismatch")
            prior = tracker._states.get(scenario.scenario_id)
            if item["event"] == "DETECTED":
                if prior is not None:
                    raise ValueError("Scenario cannot be detected twice")
                tracker._states[scenario.scenario_id] = (scenario, "ACTIVE")
            else:
                breached = item["price"] <= scenario.invalidation if scenario.direction == "BULLISH" else item["price"] >= scenario.invalidation
                if prior is None or prior != (scenario, "ACTIVE") or not breached:
                    raise ValueError("Invalid scenario invalidation transition")
                tracker._states[scenario.scenario_id] = (scenario, "INVALIDATED")
            tracker._events.append(WaveEvent(item["sequence"], scenario.scenario_id, item["event"],
                                             observed, item["price"], item["snapshot_json"]))
            last_event_time = observed
        if previous_hash != state["chain_head"]:
            raise ValueError("Wave journal chain head mismatch")
        if state["last_as_of"] is None:
            if state["last_observation"] is not None or tracker._events or state["source_hashes"]:
                raise ValueError("Journal observation clock is missing")
            return tracker
        observed = datetime.fromisoformat(state["last_as_of"])
        aware(observed)
        if last_event_time is not None and observed < last_event_time:
            raise ValueError("Journal observation clock precedes its events")
        if not isinstance(state["last_observation"], str):
            raise ValueError("Invalid journal observation checkpoint")
        last = json.loads(state["last_observation"])
        if (not isinstance(last, list) or len(last) != 3 or isinstance(last[0], bool)
                or not isfinite(last[0]) or last[0] <= 0 or not isinstance(last[1], list)):
            raise ValueError("Invalid journal last observation")
        if last[2] is not None and (not isinstance(last[2], str) or len(last[2]) != 64
                                  or any(c not in "0123456789abcdef" for c in last[2])):
            raise ValueError("Invalid journal source fingerprint")
        identities = set()
        for identity, snapshot in last[1]:
            scenario = _restore_scenario(snapshot)
            if (identity != scenario.scenario_id or identity in identities or scenario.observed_at > observed
                    or identity not in tracker._states or tracker._states[identity][0] != scenario):
                raise ValueError("Conflicting last journal observation")
            identities.add(identity)
        if not isinstance(state["source_hashes"], dict):
            raise ValueError("Invalid journal source history")
        for timestamp, fingerprint in state["source_hashes"].items():
            source_time = datetime.fromisoformat(timestamp)
            aware(source_time)
            if (source_time > observed or not isinstance(fingerprint, str) or len(fingerprint) != 64
                    or any(c not in "0123456789abcdef" for c in fingerprint)):
                raise ValueError("Invalid journal source history observation")
        tracker._source_hashes = dict(state["source_hashes"])
        tracker._as_of, tracker._observation = observed, state["last_observation"]
        return tracker


def _digest(value: dict) -> str:
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _restore_scenario(value: dict) -> WaveScenario:
    if not isinstance(value, dict) or value.get("mode") != "SHADOW" or value.get("executable") is not False:
        raise ValueError("Scenario checkpoint must remain Shadow only")
    kinds = {"WAVE_3_CANDIDATE", "ABC_ZIGZAG_CANDIDATE", "WAVE_5_PENDING", "IMPULSE_1_5_COMPLETED", "THIRD_OF_THIRD_CANDIDATE"}
    if value["kind"] not in kinds or value["degree"] not in ("main", "internal"):
        raise ValueError("Unknown wave scenario model")
    points = tuple(Pivot(p["index"], p["price"], p["kind"], datetime.fromisoformat(p["timestamp"]),
                         datetime.fromisoformat(p["confirmed_at"]), p["confirmed_index"]) for p in value["points"])
    if not 4 <= len(points) <= 6 or not alternating(points) or len(value["labels"]) != len(points):
        raise ValueError("Invalid wave checkpoint points")
    if any(isinstance(n, bool) or not isfinite(n) or n <= 0 for n in (value["invalidation"], value["activation"], *value["targets"])):
        raise ValueError("Invalid wave checkpoint levels")
    if not isfinite(value["evidence_score"]) or not 0 <= value["evidence_score"] <= 1:
        raise ValueError("Invalid wave evidence score")
    scenario = _scenario(value["kind"], value["degree"], points, tuple(value["labels"]), value["invalidation"],
                         value["activation"], tuple(value["targets"]), value["evidence_score"], value["parent_id"])
    observed = datetime.fromisoformat(value["observed_at"])
    aware(observed)
    if observed < scenario.observed_at:
        raise ValueError("Wave was observed before pivot confirmation")
    scenario = WaveScenario(**{**scenario.__dict__, "observed_at": observed})
    if scenario.to_dict() != value:
        raise ValueError("Wave checkpoint identity or schema mismatch")
    return scenario
