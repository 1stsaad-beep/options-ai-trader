"""Paper receipts are not orders; transaction, ownership and recovery acceptance."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
import sqlite3

import pytest
from app.repository import Repository
from app.service import TradingService, Rejected


@pytest.fixture
def world(tmp_path):
    class World:
        path = tmp_path / 'settlement.db'
        now = datetime(2026, 10, 13, 15, 1, 15, tzinfo=timezone.utc)
        contract = 'NVDA261016C00200000'
        def receipt(self, **changes):
            return dict(id='receipt-1', action='EXERCISE', contract=self.contract, quantity=1,
                feeCents=100, underlyingCents=22000, effectiveAt=self.now.isoformat(),
                recordedAt=self.now.isoformat(), source='fixture', reference='observed-fixture') | changes
        def order(self, **changes):
            return dict(request_key='entry', symbol='NVDA', right='CALL', expiry='2026-10-16',
                strike_cents=20000, side='BUY', quantity=2, limit_cents=210) | changes
        def restart(self):
            self.repo.close(); self.repo = Repository(f'sqlite:///{self.path}')
            self.s = TradingService(self.repo, now=lambda:self.now, today=lambda:self.now.date())
            self.s.reconcile(self.a)
    w = World(); w.repo = Repository(f'sqlite:///{w.path}')
    w.s = TradingService(w.repo, now=lambda:w.now, today=lambda:w.now.date())
    w.a = w.s.create_account('delivery', 10000000)['id']
    w.s.configure(w.a, {'session_policy':'us_equity_options_2026_2027', 'commission_cents':65, 'holding':'swing'})
    w.s.watch(w.a, 'NVDA', True)
    order = w.s.submit(w.a, w.order()); w.s.fill(w.a, order['id'], 'buy-fill', 2, 210)
    w.now += timedelta(seconds=1)
    yield w
    w.repo.close()


def test_partial_exercise_recovery_and_exact_retry(world):
    w = world; req = w.receipt(); result = w.s.settle_paper(w.a, req)
    assert result['externalOrder'] is False and result['shareDelta'] == 100
    p = w.s.performance(w.a)
    assert p['simulated_cash_cents'] == 7957770
    assert p['delivered_share_basis_cents'] == 2021165
    assert p['realized_pnl_cents'] == 0 and p['net_liquidation_cents'] is None
    assert p['valuation_complete'] is False and p['total_commissions_cents'] == 230
    assert w.s.rows(w.a, 'positions')[0]['quantity'] == 1
    w.restart()
    assert w.s.settle_paper(w.a, req) == result
    assert len(w.s.rows(w.a, 'paper_settlement_receipts')) == 1
    with pytest.raises(Rejected, match='identity conflict'):
        w.s.settle_paper(w.a, req | {'quantity':2})


def test_full_delivery_and_fractional_basis_disposal(world):
    w=world;w.s.settle_paper(w.a,w.receipt(quantity=2))
    w.s.settle_paper(w.a,w.receipt(id='sale1',action='SELL_DELIVERY',quantity=50))
    assert w.s.performance(w.a)['realized_pnl_cents']==89343
    w.s.settle_paper(w.a,w.receipt(id='sale2',action='SELL_DELIVERY',quantity=150))
    p=w.s.performance(w.a)
    assert p['realized_pnl_cents']==357570 and p['simulated_cash_cents']==10357570
    assert p['net_liquidation_cents']==10357570 and p['delivered_shares']==[]
    assert p['total_commissions_cents']==430 and p['settlement_events']==3
    w.restart();assert w.s.performance(w.a)['realized_pnl_cents']==357570


def test_option_fill_after_partial_exercise_is_interleaved_with_receipt(world):
    w=world;w.s.settle_paper(w.a,w.receipt())
    order=w.s.submit(w.a,w.order(request_key='close',side='SELL_TO_CLOSE',quantity=1,limit_cents=200))
    w.s.fill(w.a,order['id'],'close-fill',1,200)
    assert w.s.performance(w.a)['realized_pnl_cents']==-1130
    w.s.settle_paper(w.a,w.receipt(id='sale',action='SELL_DELIVERY',quantity=100))
    assert w.s.performance(w.a)['realized_pnl_cents']==177605
    w.restart();assert w.s.rows(w.a,'positions')==[]


def test_explicit_worthless_expiry_preserves_original_fills(world):
    w=world;w.now=datetime(2026,10,16,20,tzinfo=timezone.utc);w.s.reconcile(w.a)
    w.s.settle_paper(w.a,w.receipt(action='EXPIRE_WORTHLESS',quantity=2,underlyingCents=19900))
    p=w.s.performance(w.a);assert p['simulated_cash_cents']==9957770 and p['realized_pnl_cents']==-42230
    assert w.s.rows(w.a,'positions')==[]
    with w.repo.transaction() as db:
        assert db.one('SELECT COUNT(*) AS n FROM fills')['n']==1
    w.restart()


@pytest.mark.parametrize('changes',[{'quantity':3},{'source':'broker'},{'action':'ASSIGNMENT'},
    {'effectiveAt':'2026-10-13T15:00:00Z'},{'action':'SELL_DELIVERY'}, {'unknown':True}])
def test_rejected_receipts_leave_cash_inventory_and_history_unchanged(world,changes):
    w=world;before=w.s.performance(w.a);positions=w.s.rows(w.a,'positions')
    with pytest.raises(Rejected):w.s.settle_paper(w.a,w.receipt(**changes))
    assert w.s.performance(w.a)==before and w.s.rows(w.a,'positions')==positions
    assert w.s.rows(w.a,'paper_settlement_receipts')==[]


def test_armed_automation_and_pending_orders_block_settlement(world):
    w=world;w.s.configure(w.a,{'automation_enabled':True})
    with pytest.raises(Rejected,match='Stop automation'):w.s.settle_paper(w.a,w.receipt())
    w.s.configure(w.a,{'automation_enabled':False})
    w.s.submit(w.a,w.order(request_key='close',side='SELL_TO_CLOSE',quantity=1,limit_cents=200))
    with pytest.raises(Rejected,match='pending orders'):w.s.settle_paper(w.a,w.receipt())


def test_unpriced_delivery_blocks_new_exposure_and_session_change(world):
    w=world;w.s.settle_paper(w.a,w.receipt(quantity=2))
    with pytest.raises(Rejected,match='Delivered stock'):w.s.submit(w.a,w.order(request_key='new'))
    with pytest.raises(Rejected,match='Session policy'):w.s.configure(w.a,{'session_policy':'synthetic_24x7'})


def test_two_identical_requests_commit_once(world):
    w=world;request=w.receipt()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda _:w.s.settle_paper(w.a,request),range(2)))
    assert results[0]==results[1] and len(w.s.rows(w.a,'paper_settlement_receipts'))==1
    w.restart()


def test_receipts_and_fill_clocks_are_immutable(world):
    w=world;w.s.settle_paper(w.a,w.receipt())
    for table in ('paper_settlement_receipts','fill_receipt_times'):
        for sql in (f'UPDATE {table} SET recorded_at=recorded_at',f'DELETE FROM {table}'):
            with pytest.raises(sqlite3.IntegrityError):
                with w.repo.transaction() as db:db.execute(sql)


@pytest.mark.parametrize('sql',["UPDATE paper_delivery_positions SET quantity=quantity+1",
    "UPDATE paper_delivery_positions SET cost=cost+1","DELETE FROM paper_delivery_positions",
    "UPDATE accounts SET realized=realized+1","UPDATE positions SET cost=cost+1"])
def test_recovery_refuses_corrupt_inventory_or_balances(world,sql):
    w=world;w.s.settle_paper(w.a,w.receipt())
    with w.repo.transaction() as db:db.execute(sql)
    with pytest.raises(Rejected,match='ledger'):w.s.reconcile(w.a)
    with w.repo.transaction() as db:assert db.one('SELECT state_known FROM accounts')['state_known']==0


def test_failure_after_mutations_rolls_back_receipt_and_delivery(world,monkeypatch):
    w=world;original=w.s.audit
    def fail(db,account,event,detail):
        if event=='PAPER_SETTLEMENT':raise RuntimeError('fixture disk failure')
        return original(db,account,event,detail)
    monkeypatch.setattr(w.s,'audit',fail)
    with pytest.raises(RuntimeError):w.s.settle_paper(w.a,w.receipt())
    assert w.s.rows(w.a,'paper_delivery_positions')==[] and w.s.rows(w.a,'paper_settlement_receipts')==[]
    assert w.s.performance(w.a)['simulated_cash_cents']==9957870


def test_settlement_api_auth_strict_fields_and_account_scope(world):
    from fastapi.testclient import TestClient
    from app.main import create_app
    w=world;app=create_app(w.repo,token='fixture-only-token-not-a-secret')
    with TestClient(app) as client:
        app.state.service=w.s;url=f'/api/accounts/{w.a}/paper-settlements'
        assert client.post(url,json=w.receipt()).status_code==401
        headers={'Authorization':'Bearer fixture-only-token-not-a-secret'}
        assert client.post(url,json=w.receipt(quantity=True),headers=headers).status_code==422
        assert client.post(url,json=w.receipt(unknown=True),headers=headers).status_code==422
        assert client.post(url,json=w.receipt(),headers=headers).status_code==200
        assert len(client.get(url,headers=headers).json())==1
        other=w.s.create_account('separate')['id']
        assert client.get(f'/api/accounts/{other}/paper-deliveries',headers=headers).json()==[]
        assert client.post(f'/api/accounts/{other}/paper-settlements',json=w.receipt(),headers=headers).status_code==409
