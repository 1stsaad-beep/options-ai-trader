"""V1 transactional lifecycle regressions; all data is synthetic Mock data."""
import hashlib
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest
from app.automation import fixture_quotes, run_account
from app.lifecycle import advance_reversal, request_reversal, request_scaling
from app.repository import Repository
from app.service import TradingService, Rejected
from app.worker import fixture_bars


@pytest.fixture
def world():
    class World:
        time=datetime(2026,10,9,14,tzinfo=timezone.utc)
        repo=Repository()
        def refresh(self, seconds=1):
            self.time+=timedelta(seconds=seconds)
            self.s.reconcile(self.a)
            self.s.mock_market_data(self.a,'NVDA')
        def quotes(self,bid=1.,ask=1.05):
            return [replace(q,bid=bid,ask=ask) for q in fixture_quotes('NVDA',self.time)]
        def bars(self,right='CALL'):
            bars=fixture_bars('NVDA',self.time)
            return bars if right=='CALL' else [replace(b,open=300-b.open,high=300-b.low,low=300-b.high,close=300-b.close) for b in bars]
        def request(self, key='entry', **changes):
            q=self.quotes()[0]
            return dict(request_key=key,symbol='NVDA',right='CALL',expiry=q.expiry.isoformat(),strike_cents=round(q.strike*100),side='BUY',quantity=1,limit_cents=105)|changes
        def owned(self,quantity=1):
            order=self.s.submit(self.a,self.request(quantity=quantity))
            self.s.fill(self.a,order['id'],'entry-fill',quantity,105)
            q=self.quotes()[0]
            with self.repo.transaction() as db:
                self.s.record_option_mark(db,self.a,'NVDA','CALL',q.expiry.isoformat(),round(q.strike*100),100,105,self.time)
            return order
        def reversal(self,key='reverse'):
            return request_reversal(self.s,self.a,key,'NVDA','PUT',self.bars('PUT'),self.quotes())
        def advance(self,intent,right='PUT'):
            return advance_reversal(self.s,self.a,intent['id'],self.bars(right),self.quotes())
        def close(self,intent,quantity=None):
            oid=json.loads(intent['payload'])['close_order_ids'][0]
            order=next(o for o in self.s.rows(self.a,'orders') if o['id']==oid)
            return self.s.fill(self.a,oid,'close-'+str(order['filled']),quantity or order['quantity']-order['filled'],100)
    w=World()
    w.s=TradingService(w.repo,now=lambda:w.time,today=lambda:w.time.date())
    w.a=w.s.create_account('first',3000000)['id']
    w.s.watch(w.a,'NVDA',True)
    with w.repo.transaction() as db:
        for q in w.quotes():
            w.s.record_option_mark(db,w.a,q.symbol,q.right,q.expiry.isoformat(),round(q.strike*100),100,105,w.time)
    yield w
    w.repo.close()


def test_opposite_pending_partial_owned_and_other_account(world):
    order=world.s.submit(world.a,world.request(quantity=2))
    for phase in ('PENDING','PARTIAL','FILLED'):
        with pytest.raises(Rejected,match='Opposite direction'):
            world.s.submit(world.a,world.request(key=phase,right='PUT',strike_cents=10100))
        if phase!='FILLED':
            world.s.fill(world.a,order['id'],phase,1,105)
    other=world.s.create_account('independent',3000000)['id']
    world.s.watch(other,'NVDA',True)
    assert world.s.submit(other,world.request(right='PUT'))['account_id']==other


def test_simultaneous_opposing_entries_are_serialized(world):
    def submit(right):
        try:
            return world.s.submit(world.a,world.request(key=right,right=right))
        except Rejected:
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        accepted=list(pool.map(submit,['CALL','PUT']))
    assert sum(bool(o) for o in accepted)==1


def test_total_contracts_include_owned_and_pending_remaining(world):
    world.s.configure(world.a,{'max_contracts':3})
    order=world.s.submit(world.a,world.request(quantity=3))
    world.s.fill(world.a,order['id'],'partial',1,105)
    with pytest.raises(Rejected,match='owned plus pending'):
        world.s.submit(world.a,world.request(key='extra'))
    world.s.cancel(world.a,order['id'])
    assert world.s.submit(world.a,world.request(key='two',quantity=2))


