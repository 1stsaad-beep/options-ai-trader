"""RC2 failure-injection regressions. Every account and quote is synthetic.

Existing suites cover the ordinary exit/risk paths. These cases compose durable
recovery, both reversal directions, and unexpected risk-supervisor failures.
"""
import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from app.automation import fixture_quotes, run_account
from app.lifecycle import advance_reversal, request_reversal
from app.repository import Repository
from app.service import Rejected, TradingService
from app.worker import fixture_bars


class DurableWorld:
    def __init__(self, path):
        self.url = "sqlite:///" + str(path)
        self.time = datetime(2026, 10, 9, 14, tzinfo=timezone.utc)
        self.reopen()
        self.account = self.service.create_account("recovery", 3_000_000)["id"]
        self.service.watch(self.account, "NVDA", True)
        self.service.configure(self.account, {"commission_cents": 65})

    def reopen(self):
        if hasattr(self, "repo"):
            self.repo.close()
        self.repo = Repository(self.url)
        self.service = TradingService(self.repo, now=lambda: self.time, today=lambda: self.time.date())

    def bars(self, right):
        bars = fixture_bars("NVDA", self.time)
        return bars if right == "CALL" else [
            replace(b, open=300-b.open, high=300-b.low, low=300-b.high, close=300-b.close)
            for b in bars
        ]

    def quotes(self):
        return fixture_quotes("NVDA", self.time)

    def request(self, key="entry", right="CALL", **changes):
        return {"request_key": key, "symbol": "NVDA", "right": right,
                "expiry": self.quotes()[0].expiry.isoformat(), "strike_cents": 10000,
                "side": "BUY", "quantity": 1, "limit_cents": 105} | changes

    def mark(self, right="CALL"):
        q = next(q for q in self.quotes() if q.right == right)
        with self.repo.transaction() as db:
            self.service.record_option_mark(db, self.account, q.symbol, q.right,
                                            q.expiry.isoformat(), round(q.strike*100),
                                            100, 105, self.time)

    def own(self, right="CALL", quantity=1):
        order = self.service.submit(self.account, self.request(right=right, quantity=quantity))
        self.service.fill(self.account, order["id"], "entry-fill", quantity, 105)
        self.mark(right)
        return order


@pytest.fixture
def durable(tmp_path):
    world = DurableWorld(tmp_path / "rc2-safety.db")
    yield world
    world.repo.close()


@pytest.mark.parametrize("old_right,new_right", [("CALL", "PUT"), ("PUT", "CALL")])
def test_reversal_both_directions_restart_partial_close_lost_reply_and_fees(durable, old_right, new_right):
    w = durable
    w.own(old_right, 2)
    other = w.service.create_account("unrelated", 3_000_000)["id"]
    w.service.watch(other, "NVDA", True)
    untouched = {table: w.service.rows(other, table) for table in
                 ("orders", "positions", "lifecycle_intents", "decision_snapshots")}
    intent = request_reversal(w.service, w.account, "reverse", "NVDA", new_right,
                              w.bars(new_right), w.quotes())
    close_id = json.loads(intent["payload"])["close_order_ids"][0]
    w.service.fill(w.account, close_id, "close-partial", 1, 100)
    assert advance_reversal(w.service, w.account, intent["id"], w.bars(new_right), w.quotes())["state"] == "WAIT_FLAT"
    assert len(w.service.rows(w.account, "orders")) == 2
    # The receipt was committed but the caller lost its response and the
    # process ended. Neither a retry nor restart proves the account is flat.
    w.reopen()
    assert request_reversal(w.service, w.account, "reverse", "NVDA", new_right, [], [])["id"] == intent["id"]
    assert w.service.fill(w.account, close_id, "close-partial", 1, 100)["filled"] == 1
    with pytest.raises(Rejected, match="trusted"):
        advance_reversal(w.service, w.account, intent["id"], w.bars(new_right), w.quotes())
    with pytest.raises(Rejected):
        w.service.fill(w.account, close_id, "untrusted-remainder", 1, 100)
    w.service.reconcile(w.account)
    w.service.mock_market_data(w.account, "NVDA")
    with pytest.raises(Rejected):
        w.service.submit(w.account, w.request("premature-opposite", new_right))
    w.service.fill(w.account, close_id, "close-remainder", 1, 100)
    assert not w.service.rows(w.account, "positions")
    assert w.service.performance(w.account)["realized_pnl_cents"] == -1260
    # Changing commission after acceptance must not rewrite the closing fee.
    w.service.configure(w.account, {"commission_cents": 75})
    advanced = advance_reversal(w.service, w.account, intent["id"], w.bars(new_right), w.quotes())
    assert advanced["state"] == "WAIT_ENTRY"
    assert advance_reversal(w.service, w.account, intent["id"], w.bars(new_right), w.quotes())["order_id"] == advanced["order_id"]
    w.service.fill(w.account, advanced["order_id"], "opposite-fill", 1, 105)
    assert advance_reversal(w.service, w.account, intent["id"], w.bars(new_right), w.quotes())["state"] == "COMPLETE"
    position = w.service.rows(w.account, "positions")[0]
    assert (position["right_kind"], position["quantity"], position["cost"]) == (new_right, 1, 10575)
    assert len(w.service.rows(w.account, "orders")) == 3
    assert w.service.reconcile(w.account)["resubmitted"] == 0
    assert {table: w.service.rows(other, table) for table in untouched} == untouched


