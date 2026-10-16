from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3

import pytest

from app.observed_paper import DEFAULTS, apply, create, validate
from app.observed_paper_store import ObservedPaperStore, LedgerConflict
from app.observed_option_replay import iso
from app.repository import Repository

AT=datetime(2026,10,13,15,tzinfo=timezone.utc)
CALL='NVDA261023C00150000'
PUT='NVDA261023P00150000'
FIXTURE=json.loads((Path(__file__).parents[2]/'mobile/test/fixtures/market_strategy_v1.json').read_text())


def config(**values):
    return deepcopy(DEFAULTS)|{'contracts':{'NVDA':{'CALL':CALL,'PUT':PUT}}}|values


def observation(at=AT, *, bid=100, ask=105, size=40, bars=True, direction='CALL', contract=None):
    rows=deepcopy(FIXTURE['cases'][2 if direction=='CALL' else 0]['bars'])
    offset=at-AT
    for b in rows: b['at']=iso(datetime.fromisoformat(b['at'])+offset)
    return {'source':'fixture','capturedAt':iso(at),'stockFeed':'iex',
        'quotes':[{'contract':contract or (CALL if direction=='CALL' else PUT),'feed':'opra','at':iso(at),
            'bid':bid,'ask':ask,'bidSize':size,'askSize':size}],
        'bars':{'NVDA':rows} if bars else {}}


def configured(**values):
    state=create('a','A',1000000,'fixture')
    state,_=apply(state,{'kind':'CONFIGURE','config':config(**values)},iso(AT))
    return apply(state,{'kind':'ENABLE','enabled':True},iso(AT))[0]


def cycle(state,obs):
    return apply(state,{'kind':'CYCLE','observation':obs},obs['capturedAt'])


class Clock:
    def __init__(self): self.value=AT
    def __call__(self): return self.value
    def step(self,seconds=1): self.value+=timedelta(seconds=seconds); return self.value


def stored(tmp_path):
    repo=Repository('sqlite:///'+str(tmp_path/'observed.db'),invalidate_accounts=False)
    clock=Clock(); store=ObservedPaperStore(repo,clock)
    store.create('a','A')
    store.command('a','config',{'kind':'CONFIGURE','config':config(quantity=3)})
    store.command('a','enable',{'kind':'ENABLE','enabled':True})
    return repo,store,clock


@pytest.mark.parametrize('direction',['CALL','PUT'])
def test_qualified_entry_and_protection_without_optional_bars(direction):
    original=configured(quantity=3); before=deepcopy(original)
    opened,facts=cycle(original,observation(direction=direction))
    assert original==before and facts['fills'][0]['execution']['quantity']==3
    assert opened['cash']==1000000-3*(106*100+70)
    obs=observation(AT+timedelta(seconds=1),bid=70,ask=74,bars=False,direction=direction)
    closed,facts=cycle(opened,obs)
    assert not closed['positions'] and facts['fills'][0]['reason']=='STOP_LOSS'
    assert closed['cash']==1000000+3*((69-106)*100-140)
    assert closed['fees']==420 and closed['closedTrades']==1 and closed['winningTrades']==0
    validate(closed)


def test_residual_close_exactly_once_and_explicit_stop_survives_restart(tmp_path):
    repo,store,clock=stored(tmp_path); lease=store.acquire('first')
    receipt=store.command('a','open',{'kind':'CYCLE','observation':observation()},expected_version=2,lease=lease)
    store.command('a','close',{'kind':'REQUEST_CLOSE','symbol':'NVDA'})
    store.command('a','stop',{'kind':'ENABLE','enabled':False})
    obs=observation(clock.step(),bid=110,ask=115,size=4,bars=False)
    command={'kind':'CYCLE','observation':obs}
    partial=store.command('a','partial',command,expected_version=5,lease=lease)
    assert store.command('a','partial',command,expected_version=5,lease=lease)==partial
    snap=store.snapshot('a'); assert snap['state']['positions']['NVDA']['closeIntent']['quantity']==2
    # Same observed display cannot be reused, even under a different operation ID.
    store.command('a','same-quote',command,expected_version=6,lease=lease)
    assert store.snapshot('a')['state']['positions']['NVDA']['quantity']==2
    repo.close()
    repo=Repository('sqlite:///'+str(tmp_path/'observed.db'),invalidate_accounts=False)
    reopened=ObservedPaperStore(repo,clock)
    assert reopened.snapshot('a',full=True)['state']['positions']['NVDA']['quantity']==2
    assert reopened.acquire('second') is None
    clock.step(31); nextlease=reopened.acquire('second')
    with pytest.raises(LedgerConflict,match='ownership'):
        reopened.command('a','old-owner',{'kind':'CYCLE','observation':observation(clock(),bars=False)},expected_version=7,lease=lease)
    result=reopened.command('a','finish',{'kind':'CYCLE','observation':observation(clock(),bid=110,ask=115,bars=False)},expected_version=7,lease=nextlease)
    assert result['facts']['fills'][0]['execution']['quantity']==2
    assert not reopened.snapshot('a',full=True)['state']['positions']
    assert not reopened.snapshot('a')['state']['enabled']
    with repo.transaction() as db: assert db.one('SELECT COUNT(*) AS n FROM accounts')['n']==0
    repo.close()