def test_lowered_entry_cap_does_not_strand_owned_close(world):
    world.owned(3)
    world.s.configure(world.a,{'max_contracts':1})
    close=world.s.submit(world.a,world.request(key='close',side='SELL_TO_CLOSE',quantity=3,limit_cents=100))
    world.s.stop(world.a)
    assert world.s.rows(world.a,'orders')[-1]['status']=='PENDING'
    assert world.s.fill(world.a,close['id'],'close-fill',3,100)['status']=='FILLED'
    assert not world.s.rows(world.a,'positions')


def test_exact_elevated_ack_and_zero_allocation(world):
    with pytest.raises(Rejected,match='acknowledgement'):
        world.s.configure(world.a,{'allocation_pct':100,'trade_risk_pct':10})
    account=world.s.configure(world.a,{'allocation_pct':100,'trade_risk_pct':10,'elevated_risk_ack':True})
    assert len(account['config']['elevated_risk_ack'])==64
    with pytest.raises(Rejected,match='acknowledgement'):
        world.s.configure(world.a,{'trade_risk_pct':11})
    world.s.configure(world.a,{'allocation_pct':0,'elevated_risk_ack':True})
    with pytest.raises(Rejected,match='allocation'):
        world.s.submit(world.a,world.request())


@pytest.mark.parametrize('change',[{'trade_risk_pct':True},{'allocation_pct':101},{'allocation_pct':-1},{'mode':'live'},{'broker':'ibkr'},{'scaling_enabled':'true'}])
def test_invalid_config_never_enables_execution(world,change):
    with pytest.raises(Rejected):
        world.s.configure(world.a,change)


def test_snapshot_atomic_immutable_and_original_reasons(world):
    order=world.owned()
    snapshots=world.s.rows(world.a,'decision_snapshots')
    assert len(snapshots)==1 and snapshots[0]['order_id']==order['id']
    snap=snapshots[0]
    assert hashlib.sha256(snap['payload'].encode()).hexdigest()==snap['digest']
    world.s.configure(world.a,{'stop_loss_pct':25})
    assert world.s.rows(world.a,'decision_snapshots')[0]==snap
    for sql in ('UPDATE decision_snapshots SET payload=\'{}\'','DELETE FROM decision_snapshots'):
        with pytest.raises(sqlite3.IntegrityError,match='immutable'):
            with world.repo.transaction() as db:
                db.execute(sql)


def test_rejection_has_snapshot_without_an_order(world):
    with pytest.raises(Rejected):
        world.s.submit(world.a,world.request(side='SELL_TO_CLOSE'))
    row=world.s.rows(world.a,'decision_snapshots')[0]
    assert row['action']=='ORDER_REJECTED' and row['order_id'] is None


def test_reversal_full_cycle_and_idempotent_lost_reply(world):
    world.owned(2)
    intent=world.reversal()
    assert intent['state']=='WAIT_FLAT'
    assert world.reversal()['id']==intent['id']
    world.close(intent,1)
    assert world.advance(intent)['state']=='WAIT_FLAT'
    assert not any(o['side']=='BUY' and o['right_kind']=='PUT' for o in world.s.rows(world.a,'orders'))
    world.close(intent,1)
    advanced=world.advance(intent)
    assert advanced['state']=='WAIT_ENTRY'
    assert world.advance(intent)['order_id']==advanced['order_id']
    order=next(o for o in world.s.rows(world.a,'orders') if o['id']==advanced['order_id'])
    world.s.fill(world.a,order['id'],'new-fill',1,105)
    assert world.advance(intent)['state']=='COMPLETE'
    assert world.s.rows(world.a,'positions')[0]['right_kind']=='PUT'


def test_reversal_cancels_old_entry_remainder_before_owned_close(world):
    order=world.s.submit(world.a,world.request(quantity=3))
    world.s.fill(world.a,order['id'],'partial',1,105)
    intent=world.reversal()
    orders=world.s.rows(world.a,'orders')
    assert orders[0]['status']=='CANCELLED'
    assert orders[1]['side']=='SELL_TO_CLOSE' and orders[1]['quantity']==1
    assert world.advance(intent)['state']=='WAIT_FLAT'


