"""Independent fail-closed regressions. All data and executions are synthetic."""
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.repository import Repository
from app.service import Rejected, TradingService

TOKEN = "adversarial-review-local-token-32-characters"


@pytest.fixture
def demo():
    repo = Repository()
    clock = [datetime(2026, 10, 9, 14, tzinfo=timezone.utc)]
    service = TradingService(repo, today=lambda: clock[0].date(), now=lambda: clock[0])
    a = service.create_account("independent A")["id"]
    b = service.create_account("independent B")["id"]
    for account in (a, b):
        service.watch(account, "AAPL", True)
    yield repo, service, a, b, clock
    repo.close()


def request(key="adversarial", **changes):
    return dict(request_key=key, symbol="AAPL", right="CALL", expiry="2026-11-20",
                strike_cents=20000, side="BUY", quantity=2, limit_cents=100) | changes


def test_lost_response_replay_after_disconnect_and_expiry_never_resends(demo):
    _, service, a, _, clock = demo
    order = service.submit(a, request())
    service.fill(a, order["id"], "first", 1, 100)
    service.disconnect(a)
    assert service.submit(a, request())["id"] == order["id"]
    clock[0] = datetime(2026, 11, 21, 14, tzinfo=timezone.utc)
    with pytest.raises(Rejected, match='trusted reconciliation'):
        service.expire()  # V1 never settles an untrusted account, including global expiry.
    service.reconcile(a)
    service.expire()
    replay = service.submit(a, request())
    assert replay["id"] == order["id"]
    assert replay["status"] == "EXPIRED"
    assert len(service.rows(a, "orders")) == 1
    assert service.reconcile(a)["resubmitted"] == 0


def test_replay_payload_collision_after_expiry_is_rejected(demo):
    _, service, a, _, clock = demo
    service.submit(a, request())
    clock[0] = datetime(2026, 11, 21, 14, tzinfo=timezone.utc)
    service.expire()
    with pytest.raises(Rejected, match="Idempotency"):
        service.submit(a, request(quantity=1))


@pytest.mark.parametrize("corruption", ["status", "identity", "balance", "daily", "positions"])
def test_corrupt_ledger_reconciliation_remains_locked(demo, corruption):
    repo, service, a, _, _ = demo
    order = service.submit(a, request())
    service.fill(a, order["id"], "trusted", 1, 100)
    with repo.transaction() as db:
        if corruption == "status":
            db.execute("UPDATE orders SET status='FILLED' WHERE id=?", (order["id"],))
        elif corruption == "identity":
            db.execute("UPDATE orders SET symbol='TSLA' WHERE id=?", (order["id"],))
        elif corruption == "balance":
            db.execute("UPDATE accounts SET equity=equity+100000 WHERE id=?", (a,))
        elif corruption == "daily":
            db.execute("INSERT INTO daily_pnl VALUES(?,?,?)", (a, "2026-10-09", 1))
        else:
            db.execute("UPDATE positions SET cost=cost+1 WHERE account_id=?", (a,))
    with pytest.raises(Rejected):
        service.reconcile(a)
    assert service.status(a)["state_known"] is False
    with pytest.raises(Rejected):
        service.submit(a, request("fresh"))


@pytest.mark.parametrize("offset", [-61, 1])
def test_stale_or_future_market_observation_cannot_admit_buy(demo, offset):
    repo, service, a, _, clock = demo
    with repo.transaction() as db:
        db.execute("UPDATE market_snapshots SET observed_at=? WHERE account_id=?",
                   ((clock[0]+timedelta(seconds=offset)).isoformat(), a))
    with pytest.raises(Rejected, match="Market"):
        service.submit(a, request())
    assert service.rows(a, "orders") == []


def test_market_outage_blocks_new_entry_and_pending_buy_fill(demo):
    _, service, a, _, _ = demo
    order = service.submit(a, request())
    service.mock_market_data(a, "AAPL", False)
    with pytest.raises(Rejected):
        service.submit(a, request("new"))
    with pytest.raises(Rejected):
        service.fill(a, order["id"], "outage", 1, 100)
    assert service.rows(a, "positions") == []


def test_owned_emergency_close_survives_stop_and_market_outage(demo):
    _, service, a, _, _ = demo
    order = service.submit(a, request())
    service.fill(a, order["id"], "entry", 2, 100)
    service.stop(a)
    service.mock_market_data(a, "AAPL", False)
    service.disconnect(a)
    with pytest.raises(Rejected):
        service.submit(a, request("close", side="SELL_TO_CLOSE"))
    service.reconcile(a)
    close = service.submit(a, request("close", side="SELL_TO_CLOSE"))
    service.fill(a, close["id"], "owned-exit", 2, 100)
    assert service.rows(a, "positions") == []


def test_lowered_risk_cannot_be_bypassed_by_old_pending_order(demo):
    _, service, a, _, _ = demo
    order = service.submit(a, request())
    service.configure(a, {"trade_risk_pct": 1})
    with pytest.raises(Rejected):
        service.fill(a, order["id"], "old-policy", 2, 100)


@pytest.mark.parametrize("change", ["contract_limit", "disabled_symbol", "deleted_symbol"])
def test_pending_buy_respects_current_limits_and_watchlist(demo, change):
    _, service, a, _, _ = demo
    order = service.submit(a, request())
    if change == "contract_limit":
        service.configure(a, {"max_contracts": 1})
    elif change == "disabled_symbol":
        service.watch(a, "AAPL", False)
    else:
        service.remove_watch(a, "AAPL")
    with pytest.raises(Rejected):
        service.fill(a, order["id"], "after-policy-change", 1, 100)
    assert service.rows(a, "positions") == []