@pytest.mark.parametrize('mutation',[
    lambda o:o['quotes'][0].update(feed='indicative'),
    lambda o:o['quotes'][0].update(at=iso(AT-timedelta(seconds=31))),
    lambda o:o['quotes'][0].update(at=iso(AT+timedelta(seconds=1))),
    lambda o:o['quotes'][0].update(bidSize=True),
    lambda o:o['quotes'][0].update(ask=200),
    lambda o:o['quotes'].append(deepcopy(o['quotes'][0])),
    lambda o:o['bars']['NVDA'][-1].update(at=iso(AT)),
    lambda o:o['bars']['NVDA'][-2].update(at=o['bars']['NVDA'][-1]['at']),
    lambda o:o.update(stockFeed='synthetic'),
])
def test_unqualified_sources_cannot_open(mutation):
    state=configured(); obs=observation(); mutation(obs)
    result,facts=cycle(state,obs)
    assert not result['positions'] and not facts['fills']


def test_stop_priority_partial_upgrade_and_overdue_intraday():
    state,_=cycle(configured(quantity=3),observation())
    partial,_=cycle(state,observation(AT+timedelta(seconds=1),bid=133,ask=138,size=4,bars=False))
    assert partial['positions']['NVDA']['closeIntent']['reason']=='PARTIAL_PROFIT'
    stopped,facts=cycle(partial,observation(AT+timedelta(seconds=2),bid=70,ask=74,bars=False))
    assert not stopped['positions'] and facts['fills'][0]['reason']=='STOP_LOSS'
    tomorrow,facts=cycle(state,observation(AT+timedelta(days=1),bars=False))
    assert not tomorrow['positions'] and facts['fills'][0]['reason']=='INTRADAY_EXIT'


def test_quote_chronology_cannot_reuse_changed_display():
    state,_=cycle(configured(quantity=3),observation())
    state,_=apply(state,{'kind':'REQUEST_CLOSE','symbol':'NVDA'},iso(AT))
    ambiguous=observation(bid=101,ask=106,bars=False)
    unchanged,facts=cycle(state,ambiguous)
    assert not facts['fills'] and unchanged['positions']['NVDA']['quantity']==3


def test_cas_stop_during_capture_and_duplicate_identity(tmp_path):
    repo,store,clock=stored(tmp_path); lease=store.acquire('worker')
    store.command('a','stop',{'kind':'ENABLE','enabled':False})
    with pytest.raises(LedgerConflict,match='changed'):
        store.command('a','stale',{'kind':'CYCLE','observation':observation()},expected_version=2,lease=lease)
    with pytest.raises(LedgerConflict,match='different'):
        store.command('a','stop',{'kind':'ENABLE','enabled':True})
    assert not store.snapshot('a')['state']['positions']
    repo.close()


def test_sql_immutability_snapshot_tamper_and_atomic_rollback(tmp_path,monkeypatch):
    repo,store,clock=stored(tmp_path)
    before=store.snapshot('a')
    with pytest.raises(sqlite3.IntegrityError):
        with repo.transaction() as db: db.execute('DELETE FROM observed_paper_events')
    original=store._append
    def fail(*args,**kwargs):
        original(*args,**kwargs); raise OSError('simulated write failure')
    monkeypatch.setattr(store,'_append',fail)
    with pytest.raises(OSError): store.command('a','stop',{'kind':'ENABLE','enabled':False})
    assert store.snapshot('a',full=True)==before
    with repo.transaction() as db:
        value=deepcopy(before['state']); value['cash']+=1
        db.execute('UPDATE observed_paper_accounts SET payload=? WHERE id=?',(json.dumps(value),'a'))
    with pytest.raises(LedgerConflict,match='offline review'): store.snapshot('a')
    repo.close()


def test_segment_rotation_streamed_replay_and_sealed_guard(tmp_path,monkeypatch):
    import app.observed_paper_store as module
    monkeypatch.setattr(module,'SEGMENT_EVENTS',3)
    repo,store,clock=stored(tmp_path)
    for i in range(7): store.command('a','toggle'+str(i),{'kind':'ENABLE','enabled':bool(i%2)})
    assert store.snapshot('a',full=True)['version']==9
    assert len(store.events('a',after=2,limit=2))==2
    with repo.transaction() as db:
        rows=db.all('SELECT * FROM observed_paper_segments ORDER BY number')
        assert len(rows)==4 and [r['sealed'] for r in rows]==[1,1,1,0]
    with pytest.raises(sqlite3.IntegrityError):
        with repo.transaction() as db: db.execute('UPDATE observed_paper_segments SET size_bytes=1 WHERE number=1')
    repo.close()


