"""Independent transaction/security regression review, synthetic execution only."""
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient
from app.main import create_app
from app.repository import Repository
from app.service import Rejected, TradingService

NOW = datetime(2026, 10, 9, 14, 0, tzinfo=timezone.utc)
TOKEN = "independent-review-token-32-characters"


class TransactionReviewTests(unittest.TestCase):
    def setUp(self):
        self.repo = Repository()
        self.service = TradingService(self.repo, today=lambda: NOW.date(), now=lambda: NOW)
        self.a = self.service.create_account("a")['id']
        self.b = self.service.create_account("b")['id']
        self.service.watch(self.a, "AAPL", True)
        self.service.watch(self.b, "AAPL", True)

    def tearDown(self):
        self.repo.close()

    def request(self, key="request", **changes):
        return dict(request_key=key, symbol="AAPL", right="CALL", expiry="2026-11-20",
                    strike_cents=20000, side="BUY", quantity=2, limit_cents=100) | changes

    def test_other_account_cannot_fill_cancel_or_sell_owned_inventory(self):
        order = self.service.submit(self.a, self.request())
        with self.assertRaises(Rejected):
            self.service.fill(self.b, order['id'], "foreign-fill", 1, 100)
        with self.assertRaises(Rejected):
            self.service.cancel(self.b, order['id'])
        self.service.fill(self.a, order['id'], "owned-fill", 2, 100)
        with self.assertRaises(Rejected):
            self.service.submit(self.b, self.request("foreign-sell", side="SELL_TO_CLOSE"))
        self.assertEqual(self.service.rows(self.b, "positions"), [])
        self.assertEqual(self.service.rows(self.b, "orders"), [])

    def test_partial_fill_replay_and_collision_are_atomic(self):
        order = self.service.submit(self.a, self.request())
        self.service.fill(self.a, order['id'], "first", 1, 90)
        self.service.fill(self.a, order['id'], "first", 1, 90)
        with self.assertRaises(Rejected):
            self.service.fill(self.a, order['id'], "first", 1, 91)
        self.assertEqual(self.service.rows(self.a, "positions")[0]['cost'], 9000)
        with self.assertRaises(Rejected):
            self.service.fill(self.a, order['id'], "overfill", 2, 100)
        self.service.fill(self.a, order['id'], "second", 1, 100)
        position = self.service.rows(self.a, "positions")[0]
        self.assertEqual((position['quantity'], position['cost']), (2, 19000))

    def test_pending_closes_reserve_inventory_across_requests(self):
        order = self.service.submit(self.a, self.request())
        self.service.fill(self.a, order['id'], "entry", 2, 100)
        close = self.service.submit(self.a, self.request("close-1", side="SELL_TO_CLOSE"))
        self.service.fill(self.a, close['id'], "exit-1", 1, 100)
        with self.assertRaises(Rejected):
            self.service.submit(self.a, self.request("close-2", side="SELL_TO_CLOSE", quantity=1))

    def test_realized_loss_reduces_new_trade_risk_budget(self):
        order = self.service.submit(self.a, self.request())
        self.service.fill(self.a, order['id'], "entry", 2, 100)
        close = self.service.submit(self.a, self.request("loss-close", side="SELL_TO_CLOSE", limit_cents=50))
        self.service.fill(self.a, close['id'], "loss-exit", 2, 50)
        # Remaining capital is 990000 cents, whose 2% budget is 19800 cents.
        with self.assertRaises(Rejected):
            self.service.submit(self.a, self.request("after-loss"))

    def test_concurrent_orders_cannot_overallocate(self):
        def submit(index):
            try:
                return self.service.submit(self.a, self.request(str(index)))
            except Rejected:
                return None
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(submit, range(30)))
        accepted = [r for r in results if r is not None]
        self.assertEqual(len(accepted), 15)
        self.assertEqual(sum(r['quantity'] * r['limit_cents'] * 100 for r in accepted), 300000)

    def test_concurrent_duplicate_fill_has_one_effect(self):
        order = self.service.submit(self.a, self.request())
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: self.service.fill(self.a, order['id'], "same-fill", 1, 100), range(16)))
        self.assertTrue(all(r['filled'] == 1 for r in results))
        self.assertEqual(self.service.rows(self.a, "positions")[0]['quantity'], 1)

    def test_independent_database_connections_share_risk_reservations(self):
        with tempfile.TemporaryDirectory() as directory:
            url = "sqlite:///" + str(Path(directory) / "concurrency.db")
            repositories = [Repository(url), Repository(url)]
            services = [TradingService(repo, today=lambda: NOW.date(), now=lambda: NOW) for repo in repositories]
            account = services[0].create_account('multiple workers')['id']
            services[0].watch(account, 'AAPL', True)
            def submit(index):
                try:
                    return services[index % 2].submit(account, self.request(str(index)))
                except Rejected:
                    return None
            try:
                with ThreadPoolExecutor(max_workers=2) as pool:
                    results = list(pool.map(submit, range(30)))
                self.assertEqual(sum(r is not None for r in results), 15)
                self.assertEqual(len(services[1].rows(account, 'orders')), 15)
            finally:
                for repo in repositories:
                    repo.close()

    def test_future_snapshot_fails_closed(self):
        with self.repo.transaction() as db:
            db.execute("UPDATE accounts SET snapshot_at=? WHERE id=?", ((NOW+timedelta(days=1)).isoformat(), self.a))
        with self.assertRaises(Rejected):
            self.service.submit(self.a, self.request())

    def test_corrupt_inventory_cannot_unlock_reconciliation(self):
        order = self.service.submit(self.a, self.request())
        self.service.fill(self.a, order['id'], "entry", 2, 100)
        self.service.disconnect(self.a)
        with self.repo.transaction() as db:
            db.execute("UPDATE positions SET quantity=999 WHERE account_id=?", (self.a,))
        with self.assertRaises(Rejected):
            self.service.reconcile(self.a)
        with self.repo.transaction() as db:
            self.assertEqual(db.one("SELECT state_known FROM accounts WHERE id=?", (self.a,))['state_known'], 0)

    def test_corrupt_daily_loss_ledger_cannot_unlock_reconciliation(self):
        order = self.service.submit(self.a, self.request())
        self.service.fill(self.a, order['id'], "entry", 2, 100)
        close = self.service.submit(self.a, self.request("close-loss", side="SELL_TO_CLOSE", limit_cents=50))
        self.service.fill(self.a, close['id'], "exit", 2, 50)
        self.service.disconnect(self.a)
        with self.repo.transaction() as db:
            db.execute("UPDATE daily_pnl SET pnl=0 WHERE account_id=?", (self.a,))
        with self.assertRaises(Rejected):
            self.service.reconcile(self.a)

    def test_durable_restart_requires_reconcile_without_resubmission(self):
        with tempfile.TemporaryDirectory() as directory:
            url = "sqlite:///" + str(Path(directory) / "restart.db")
            first = Repository(url)
            s = TradingService(first, today=lambda: NOW.date(), now=lambda: NOW)
            account = s.create_account("durable")['id']
            s.watch(account, "AAPL", True)
            order = s.submit(account, self.request())
            s.fill(account, order['id'], "persisted", 1, 90)
            first.close()
            second = Repository(url)
            try:
                restarted = TradingService(second, today=lambda: NOW.date(), now=lambda: NOW)
                with self.assertRaises(Rejected):
                    restarted.submit(account, self.request("new-order"))
                result = restarted.reconcile(account)
                self.assertEqual(result['resubmitted'], 0)
                replay = restarted.submit(account, self.request())
                self.assertEqual(replay['id'], order['id'])
                self.assertEqual(restarted.rows(account, 'positions')[0]['cost'], 9000)
                self.assertEqual(len(restarted.rows(account, 'orders')), 1)
            finally:
                second.close()


