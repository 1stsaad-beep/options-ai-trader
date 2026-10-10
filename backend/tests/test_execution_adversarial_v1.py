"""Independent V1 risk/lifecycle adversarial review (synthetic Mock only)."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
import sqlite3

import pytest

from app.automation import fixture_quotes, run_account
from app.lifecycle import request_scaling
from app.repository import Repository
from app.service import Rejected, TradingService
from app.worker import fixture_bars


@pytest.fixture
def isolated():
    class World:
        time = datetime(2026, 10, 9, 14, tzinfo=timezone.utc)

        def __init__(self):
            self.repo = Repository()
            self.service = TradingService(self.repo, now=lambda: self.time, today=lambda: self.time.date())
            self.account = self.service.create_account("adversarial", 1_000_000)["id"]
            self.service.watch(self.account, "NVDA", True)

        def quotes(self, bid=1., ask=1.05):
            return [replace(q, bid=bid, ask=ask) for q in fixture_quotes("NVDA", self.time)]

        def request(self, key="entry", **changes):
            q = self.quotes()[0]
            return {"request_key": key, "symbol": "NVDA", "right": "CALL",
                    "expiry": q.expiry.isoformat(), "strike_cents": 10000,
                    "side": "BUY", "quantity": 1, "limit_cents": 105} | changes

        def own(self, quantity=1):
            order = self.service.submit(self.account, self.request(quantity=quantity))
            self.service.fill(self.account, order["id"], "initial-fill", quantity, 105)
            return order

        def mark(self, bid=100, ask=105):
            q = self.quotes()[0]
            with self.repo.transaction() as db:
                self.service.record_option_mark(db, self.account, "NVDA", "CALL", q.expiry.isoformat(),
                                                10000, bid, ask, self.time)

        def advance(self, seconds=1):
            self.time += timedelta(seconds=seconds)
            self.service.reconcile(self.account)
            self.service.mock_market_data(self.account, "NVDA")

        def bars(self, right="CALL"):
            bars = fixture_bars("NVDA", self.time)
            return bars if right == "CALL" else [replace(b, open=300-b.open, high=300-b.low,
                                                          low=300-b.high, close=300-b.close) for b in bars]

    world = World()
    yield world
    world.repo.close()


def test_missing_owned_marks_cannot_be_counted_as_zero_open_loss(isolated):
    w = isolated
    w.own()
    w.service.configure(w.account, {"daily_loss_pct": 1})
    # Potential full-premium loss 10,500 cents is above the 10,000-cent daily
    # limit. Unknown current value cannot silently become zero open loss.
    with pytest.raises(Rejected):
        w.service.submit(w.account, w.request("unknown-loss", strike_cents=10100))
    assert len(w.service.rows(w.account, "orders")) == 1


def test_stale_loss_mark_cannot_reopen_risk_gate(isolated):
    w = isolated
    w.own()
    w.service.configure(w.account, {"daily_loss_pct": 1})
    w.mark(1, 5)
    with pytest.raises(Rejected):
        w.service.submit(w.account, w.request("fresh-loss", strike_cents=10100))
    # Account and stock observation remain trusted; only the option loss mark
    # expires. A stale loss must not remove its blocking effect.
    w.advance(61)
    with pytest.raises(Rejected):
        w.service.submit(w.account, w.request("stale-loss", strike_cents=10100))


def test_recent_mark_does_not_override_owned_market_feed_outage(isolated):
    w = isolated
    w.own()
    w.mark()
    w.service.mock_market_data(w.account, "NVDA", available=False)
    w.service.watch(w.account, "AAPL", True)
    # AAPL's feed is fresh, but the account's owned NVDA valuation has become
    # untrustworthy. A recently cached mark must not conceal the outage.
    with pytest.raises(Rejected):
        w.service.submit(w.account, w.request("different-stock-outage", symbol="AAPL", strike_cents=20000))


def test_scaling_requires_profit_after_close_commission(isolated):
    w = isolated
    w.service.configure(w.account, {"commission_cents": 1000, "scaling_enabled": True})
    w.own()
    # Cost=11,500; gross bid=12,000; after 1,000 closing fee=11,000.
    # Position is still losing 500 cents, so it is not eligible for profitable scaling.
    with pytest.raises(Rejected, match="profit"):
        request_scaling(w.service, w.account, "net-loser-scale", "NVDA", "CALL", w.bars(), w.quotes(1.20, 1.25))
    assert len(w.service.rows(w.account, "orders")) == 1


def test_reversal_repriced_close_can_complete_without_ignoring_old_remainder(isolated):
    w = isolated
    w.service.configure(w.account, {"trade_risk_pct": 10, "elevated_risk_ack": True,
                                     "automation_enabled": True, "reversal_enabled": True})
    w.own(2)
    feed = lambda symbol, now: w.bars("PUT")
    run_account(w.service, w.account, feed=feed, quote_feed=lambda symbol, now: w.quotes())
    assert w.service.rows(w.account, "positions")[0]["quantity"] == 1
    w.advance()
    run_account(w.service, w.account, feed=feed, quote_feed=lambda symbol, now: w.quotes(.90, .95))
    assert not w.service.rows(w.account, "positions")
    intent = w.service.rows(w.account, "lifecycle_intents")[0]
    assert intent["state"] == "WAIT_ENTRY"
    orders = w.service.rows(w.account, "orders")
    assert sum(o["filled"] for o in orders if o["side"] == "SELL_TO_CLOSE") == 2
    assert sum(o["side"] == "BUY" and o["right_kind"] == "PUT" for o in orders) == 1


def test_decision_reference_cannot_cross_account(isolated):
    w = isolated
    order = w.service.submit(w.account, w.request())
    other = w.service.create_account("other", 1_000_000)["id"]
    with pytest.raises((Rejected, sqlite3.IntegrityError)):
        with w.repo.transaction() as db:
            w.service.decision(db, other, "ORDER_ACCEPTED", {"reason": "wrong account"}, order["id"])
    assert not w.service.rows(other, "decision_snapshots")


def test_pending_fees_survive_commission_configuration_change(isolated):
    w = isolated
    w.service.configure(w.account, {"commission_cents": 1000, "allocation_pct": 2})
    first = w.service.submit(w.account, w.request(limit_cents=95))
    w.service.configure(w.account, {"commission_cents": 0})
    # Prior reservation stays 9,500+1,000, leaving only 9,500 of the 20,000
    # allocation. A new 10,000-cent contract must still fail.
    with pytest.raises(Rejected, match="allocation"):
        w.service.submit(w.account, w.request("second", strike_cents=10100, limit_cents=100))
    w.service.fill(w.account, first["id"], "first-fee-fill", 1, 95)
    assert w.service.rows(w.account, "positions")[0]["cost"] == 10500
    assert w.service.reconcile(w.account)["state_known"]


@pytest.mark.parametrize("reduction", [{"allocation_pct": 0}, {"trade_risk_pct": 0},
                                       {"global_allocation_pct": 0}, {"max_contract_premium_cents": 10499}])
def test_lowered_risk_is_rechecked_before_pending_fill(isolated, reduction):
    w = isolated
    order = w.service.submit(w.account, w.request())
    w.service.configure(w.account, reduction)
    with pytest.raises(Rejected):
        w.service.fill(w.account, order["id"], "blocked-fill", 1, 105)
    assert not w.service.rows(w.account, "positions")


def test_duplicate_receipt_after_disconnect_does_not_resubmit_or_mutate(isolated):
    w = isolated
    request = w.request()
    order = w.service.submit(w.account, request)
    w.service.disconnect(w.account)
    assert w.service.submit(w.account, request)["id"] == order["id"]
    assert len(w.service.rows(w.account, "orders")) == 1
    with pytest.raises(Rejected, match="unknown"):
        w.service.submit(w.account, w.request("different"))
    with pytest.raises(Rejected):
        w.service.fill(w.account, order["id"], "not-reconciled", 1, 105)
    assert not w.service.rows(w.account, "positions")


def test_same_fill_id_cannot_credit_different_account(isolated):
    w = isolated
    first = w.own()
    w.mark()
    other = w.service.create_account("other", 1_000_000)["id"]
    w.service.watch(other, "NVDA", True)
    second = w.service.submit(other, w.request())
    with pytest.raises(Rejected, match="collision"):
        w.service.fill(other, second["id"], "initial-fill", 1, 105)
    assert not w.service.rows(other, "positions")
    assert w.service.rows(w.account, "positions")[0]["quantity"] == 1
    assert w.service.submit(w.account, w.request())["id"] == first["id"]


def test_mark_safety_cannot_be_disabled_by_account_configuration(isolated):
    with pytest.raises(Rejected):
        isolated.service.configure(isolated.account, {"require_open_loss_marks": False})


def test_scaling_profitability_is_rechecked_after_close_fee_changes(isolated):
    w = isolated
    w.service.configure(w.account, {"scaling_enabled": True})
    w.own()
    intent = request_scaling(w.service, w.account, "initially-profitable", "NVDA", "CALL",
                             w.bars(), w.quotes(1.2, 1.25))
    # Owned cost is 10,500; a closing fee of 2,000 turns 12,000 gross value
    # into a loss. Its previously accepted scaling BUY must not fill now.
    w.service.configure(w.account, {"commission_cents": 2000})
    with pytest.raises(Rejected, match="profit"):
        w.service.fill(w.account, intent["order_id"], "late-scale-fill", 1, 125)
    assert w.service.rows(w.account, "positions")[0]["quantity"] == 1


def test_pending_close_fee_cannot_disappear_from_open_loss_after_config_change(isolated):
    w = isolated
    w.service.configure(w.account, {"commission_cents": 1000, "daily_loss_pct": 1})
    w.own()
    w.mark(20, 25)
    w.service.submit(w.account, w.request("already-priced-close", side="SELL_TO_CLOSE", limit_cents=20))
    # The closing order retains its 1,000-cent commission even after the next
    # order's fee is set to zero. Net liquidation loss remains 10,500 > 10,000.
    w.service.configure(w.account, {"commission_cents": 0})
    with pytest.raises(Rejected, match="loss"):
        w.service.submit(w.account, w.request("cannot-offset-frozen-close-fee", strike_cents=10100))


def test_database_itself_rejects_cross_account_decision_order_reference(isolated):
    w = isolated
    order = w.service.submit(w.account, w.request())
    other = w.service.create_account("other", 1_000_000)["id"]
    with pytest.raises(sqlite3.IntegrityError):
        with w.repo.transaction() as db:
            db.execute("INSERT INTO decision_snapshots VALUES(?,?,?,?,?,?,?,?)",
                       ("wrong-cross-account-snapshot", other, order["id"], None,
                        "ORDER_ACCEPTED", "{}", "invalid-digest", w.time.isoformat()))


def test_decision_intent_reference_cannot_cross_account_even_at_commit(isolated):
    w = isolated
    w.service.configure(w.account, {"scaling_enabled": True})
    w.own()
    intent = request_scaling(w.service, w.account, "legitimate", "NVDA", "CALL", w.bars(), w.quotes(1.4, 1.45))
    other = w.service.create_account("other", 1_000_000)["id"]
    with pytest.raises((Rejected, sqlite3.IntegrityError)):
        with w.repo.transaction() as db:
            w.service.decision(db, other, "SCALING_RESERVED", {}, intent_id=intent["id"])
    with pytest.raises(sqlite3.IntegrityError):
        with w.repo.transaction() as db:
            db.execute("INSERT INTO decision_snapshots VALUES(?,?,?,?,?,?,?,?)",
                       ("wrong-intent-account", other, None, intent["id"], "SCALING_RESERVED", "{}", "digest", w.time.isoformat()))
    assert not w.service.rows(other, "decision_snapshots")


def test_unknown_owned_inventory_blocks_even_emergency_close(isolated):
    w = isolated
    w.own()
    w.service.stop(w.account)
    w.service.disconnect(w.account)
    with pytest.raises(Rejected, match="unknown"):
        w.service.submit(w.account, w.request("close", side="SELL_TO_CLOSE", limit_cents=100))
    w.service.reconcile(w.account)
    assert w.service.submit(w.account, w.request("close", side="SELL_TO_CLOSE", limit_cents=100))["side"] == "SELL_TO_CLOSE"
