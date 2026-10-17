from datetime import timedelta
import json
from types import SimpleNamespace
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.market_data import MarketDataError
from app.observed_paper_runtime import ObservedPaperRuntime
from app.observed_paper_status import status
from app.observed_paper_store import ObservedPaperStore
from test_observed_paper import stored, iso
from test_alpaca_market_api import TOKEN, HEADERS


def budget(repo,value):
    with repo.transaction() as db:
        db.execute("INSERT INTO observed_paper_data_state VALUES('budget',?)",(json.dumps(value),))


@pytest.mark.parametrize('code',['DATA_AUTH_OR_ENTITLEMENT_DENIED','DATA_RATE_LIMITED','OBSERVED_DEMAND_LIMIT','PRIVATE_PROVIDER_SECRET'])
def test_durable_worker_diagnostic_is_allowlisted_and_read_does_not_modify_ledger(tmp_path,code):
    repo,store,clock=stored(tmp_path);before=store.snapshot('a',full=True)
    def capture(*_):raise MarketDataError(code)
    runtime=ObservedPaperRuntime(store,SimpleNamespace(source='fixture',capture=capture))
    result=runtime.tick();expected='DATA_UNAVAILABLE' if code.startswith('PRIVATE') else code
    assert result['diagnosticCode']==expected
    read=status(ObservedPaperStore(repo,clock))
    assert read['heartbeatFresh'] and read['state']=='DATA_UNAVAILABLE' and read['diagnosticCode']==expected
    assert expected in read['alerts'] and 'PRIVATE' not in json.dumps(read)
    assert not read['newMarketEntryAllowed'] and not read['externalOrder']
    clock.step(61);late=status(store)
    assert late['diagnosticCode'] is None and late['alerts']==['WORKER_UNAVAILABLE']
    assert store.snapshot('a',full=True)==before
    repo.close()


def test_auth_backoff_persists_across_restart_and_clock_regression(tmp_path):
    repo,store,clock=stored(tmp_path)
    value={'authBlocked':True,'retryAt':iso(clock()+timedelta(seconds=90)),'failures':2,
        'calls':[iso(clock()-timedelta(seconds=60)),iso(clock()),iso(clock()+timedelta(seconds=2))]}
    budget(repo,value)
    read=status(ObservedPaperStore(repo,clock))
    assert read['alerts']==['WORKER_UNAVAILABLE','DATA_AUTH_OR_ENTITLEMENT_DENIED','DATA_BACKOFF']
    assert read['dataAccess']['chargedRequestsLastMinute']==2  # future reservation stays charged
    clock.step(91);read=status(store)
    assert read['dataAccess']['authBlocked'] is True and read['dataAccess']['chargedRequestsLastMinute']==0
    assert 'DATA_BACKOFF' not in read['alerts']
    with repo.transaction() as db:
        assert json.loads(db.one("SELECT payload FROM observed_paper_data_state WHERE name='budget'")['payload'])==value
    repo.close()


@pytest.mark.parametrize('change',[{'authBlocked':'secret'},{'retryAt':'secret'},{'failures':True},{'calls':[True]},
    {'calls':['bad']},{'calls':['2026-10-13T15:00:00Z']*31},{'unexpected':'secret'}])
def test_corrupt_budget_is_not_displayed_or_reset(tmp_path,change):
    repo,store,_=stored(tmp_path)
    value={'authBlocked':False,'retryAt':None,'calls':[],'failures':0}|change;budget(repo,value)
    read=status(store)
    assert read['dataAccess']=={'status':'UNVERIFIED','authBlocked':None,'retryAt':None,'chargedRequestsLastMinute':None}
    assert 'DATA_STATE_REVIEW_REQUIRED' in read['alerts'] and 'secret' not in json.dumps(read)
    with repo.transaction() as db:assert json.loads(db.one("SELECT payload FROM observed_paper_data_state WHERE name='budget'")['payload'])==value
    repo.close()


def test_authenticated_status_does_not_clear_auth_or_touch_lease(tmp_path):
    repo,store,clock=stored(tmp_path)
    budget(repo,{'authBlocked':True,'retryAt':None,'calls':[],'failures':0})
    before=store.snapshot('a',full=True)
    with TestClient(create_app(repo,TOKEN)) as client:
        path='/api/observed-paper/status'
        assert client.get(path).status_code==401
        result=client.get(path,headers=HEADERS).json()
        assert 'DATA_AUTH_OR_ENTITLEMENT_DENIED' in result['alerts']
        assert result['alertScope']=='CURRENT_STATE_READ_ONLY_NO_PUSH_DELIVERY'
    assert store.snapshot('a',full=True)==before
    with repo.transaction() as db:assert db.one("SELECT * FROM observed_paper_lease WHERE name='worker'") is None
    repo.close()