class ApiReviewTests(unittest.TestCase):
    def test_token_and_strict_order_types_and_live_lock(self):
        repo = Repository()
        try:
            with TestClient(create_app(repo, token=TOKEN)) as client:
                self.assertEqual(client.get('/api/accounts').status_code, 401)
                self.assertEqual(client.get('/api/accounts', headers={'Authorization':'Bearer wrong'}).status_code, 401)
                self.assertEqual(client.get('/api/accounts', headers={b'Authorization': b'Bearer caf\xe9'}).status_code, 401)
                headers = {'Authorization': 'Bearer ' + TOKEN}
                account = client.post('/api/accounts', json={'name':'review'}, headers=headers).json()['id']
                self.assertEqual(client.put(f'/api/accounts/{account}/risk', json={'mode':'live'}, headers=headers).status_code, 409)
                self.assertEqual(client.put(f'/api/accounts/{account}/risk', json={'strategies':['breakout',{}]}, headers=headers).status_code, 409)
                payload = dict(request_key='strict', symbol='AAPL', right='CALL', expiry='2027-01-15', strike_cents=20000, side='BUY', quantity=True, limit_cents=100)
                self.assertEqual(client.post(f'/api/accounts/{account}/orders', json=payload, headers=headers).status_code, 422)
                payload['quantity'] = 1
                payload['legs'] = []
                self.assertEqual(client.post(f'/api/accounts/{account}/orders', json=payload, headers=headers).status_code, 422)
        finally:
            repo.close()


if __name__ == '__main__':
    unittest.main()
