"""Independent V0.4 negative-path and concurrency checks, synthetic accounts only."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest

from app.repository import Repository
from app.service import Rejected, TradingService


@pytest.fixture
def review_demo():
    repo = Repository()
    clock = [datetime(2026, 10, 9, 14, tzinfo=timezone.utc)]
    service = TradingService(repo, now=lambda: clock[0], today=lambda: clock[0].date())
    a = service.create_account("review A")["id"]
    b = service.create_account("review B")["id"]
    for account in (a, b):
        service.watch(account, "AAPL", True)
        # Explicit fixture quote, independent of fills; V1 values open losses.
        with repo.transaction() as db:
            service.record_option_mark(db, account, "AAPL", "CALL", "2026-11-20", 20000, 100, 100, clock[0])
    yield repo, service, a, b, clock
    repo.close()


def request(key="review-v04", **changes):
    return dict(request_key=key, symbol="AAPL", right="CALL", expiry="2026-11-20",
                strike_cents=20000, side="BUY", quantity=2, limit_cents=100) | changes


@pytest.mark.parametrize("mode", ["shadow", "analysis"])
def test_preapproved_owned_close_cannot_fill_after_leaving_paper(review_demo, mode):
    _, service, a, _, _ = review_demo
    buy = service.submit(a, request())
    service.fill(a, buy["id"], "mode-entry", 2, 100)
    close = service.submit(a, request("mode-close", side="SELL_TO_CLOSE"))
    service.configure(a, {"mode": mode})
    with pytest.raises(Rejected):
        service.fill(a, close["id"], "after-mode", 1, 100)
    assert service.rows(a, "positions")[0]["quantity"] == 2


def test_concurrent_duplicate_submission_has_one_durable_order(review_demo):
    _, service, a, _, _ = review_demo
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: service.submit(a, request()), range(16)))
    assert len({order["id"] for order in results}) == 1
    assert len(service.rows(a, "orders")) == 1


def test_concurrent_duplicate_fill_changes_inventory_once(review_demo):
    _, service, a, _, _ = review_demo
    order = service.submit(a, request())
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: service.fill(a, order["id"], "same-fill", 1, 100), range(16)))
    assert all(result["filled"] == 1 for result in results)
    assert service.rows(a, "positions")[0]["quantity"] == 1


def test_concurrent_owned_closes_cannot_reserve_inventory_twice(review_demo):
    _, service, a, _, _ = review_demo
    order = service.submit(a, request())
    service.fill(a, order["id"], "close-entry", 2, 100)

    def reserve(index):
        try:
            return service.submit(a, request(f"reserve-{index}", side="SELL_TO_CLOSE"))
        except Rejected:
            return None

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(reserve, range(16)))
    assert sum(result is not None for result in results) == 1
    assert service.rows(a, "positions")[0]["quantity"] == 2


def test_cross_account_fill_identifier_collision_cannot_transfer_inventory(review_demo):
    _, service, a, b, _ = review_demo
    left = service.submit(a, request())
    right = service.submit(b, request())
    service.fill(a, left["id"], "shared-fill-id", 1, 100)
    with pytest.raises(Rejected, match="collision"):
        service.fill(b, right["id"], "shared-fill-id", 1, 100)
    assert service.rows(a, "positions")[0]["quantity"] == 1
    assert service.rows(b, "positions") == []


def test_replayed_close_fill_returns_receipt_without_second_realized_pnl(review_demo):
    _, service, a, _, _ = review_demo
    buy = service.submit(a, request())
    service.fill(a, buy["id"], "loss-entry", 2, 100)
    close = service.submit(a, request("loss-close", side="SELL_TO_CLOSE", limit_cents=80))
    receipt = service.fill(a, close["id"], "loss-fill", 1, 80)
    service.disconnect(a)
    assert service.fill(a, close["id"], "loss-fill", 1, 80) == receipt
    assert service.performance(a)["realized_pnl_cents"] == -2000
    assert service.rows(a, "positions")[0]["quantity"] == 1


def test_restart_preserves_partial_receipt_and_requires_explicit_reconcile(tmp_path):
    url = "sqlite:///" + str(tmp_path / "restart.sqlite")
    now = datetime(2026, 10, 9, 14, tzinfo=timezone.utc)
    repo = Repository(url)
    service = TradingService(repo, now=lambda: now, today=lambda: now.date())
    account = service.create_account("restart")['id']
    service.watch(account, "AAPL", True)
    with repo.transaction() as db:
        service.record_option_mark(db, account, "AAPL", "CALL", "2026-11-20", 20000, 100, 100, now)
    order = service.submit(account, request())
    service.fill(account, order["id"], "before-restart", 1, 100)
    repo.close()
    repo = Repository(url)
    try:
        service = TradingService(repo, now=lambda: now, today=lambda: now.date())
        assert service.submit(account, request())["filled"] == 1
        with pytest.raises(Rejected):
            service.fill(account, order["id"], "after-restart", 1, 100)
        assert service.reconcile(account)["resubmitted"] == 0
        assert service.fill(account, order["id"], "after-restart", 1, 100)["status"] == "FILLED"
        assert service.rows(account, "positions")[0]["quantity"] == 2
        assert len(service.rows(account, "orders")) == 1
    finally:
        repo.close()


@pytest.fixture
def automated_demo():
    repo = Repository()
    clock = [datetime(2026, 10, 9, 14, tzinfo=timezone.utc)]
    service = TradingService(repo, now=lambda: clock[0], today=lambda: clock[0].date())
    a = service.create_account("automated review A", equity=2000000)["id"]
    b = service.create_account("automated review B", equity=2000000)["id"]
    for account in (a, b):
        service.watch(account, "AAPL", True)
        service.configure(account, {"automation_enabled": True, "auto_quantity": 2,
                                    "auto_fill_chunk": 1, "strategies": ["breakout"]})
    yield repo, service, a, b, clock
    repo.close()


def auto_run(service, account, clock, **kwargs):
    from app.automation import run_account
    return run_account(service, account, now=clock[0], **kwargs)


def test_automatic_cycle_default_off_requires_account_opt_in(review_demo):
    _, service, a, _, clock = review_demo
    auto_run(service, a, clock)
    assert service.rows(a, "orders") == []


def test_concurrent_automatic_cycles_cannot_duplicate_signal_or_fill(automated_demo):
    _, service, a, b, clock = automated_demo
    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(lambda _: auto_run(service, a, clock), range(12)))
    orders = service.rows(a, "orders")
    assert len(orders) == 1
    assert orders[0]["side"] == "BUY"
    assert orders[0]["filled"] == 1
    assert service.rows(a, "positions")[0]["quantity"] == 1
    assert service.rows(b, "orders") == []


@pytest.mark.parametrize("offset", [-61, 1])
def test_auto_entry_rejects_stale_or_future_option_quotes(automated_demo, offset):
    from dataclasses import replace
    from app.automation import fixture_quotes
    _, service, a, _, clock = automated_demo

    def malformed(symbol, now):
        return [replace(q, timestamp=now+timedelta(seconds=offset)) for q in fixture_quotes(symbol, now)]

    auto_run(service, a, clock, quote_feed=malformed)
    assert service.rows(a, "orders") == []


def test_auto_entry_rejects_ambiguous_contract_quote(automated_demo):
    from dataclasses import replace
    from app.automation import fixture_quotes
    _, service, a, _, clock = automated_demo

    def duplicate(symbol, now):
        quotes = list(fixture_quotes(symbol, now))
        return quotes + [replace(quotes[0], bid=.9, ask=.95)]

    auto_run(service, a, clock, quote_feed=duplicate)
    assert service.rows(a, "orders") == []


def test_disconnected_automatic_cycle_never_self_reconciles(automated_demo):
    _, service, a, _, clock = automated_demo
    auto_run(service, a, clock)
    service.disconnect(a)
    clock[0] += timedelta(seconds=1)
    auto_run(service, a, clock)
    assert service.status(a)["state_known"] is False
    assert service.rows(a, "orders")[0]["filled"] == 1
    assert not any(row["event"] == "MOCK_RECONCILED" for row in service.rows(a, "audit")
                   if "orders" not in row["detail"])


def test_automatic_cycle_pauses_after_automation_disabled(automated_demo):
    _, service, a, _, clock = automated_demo
    auto_run(service, a, clock)
    service.configure(a, {"automation_enabled": False})
    clock[0] += timedelta(seconds=1)
    auto_run(service, a, clock)
    assert service.rows(a, "orders")[0]["filled"] == 1


def test_automatic_pending_entry_cannot_ignore_market_outage(automated_demo):
    _, service, a, _, clock = automated_demo
    auto_run(service, a, clock)
    service.mock_market_data(a, "AAPL", False)
    clock[0] += timedelta(seconds=1)
    auto_run(service, a, clock)
    assert service.rows(a, "orders")[0]["filled"] == 1


def test_automatic_cycle_detects_corrupt_inventory_before_filling(automated_demo):
    repo, service, a, _, clock = automated_demo
    auto_run(service, a, clock)
    with repo.transaction() as db:
        db.execute("UPDATE positions SET cost=cost+1 WHERE account_id=?", (a,))
    clock[0] += timedelta(seconds=1)
    auto_run(service, a, clock)
    assert service.status(a)["state_known"] is False
    assert service.rows(a, "orders")[0]["filled"] == 1


def test_stop_loss_cancels_partial_entry_before_owned_close(automated_demo):
    from dataclasses import replace
    from app.automation import fixture_quotes
    _, service, a, b, clock = automated_demo
    auto_run(service, a, clock)
    clock[0] += timedelta(seconds=1)

    def loss_quote(symbol, now):
        return [replace(q, bid=.7, ask=.75) for q in fixture_quotes(symbol, now)]

    auto_run(service, a, clock, quote_feed=loss_quote)
    orders = service.rows(a, "orders")
    entry = next(o for o in orders if o["side"] == "BUY")
    closes = [o for o in orders if o["side"] == "SELL_TO_CLOSE"]
    assert entry["status"] == "CANCELLED"
    assert entry["filled"] == 1
    assert len(closes) == 1 and closes[0]["quantity"] == 1
    assert service.rows(a, "positions") == []
    assert service.rows(b, "orders") == []
    # Same quote response is replayed; an exit does not create another entry/close.
    auto_run(service, a, clock, quote_feed=loss_quote)
    assert len(service.rows(a, "orders")) == len(orders)


def test_account_expiry_does_not_settle_another_account(review_demo):
    _, service, a, b, clock = review_demo
    for account in (a, b):
        order = service.submit(account, request())
        service.fill(account, order["id"], f"expiry-{account}", 1, 100)
    clock[0] = datetime(2026, 11, 20, 14, tzinfo=timezone.utc)
    service.reconcile(a)
    assert service.expire(account_id=a) == 1
    assert service.rows(a, "positions") == []
    assert service.rows(b, "positions")[0]["quantity"] == 1
    assert service.performance(b)["realized_pnl_cents"] == 0
    assert service.expire(account_id=a) == 0


def test_account_expiry_requires_trust_and_cannot_self_reconcile(review_demo):
    _, service, a, _, clock = review_demo
    order = service.submit(a, request())
    service.fill(a, order["id"], "unknown-expiry", 1, 100)
    clock[0] = datetime(2026, 11, 20, 14, tzinfo=timezone.utc)
    service.disconnect(a)
    with pytest.raises(Rejected):
        service.expire(account_id=a)
    assert service.performance(a)["realized_pnl_cents"] == 0
    assert service.rows(a, "positions")[0]["quantity"] == 1


def priced_quotes(bid, ask):
    from dataclasses import replace
    from app.automation import fixture_quotes
    return lambda symbol, now: [replace(q, bid=bid, ask=ask) for q in fixture_quotes(symbol, now)]


def test_partial_profit_exit_reprices_remaining_owned_quantity(automated_demo):
    _, service, a, _, clock = automated_demo
    auto_run(service, a, clock)
    clock[0] += timedelta(seconds=1)
    auto_run(service, a, clock)
    assert service.rows(a, "positions")[0]["quantity"] == 2
    clock[0] += timedelta(seconds=1)
    auto_run(service, a, clock, quote_feed=priced_quotes(1.45, 1.50))
    assert service.rows(a, "positions")[0]["quantity"] == 1
    old_close = next(o for o in service.rows(a, "orders") if o["side"] == "SELL_TO_CLOSE")
    assert old_close["status"] == "PARTIAL"
    clock[0] += timedelta(seconds=1)
    # An already triggered exit finishes even if the next quote retreats below
    # take-profit: cancel the old remaining reservation and close only 1 owned.
    auto_run(service, a, clock, quote_feed=priced_quotes(1.20, 1.25))
    assert service.rows(a, "positions") == []
    closes = [o for o in service.rows(a, "orders") if o["side"] == "SELL_TO_CLOSE"]
    assert len(closes) == 2
    assert next(o for o in closes if o["id"] == old_close["id"])["status"] == "CANCELLED"
    assert sum(o["filled"] for o in closes) == 2


def test_emergency_stop_allows_only_trusted_automated_owned_exit(automated_demo):
    _, service, a, b, clock = automated_demo
    auto_run(service, a, clock)
    service.stop()
    clock[0] += timedelta(seconds=1)
    auto_run(service, a, clock, quote_feed=priced_quotes(.7, .75))
    auto_run(service, b, clock)
    assert service.rows(a, "positions") == []
    assert len([o for o in service.rows(a, "orders") if o["side"] == "BUY"]) == 1
    assert len([o for o in service.rows(a, "orders") if o["side"] == "SELL_TO_CLOSE"]) == 1
    assert service.rows(b, "orders") == []


def test_stale_account_blocks_auto_close_without_self_refresh(automated_demo):
    _, service, a, _, clock = automated_demo
    auto_run(service, a, clock)
    clock[0] += timedelta(seconds=121)
    service.mock_market_data(a, "AAPL", True)
    auto_run(service, a, clock, quote_feed=priced_quotes(.7, .75))
    assert service.status(a)["snapshot_valid"] is False
    assert service.rows(a, "positions")[0]["quantity"] == 1
    assert len(service.rows(a, "orders")) == 1


def test_quote_feed_exception_cannot_fill_pending_auto_order(automated_demo):
    _, service, a, _, clock = automated_demo
    auto_run(service, a, clock)
    clock[0] += timedelta(seconds=1)

    def outage(symbol, now):
        raise ConnectionError("synthetic quote outage")

    auto_run(service, a, clock, quote_feed=outage)
    assert service.rows(a, "orders")[0]["filled"] == 1


def test_auto_expiry_is_idempotent_and_never_creates_closing_sale(automated_demo):
    _, service, a, b, clock = automated_demo
    auto_run(service, a, clock)
    position = service.rows(a, "positions")[0]
    clock[0] = datetime.fromisoformat(position["expiry"] + "T14:00:00+00:00")
    service.reconcile(a)
    service.mock_market_data(a, "AAPL", True)
    # Block new signals to isolate settlement from the next simulated session.
    service.configure(a, {"strategies": []})
    first = auto_run(service, a, clock)
    second = auto_run(service, a, clock)
    assert first["expired_positions"] == 1
    assert second["expired_positions"] == 0
    assert service.rows(a, "positions") == []
    assert service.performance(a)["realized_pnl_cents"] == -position["cost"]
    assert not any(o["side"] == "SELL_TO_CLOSE" for o in service.rows(a, "orders"))
    assert service.rows(b, "orders") == []


@pytest.mark.parametrize("changes", [{"mode": "live"}, {"broker": "ibkr"},
                                      {"automation_enabled": 1}, {"auto_quantity": True},
                                      {"stop_loss_pct": 0}, {"max_spread_pct": 101}])
def test_invalid_auto_config_never_changes_safe_defaults(review_demo, changes):
    _, service, a, _, _ = review_demo
    with pytest.raises(Rejected):
        service.configure(a, changes)
    account = next(row for row in service.list_accounts() if row["id"] == a)
    assert account["config"]["mode"] == "paper"
    assert account["config"]["broker"] == "mock"
    assert account["config"]["automation_enabled"] is False


def test_distinct_worker_connections_serialize_same_account_cycle(tmp_path):
    url = "sqlite:///" + str(tmp_path / "two-workers.sqlite")
    repos = [Repository(url), Repository(url)]
    now = datetime(2026, 10, 9, 14, tzinfo=timezone.utc)
    services = [TradingService(repo, now=lambda: now, today=lambda: now.date()) for repo in repos]
    try:
        account = services[0].create_account("concurrent processes", equity=2000000)["id"]
        services[0].watch(account, "AAPL", True)
        services[0].configure(account, {"automation_enabled": True, "auto_quantity": 2,
                                         "auto_fill_chunk": 1, "strategies": ["breakout"]})
        from app.automation import run_account
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(lambda service: run_account(service, account, now=now), services))
        orders = services[0].rows(account, "orders")
        assert len(orders) == 1
        assert orders[0]["filled"] == 1
        assert services[0].rows(account, "positions")[0]["quantity"] == 1
    finally:
        for repo in repos:
            repo.close()


@pytest.mark.parametrize("prefix", ["auto-e:", "auto-x:"])
def test_manual_order_cannot_forge_automatic_execution_identity(review_demo, prefix):
    _, service, a, _, _ = review_demo
    with pytest.raises(Rejected, match="[Rr]eserved|[Aa]utomatic"):
        service.submit(a, request(prefix + "manual-forgery"))
    assert service.rows(a, "orders") == []


@pytest.mark.parametrize("target", ["config", "creation_audit"])
def test_malformed_durable_json_locks_auto_execution(automated_demo, target):
    repo, service, a, _, clock = automated_demo
    auto_run(service, a, clock)
    with repo.transaction() as db:
        if target == "config":
            db.execute("UPDATE accounts SET config='not-json' WHERE id=?", (a,))
        else:
            db.execute("UPDATE audit SET detail='not-json' WHERE account_id=? AND event='ACCOUNT_CREATED'", (a,))
    clock[0] += timedelta(seconds=1)
    result = auto_run(service, a, clock)
    assert result["fills_applied"] == 0
    assert result["blocked_reasons"]
    with repo.transaction() as db:
        assert db.one("SELECT state_known FROM accounts WHERE id=?", (a,))["state_known"] == 0
        assert db.one("SELECT filled FROM orders WHERE account_id=?", (a,))["filled"] == 1
