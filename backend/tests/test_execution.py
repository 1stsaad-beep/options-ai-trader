import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from app.repository import Repository
from app.service import TradingService, Rejected
from app.adapters import IBKRAdapter, GenericAnalysisAdapter
from app.worker import tick, opportunities_for

class ExecutionTests(unittest.TestCase):
    def setUp(self):
        self.repo=Repository()
        self.now=datetime(2026,10,9,14,tzinfo=timezone.utc)
        self.day=self.now.date()
        self.s=TradingService(self.repo,today=lambda:self.day,now=lambda:self.now)
        self.a=self.s.create_account('a')['id']
        self.b=self.s.create_account('b')['id']
        for account in (self.a,self.b): self.s.watch(account,'NVDA',True)
    def tearDown(self): self.repo.close()
    def req(self,**changes):
        return dict(request_key='unique',symbol='NVDA',right='CALL',expiry='2026-11-20',strike_cents=15000,side='BUY',quantity=2,limit_cents=50)|changes
    def test_idempotent_payload_and_keys_isolated(self):
        a=self.s.submit(self.a,self.req())
        self.assertEqual(a['id'],self.s.submit(self.a,self.req())['id'])
        self.assertNotEqual(a['id'],self.s.submit(self.b,self.req())['id'])
        with self.assertRaises(Rejected): self.s.submit(self.a,self.req(quantity=1))
        with self.assertRaises(Rejected): self.s.fill(self.b,a['id'],'f',1,50)
        self.assertEqual(len(self.s.rows(self.a,'orders')),1)
    def test_partial_fill_idempotent_and_limit_enforced(self):
        # Fresh synthetic quote supports the risk check on the second fill.
        with self.repo.transaction() as db:
            self.s.record_option_mark(db,self.a,'NVDA','CALL','2026-11-20',15000,50,50,self.now)
        order=self.s.submit(self.a,self.req())
        with self.assertRaises(Rejected): self.s.fill(self.a,order['id'],'f',1,51)
        self.assertEqual(self.s.fill(self.a,order['id'],'f',1,50)['status'],'PARTIAL')
        self.s.fill(self.a,order['id'],'f',1,50)
        with self.assertRaises(Rejected): self.s.fill(self.a,order['id'],'f',1,40)
        self.assertEqual(self.s.rows(self.a,'positions')[0]['quantity'],1)
        self.assertEqual(self.s.fill(self.a,order['id'],'g',1,45)['status'],'FILLED')
        self.assertEqual(self.s.rows(self.a,'positions')[0]['cost'],9500)
        with self.assertRaises(Rejected): self.s.fill(self.a,order['id'],'h',1,50)
    def test_caps_and_live_external_broker_locked(self):
        with self.assertRaises(Rejected): self.s.submit(self.a,self.req(limit_cents=101))
        for config in ({'mode':'live'},{'broker':'ibkr'},{'allocation_pct':31},{'trade_risk_pct':3},{'daily_loss_pct':4}):
            with self.assertRaises(Rejected): self.s.configure(self.a,config)
        with self.assertRaises(RuntimeError): IBKRAdapter().connect()
        with self.assertRaises(PermissionError): GenericAnalysisAdapter().analyze()
    def test_unowned_and_double_reserved_close(self):
        with self.assertRaises(Rejected): self.s.submit(self.a,self.req(side='SELL_TO_CLOSE'))
        order=self.s.submit(self.a,self.req())
        self.s.fill(self.a,order['id'],'f',2,50)
        self.s.submit(self.a,self.req(request_key='close',side='SELL_TO_CLOSE'))
        with self.assertRaises(Rejected): self.s.submit(self.a,self.req(request_key='close2',quantity=1,side='SELL_TO_CLOSE'))
    def test_disconnect_snapshot_and_reconcile_no_resend(self):
        order=self.s.submit(self.a,self.req())
        self.s.disconnect(self.a)
        with self.assertRaises(Rejected): self.s.submit(self.a,self.req(request_key='new'))
        with self.assertRaises(Rejected): self.s.fill(self.a,order['id'],'f',1,50)
        self.assertEqual(self.s.reconcile(self.a)['resubmitted'],0)
        self.now+=timedelta(seconds=121)
        with self.assertRaises(Rejected): self.s.submit(self.a,self.req(request_key='new'))
        self.s.reconcile(self.a)
        # V0.3: account reconciliation must not fabricate fresh market data.
        self.s.mock_market_data(self.a,'NVDA',True)
        self.s.fill(self.a,order['id'],'f',1,50)
        self.assertEqual(len(self.s.rows(self.a,'orders')),1)
    def test_kill_switch_account_then_global(self):
        self.s.submit(self.a,self.req())
        self.s.stop(self.a)
        self.assertEqual(self.s.rows(self.a,'orders')[0]['status'],'CANCELLED')
        with self.assertRaises(Rejected): self.s.submit(self.a,self.req(request_key='new'))
        self.s.submit(self.b,self.req())
        self.s.stop()
        with self.assertRaises(Rejected): self.s.submit(self.b,self.req(request_key='new'))
    def test_expiry_writeoff_idempotent(self):
        order=self.s.submit(self.a,self.req())
        self.s.fill(self.a,order['id'],'f',1,50)
        self.day=date(2026,11,20)
        self.assertEqual(self.s.expire(),1)
        self.assertEqual(self.s.rows(self.a,'positions'),[])
        self.assertEqual(self.s.performance(self.a)['realized_pnl_cents'],-5000)
        self.assertEqual(self.s.rows(self.a,'orders')[0]['status'],'EXPIRED')
        self.assertEqual(self.s.expire(),0)
    def test_invalid_expiry_types_and_multileg(self):
        for changes in ({'expiry':'2026-10-09'},{'quantity':True},{'limit_cents':float('nan')},{'right':'SPREAD'},{'legs':[]},{'side':'SELL_TO_OPEN'}):
            with self.assertRaises(Rejected): self.s.submit(self.a,self.req(**changes))
    def test_mock_entitlements_required(self):
        with self.assertRaises(Rejected): self.s.watch(self.a,'UNKNOWN',True)
        self.s.watch(self.a,'AAPL',False)
        with self.assertRaises(Rejected): self.s.submit(self.a,self.req(symbol='AAPL'))
    def test_atomic_risk_concurrent_admission(self):
        self.s.configure(self.a, {'max_contracts': 100})  # Isolate allocation from the V1 aggregate quantity gate.
        def submit(index):
            try:
                self.s.submit(self.a,self.req(request_key=str(index),quantity=2,limit_cents=100))
                return True
            except Rejected: return False
        with ThreadPoolExecutor(max_workers=10) as pool: results=list(pool.map(submit,range(25)))
        self.assertEqual(sum(results),15)
        self.assertEqual(len(self.s.rows(self.a,'orders')),15)
    def test_daily_limit_and_next_date_reset(self):
        for index in range(2):
            buy=self.s.submit(self.a,self.req(request_key=f'b{index}',quantity=2,limit_cents=95))
            self.s.fill(self.a,buy['id'],f'f{index}',2,95)
            sell=self.s.submit(self.a,self.req(request_key=f's{index}',side='SELL_TO_CLOSE',quantity=2,limit_cents=1))
            self.s.fill(self.a,sell['id'],f'c{index}',2,1)
        with self.assertRaises(Rejected): self.s.submit(self.a,self.req(request_key='third'))
        self.day+=timedelta(days=1)
        self.s.submit(self.a,self.req(request_key='nextday'))
    def test_loss_threshold_cancels_preapproved_pending_buy(self):
        pending=self.s.submit(self.a,self.req(request_key='pending'))
        for index in range(2):
            buy=self.s.submit(self.a,self.req(request_key=f'loss-buy{index}',quantity=2,limit_cents=95))
            self.s.fill(self.a,buy['id'],f'loss-fill{index}',2,95)
            sell=self.s.submit(self.a,self.req(request_key=f'loss-sell{index}',side='SELL_TO_CLOSE',quantity=2,limit_cents=1))
            self.s.fill(self.a,sell['id'],f'loss-close{index}',2,1)
        orders={o['id']:o for o in self.s.rows(self.a,'orders')}
        self.assertEqual(orders[pending['id']]['status'],'CANCELLED')
        with self.assertRaises(Rejected): self.s.fill(self.a,pending['id'],'after-loss',1,50)
        self.assertTrue(any(a['event']=='DAILY_LOSS_PENDING_BUYS_CANCELLED' for a in self.s.rows(self.a,'audit')))
    def test_global_loss_blocks_otherwise_valid_small_account(self):
        for account in (self.a,self.b):
            for index in range(2):
                buy=self.s.submit(account,self.req(request_key=f'global-buy{index}',quantity=2,limit_cents=95))
                self.s.fill(account,buy['id'],f'{account}-gf{index}',2,95)
                sell=self.s.submit(account,self.req(request_key=f'global-sell{index}',side='SELL_TO_CLOSE',quantity=2,limit_cents=1))
                self.s.fill(account,sell['id'],f'{account}-gc{index}',2,1)
        small=self.s.create_account('small',10000)['id']
        self.s.watch(small,'NVDA',True)
        with self.assertRaisesRegex(Rejected,'Global daily loss'):
            self.s.submit(small,self.req(quantity=1,limit_cents=1))
        self.assertTrue(any(row['event']=='ORDER_REJECTED' for row in self.s.rows(small,'audit')))
    def test_restart_state_unknown_durable_idempotency(self):
        with tempfile.TemporaryDirectory() as directory:
            path='sqlite:///'+os.path.join(directory,'db.sqlite')
            first=Repository(path)
            s=TradingService(first,today=lambda:self.day,now=lambda:self.now)
            account=s.create_account('durable')['id']
            s.watch(account,'NVDA',True)
            order=s.submit(account,self.req())
            first.close()
            second=Repository(path)
            s=TradingService(second,today=lambda:self.day,now=lambda:self.now)
            with self.assertRaises(Rejected): s.submit(account,self.req(request_key='new'))
            s.reconcile(account)
            self.assertEqual(s.submit(account,self.req())['id'],order['id'])
            second.close()
    def test_shadow_worker_independent_and_no_execution(self):
        result=tick(self.s,self.now)
        self.assertEqual(result['orders_submitted'],0)
        self.assertGreater(result['shadow_decisions_recorded'],0)
        self.assertEqual(tick(self.s,self.now)['shadow_decisions_recorded'],0)
        self.assertEqual(self.s.rows(self.a,'orders'),[])
        self.assertTrue(all(not o['actionable'] for o in opportunities_for(self.s,self.a)))