def receipt(action,at,qty=1,contract=CALL,spot=16000):
    return {'id':'receipt1','action':action,'contract':contract,'quantity':qty,'feeCents':10,
        'underlyingCents':spot,'effectiveAt':iso(at),'recordedAt':iso(at),'source':'fixture','reference':'explicit fixture receipt'}


def test_call_delivery_stock_disposal_and_receipt_idempotence(tmp_path):
    repo,store,clock=stored(tmp_path)
    # Funded capital needed for standard stock delivery is explicit.
    store.command('a','stop',{'kind':'ENABLE','enabled':False})
    store.create('funded','Funded',10000000)
    store.command('funded','config',{'kind':'CONFIGURE','config':config()})
    store.command('funded','enable',{'kind':'ENABLE','enabled':True})
    lease=store.acquire('worker')
    store.command('funded','buy',{'kind':'CYCLE','observation':observation()},expected_version=2,lease=lease)
    store.command('funded','stop',{'kind':'ENABLE','enabled':False})
    command={'kind':'SETTLE','request':receipt('EXERCISE',clock.step())}
    settled=store.command('funded','exercise',command)
    assert store.command('funded','exercise',command)==settled
    with pytest.raises(LedgerConflict,match='already recorded'): store.command('funded','duplicate',command)
    state=store.snapshot('funded',full=True)['state']
    assert not state['positions'] and state['deliveries']['NVDA']['quantity']==100
    sale=receipt('SELL_DELIVERY',clock.step(),qty=100); sale['id']='sell'
    store.command('funded','sell',{'kind':'SETTLE','request':sale})
    state=store.snapshot('funded',full=True)['state']
    assert not state['deliveries'] and state['cash']==10000000+100000-10670-20
    repo.close()


def test_unfunded_exercise_and_stale_capture_are_rejected_without_mutation():
    state,_=cycle(configured(),observation()); state,_=apply(state,{'kind':'ENABLE','enabled':False},iso(AT))
    original=deepcopy(state)
    with pytest.raises(ValueError): apply(state,{'kind':'SETTLE','request':receipt('EXERCISE',AT)},iso(AT))
    with pytest.raises(ValueError): apply(state,{'kind':'CYCLE','observation':observation()},iso(AT+timedelta(seconds=9)))
    assert state==original


@pytest.mark.parametrize('limits,reason',[
    ({'quantity':20},'TRADE_RISK_LIMIT'),
    ({'allocationPercent':1},'ALLOCATION_RISK_LIMIT'),
    ({'quantity':3,'maxContracts':2},'POSITION_OR_QUANTITY_LIMIT'),
])
def test_risk_limits_checked_against_adverse_actual_fill(limits,reason):
    state=configured(**limits)
    after,facts=cycle(state,observation())
    assert not after['positions'] and facts['blocked'][0]['reason']==reason


def test_live_label_never_converts_fixture_contract_terms_to_eligibility():
    state=configured(); state['source']='alpaca'; obs=observation(); obs['source']='alpaca'
    result,facts=cycle(state,obs)
    assert not result['positions'] and facts['blocked'][0]['reason']=='CONTRACT_ELIGIBILITY_UNVERIFIED'


def test_put_requires_stock_acquisition_then_disposal_without_short_inventory():
    state=create('funded','Funded',10000000,'fixture')
    state,_=apply(state,{'kind':'CONFIGURE','config':config()},iso(AT))
    state,_=apply(state,{'kind':'ENABLE','enabled':True},iso(AT))
    state,_=cycle(state,observation(direction='PUT'))
    state,_=apply(state,{'kind':'ENABLE','enabled':False},iso(AT))
    with pytest.raises(ValueError,match='requires owned'):
        apply(state,{'kind':'SETTLE','request':receipt('EXERCISE',AT,contract=PUT)},iso(AT))
    buy=receipt('BUY_FOR_PUT',AT,qty=100,contract=PUT,spot=14000)
    state,_=apply(state,{'kind':'SETTLE','request':buy},iso(AT))
    result,facts=apply(state,{'kind':'SETTLE','request':receipt('EXERCISE',AT,contract=PUT,spot=14000)},iso(AT))
    assert not result['deliveries'] and not result['positions']
    assert result['realized']==100000-10670-20 and result['cash']==10000000+result['realized']
    validate(result)