@pytest.mark.parametrize("stage", ["submit", "fill"])
def test_unexpected_risk_failure_blocks_manual_new_exposure_atomically(durable, monkeypatch, stage):
    w = durable
    order = w.service.submit(w.account, w.request()) if stage == "fill" else None

    def unavailable(*args, **kwargs):
        raise RuntimeError("injected supervisor outage")

    monkeypatch.setattr(TradingService, "_check_supervisor", unavailable)
    with pytest.raises(RuntimeError, match="injected supervisor outage"):
        if order:
            w.service.fill(w.account, order["id"], "not-applied", 1, 105)
        else:
            w.service.submit(w.account, w.request())
    assert not w.service.rows(w.account, "positions")
    orders = w.service.rows(w.account, "orders")
    assert len(orders) == (1 if order else 0)
    assert all(o["filled"] == 0 for o in orders)
    with w.repo.transaction() as db:
        assert db.one("SELECT COUNT(*) AS n FROM fills")["n"] == 0


@pytest.mark.parametrize("pending", [False, True])
def test_risk_exception_cannot_create_or_fill_automatic_entry(durable, monkeypatch, pending):
    w = durable
    w.service.configure(w.account, {"automation_enabled": True, "auto_quantity": 2})
    if pending:
        result = run_account(w.service, w.account)
        assert result["fills_applied"] == 1
        w.time += timedelta(seconds=1)
        w.mark()
    before_orders = w.service.rows(w.account, "orders")
    before_positions = w.service.rows(w.account, "positions")

    def unavailable(*args, **kwargs):
        raise RuntimeError("injected risk outage; no fallback authorization")

    monkeypatch.setattr(TradingService, "_check_supervisor", unavailable)
    result = run_account(w.service, w.account)
    assert result["blocked_reasons"]
    assert result["orders_submitted"] == result["fills_applied"] == 0
    assert w.service.rows(w.account, "orders") == before_orders
    assert w.service.rows(w.account, "positions") == before_positions


@pytest.mark.parametrize("automatic", [False, True])
def test_owned_close_survives_risk_outage_and_cancels_uncheckable_pending_buys(durable, monkeypatch, automatic):
    w = durable
    w.own()
    other = w.service.create_account("pending-risk", 3_000_000)["id"]
    w.service.watch(other, "NVDA", True)
    pending = w.service.submit(other, w.request("other-pending", "PUT"))
    close = None
    if automatic:
        w.service.configure(w.account, {"automation_enabled": True})
    else:
        close = w.service.submit(w.account, w.request("manual-close", side="SELL_TO_CLOSE", limit_cents=100))

    def unavailable(*args, **kwargs):
        raise RuntimeError("private diagnostic must not enter public audit")

    monkeypatch.setattr(TradingService, "_check_supervisor", unavailable)
    if automatic:
        result = run_account(w.service, w.account, quote_feed=lambda symbol, now: [
            replace(q, bid=.70, ask=.73) for q in fixture_quotes(symbol, now)
        ])
        assert result["orders_submitted"] == result["fills_applied"] == 1
        assert not result["blocked_reasons"]
        filled = next(o for o in w.service.rows(w.account, "orders") if o["side"] == "SELL_TO_CLOSE")
    else:
        filled = w.service.fill(w.account, close["id"], "owned-close", 1, 100)
    assert filled["status"] == "FILLED"
    assert not w.service.rows(w.account, "positions")
    expected_pnl = -3630 if automatic else -630
    assert w.service.performance(w.account)["realized_pnl_cents"] == expected_pnl
    other_order = next(o for o in w.service.rows(other, "orders") if o["id"] == pending["id"])
    assert other_order["status"] == "CANCELLED" and other_order["filled"] == 0
    assert not w.service.rows(other, "positions")
    with w.repo.transaction() as db:
        audits = db.all("SELECT * FROM audit WHERE account_id=?", (other,))
        serialized = json.dumps(audits)
        assert "RISK_PENDING_BUYS_CANCELLED" in serialized
        assert "private diagnostic" not in serialized
    if not automatic:
        assert w.service.fill(w.account, close["id"], "owned-close", 1, 100)["status"] == "FILLED"
    with pytest.raises(Rejected):
        w.service.submit(w.account, w.request("unowned-close", side="SELL_TO_CLOSE", limit_cents=100))
    with pytest.raises(RuntimeError):
        w.service.submit(w.account, w.request("outage-new-exposure"))
    assert w.service.performance(w.account)["realized_pnl_cents"] == expected_pnl
