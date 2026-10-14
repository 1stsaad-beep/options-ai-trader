from copy import deepcopy
from datetime import datetime, timezone
import pytest
from app.paper_settlement import project

NOW = datetime(2026, 10, 17, 15, tzinfo=timezone.utc)
CALL = 'NVDA261016C00200000'
PUT = 'NVDA261016P00200000'


def receipt(action='EXERCISE', contract=CALL, quantity=1, **changes):
    return dict(id='receipt-1', action=action, contract=contract, quantity=quantity,
                feeCents=100, underlyingCents=21000, effectiveAt='2026-10-16T20:00:00Z',
                recordedAt='2026-10-17T14:00:00Z', source='fixture', reference='observed-paper', **changes)


def position(contract=CALL, quantity=2):
    return dict(contract=contract, quantity=quantity, cost=42000, entryFees=130, opened='2026-10-13T15:00:00Z')


def test_call_converts_premium_and_fees_to_delivered_stock_basis():
    p=position();before=deepcopy(p)
    r=project(p,None,3000000,receipt(),NOW)
    assert (r['cashDelta'],r['shareDelta'],r['shareBasisDelta'],r['realizedPnl'])==(-2000100,100,2021165,0)
    assert (r['removedCost'],r['removedEntryFees'])==(21000,65)
    assert p==before and r['externalOrder'] is False


def test_put_delivery_consumes_owned_stock_and_option_basis():
    r=project(position(PUT),{'quantity':200,'cost':3800000},100000,receipt(contract=PUT),NOW)
    assert (r['cashDelta'],r['shareDelta'],r['shareBasisDelta'],r['realizedPnl'])==(1999900,-100,-1900000,78835)


def test_delivery_sale_partial_cost_allocation():
    r=project(None,{'quantity':100,'cost':2021165},0,receipt('SELL_DELIVERY',quantity=33),NOW)
    assert r['shareDelta']==-33 and r['shareBasisDelta']==-(2021165*33//100)
    assert r['realizedPnl']==21000*33-100-2021165*33//100


def test_expiry_is_not_a_fictitious_option_fill():
    req=receipt('EXPIRE_WORTHLESS');req['underlyingCents']=20000
    r=project(position(),None,100000,req,NOW)
    assert r['cashDelta']==-100 and r['realizedPnl']==-21165 and r['optionQuantity']==1


@pytest.mark.parametrize('change',[
    {'source':'broker'}, {'action':'ASSIGNMENT'}, {'action':'CASH_SETTLEMENT'},
    {'quantity':3}, {'quantity':True}, {'feeCents':-1}, {'underlyingCents':0},
    {'effectiveAt':'2026-10-16T20:00:01Z'}, {'effectiveAt':'2026-10-12T12:00:00Z'},
    {'recordedAt':'2026-10-18T00:00:00Z'}, {'effectiveAt':'2026-10-16T20:00:00'},
    {'contract':'NVDA261016C00200001'}, {'contract':'NVDA261332C00200000'},
])
def test_invalid_receipts_never_produce_deltas(change):
    req=receipt();req.update(change)
    with pytest.raises(ValueError):project(position(),None,3000000,req,NOW)


def test_call_needs_full_strike_cash_and_put_needs_full_deliverable():
    with pytest.raises(ValueError):project(position(),None,2000099,receipt(),NOW)
    with pytest.raises(ValueError):project(position(PUT),{'quantity':99,'cost':1},3000000,receipt(contract=PUT),NOW)


@pytest.mark.parametrize('contract,spot',[(CALL,20001),(PUT,19999)])
def test_itm_cannot_be_written_off_as_worthless(contract,spot):
    req=receipt('EXPIRE_WORTHLESS',contract);req['underlyingCents']=spot
    with pytest.raises(ValueError):project(position(contract),None,100000,req,NOW)


def test_worthless_event_requires_exact_cutoff_observation():
    req=receipt('EXPIRE_WORTHLESS');req.update(underlyingCents=19000,effectiveAt='2026-10-16T19:59:00Z')
    with pytest.raises(ValueError):project(position(),None,100000,req,NOW)


def test_checked_in_cross_language_receipts_match_python():
    import json
    from pathlib import Path
    cases=json.loads((Path(__file__).parents[2]/'mobile/test/fixtures/paper_settlement_v1.json').read_text())['cases']
    for c in cases:
        if c.get('rejected'):
            with pytest.raises(ValueError):project(c['position'],c['delivery'],c['cash'],c['request'],datetime.fromisoformat(c['now']))
        else:
            assert project(c['position'],c['delivery'],c['cash'],c['request'],datetime.fromisoformat(c['now']))==c['expected']