def test_reversal_disconnect_and_signal_loss_remain_flat(world):
    world.owned()
    intent=world.reversal()
    world.close(intent)
    world.s.disconnect(world.a)
    with pytest.raises(Rejected,match='trusted'):
        world.advance(intent)
    world.s.reconcile(world.a)
    with pytest.raises(Rejected,match='signal'):
        world.advance(intent,right='CALL')
    assert not world.s.rows(world.a,'positions')
    assert len(world.s.rows(world.a,'orders'))==2


def test_reversal_stale_signal_and_emergency_never_open(world):
    world.owned()
    intent=world.reversal()
    world.close(intent)
    world.refresh(61)
    assert world.advance(intent)['state']=='EXPIRED'
    assert len(world.s.rows(world.a,'orders'))==2


def test_reversal_flat_interval_is_locked_against_manual_old_entry(world):
    world.owned()
    intent=world.reversal()
    world.close(intent)
    with pytest.raises(Rejected,match='reversal'):
        world.s.submit(world.a,world.request(key='race'))
    world.s.stop(world.a)
    with pytest.raises(Rejected,match='Emergency'):
        world.advance(intent)


def test_reversal_does_not_cross_account(world):
    world.owned()
    intent=world.reversal()
    other=world.s.create_account('other')['id']
    with pytest.raises(Rejected,match='Unknown account'):
        advance_reversal(world.s,other,intent['id'],world.bars('PUT'),world.quotes())


def test_scaling_disabled_loss_and_unresolved_order_guards(world):
    world.owned()
    args=lambda key,quotes: request_scaling(world.s,world.a,key,'NVDA','CALL',world.bars(),quotes)
    with pytest.raises(Rejected,match='disabled'):
        args('s1',world.quotes(1.4,1.45))
    world.s.configure(world.a,{'scaling_enabled':True})
    with pytest.raises(Rejected,match='profitable'):
        args('s1',world.quotes(.8,.83))
    intent=args('s1',world.quotes(1.4,1.45))
    assert args('s1',[])['id']==intent['id']
    with pytest.raises(Rejected,match='Unresolved'):
        args('s2',world.quotes(1.4,1.45))


def test_scaling_cooldown_cap_and_risk_recheck(world):
    world.owned()
    world.s.configure(world.a,{'scaling_enabled':True,'scaling_max_additions':1})
    intent=request_scaling(world.s,world.a,'s1','NVDA','CALL',world.bars(),world.quotes(1.4,1.45))
    world.s.fill(world.a,intent['order_id'],'scale-fill',1,145)
    world.refresh(61)
    with pytest.raises(Rejected,match='budget'):
        request_scaling(world.s,world.a,'s2','NVDA','CALL',world.bars(),world.quotes(1.8,1.85))
    assert world.s.rows(world.a,'positions')[0]['quantity']==2


def test_reduced_risk_blocks_preapproved_fill(world):
    order=world.s.submit(world.a,world.request(quantity=3))
    world.s.configure(world.a,{'max_contracts':2})
    with pytest.raises(Rejected,match='Contract limit'):
        world.s.fill(world.a,order['id'],'f',1,105)


def test_open_loss_marks_enforced_and_missing_mark_blocks(world):
    world.owned(2)
    world.s.configure(world.a,{'require_open_loss_marks':True,'daily_loss_pct':0})
    with world.repo.transaction() as db:
        db.execute('DELETE FROM option_marks WHERE account_id=?',(world.a,))
    with pytest.raises(Rejected,match='marks required'):
        world.s.submit(world.a,world.request(key='extra'))
    with world.repo.transaction() as db:
        q=world.quotes()[0]
        world.s.record_option_mark(db,world.a,'NVDA','CALL',q.expiry.isoformat(),round(q.strike*100),50,55,world.time)
    with pytest.raises(Rejected,match='Daily loss'):
        world.s.submit(world.a,world.request(key='extra'))
    assert world.s.submit(world.a,world.request(key='close',side='SELL_TO_CLOSE',quantity=2,limit_cents=50))


