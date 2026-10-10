"""V0.3 regression cases use durable synthetic execution only."""
from datetime import datetime, timedelta, timezone
import unittest
from app.repository import Repository
from app.service import Rejected, TradingService
from app.adapters import MockBrokerAdapter

class V03SafetyTests(unittest.TestCase):
    def setUp(self):
        self.repo=Repository()
        self.now=datetime(2026,10,9,14,tzinfo=timezone.utc)
        self.day=self.now.date()
        self.s=TradingService(self.repo,today=lambda:self.day,now=lambda:self.now)
        self.a=self.s.create_account('one')['id']
        self.b=self.s.create_account('two')['id']
        for a in (self.a,self.b): self.s.watch(a,'NVDA',True)
    def tearDown(self): self.repo.close()
    def req(self,key='entry',**changes):
        return dict(request_key=key,symbol='NVDA',right='CALL',expiry='2026-11-20',strike_cents=15000,side='BUY',quantity=2,limit_cents=50)|changes
    def own(self):
        order=self.s.submit(self.a,self.req())
        self.s.fill(self.a,order['id'],'first',1,50)
        return order
    def test_lost_response_retry_after_expiry_returns_same_order_even_disconnected(self):
        order=self.s.submit(self.a,self.req()) # Committed broker acceptance; client loses response.
        self.s.disconnect(self.a)
        self.day=self.day+timedelta(days=60)
        replay=self.s.submit(self.a,self.req())
        self.assertEqual(replay['id'],order['id'])
        self.assertEqual(len(self.s.rows(self.a,'orders')),1)
        with self.assertRaises(Rejected): self.s.submit(self.a,self.req(quantity=1))
    def test_partial_fill_stop_preserves_holding_and_allows_owned_close(self):
        order=self.own()
        self.s.stop(self.a)
        self.assertEqual(self.s.rows(self.a,'orders')[0]['status'],'CANCELLED')
        with self.assertRaises(Rejected): self.s.fill(self.a,order['id'],'second',1,50)
        close=self.s.submit(self.a,self.req('emergency-close',side='SELL_TO_CLOSE',quantity=1))
        self.s.fill(self.a,close['id'],'exit',1,50)
        self.assertEqual(self.s.rows(self.a,'positions'),[])
        with self.assertRaises(Rejected): self.s.submit(self.a,self.req('new-entry'))
    def test_global_stop_owned_close_requires_reconciliation_if_unknown(self):
        self.own()
        self.s.stop()
        self.s.disconnect(self.a)
        with self.assertRaises(Rejected): self.s.submit(self.a,self.req('close',side='SELL_TO_CLOSE',quantity=1))
        self.s.reconcile(self.a)
        close=self.s.submit(self.a,self.req('close',side='SELL_TO_CLOSE',quantity=1))
        self.s.fill(self.a,close['id'],'exit',1,50)
        self.assertFalse(self.s.status(self.a)['new_entries_allowed'])
    def test_cancel_partial_reconnect_releases_remaining_reservation_only(self):
        order=self.own()
        self.s.cancel(self.a,order['id'])
        self.s.disconnect(self.a)
        self.s.reconcile(self.a)
        self.assertEqual(self.s.rows(self.a,'positions')[0]['quantity'],1)
        self.assertEqual(self.s.submit(self.a,self.req())['status'],'CANCELLED')
        self.assertEqual(self.s.submit(self.a,self.req('new'))['status'],'PENDING')
    def test_missing_stale_or_future_market_data_fails_closed(self):
        self.now+=timedelta(seconds=61)
        self.s.reconcile(self.a)
        with self.assertRaisesRegex(Rejected,'Market data'): self.s.submit(self.a,self.req())
        self.s.mock_market_data(self.a,'NVDA',False)
        with self.assertRaises(Rejected): self.s.submit(self.a,self.req())
        self.s.mock_market_data(self.a,'NVDA',True)
        with self.repo.transaction() as db:
            db.execute('UPDATE market_snapshots SET observed_at=? WHERE account_id=?',((self.now+timedelta(seconds=1)).isoformat(),self.a))
        with self.assertRaises(Rejected): self.s.submit(self.a,self.req())
        self.s.mock_market_data(self.a,'NVDA',True)
        self.s.submit(self.a,self.req())
    def test_market_disconnect_still_allows_safe_owned_close(self):
        self.own()
        self.s.mock_market_data(self.a,'NVDA',False)
        close=self.s.submit(self.a,self.req('close',side='SELL_TO_CLOSE',quantity=1))
        self.s.fill(self.a,close['id'],'exit',1,50)
    def test_balance_corruption_before_order_fails_closed(self):
        with self.repo.transaction() as db: db.execute('UPDATE accounts SET equity=99999999 WHERE id=?',(self.a,))
        with self.assertRaisesRegex(Rejected,'balance provenance'): self.s.submit(self.a,self.req())
        self.assertFalse(self.s.status(self.a)['state_known'])
        self.assertEqual(self.s.rows(self.a,'orders'),[])
    def test_order_corruption_cannot_reconcile_or_accept_new_order(self):
        self.s.submit(self.a,self.req())
        with self.repo.transaction() as db: db.execute('UPDATE orders SET quantity=0 WHERE account_id=?',(self.a,))
        with self.assertRaises(Rejected): self.s.reconcile(self.a)
        self.assertFalse(self.s.status(self.a)['state_known'])
    def test_position_corruption_is_checked_before_new_admission(self):
        self.own()
        with self.repo.transaction() as db: db.execute('UPDATE positions SET quantity=3 WHERE account_id=?',(self.a,))
        with self.assertRaises(Rejected): self.s.submit(self.a,self.req('new'))
        self.assertFalse(self.s.status(self.a)['state_known'])
    def test_shared_connection_never_shares_account_orders(self):
        for a in (self.a,self.b): self.s.configure(a,{'connection_id':'shared-mock'})
        order=self.own()
        with self.assertRaises(Rejected): self.s.cancel(self.b,order['id'])
        with self.assertRaises(Rejected): self.s.fill(self.b,order['id'],'foreign',1,50)
        with self.assertRaises(Rejected): self.s.submit(self.b,self.req('close',side='SELL_TO_CLOSE',quantity=1))
        self.assertEqual(self.s.rows(self.b,'orders'),[])
    def test_linked_group_uses_strictest_group_allocation(self):
        self.s.configure(self.a,{'risk_group':'family','group_allocation_pct':1})
        self.s.configure(self.b,{'risk_group':'family','group_allocation_pct':2})
        self.s.submit(self.a,self.req('a',quantity=2,limit_cents=100))
        with self.assertRaisesRegex(Rejected,'Linked group allocation'): self.s.submit(self.b,self.req('b'))
        self.s.configure(self.b,{'risk_group':None})
        self.s.submit(self.b,self.req('b'))
    def test_linked_group_cannot_use_unknown_balance(self):
        for a in (self.a,self.b): self.s.configure(a,{'risk_group':'family'})
        self.s.disconnect(self.b)
        with self.assertRaisesRegex(Rejected,'Linked account state unknown'): self.s.submit(self.a,self.req())
        self.s.reconcile(self.b)
        self.s.submit(self.a,self.req())
    def test_shadow_analysis_modes_are_independent_and_live_always_locked(self):
        for mode in ('shadow','analysis'):
            self.s.configure(self.a,{'mode':mode})
            with self.assertRaises(Rejected): self.s.submit(self.a,self.req())
        self.assertEqual(self.s.submit(self.b,self.req())['account_id'],self.b)
        with self.assertRaises(Rejected): self.s.configure(self.a,{'mode':'live'})
    def test_mock_symbol_validation_does_not_claim_ibkr_entitlement(self):
        for symbol in ('NVDA','AAPL','TSLA','AMD','MSFT','SPY','QQQ'):
            status=MockBrokerAdapter().verify_symbol(symbol)
            self.assertTrue(status['verified'])
            self.assertFalse(status['real_broker_verification'])
        self.s.watch(self.a,'OTHER',False)
        with self.assertRaises(Rejected): self.s.watch(self.a,'OTHER',True)
    def test_account_watchlists_can_grow_and_toggle_independently(self):
        self.s.watch(self.a,'AMD',True)
        self.s.watch(self.a,'SPY',True)
        self.assertEqual(len(self.s.rows(self.a,'watchlist')),5)
        self.assertEqual(len(self.s.rows(self.b,'watchlist')),3)
        self.s.watch(self.a,'AMD',False)
        self.s.remove_watch(self.a,'SPY')
        self.assertEqual(len(self.s.rows(self.a,'watchlist')),4)

    def test_fill_corrupted_ledger_persists_distrust_after_rejection(self):
        order=self.own()
        with self.repo.transaction() as db:
            db.execute('UPDATE positions SET quantity=99 WHERE account_id=?',(self.a,))
        with self.assertRaises(Rejected): self.s.fill(self.a,order['id'],'later',1,50)
        self.assertFalse(self.s.status(self.a)['state_known'])
        self.assertFalse(self.s.status(self.a)['new_entries_allowed'])

    def test_status_is_conservative_after_market_loss_or_corrupt_ledger(self):
        self.assertTrue(self.s.status(self.a)['new_entries_allowed'])
        self.s.mock_market_data(self.a,'NVDA',False)
        self.assertFalse(self.s.status(self.a)['new_entries_allowed'])
        with self.repo.transaction() as db: db.execute('UPDATE accounts SET equity=99999999 WHERE id=?',(self.a,))
        self.assertFalse(self.s.status(self.a)['risk_guard_ready'])
