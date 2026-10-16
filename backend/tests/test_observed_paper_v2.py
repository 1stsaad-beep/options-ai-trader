from copy import deepcopy
from datetime import timedelta
import json
from pathlib import Path

import pytest

from app import observed_paper_v1 as legacy
from app.observed_paper import apply, create, validate, VERSION
from app.observed_paper_store import ObservedPaperStore
from app.observed_option_replay import iso
from app.repository import Repository
from test_observed_paper import AT, CALL, PUT, config, configured, observation, cycle, Clock


def test_new_version_preserves_old_saved_facts_and_hashes(tmp_path):
    saved=json.loads((Path(__file__).parents[2]/'mobile/test/fixtures/observed_server_v1.json').read_text())
    clock=Clock();repo=Repository('sqlite:///'+str(tmp_path/'old.db'),invalidate_accounts=False)
    store=ObservedPaperStore(repo,clock)
    events=saved['events']['events'];seed=events[0]['original']['command']['state']
    store.create(seed['id'],seed['name'],seed['initialCash'],seed['source'],version=legacy.VERSION)
    rebuilt=None
    for e in events:
        original=e['original'];clock.value=__import__('datetime').datetime.fromisoformat(original['at'].replace('Z','+00:00'))
        if e['version']==0:rebuilt=create(seed['id'],seed['name'],seed['initialCash'],seed['source'],version=legacy.VERSION)
        else:
            expected,facts=legacy.apply(rebuilt,original['command'],original['at'])
            rebuilt,newfacts=apply(rebuilt,original['command'],original['at'])
            assert rebuilt==expected and newfacts==facts==original['facts']
            # Request IDs are deliberately recovered from the known fixture contract.
            key=['create','config','enable','open','stop'][e['version']]
            result=store.command(seed['id'],key,original['command'],expected_version=e['version']-1,
                lease=store.acquire('fixture') if original['command']['kind']=='CYCLE' else None)
            assert result['eventHash']==e['eventHash']
    assert store.snapshot(seed['id'],full=True)==saved['snapshot'];repo.close()


def test_add_requires_new_signal_profitable_owned_quote_and_only_once():
    state,_=cycle(configured(addEnabled=True,quantity=1),observation())
    same,facts=cycle(state,observation(AT+timedelta(seconds=1),bid=120,ask=125))
    assert not facts['fills'] and not same['positions']['NVDA']['added']
    added,facts=cycle(same,observation(AT+timedelta(minutes=1),bid=120,ask=125))
    assert len(facts['fills'])==1 and facts['fills'][0]['reason']=='ADD_ON_QUALIFIED_QUOTE'
    assert added['positions']['NVDA']['quantity']==2 and added['positions']['NVDA']['added']
    assert added['cash']+added['positions']['NVDA']['cost']==added['initialCash']
    again,facts=cycle(added,observation(AT+timedelta(minutes=2),bid=130,ask=135))
    assert not facts['fills'] and again['positions']['NVDA']['quantity']==2


@pytest.mark.parametrize('overrides,reason',[
    ({'maxContracts':1},'POSITION_OR_QUANTITY_LIMIT'),
    ({'riskPercent':2},'TRADE_RISK_LIMIT'),
    ({'allocationPercent':2},'ALLOCATION_RISK_LIMIT'),
])
def test_add_obeys_total_owned_basis_and_portfolio_limits(overrides,reason):
    state,_=cycle(configured(addEnabled=True,quantity=1,**overrides),observation())
    unchanged,facts=cycle(state,observation(AT+timedelta(minutes=1),bid=120,ask=125))
    assert not facts['fills'] and facts['blocked']==[{'symbol':'NVDA','reason':reason}]
    assert unchanged['positions']['NVDA']['quantity']==1


def test_add_does_not_need_new_position_slot_but_never_adds_after_partial_exit():
    state,_=cycle(configured(addEnabled=True,quantity=1,maxPositions=1),observation())
    added,facts=cycle(state,observation(AT+timedelta(minutes=1),bid=120,ask=125))
    assert added['positions']['NVDA']['quantity']==2
    partial,facts=cycle(added,observation(AT+timedelta(minutes=2),bid=150,ask=155,size=4))
    assert len(facts['fills'])==1 and facts['fills'][0]['side']=='SELL_TO_CLOSE'


@pytest.mark.parametrize('direction',['CALL','PUT'])
def test_saved_scenario_break_retains_owned_exit_without_quote(direction):
    state,_=cycle(configured(quantity=2,scenarioExit=True),observation(direction=direction))
    level=state['positions']['NVDA']['scenarioLevel'];obs=observation(AT+timedelta(minutes=1),direction=direction)
    price=level-2 if direction=='CALL' else level+2
    row=obs['bars']['NVDA'][-1];row.update(o=price,h=price+1,l=price-1,c=price);obs['quotes']=[]
    retained,facts=cycle(state,obs)
    assert not facts['fills'] and retained['positions']['NVDA']['closeIntent']['reason']=='SCENARIO_EXIT'
    final,facts=cycle(retained,observation(AT+timedelta(minutes=1,seconds=1),direction=direction,bars=False))
    assert not final['positions'] and facts['fills'][0]['reason']=='SCENARIO_EXIT'