@pytest.mark.parametrize('settings,bids,reason',[
    ({'trailing_stop_pct':10,'take_profit_pct':500},[1.4,1.2],'TRAILING_STOP'),
    ({'intraday_exit_hour_utc':14},[1.0],'INTRADAY_EXIT'),
    ({'partial_profit_pct':10,'take_profit_pct':500},[1.2],'PARTIAL_PROFIT'),
])
def test_adaptive_exit_rules(world,settings,bids,reason):
    world.owned(3)
    world.s.configure(world.a,{'automation_enabled':True,**settings})
    last=None
    for bid in bids:
        world.refresh()
        last=run_account(world.s,world.a,quote_feed=lambda symbol,now,bid=bid:world.quotes(bid,bid+.05))
    assert any(a.get('reason')==reason for a in last['actions'])
    positions=world.s.rows(world.a,'positions')
    if reason=='PARTIAL_PROFIT':
        assert positions[0]['quantity']==2
    assert sum(o['quantity'] for o in world.s.rows(world.a,'orders') if o['side']=='SELL_TO_CLOSE')<=3


def test_autonomous_reversal_cycle_partial_close_and_new_entry(world):
    world.owned(2)
    world.s.configure(world.a,{'automation_enabled':True,'reversal_enabled':True})
    quote_feed=lambda symbol,now:world.quotes()
    feed=lambda symbol,now:world.bars('PUT')
    first=run_account(world.s,world.a,feed=feed,quote_feed=quote_feed)
    assert first['orders_submitted']==1
    assert world.s.rows(world.a,'positions')[0]['quantity']==1
    assert len(world.s.rows(world.a,'orders'))==2
    world.refresh()
    second=run_account(world.s,world.a,feed=feed,quote_feed=quote_feed)
    assert second['orders_submitted']==1
    orders=world.s.rows(world.a,'orders')
    assert orders[-1]['right_kind']=='PUT' and orders[-1]['status']=='PENDING'
    assert not world.s.rows(world.a,'positions')
    world.refresh()
    run_account(world.s,world.a,feed=feed,quote_feed=quote_feed)
    assert world.s.rows(world.a,'positions')[0]['right_kind']=='PUT'
    assert world.s.rows(world.a,'lifecycle_intents')[0]['state']=='COMPLETE'


def test_autonomous_scaling_resumes_durable_addition_without_duplicate(world):
    world.owned()
    world.s.configure(world.a,{'automation_enabled':True,'scaling_enabled':True,'take_profit_pct':500})
    quote_feed=lambda symbol,now:world.quotes(1.4,1.45)
    first=run_account(world.s,world.a,quote_feed=quote_feed)
    assert first['orders_submitted']==1
    assert len(world.s.rows(world.a,'orders'))==2
    run_account(world.s,world.a,quote_feed=quote_feed)
    assert len(world.s.rows(world.a,'orders'))==2
    assert world.s.rows(world.a,'positions')[0]['quantity']==2


def test_scale_pending_fill_rejects_fallen_mark_and_disabled_policy(world):
    world.owned()
    world.s.configure(world.a,{'scaling_enabled':True})
    intent=request_scaling(world.s,world.a,'scale','NVDA','CALL',world.bars(),world.quotes(1.4,1.45))
    with world.repo.transaction() as db:
        q=world.quotes()[0]
        world.s.record_option_mark(db,world.a,'NVDA','CALL',q.expiry.isoformat(),round(q.strike*100),90,95,world.time)
    with pytest.raises(Rejected,match='no longer profitable'):
        world.s.fill(world.a,intent['order_id'],'scale-fill',1,95)
    world.s.configure(world.a,{'scaling_enabled':False})
    with pytest.raises(Rejected,match='disabled'):
        world.s.fill(world.a,intent['order_id'],'scale-fill',1,95)


def test_commission_reservation_cost_basis_close_pnl_and_replay(world):
    world.s.configure(world.a,{'commission_cents':65})
    order=world.owned(2)
    assert world.s.rows(world.a,'positions')[0]['cost']==21130
    world.s.configure(world.a,{'commission_cents':75})
    close=world.s.submit(world.a,world.request(key='close',side='SELL_TO_CLOSE',quantity=2,limit_cents=110))
    world.s.fill(world.a,close['id'],'c1',1,110)
    world.s.fill(world.a,close['id'],'c2',1,110)
    assert world.s.performance(world.a)['realized_pnl_cents']==720
    assert world.s.reconcile(world.a)['resubmitted']==0
    assert world.s.fill(world.a,order['id'],'entry-fill',2,105)['status']=='FILLED'
    assert world.s.performance(world.a)['realized_pnl_cents']==720
    with pytest.raises(sqlite3.IntegrityError,match='immutable'):
        with world.repo.transaction() as db:
            db.execute('UPDATE order_costs SET commission_cents=0')


