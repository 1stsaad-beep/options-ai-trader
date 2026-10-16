from copy import deepcopy
from datetime import timedelta
import json
import sqlite3
from types import SimpleNamespace

import pytest

from app.market_data import DataResponse, MarketDataError, allowed_query
from app.observed_paper_data import ObservedPaperData, cents
from app.observed_paper_runtime import ObservedPaperRuntime
from app.observed_paper_store import ObservedPaperStore, LedgerConflict
from app.observed_paper_worker import build_provider, reset_auth_lock, main
from app.repository import Repository
from app.runtime_health import probe_heartbeat
from test_observed_paper import stored, config, observation, iso, Clock, CALL


class FixtureProvider:
    source='fixture'
    def __init__(self,clock): self.clock=clock; self.calls=0
    def capture(self,states,lease): self.calls+=1; return observation(self.clock())


def test_worker_restart_fenced_batch_and_fixture_source_isolation(tmp_path):
    repo,store,clock=stored(tmp_path)
    store.create('real','Real',source='alpaca')
    store.command('real','enable',{'kind':'ENABLE','enabled':True})
    data=FixtureProvider(clock)
    runtime=ObservedPaperRuntime(store,data,owner='one')
    assert runtime.tick()['processed']==1
    assert store.snapshot('a')['state']['positions']['NVDA']['quantity']==3
    assert not store.snapshot('real')['state']['positions']
    other=ObservedPaperRuntime(ObservedPaperStore(repo,clock),data,owner='two')
    assert other.tick()['state']=='STANDBY' and data.calls==1
    runtime.close(); clock.step()
    assert other.tick()['processed']==1 and data.calls==2
    assert store.snapshot('a',full=True)['state']['positions']['NVDA']['quantity']==3
    with repo.transaction() as db:
        assert db.one('SELECT COUNT(*) AS n FROM accounts')['n']==0
        assert db.one('SELECT COUNT(*) AS n FROM orders')['n']==0
    assert probe_heartbeat('sqlite:///'+str(tmp_path/'observed.db'),'observed_paper',clock())
    repo.close()


def test_control_during_network_capture_cancels_admission(tmp_path):
    repo,store,clock=stored(tmp_path)
    def capture(states,lease):
        store.command('a','stop-in-flight',{'kind':'ENABLE','enabled':False})
        return observation(clock())
    runtime=ObservedPaperRuntime(store,SimpleNamespace(source='fixture',capture=capture))
    assert runtime.tick()['blocked']==1
    assert not store.snapshot('a')['state']['positions']
    repo.close()


def test_provider_latency_expires_lease_and_stale_source(tmp_path):
    repo,store,clock=stored(tmp_path)
    def capture(states,lease):
        saved=observation(clock()); clock.step(31); return saved
    runtime=ObservedPaperRuntime(store,SimpleNamespace(source='fixture',capture=capture))
    assert runtime.tick()['blocked']==1
    assert not store.snapshot('a')['state']['positions']
    repo.close()


def test_default_disabled_and_outside_session_never_capture(tmp_path,monkeypatch):
    repo,store,clock=stored(tmp_path)
    monkeypatch.delenv('OAT_OBSERVED_PAPER_APPROVAL',raising=False)
    monkeypatch.setenv('OAT_ALPACA_DATA_APPROVAL','read_only_approved')
    monkeypatch.setattr('app.observed_paper_worker.credentials_from_file',lambda *_:pytest.fail('Secret must not be read'))
    assert build_provider(store) is None
    runtime=ObservedPaperRuntime(store)
    assert runtime.tick()['state']=='DISABLED'; runtime.close()
    clock.step(6*3600); data=FixtureProvider(clock)
    assert ObservedPaperRuntime(store,data).tick()['state']=='SESSION_CLOSED'
    assert data.calls==0
    repo.close()


def test_disabled_cli_and_health_do_not_create_probe_database(tmp_path,monkeypatch,capsys):
    path=tmp_path/'worker.db'
    monkeypatch.setenv('DATABASE_URL','sqlite:///'+str(path))
    monkeypatch.delenv('OAT_OBSERVED_PAPER_APPROVAL',raising=False)
    assert main(['--healthcheck'])==1 and not path.exists()
    assert main(['--once'])==0
    assert 'DISABLED' in capsys.readouterr().out
    assert main(['--healthcheck'])==0
    monkeypatch.setenv('ENABLE_LIVE','true')
    with pytest.raises(SystemExit,match='hard locked'): main(['--once'])


def data_fixture(store,clock,override=None):
    requests=[]
    def get(path,params):
        requests.append((path,params))
        if override: return override(path,params)
        o=observation(clock())
        if path=='/v2/stocks/bars':
            return DataResponse(200,{}, {'bars':{'NVDA':[{'t':b['at'],**{k:v for k,v in b.items() if k!='at'}} for b in o['bars']['NVDA']]},'next_page_token':None})
        q=o['quotes'][0]
        return DataResponse(200,{}, {'quotes':{CALL:{'t':q['at'],'bp':q['bid']/100,'ap':q['ask']/100,'bs':q['bidSize'],'as':q['askSize']}}})
    provider=ObservedPaperData(store,SimpleNamespace(get=get))
    provider.lease=store.acquire('data')
    return provider,requests


