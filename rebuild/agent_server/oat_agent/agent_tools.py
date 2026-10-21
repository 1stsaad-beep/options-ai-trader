"""The strong model's tools (spec §4). Data tools pass through ToolBox (recorded for the decision snapshot); trading
tools go only through the Executor (all guards). The model cannot change owner settings, enable trading, or reach the
broker any other way."""
from __future__ import annotations
import datetime as dt
import json
from . import alerts as AL, nyse
from .atlas_client import AtlasError, dec, validate_journal
from .models import Contract, EntryRequest
from .prompts import PROMPT_VERSION


def _obj(props, req):
    return {"type": "object", "properties": props, "required": req, "additionalProperties": False}


S, N, I, B = {"type": "string"}, {"type": "number"}, {"type": "integer"}, {"type": "boolean"}
TOOL_SCHEMAS = [
    {"name": "get_bars", "description": "Completed SIP bars (regular session unless ext_hours). tf: 1m 5m 15m 1h 1d 1w 1M.",
     "input_schema": _obj({"sym": S, "tf": S, "n": I, "ext_hours": B}, ["sym", "tf"])},
    {"name": "get_indicators", "description": "Indicators computed in code: rsi macd bollinger keltner atr adx sma20 sma50 sma200 ema20 ema50 ema200 vwap avwap volume_profile rvol rs_spy rs_qqq. avwap needs anchor (ISO time).",
     "input_schema": _obj({"sym": S, "tf": S, "names": {"type": "array", "items": S}, "anchor": S}, ["sym", "tf", "names"])},
    {"name": "get_quote", "description": "Last trade with its age in seconds, bid/ask, day high/low, VWAP.", "input_schema": _obj({"sym": S}, ["sym"])},
    {"name": "get_chain", "description": "OPRA chain for expiries (YYYY-MM-DD): bid/ask, IV, greeks, OI, volume, straddle-implied move.",
     "input_schema": _obj({"sym": S, "expiries": {"type": "array", "items": S}}, ["sym", "expiries"])},
    {"name": "expected_range", "description": "ER3 15m (proven) and BV1 1h (calibrated): SIZE only, not direction.", "input_schema": _obj({"sym": S}, ["sym"])},
    {"name": "check_target", "description": "Is this price a normal move within ~1h / today / ~2 sessions, or outside? Uses ER3/BV1 only.",
     "input_schema": _obj({"sym": S, "price": N}, ["sym", "price"])},
    {"name": "get_events", "description": "Earnings / CPI / FOMC dates near the trade (dates only).", "input_schema": _obj({"sym": S, "days": I}, ["sym"])},
    {"name": "tradable_today", "description": "Which universe symbols have an expiry today or next session (from the real chain).", "input_schema": _obj({}, [])},
    {"name": "get_positions", "description": "Account equity, open positions with their thesis id and invalidation, working orders, today's guard counters.",
     "input_schema": _obj({}, [])},
    {"name": "journal_write", "description": "Write the thesis BEFORE an order (spec §8). Returns journal_id. Prices as numbers.",
     "input_schema": _obj({"sym": S, "scenarios": {"type": "array", "items": {"type": "object"}}, "events_near": {"type": "array", "items": {"type": "object"}},
                           "contract": {"type": "object"}, "entry_plan": {"type": "object"}, "invalidation_level": N, "exit_plan": {"type": "object"},
                           "expected_option_value_at_target": N, "confidence_note": S},
                          ["sym", "scenarios", "contract", "entry_plan", "invalidation_level", "exit_plan", "expected_option_value_at_target", "confidence_note"])},
    {"name": "journal_read", "description": "Read a thesis/outcome by journal_id, or the most recent entries.", "input_schema": _obj({"journal_id": S, "limit": I}, [])},
    {"name": "place_order", "description": "Buy-to-open LIMIT order for a thesis already written. All guards apply.",
     "input_schema": _obj({"journal_id": S, "occ_symbol": S, "qty": I, "limit": N}, ["journal_id", "occ_symbol", "qty", "limit"])},
    {"name": "modify", "description": "Cancel a working entry order and re-place it at a new limit (guards apply again).",
     "input_schema": _obj({"order_id": S, "limit": N}, ["order_id", "limit"])},
    {"name": "close", "description": "Discretionary exit of an open position (sell at the bid).", "input_schema": _obj({"occ_symbol": S, "reason": S}, ["occ_symbol", "reason"])},
    {"name": "set_alert", "description": "Alert evaluated in code: '<1m|5m|15m|1h> close <op> <price>' or 'last <op> <price>'.",
     "input_schema": _obj({"sym": S, "condition": S, "note": S}, ["sym", "condition"])},
    {"name": "dossier_read", "description": "Per-stock dossier: code statistics + your own notes.", "input_schema": _obj({"sym": S}, ["sym"])},
    {"name": "dossier_write", "description": "Add a short note to a stock's dossier (your wave counts, what worked).",
     "input_schema": _obj({"sym": S, "note": S, "tags": {"type": "array", "items": S}}, ["sym", "note"])},
    {"name": "hypothesis_add", "description": "Record a candidate repeatable setup for the research pipeline (never changes app rules).",
     "input_schema": _obj({"name": S, "description": S, "journal_ids": {"type": "array", "items": S}}, ["name", "description"])},
]
DATA_TOOLS = {"get_bars", "get_indicators", "get_quote", "get_chain", "expected_range", "check_target", "get_events", "tradable_today"}


