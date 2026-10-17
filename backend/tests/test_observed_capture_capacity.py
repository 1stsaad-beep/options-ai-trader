"""Offline bounded-demand/recovery tests; no provider session or entitlement proof."""
import json
from types import SimpleNamespace

import pytest

from app.market_data import DataResponse, MarketDataError
from app.observed_paper_data import ObservedPaperData
from app.observed_paper_runtime import ObservedPaperRuntime
from app.observed_paper_status import status
from app.observed_paper_alerts import page
from test_observed_paper import stored, observation, CALL, iso


def symbol(i): return chr(65+i//26)+chr(65+i%26)
def contract(i): return symbol(i)+'261023C00150000'

def demands(count, *, owned=True):
    states=[]
    for start in range(0,count,10):
        symbols=[symbol(i) for i in range(start,min(count,start+10))]
        states.append({'enabled':True,'positions':{s:{'contract':s+'261023C00150000'} for s in symbols} if owned else {},
            'config':{'contracts':{s:{'CALL':s+'261023C00150000'} for s in symbols}}})
    return states


def transport(clock):
    calls=[]
    def get(path,params):
        calls.append((path,dict(params)))
        symbols=params['symbols'].split(',')
        if path.endswith('/bars'):
            return DataResponse(200,{}, {'bars':{s:[] for s in symbols},'next_page_token':None})
        return DataResponse(200,{}, {'quotes':{s:{'t':iso(clock()),'bp':1,'ap':1.05,'bs':40,'as':40} for s in symbols}})
    return SimpleNamespace(get=get),calls


def test_owned_quotes_survive_large_optional_demand_and_last_budget_slot(tmp_path):
    repo,store,clock=stored(tmp_path); store.command('a','open',{'kind':'CYCLE','observation':observation()},lease=store.acquire('fixture'),expected_version=2)
    before=store.snapshot('a',full=True);state=before['state'];wire,calls=transport(clock)
    provider=ObservedPaperData(store,wire,requests_per_minute=2);provider.lease=store.acquire('fixture')
    provider.request('/v1beta1/options/quotes/latest',{'symbols':CALL,'feed':'opra'})
    got=provider.capture([state]+demands(80,owned=False),provider.lease)
    assert CALL in {q['contract'] for q in got['quotes']} and len(got['quotes'])==30
    assert got['bars']=={} and provider.coverage_limited
    assert len(calls)==2 and all(p.endswith('/quotes/latest') for p,_ in calls)
    assert store.snapshot('a',full=True)==before
    repo.close()


def test_round_robin_survives_restart_and_covers_more_than_batch_limit(tmp_path):
    repo,store,clock=stored(tmp_path); wire,calls=transport(clock)
    batches=[]
    for _ in range(4):
        provider=ObservedPaperData(store,wire)
        got=provider.capture(demands(40),store.acquire('fixture'))
        batches.append({q['contract'] for q in got['quotes']})
        assert len(got['quotes'])==30 and len(got['bars'])==10 and provider.coverage_limited
        clock.step(15)
    assert batches[0]!=batches[1] and batches[0]|batches[1]=={contract(i) for i in range(40)}
    assert len(calls)==8
    with repo.transaction() as db:
        assert set(json.loads(db.one("SELECT payload FROM observed_paper_data_state WHERE name='capture_cursor'")['payload']))=={'version','quotes','bars'}
    repo.close()


def test_fixed_ownership_never_starved_by_optional_rotation(tmp_path):
    repo,store,clock=stored(tmp_path);wire,calls=transport(clock); batches=[]
    states=demands(3)+demands(60,owned=False)
    for _ in range(3):
        provider=ObservedPaperData(store,wire)
        got=provider.capture(states,store.acquire('fixture'))
        chosen={q['contract'] for q in got['quotes']};batches.append(chosen)
        assert {contract(i) for i in range(3)}<=chosen
        clock.step(15)
    assert set.union(*batches)=={contract(i) for i in range(60)}
    repo.close()


def test_request_failure_commits_rotation_but_rejected_reservation_does_not(tmp_path):
    repo,store,clock=stored(tmp_path)
    calls=[]
    def failed(path,params):
        calls.append((path,params));raise OSError('secret connection text')
    provider=ObservedPaperData(store,SimpleNamespace(get=failed));lease=store.acquire('fixture')
    # Stopped demand needs only owned quotes, not optional analysis bars.
    states=demands(40)
    for state in states: state['enabled']=False
    with pytest.raises(MarketDataError,match='DATA_UNAVAILABLE'): provider.capture(states,lease)
    with repo.transaction() as db: saved=db.one("SELECT payload FROM observed_paper_data_state WHERE name='capture_cursor'")['payload']
    with pytest.raises(MarketDataError,match='DATA_RATE_LIMITED'): provider.capture(states,lease)
    with repo.transaction() as db: assert db.one("SELECT payload FROM observed_paper_data_state WHERE name='capture_cursor'")['payload']==saved
    assert len(calls)==1
    clock.step(6);wire,next_calls=transport(clock);provider=ObservedPaperData(store,wire)
    got=provider.capture(states,store.acquire('fixture'))
    assert len(got['quotes'])==30 and set(calls[0][1]['symbols'].split(','))|{q['contract'] for q in got['quotes']}=={contract(i) for i in range(40)}
    repo.close()


@pytest.mark.parametrize('value',[{}, {'version':True,'quotes':None,'bars':None}, {'version':1,'quotes':'secret','bars':None},
    {'version':1,'quotes':None,'bars':['secret']}, 'secret raw json'])
def test_bad_cursor_never_reset_or_sent_to_provider(tmp_path,value):
    repo,store,clock=stored(tmp_path);wire,calls=transport(clock)
    encoded=json.dumps(value)
    with repo.transaction() as db:db.execute("INSERT INTO observed_paper_data_state VALUES('capture_cursor',?)",(encoded,))
    provider=ObservedPaperData(store,wire)
    with pytest.raises(MarketDataError,match='DATA_STATE_REVIEW_REQUIRED'):provider.capture(demands(1),store.acquire('fixture'))
    assert not calls
    with repo.transaction() as db:assert db.one("SELECT payload FROM observed_paper_data_state WHERE name='capture_cursor'")['payload']==encoded
    repo.close()


def test_expired_owner_cannot_rotate_or_read_provider(tmp_path):
    repo,store,clock=stored(tmp_path);wire,calls=transport(clock);lease=store.acquire('old');clock.step(31);store.acquire('new')
    with pytest.raises(MarketDataError,match='WORKER_LEASE_LOST'):ObservedPaperData(store,wire).capture(demands(40),lease)
    assert not calls
    with repo.transaction() as db:assert db.one("SELECT payload FROM observed_paper_data_state WHERE name='capture_cursor'") is None
    repo.close()


def test_partial_member_warning_is_durable_and_does_not_suppress_owned_close(tmp_path):
    repo,store,clock=stored(tmp_path);lease=store.acquire('fixture')
    store.command('a','open',{'kind':'CYCLE','observation':observation()},lease=lease,expected_version=2)
    store.command('a','close',{'kind':'REQUEST_CLOSE','symbol':'NVDA'});clock.step()
    def get(path,params):
        if path.endswith('/bars'):return DataResponse(200,{}, {'bars':{},'next_page_token':'incomplete'})
        return DataResponse(200,{}, {'quotes':{CALL:{'t':iso(clock()),'bp':1,'ap':1.05,'bs':40,'as':40}}})
    data=ObservedPaperData(store,SimpleNamespace(get=get))
    def capture(states,lease):
        result=data.capture(states,lease)
        provider.coverage_limited=data.coverage_limited
        return result|{'source':'fixture'}  # Explicit offline fixture adapter, never a market attestation.
    provider=SimpleNamespace(source='fixture',capture=capture,coverage_limited=False)
    result=ObservedPaperRuntime(store,provider,owner='fixture').tick()
    assert result['diagnosticCode']=='OBSERVED_PARTIAL_COVERAGE'
    assert not store.snapshot('a',full=True)['state']['positions']
    assert 'OBSERVED_PARTIAL_COVERAGE' in status(store)['alerts']
    assert page(store)['events'][-1]['active']==['OBSERVED_PARTIAL_COVERAGE']
    repo.close()


def test_sustained_bounded_selection_uses_original_quotes_and_retains_all_receipts(tmp_path):
    repo,store,clock=stored(tmp_path);before=store.snapshot('a',full=True);wire,calls=transport(clock)
    states=demands(40);seen=set()
    for i in range(240):
        provider=ObservedPaperData(store,wire,requests_per_minute=10)
        got=provider.capture(states,store.acquire('fixture'))
        assert len(got['quotes'])==30 and len(got['bars'])==10
        assert all(q['at']==iso(clock()) for q in got['quotes'])
        seen.update(q['contract'] for q in got['quotes'])
        if i%2: assert seen=={contract(n) for n in range(40)};seen.clear()
        clock.step(15)
    assert len(calls)==480
    assert store.snapshot('a',full=True)==before
    repo.close()


def test_oversized_peer_quote_cannot_suppress_valid_owned_quote(tmp_path):
    repo,store,clock=stored(tmp_path)
    store.command('a','open',{'kind':'CYCLE','observation':observation()},expected_version=2,lease=store.acquire('fixture'))
    clock.step()
    from test_observed_paper import PUT
    def get(path,params):
        if path.endswith('/bars'):return DataResponse(200,{}, {'bars':{},'next_page_token':None})
        valid={'t':iso(clock()),'bp':1,'ap':1.05,'bs':40,'as':40}
        return DataResponse(200,{}, {'quotes':{PUT:valid|{'bp':10**400},CALL:valid}})
    provider=ObservedPaperData(store,SimpleNamespace(get=get))
    result=provider.capture([store.snapshot('a')['state']],store.acquire('fixture'))
    assert [q['contract'] for q in result['quotes']]==[CALL]
    assert provider.coverage_limited
    assert store.snapshot('a',full=True)['state']['positions']['NVDA']['quantity']==3
    repo.close()
