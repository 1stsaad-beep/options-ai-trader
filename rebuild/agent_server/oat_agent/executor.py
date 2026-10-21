"""Executor: the ONLY path to the broker. Entries pass every guard (guards.py) on freshly fetched broker state;
exits are blocked only by market hours. The model never calls the broker directly."""
from __future__ import annotations
import datetime as dt
import logging
from dataclasses import dataclass
from . import guards, nyse
from .config import OwnerSettings
from .costs import CostCap
from .models import EntryRequest, Position

log = logging.getLogger("oat.executor")


@dataclass(frozen=True)
class Result:
    ok: bool
    codes: tuple = ()
    reasons_ar: tuple = ()
    order_id: str | None = None


class Executor:
    def __init__(self, broker, store, settings: OwnerSettings, clock, gate: nyse.MarketHoursGate | None = None):
        self.broker, self.store, self.s, self.clock = broker, store, settings, clock
        self.gate = gate or nyse.MarketHoursGate(getattr(broker, "clock", None))
        self.cost = CostCap(store, settings.monthly_cap_usd)

    # ------------------------------------------------------------------ state
    def snapshot(self):
        now = self.clock()
        acct = self.broker.account()
        st = self.store.guard_state()
        guards.on_snapshot(st, now, acct["equity"])
        self.store.save_guard_state(st)
        return now, acct, st

    def status(self, now):
        return self.gate.status(now)

    # ------------------------------------------------------------------ entry
    def enter(self, req: EntryRequest) -> Result:
        now, acct, st = self.snapshot()
        positions, orders = self.broker.positions(), self.broker.open_orders()
        try:
            px, pts = self.broker.stock_last(req.contract.underlying)
        except Exception:  # noqa: BLE001 — no price = no entry
            px, pts = None, None
        try:
            q = self.broker.option_quote(req.contract)
        except Exception:  # noqa: BLE001
            q = None
        v = guards.check_entry(req, now=now, status=self.status(now), settings=self.s, st=st, equity=acct["equity"],
                               positions=positions, orders=orders, underlying_price=px, underlying_ts=pts, option_quote=q,
                               month_spend_usd=self.cost.month_spend(now), journal_exists=self.store.journal_exists)
        if not v.allowed:
            self.store.event(now, "entry_blocked", dict(occ=req.contract.occ, codes=v.codes, reasons=[r for _, r in v.reasons],
                                                         journal_id=req.journal_id), sym=req.contract.underlying)
            return Result(False, tuple(v.codes), tuple(r for _, r in v.reasons))
        # last-line re-check of the direction lock on fresh broker state (Dart _enter does the same)
        lock = guards.direction_lock(req.contract.underlying, req.contract.right, self.broker.positions(), self.broker.open_orders())
        if lock:
            self.store.event(now, "entry_blocked", dict(occ=req.contract.occ, codes=["LOCK"], reasons=[lock]), sym=req.contract.underlying)
            return Result(False, ("LOCK",), (lock,))
        o = self.broker.place(req.contract, "buy_to_open", req.qty, req.limit, client_id=f"oat-{req.journal_id}"[:48])
        guards.record_submission(st, now, req.contract.underlying, opening=True)
        self.store.save_guard_state(st)
        self.store.meta_put(req.contract.occ, req.contract.underlying, req.journal_id, req.invalidation, now,
                            dict(limit=req.limit, qty=req.qty, bid=q.bid, ask=q.ask, underlying=px))
        self.store.event(now, "entry_submitted", dict(occ=req.contract.occ, qty=req.qty, limit=req.limit, order_id=o.id,
                                                       status=o.status, journal_id=req.journal_id, invalidation=req.invalidation),
                         sym=req.contract.underlying)
        return Result(True, order_id=o.id)

    # ------------------------------------------------------------------ exit
    def exit(self, position: Position, reason_code: str, reason_ar: str) -> Result:
        now = self.clock()
        v = guards.check_exit(status=self.status(now))
        if not v.allowed:
            return Result(False, tuple(v.codes), tuple(r for _, r in v.reasons))
        if any(o.contract == position.contract and o.side == "sell_to_close" for o in self.broker.open_orders()):
            return Result(False, ("EXIT_WORKING",), ("أمر خروج قائم بالفعل",))
        q = self.broker.option_quote(position.contract)
        if q is None or not q.bid:
            self.store.event(now, "exit_no_bid", dict(occ=position.contract.occ, reason=reason_code), sym=position.contract.underlying)
            return Result(False, ("NO_BID",), ("لا يوجد سعر شراء للعقد — إعادة المحاولة في الدورة التالية",))
        meta = self.store.meta(position.contract.occ) or {}
        o = self.broker.place(position.contract, "sell_to_close", position.qty, q.bid,
                              client_id=f"oat-x-{meta.get('journal_id', 'na')}-{reason_code}"[:48])
        st = self.store.guard_state()
        guards.record_submission(st, now, position.contract.underlying, opening=False)
        self.store.save_guard_state(st)
        self.store.event(now, "exit_submitted", dict(occ=position.contract.occ, qty=position.qty, limit=q.bid, order_id=o.id,
                                                      status=o.status, reason=reason_code, reason_ar=reason_ar,
                                                      journal_id=meta.get("journal_id")), sym=position.contract.underlying)
        return Result(True, order_id=o.id)