def test_linked_group_requires_trusted_other_account_balance(demo):
    _, service, a, b, _ = demo
    service.configure(a, {"risk_group": "linked"})
    service.configure(b, {"risk_group": "linked"})
    service.disconnect(b)
    with pytest.raises(Rejected):
        service.submit(a, request())


def test_global_supervisor_cannot_use_disconnected_capital(demo):
    _, service, a, b, _ = demo
    # B's committed exposure is retained even when its capital becomes untrusted.
    service.configure(b, {'max_contracts': 100})  # Isolate global capital policy.
    for index in range(15):
        service.submit(b, request(f"reserved-{index}"))
    service.disconnect(b)
    with pytest.raises(Rejected):
        service.submit(a, request())


def test_linked_daily_loss_blocks_other_members_preapproved_fill(demo):
    _, service, a, b, _ = demo
    for account in (a, b):
        service.configure(account, {"risk_group": "shared", "group_daily_loss_pct": 1})
    pending = service.submit(b, request("before-loss", quantity=1, limit_cents=50))
    for index in range(2):
        buy = service.submit(a, request(f"loss-buy-{index}", limit_cents=95))
        service.fill(a, buy["id"], f"loss-entry-{index}", 2, 95)
        close = service.submit(a, request(f"loss-close-{index}", side="SELL_TO_CLOSE", limit_cents=1))
        service.fill(a, close["id"], f"loss-exit-{index}", 2, 1)
    with pytest.raises(Rejected):
        service.fill(b, pending["id"], "after-group-loss", 1, 50)
    assert service.rows(b, "positions") == []
    assert next(order for order in service.rows(b, "orders") if order["id"] == pending["id"])["status"] == "CANCELLED"


def test_expiry_never_settles_corrupted_inventory(demo):
    repo, service, a, _, clock = demo
    order = service.submit(a, request())
    service.fill(a, order["id"], "expiry-entry", 1, 100)
    with repo.transaction() as db:
        db.execute("UPDATE positions SET cost=999999 WHERE account_id=?", (a,))
    clock[0] = datetime(2026, 11, 21, 14, tzinfo=timezone.utc)
    with pytest.raises(Rejected):
        service.expire()
    assert service.performance(a)["realized_pnl_cents"] == 0
    assert service.status(a)["state_known"] is False
    assert not any(event["event"] == "MOCK_EXPIRY_WRITEOFF" for event in service.rows(a, "audit"))


def test_other_account_cannot_cancel_or_fill_same_request_key(demo):
    _, service, a, b, _ = demo
    left = service.submit(a, request())
    right = service.submit(b, request())
    with pytest.raises(Rejected):
        service.cancel(b, left["id"])
    with pytest.raises(Rejected):
        service.fill(b, left["id"], "foreign", 1, 100)
    assert left["id"] != right["id"]
    assert service.rows(b, "orders")[0]["filled"] == 0


@pytest.mark.parametrize("mode", ["live", "LIVE"])
def test_live_environment_refuses_startup(demo, mode):
    repo, _, _, _, _ = demo
    with patch.dict("os.environ", {"TRADING_MODE": mode, "ENABLE_LIVE": "false"}):
        with pytest.raises(RuntimeError, match="Live"):
            with TestClient(create_app(repo, token=TOKEN)):
                pass


def test_all_sensitive_api_routes_require_authentication(demo):
    repo, _, a, _, _ = demo
    with TestClient(create_app(repo, token=TOKEN)) as client:
        routes = [("GET", "/api/accounts"), ("POST", "/api/accounts"),
                  ("POST", "/api/emergency-stop")]
        routes += [("GET", f"/api/accounts/{a}/{route}") for route in
                   ("status", "risk", "watchlist", "orders", "positions", "audit", "performance", "opportunities")]
        routes += [("POST", f"/api/accounts/{a}/{route}") for route in
                   ("orders", "watchlist", "disconnect", "reconcile", "mock-market-data")]
        for method, path in routes:
            response = client.request(method, path, json={})
            assert response.status_code == 401, (method, path, response.text)


def test_api_rejects_coercion_or_llm_authority_fields(demo):
    repo, _, a, _, _ = demo
    headers = {"Authorization": "Bearer " + TOKEN}
    with TestClient(create_app(repo, token=TOKEN)) as client:
        for payload in (request(quantity=True), request(quantity="1"),
                        request(force=True), request(ai_approved=True), request(legs=[])):
            response = client.post(f"/api/accounts/{a}/orders", json=payload, headers=headers)
            assert response.status_code == 422
        for payload in ({"mode": "live"}, {"broker": "ibkr"}, {"trade_risk_pct": True},
                        {"strategies": ["breakout", {}]}, {"allocation_pct": 31}):
            response = client.put(f"/api/accounts/{a}/risk", json=payload, headers=headers)
            assert response.status_code == 409


def test_unknown_account_errors_preserve_api_rejection_and_database(demo):
    repo, _, _, _, _ = demo
    headers = {"Authorization": "Bearer " + TOKEN}
    with TestClient(create_app(repo, token=TOKEN), raise_server_exceptions=False) as client:
        for suffix, payload in (("orders", request()), ("reconcile", {})):
            response = client.post(f"/api/accounts/missing/{suffix}", json=payload, headers=headers)
            assert response.status_code == 409, response.text
        assert client.get("/api/accounts", headers=headers).status_code == 200