def test_fee_inclusive_per_trade_risk_cannot_overdraw_boundary(world):
    world.s.configure(world.a,{'commission_cents':65})
    # 2% of 3,000,000 = 60,000; premium alone exactly meets budget.
    with pytest.raises(Rejected,match='premium risk'):
        world.s.submit(world.a,world.request(limit_cents=600))


def test_scaling_decreasing_quantity_and_cooldown(world):
    world.owned()
    world.s.configure(world.a,{'scaling_enabled':True,'scaling_decreasing':True,'scaling_quantity':2,'scaling_cooldown_seconds':5})
    first=request_scaling(world.s,world.a,'s1','NVDA','CALL',world.bars(),world.quotes(1.4,1.45))
    world.s.fill(world.a,first['order_id'],'s1-fill',2,145)
    with pytest.raises(Rejected,match='cooldown'):
        request_scaling(world.s,world.a,'s2','NVDA','CALL',world.bars(),world.quotes(2.,2.05))
    world.refresh(5)
    second=request_scaling(world.s,world.a,'s2','NVDA','CALL',world.bars(),world.quotes(2.,2.05))
    assert json.loads(second['payload'])['quantity']==1


def test_reversal_restart_keeps_unknown_account_and_exact_receipt(tmp_path):
    url='sqlite:///'+str(tmp_path/'saved.db')
    repo=Repository(url)
    now=datetime(2026,10,9,14,tzinfo=timezone.utc)
    service=TradingService(repo,now=lambda:now,today=lambda:now.date())
    account=service.create_account('durable',3000000)['id']
    service.watch(account,'NVDA',True)
    quotes=fixture_quotes('NVDA',now)
    q=quotes[0]
    order=service.submit(account,dict(request_key='own',symbol='NVDA',right='CALL',expiry=q.expiry.isoformat(),strike_cents=10000,side='BUY',quantity=1,limit_cents=105))
    service.fill(account,order['id'],'own-fill',1,105)
    down=[replace(b,open=300-b.open,high=300-b.low,low=300-b.high,close=300-b.close) for b in fixture_bars('NVDA',now)]
    intent=request_reversal(service,account,'reverse','NVDA','PUT',down,quotes)
    repo.close()
    repo=Repository(url)
    service=TradingService(repo,now=lambda:now,today=lambda:now.date())
    try:
        assert request_reversal(service,account,'reverse','NVDA','PUT',[],[])['id']==intent['id']
        with pytest.raises(Rejected,match='trusted'):
            advance_reversal(service,account,intent['id'],down,quotes)
        service.reconcile(account)
        close=json.loads(intent['payload'])['close_order_ids'][0]
        service.fill(account,close,'close-fill',1,100)
        assert advance_reversal(service,account,intent['id'],down,quotes)['state']=='WAIT_ENTRY'
        assert len(service.rows(account,'orders'))==3
    finally:
        repo.close()


def test_swing_expiry_and_scenario_exit_rules(world):
    world.owned()
    world.s.configure(world.a,{'automation_enabled':True,'holding':'swing','swing_max_days':1})
    contracts=world.s.rows(world.a,'positions')
    world.refresh(86400)
    result=run_account(world.s,world.a,quote_feed=lambda s,n:fixture_quotes(s,n,contracts))
    assert any(a.get('reason')=='SWING_TIME_EXIT' for a in result['actions'])


def test_confirmed_opposite_strategy_can_exit_without_reopening(world):
    world.owned()
    world.s.configure(world.a,{'automation_enabled':True,'scenario_exit_enabled':True})
    result=run_account(world.s,world.a,feed=lambda s,n:world.bars('PUT'),quote_feed=lambda s,n:world.quotes())
    assert any(a.get('reason')=='SCENARIO_INVALIDATED' for a in result['actions'])
    assert not world.s.rows(world.a,'positions')
    assert len(world.s.rows(world.a,'orders'))==2