def test_explicit_opra_transport_normalizes_and_preserves_basic_default(tmp_path):
    repo,store,clock=stored(tmp_path)
    provider,requests=data_fixture(store,clock)
    state=store.snapshot('a')['state']
    got=provider.capture([state],provider.lease)
    assert got['source']=='alpaca' and got['quotes']==observation()['quotes']
    assert got['bars']==observation()['bars']
    assert requests[1][1]['feed']=='opra'
    path,params=requests[1]
    assert not allowed_query(path,params) and allowed_query(path,params,observed_options=True)
    assert not allowed_query('/v2/orders',{},observed_options=True)
    with pytest.raises(MarketDataError,match='FORBIDDEN'): provider.request('/v2/orders',{})
    assert len(requests)==2
    repo.close()


@pytest.mark.parametrize('value',[True,0,-1,1.001,float('nan'),float('inf'),1e20,'1.00'])
def test_no_invented_or_rounded_option_cent_price(value):
    with pytest.raises((ValueError,MarketDataError)): cents(value)


def test_optional_partial_bars_and_malformed_peer_do_not_block_owned_quote(tmp_path):
    repo,store,clock=stored(tmp_path)
    def responses(path,params):
        if path.endswith('/bars'): return DataResponse(200,{}, {'bars':{},'next_page_token':'more'})
        return DataResponse(200,{}, {'quotes':{CALL:{'t':iso(clock()),'bp':1,'ap':1.05,'bs':8,'as':8}}})
    provider,calls=data_fixture(store,clock,responses)
    got=provider.capture([store.snapshot('a')['state']],provider.lease)
    assert got['bars']=={} and len(got['quotes'])==1
    assert len(calls)==2
    repo.close()


def test_budget_backoff_and_auth_latch_survive_provider_restart(tmp_path):
    repo,store,clock=stored(tmp_path)
    provider,calls=data_fixture(store,clock,lambda *_:DataResponse(403,{},{}))
    path='/v1beta1/options/quotes/latest'; params={'symbols':CALL,'feed':'opra'}
    with pytest.raises(MarketDataError,match='ENTITLEMENT'): provider.request(path,params)
    again=ObservedPaperData(store,provider.transport); again.lease=provider.lease
    with pytest.raises(MarketDataError,match='ENTITLEMENT'): again.request(path,params)
    assert len(calls)==1
    with pytest.raises(LedgerConflict,match='Stop'): reset_auth_lock(store)
    store.release(provider.lease); reset_auth_lock(store)
    provider.lease=store.acquire('data'); provider.transport=SimpleNamespace(get=lambda *_:DataResponse(429,{'Retry-After':'90'},{}))
    with pytest.raises(MarketDataError): provider.request(path,params)
    clock.step(60); provider.lease=store.acquire('data')
    with pytest.raises(MarketDataError,match='RATE_LIMITED'): provider.request(path,params)
    clock.step(31); provider.lease=store.acquire('data'); provider.transport=SimpleNamespace(get=lambda *_:DataResponse(200,{},{}))
    assert provider.request(path,params)=={}
    repo.close()


def test_last_request_budget_reserved_for_quote_protection(tmp_path):
    repo,store,clock=stored(tmp_path)
    provider,calls=data_fixture(store,clock)
    provider.budget=2
    provider.request('/v1beta1/options/quotes/latest',{'symbols':CALL,'feed':'opra'})
    result=provider.capture([store.snapshot('a')['state']],provider.lease)
    assert result['bars']=={} and len(result['quotes'])==1
    assert len(calls)==2 and all(p.endswith('/quotes/latest') for p,_ in calls)
    repo.close()


def test_authenticated_controls_reject_price_injection_and_other_mode(tmp_path):
    from fastapi.testclient import TestClient
    from app.main import create_app
    from test_alpaca_market_api import TOKEN, HEADERS
    repo=Repository()
    with TestClient(create_app(repo,TOKEN)) as client:
        prefix='/api/observed-paper/accounts'
        assert client.get(prefix).status_code==401
        assert client.post(prefix,headers=HEADERS,json={'id':'a','name':'A','source':'fixture'}).status_code==201
        body={'request_key':'injected','expected_version':0,'command':{'kind':'CYCLE','observation':observation()}}
        assert client.post(prefix+'/a/control',headers=HEADERS,json=body).status_code==422
        body['command']={'kind':'ENABLE','enabled':True}
        assert client.post(prefix+'/a/control',headers=HEADERS,json=body).status_code==200
        assert client.get('/api/accounts',headers=HEADERS).json()==[]
        assert client.post(prefix+'/a/reconcile',headers=HEADERS).json()['version']==1
        assert len(client.get(prefix+'/a/events',headers=HEADERS).json()['events'])==2
        assert client.get(prefix+'/missing/state',headers=HEADERS).status_code==409
    repo.close()


def test_two_database_connections_use_same_acceptance_contract(tmp_path):
    import sys
    from pathlib import Path
    sys.path.insert(0,str(Path(__file__).parents[2]/'scripts'))
    from observed_paper_check import check
    url='sqlite:///'+str(tmp_path/'parallel.db')
    repositories=[Repository(url,invalidate_accounts=False) for _ in range(2)]
    try: assert check(repositories)['status']=='passed'
    finally:
        for repo in repositories: repo.close()
