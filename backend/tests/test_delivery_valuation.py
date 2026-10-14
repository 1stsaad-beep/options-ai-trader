from copy import deepcopy
from datetime import datetime, timedelta
import json
from pathlib import Path
import pytest
from app.delivery_valuation import value_deliveries

CASES=json.loads((Path(__file__).parents[2]/'mobile/test/fixtures/delivery_valuation_v1.json').read_text())['cases']

@pytest.mark.parametrize('case', CASES, ids=lambda c:c['name'])
def test_shared_hand_expected_delivery_values(case):
    before=deepcopy(case)
    assert value_deliveries(case['deliveries'],case['observations'],datetime.fromisoformat(case['now']),case['source'])==case['expected']
    assert case==before


def test_missing_one_share_mark_never_becomes_zero_value_or_hides_loss():
    c=deepcopy(CASES[0]);c['deliveries']['AAPL']={'quantity':1,'cost':100}
    result=value_deliveries(c['deliveries'],c['observations'],datetime.fromisoformat(c['now']),c['source'])
    assert not result['complete'] and result['valueCents'] is None and result['openLossCents'] is None
    assert result['basisCents']==2021265 and result['positions'][0]['valueCents']==2200000


def test_empty_deliveries_need_no_quotes():
    r=value_deliveries({}, {}, datetime.fromisoformat(CASES[0]['now']), 'fixture')
    assert r['complete'] and r['riskComplete'] and r['valueCents']==0

# Exercise the real accounting/journal join, using an injected offline provider.
from test_settlement_ledger import world  # noqa: F401
from app import market_data_journal as journal
from app.market_data import MODE
from app.service import Rejected


def capture(w, monkeypatch, *, key='mark', bid=220, account=None):
    monkeypatch.setattr(journal,'utc_now',lambda:w.now)
    class Provider:
        def stock_snapshot(self,symbol):
            at=w.now.isoformat()
            return dict(schema_version=1,provider='alpaca',mode=MODE,feed='iex',
                data={'symbol':symbol,'quote':{'timestamp':at,'bp':bid,'ap':221}},
                virtual_fills_enabled=False,external_orders_enabled=False,point_in_time_backtest_verified=False,
                usage='offline test fixture',usage_url='https://example.invalid/fixture',
                captured_at=at,last_page_captured_at=at,served_at=at)
    return journal.capture(w.s,account or w.a,dict(kind='stock_snapshot',symbol='NVDA',request_key=key),Provider())


def test_saved_share_marks_are_account_bound_read_only_and_time_limited(world,monkeypatch):
    w=world;w.s.settle_paper(w.a,w.receipt(quantity=2))
    other=w.s.create_account('other')['id'];w.s.watch(other,'NVDA',True)
    capture(w,monkeypatch,account=other)
    assert w.s.performance(w.a)['net_liquidation_cents'] is None
    saved=capture(w,monkeypatch)
    before=w.s.rows(w.a,'paper_settlement_receipts'),w.s.rows(w.a,'orders')
    report=w.s.performance(w.a)
    assert report['net_liquidation_cents']==10357770 and report['unrealized_pnl_cents']==357770
    assert report['delivery_valuation']['positions'][0]['status']=='IEX_PARTIAL_MARK'
    assert not report['delivery_valuation']['riskComplete']
    with pytest.raises(Rejected,match='Delivered stock valuation unavailable'):
        w.s.submit(w.a,w.order(request_key='still-blocked'))
    assert before==(w.s.rows(w.a,'paper_settlement_receipts'),w.s.rows(w.a,'orders'))
    w.restart();assert w.s.performance(w.a)['net_liquidation_cents']==10357770
    assert journal.replay(w.s,w.a,saved['id'])==saved
    w.now+=timedelta(seconds=31)
    assert w.s.performance(w.a)['net_liquidation_cents'] is None


def test_corrupt_latest_or_fractional_stock_quote_is_not_a_zero_or_rounded_mark(world,monkeypatch):
    w=world;w.s.settle_paper(w.a,w.receipt(quantity=2));capture(w,monkeypatch)
    # Deliberately corrupt only this disposable test database below its immutable trigger.
    with w.repo.transaction() as db:
        db.execute('DROP TRIGGER immutable_market_journal_v1_update')
        db.execute("UPDATE market_data_journal SET payload='{}' WHERE account_id=?",(w.a,))
    report=w.s.performance(w.a)
    assert report['net_liquidation_cents'] is None and report['delivery_valuation']['positions'][0]['status']=='INVALID'
    capture(w,monkeypatch,key='subcent',bid=220.001)
    assert w.s.performance(w.a)['net_liquidation_cents'] is None