def test_missing_optional_source_never_hides_protection_or_invents_scenario():
    state,_=cycle(configured(scenarioExit=True,addEnabled=True),observation())
    before=deepcopy(state)
    held,facts=cycle(state,observation(AT+timedelta(minutes=1),bid=120,ask=125,bars=False))
    assert not facts['fills'] and held['positions']['NVDA']['closeIntent'] is None and before==state
    closed,facts=cycle(held,observation(AT+timedelta(minutes=1,seconds=1),bid=70,ask=75,bars=False))
    assert not closed['positions'] and facts['fills'][0]['reason']=='STOP_LOSS'


def test_market_add_remains_blocked_without_qualified_terms_and_greeks():
    state,_=cycle(configured(addEnabled=True),observation());state['source']='alpaca'
    obs=observation(AT+timedelta(minutes=1),bid=120,ask=125);obs['source']='alpaca'
    held,facts=cycle(state,obs)
    assert not facts['fills'] and facts['blocked'][0]['reason']=='CONTRACT_ELIGIBILITY_UNVERIFIED'
    assert held['positions']['NVDA']['quantity']==1


def test_strict_version_lifecycle_types_and_original_scenario():
    assert create('a','A',1000000,'fixture')['contract']==VERSION
    with pytest.raises(ValueError):create('a','A',1000000,'fixture',version='unknown')
    state,_=cycle(configured(),observation())
    for field,bad in [('added',1),('scenarioLevel',float('nan'))]:
        changed=deepcopy(state);changed['positions']['NVDA'][field]=bad
        with pytest.raises(ValueError):validate(changed)


def test_streamed_performance_counts_partial_roundtrip_and_fees_exactly(tmp_path,monkeypatch):
    from test_observed_paper import stored
    from app.repository import Session
    repo,store,clock=stored(tmp_path);lease=store.acquire('performance')
    store.command('a','open',{'kind':'CYCLE','observation':observation()},expected_version=2,lease=lease)
    store.command('a','close',{'kind':'REQUEST_CLOSE','symbol':'NVDA'})
    store.command('a','partial',{'kind':'CYCLE','observation':observation(clock.step(),bid=120,ask=125,size=4)},expected_version=4,lease=lease)
    partial=store.performance('a')
    assert partial['closedQuoteRoundTrips']==0 and partial['realizedPnlCents']==1160
    assert partial['liquidationEquityCents'] is None and partial['sharpe'] is None
    store.command('a','finish',{'kind':'CYCLE','observation':observation(clock.step(),bid=90,ask=95)},expected_version=5,lease=lease)
    # No all-events list is permitted in reporting.
    old=Session.all
    def bounded(self,sql,*args):
        assert 'observed_paper_events' not in sql
        return old(self,sql,*args)
    monkeypatch.setattr(Session,'all',bounded)
    result=store.performance('a')
    assert result['realizedPnlCents']==-2520 and result['maximumRealizedDrawdownCents']==3680
    assert result['feesCents']==420 and result['closedQuoteRoundTrips']==1 and result['quoteWinRatePercent']==0
    assert result['quoteGrossLossCents']==2520 and result['quoteProfitFactor']==0
    assert result['buyContracts']==3 and result['sellContracts']==3 and result['eventCount']==7
    assert result['cashCents']==result['bookCapitalCents']==997480
    repo.close()


def test_streamed_performance_excludes_delivery_from_quote_win_rate(tmp_path):
    repo=Repository('sqlite:///'+str(tmp_path/'settlement.db'),invalidate_accounts=False);clock=Clock();store=ObservedPaperStore(repo,clock)
    store.create('a','A',10000000)
    store.command('a','config',{'kind':'CONFIGURE','config':config()});store.command('a','enable',{'kind':'ENABLE','enabled':True})
    store.command('a','open',{'kind':'CYCLE','observation':observation()},expected_version=2,lease=store.acquire('worker'))
    store.command('a','stop',{'kind':'ENABLE','enabled':False})
    receipt={'id':'exercise','action':'EXERCISE','contract':CALL,'quantity':1,'feeCents':100,'underlyingCents':15500,
        'effectiveAt':iso(clock.step()),'recordedAt':iso(clock()),'source':'fixture','reference':'fixture owned Call'}
    store.command('a','exercise',{'kind':'SETTLE','request':receipt})
    result=store.performance('a')
    assert result['settlementAffectedClosuresExcluded']==1 and result['closedQuoteRoundTrips']==0
    assert result['realizedPnlCents']==0 and result['feesCents']==170 and result['quoteWinRatePercent'] is None
    receipt=receipt|{'id':'dispose','action':'SELL_DELIVERY','quantity':100,'effectiveAt':iso(clock.step()),'recordedAt':iso(clock())}
    store.command('a','dispose',{'kind':'SETTLE','request':receipt})
    result=store.performance('a')
    assert result['realizedPnlCents']==39130 and result['feesCents']==270 and result['ownedBasisCents']==0
    assert result['settlementReceipts']==2 and result['quoteProfitFactor'] is None
    repo.close()


def test_version_two_saved_mobile_fixture_is_reproducible():
    import sys
    root=Path(__file__).parents[2];sys.path.insert(0,str(root/'scripts'))
    from generate_observed_server_fixture import generate
    assert generate(VERSION)==json.loads((root/'mobile/test/fixtures/observed_server_v2.json').read_text())