class AgentTools:
    def __init__(self, toolbox, executor, store, outbox, dossiers, clock, model_id):
        self.tb, self.x, self.store, self.outbox, self.dos, self.clock = toolbox, executor, store, outbox, dossiers, clock
        self.model_id = model_id
        self.touched = set()           # journal ids written/used in this session (snapshot links)
        self.last_quote_age = None

    def call(self, name, args):
        if name in DATA_TOOLS:
            r = self.tb.call(name, args)
            if name == "get_quote": self.last_quote_age = r.get("last_age_s")
            return r
        return getattr(self, "_" + name)(**args)

    # ---------------------------------------------------------------- read-only state
    def _get_positions(self):
        now, acct, st = self.x.snapshot()
        pos = []
        for p in self.x.broker.positions():
            m = self.store.meta(p.contract.occ) or {}
            pos.append(dict(occ=p.contract.occ, qty=p.qty, avg_price=p.avg_price, journal_id=m.get("journal_id"),
                            invalidation=m.get("invalidation")))
        return dict(equity=acct["equity"], positions=pos, working_orders=[dict(id=o.id, occ=o.contract.occ, side=o.side, limit=o.limit)
                                                                          for o in self.x.broker.open_orders()],
                    orders_today=st.orders_today, paused=st.paused, month_spend_usd=round(self.x.cost.month_spend(now), 2),
                    monthly_cap_usd=self.x.s.monthly_cap_usd)

    # ---------------------------------------------------------------- journal
    def _journal_write(self, sym, scenarios, contract, entry_plan, invalidation_level, exit_plan,
                       expected_option_value_at_target, confidence_note, events_near=None):
        now = self.clock()
        import uuid
        jid = f"J{now:%Y%m%d%H%M%S}-{uuid.uuid4().hex[:8]}"
        er3 = self.tb.size.expected_range(sym) if self.tb.size else {}
        body = dict(journal_id=jid, ts=now.strftime("%Y-%m-%dT%H:%M:%SZ"), sym=sym, model_id=self.model_id,
                    prompt_version=PROMPT_VERSION, data_age_s=self.last_quote_age, scenarios=_decify(scenarios),
                    er3=er3.get("er3", {"available": False}), bv1=er3.get("bv1", {"available": False}),
                    events_near=events_near or [], contract=_decify(contract), entry_plan=_decify(entry_plan),
                    invalidation_level=dec(invalidation_level), exit_plan=_decify(exit_plan),
                    expected_option_value_at_target=dec(expected_option_value_at_target), confidence_note=confidence_note)
        try:
            validate_journal("thesis", body)
        except AtlasError as e:
            return {"ok": False, "error": str(e)}
        self.store.journal_add(now, "thesis", body, sym=sym, jid=jid)
        self.outbox.enqueue("thesis", body)
        self.touched.add(jid)
        return {"ok": True, "journal_id": jid}

    def _journal_read(self, journal_id=None, limit=10):
        rows = self.store.journal(limit=500 if journal_id else int(limit))
        return [r for r in rows if journal_id is None or r["id"] == journal_id or r["body"].get("journal_id") == journal_id][:max(1, int(limit))]

    # ---------------------------------------------------------------- trading (executor only)
    def _enabled(self):
        return bool(self.store.get("agent_enabled", False))

    def _place_order(self, journal_id, occ_symbol, qty, limit):
        if not self._enabled(): return {"ok": False, "codes": ["AGENT_NOT_ENABLED"], "reason_ar": "التداول التجريبي لم يُفعَّل من المالك"}
        thesis = next((r for r in self.store.journal(500) if r["id"] == journal_id and r["kind"] == "thesis"), None)
        if thesis is None: return {"ok": False, "codes": ["NO_JOURNAL"], "reason_ar": "لا توجد أطروحة بهذا الرقم — اكتبها أولًا"}
        if thesis["body"]["contract"].get("occ_symbol") not in (None, occ_symbol):
            return {"ok": False, "codes": ["CONTRACT_MISMATCH"], "reason_ar": "العقد يختلف عن عقد الأطروحة"}
        try:
            c = Contract.from_occ(occ_symbol)
        except Exception:  # noqa: BLE001
            return {"ok": False, "codes": ["BAD_OCC"], "reason_ar": "رمز العقد غير صالح"}
        if c.underlying != thesis["body"]["sym"]:
            return {"ok": False, "codes": ["CONTRACT_MISMATCH"], "reason_ar": "السهم يختلف عن سهم الأطروحة"}
        r = self.x.enter(EntryRequest(c, int(qty), float(limit), journal_id=journal_id,
                                      invalidation=float(thesis["body"]["invalidation_level"])))
        self.touched.add(journal_id)
        return {"ok": r.ok, "codes": list(r.codes), "reasons_ar": list(r.reasons_ar), "order_id": r.order_id}

    def _modify(self, order_id, limit):
        if not self._enabled(): return {"ok": False, "codes": ["AGENT_NOT_ENABLED"]}
        o = next((o for o in self.x.broker.open_orders() if o.id == order_id and o.side == "buy_to_open"), None)
        if o is None: return {"ok": False, "codes": ["NO_SUCH_ORDER"]}
        jid = self.store.get("pending_entries", {}).get(order_id)
        self.x.broker.cancel(order_id)
        self.x.reconcile()
        if jid is None: return {"ok": False, "codes": ["NO_JOURNAL"]}
        return self._place_order(jid, o.contract.occ, o.qty, limit)

    def _close(self, occ_symbol, reason):
        p = next((p for p in self.x.broker.positions() if p.contract.occ == occ_symbol), None)
        if p is None: return {"ok": False, "codes": ["NO_POSITION"]}
        r = self.x.exit(p, "DISCRETIONARY", str(reason)[:300])
        return {"ok": r.ok, "codes": list(r.codes), "order_id": r.order_id}

    # ---------------------------------------------------------------- alerts / dossiers / hypotheses
    def _set_alert(self, sym, condition, note=""):
        try:
            AL.parse(condition)
        except ValueError as e:
            return {"ok": False, "error": str(e)}
        return {"ok": True, "alert_id": self.store.alert_add(self.clock(), sym, condition, note)}

    def _dossier_read(self, sym):
        return self.dos.read(sym)

    def _dossier_write(self, sym, note, tags=None):
        self.dos.write_notes(sym, self.clock(), note, tags)
        return {"ok": True}

    def _hypothesis_add(self, name, description, journal_ids=None):
        hs = self.store.get("hypotheses", [])
        hs.append(dict(t=self.clock().isoformat(), name=name, description=description, journal_ids=journal_ids or [],
                       status="candidate (ATLAS pipeline: STRATEGY_SPEC -> registered study -> paper -> owner)"))
        self.store.put("hypotheses", hs)
        self.store.event(self.clock(), "hypothesis_add", {"name": name})
        return {"ok": True, "count": len(hs)}


def _decify(x):
    """Numbers -> decimal strings (ATLAS contract: prices as decimal strings), recursively; other values unchanged."""
    if isinstance(x, bool) or x is None: return x
    if isinstance(x, (int, float)): return dec(x)
    if isinstance(x, list): return [_decify(v) for v in x]
    if isinstance(x, dict): return {k: _decify(v) for k, v in x.items()}
    return x
