from copy import deepcopy
from datetime import timedelta
import json
from types import SimpleNamespace

import pytest
from app.market_data import DataResponse, MarketDataError
from app.observed_contract_evidence import report
from app.observed_paper_data import ObservedPaperData
from app.observed_paper_runtime import ObservedPaperRuntime
from app.observed_paper_worker import build_provider
from app.observed_paper_store import ObservedPaperStore
from app.repository import Repository
from app.option_metadata import TERMS_PREFIX, SNAPSHOTS
from test_observed_contract_evidence import setup
from test_option_eligibility import raw, GREEKS, SYMBOL, NOW
from test_observed_paper import stored, observation, iso


class Metadata:
    def __init__(self,store):self.store=store;self.calls=[];self.status=200
    def get(self,path,params):
        self.calls.append((path,params))
        value=raw() if path.startswith(TERMS_PREFIX) else {'snapshots':{SYMBOL:{'greeks':GREEKS}}}
        return DataResponse(self.status,{},value)


def provider(store, budget=10):
    metadata=Metadata(store)
    return ObservedPaperData(store,SimpleNamespace(get=lambda *_:DataResponse(200,{},{})),
        requests_per_minute=budget,metadata_transport=metadata),metadata


def test_persisted_alternation_captures_originals_and_restart(tmp_path):
    repo,store,clock,lease=setup(tmp_path);p,wire=provider(store)
    before=store.snapshot('a',full=True)
    p.capture_metadata(['a'],lease);p.capture_metadata(['a'],lease)
    assert wire.calls==[(TERMS_PREFIX+SYMBOL,{}),(SNAPSHOTS,{'symbols':SYMBOL,'feed':'opra'})]
    assert report(store,'a')['contracts'][0]['qualification']['standardDeliverableObserved']
    assert not report(store,'a')['entryEligible']
    assert store.snapshot('a',full=True)==before
    repo.close();repo=Repository('sqlite:///'+str(tmp_path/'metadata.db'),invalidate_accounts=False)
    store=ObservedPaperStore(repo,lambda:clock[0]);p,wire=provider(store)
    p.capture_metadata(['a'],lease)
    assert wire.calls==[(TERMS_PREFIX+SYMBOL,{})]
    with repo.transaction() as db:assert len(json.loads(db.one("SELECT payload FROM observed_paper_data_state WHERE name='budget'")['payload'])['calls'])==3
    repo.close()


def test_optional_capture_leaves_one_request_slot_and_advances_only_when_reserved(tmp_path):
    repo,store,_,lease=setup(tmp_path);p,wire=provider(store,budget=2)
    p.capture_metadata(['a'],lease)
    with pytest.raises(MarketDataError,match='DATA_RATE_LIMITED'):p.capture_metadata(['a'],lease)
    with repo.transaction() as db:
        assert p._metadata_cursor(db)['kind']=='terms'
    p.request('/v1beta1/options/quotes/latest',{'symbols':SYMBOL,'feed':'opra'})
    assert len(wire.calls)==1
    repo.close()


@pytest.mark.parametrize('status,code',[(401,'DATA_AUTH_OR_ENTITLEMENT_DENIED'),(403,'DATA_AUTH_OR_ENTITLEMENT_DENIED'),
    (429,'DATA_RATE_LIMITED'),(503,'DATA_UNAVAILABLE')])
def test_metadata_failure_charged_latched_and_never_refreshed(tmp_path,status,code):
    repo,store,_,lease=setup(tmp_path);p,wire=provider(store);wire.status=status
    with pytest.raises(MarketDataError,match=code):p.capture_metadata(['a'],lease)
    with pytest.raises(MarketDataError):p.capture_metadata(['a'],lease)
    assert len(wire.calls)==1 and report(store,'a')['contracts'][0]['terms'] is None
    with repo.transaction() as db:
        assert p._metadata_cursor(db)['kind']=='terms'
        assert len(json.loads(db.one("SELECT payload FROM observed_paper_data_state WHERE name='budget'")['payload'])['calls'])==1
    repo.close()


def test_network_occurs_after_financial_cycle_and_failure_cannot_veto_protection(tmp_path):
    repo,store,clock=stored(tmp_path);order=[]
    class Capture:
        source='fixture'
        def capture(self,states,lease):return observation(clock())
        def capture_metadata(self,accounts,lease):
            assert store.snapshot('a',full=True)['state']['positions']
            order.append('metadata');raise MarketDataError('secret raw provider text')
    result=ObservedPaperRuntime(store,Capture()).tick()
    assert result['processed']==1 and result['diagnosticCode']=='DATA_UNAVAILABLE' and order==['metadata']
    repo.close()


def test_metadata_disabled_is_noop_and_no_independent_credentials_read(tmp_path,monkeypatch):
    repo,store,_,lease=setup(tmp_path)
    p=ObservedPaperData(store,SimpleNamespace(get=lambda *_:pytest.fail('unexpected request')))
    p.capture_metadata(['a'],lease)
    with pytest.raises(MarketDataError,match='DATA_ROUTE_FORBIDDEN'):
        p.request(TERMS_PREFIX+SYMBOL,{},metadata=True)
    monkeypatch.setenv('OAT_OPTION_METADATA_APPROVAL','read_only_approved')
    monkeypatch.delenv('OAT_OBSERVED_PAPER_APPROVAL',raising=False)
    monkeypatch.setattr('app.observed_paper_worker.credentials_from_file',lambda _:pytest.fail('unexpected credentials'))
    assert build_provider(store) is None
    repo.close()


def test_corrupt_cursor_and_stale_owner_do_not_open_socket(tmp_path):
    repo,store,clock,lease=setup(tmp_path);p,wire=provider(store)
    clock[0]+=timedelta(seconds=31);store.acquire('successor')
    with pytest.raises(MarketDataError,match='WORKER_LEASE_LOST'):p.capture_metadata(['a'],lease)
    assert not wire.calls
    with repo.transaction() as db:db.execute("INSERT INTO observed_paper_data_state VALUES('metadata_cursor','{}')")
    lease=store.acquire('successor')
    with pytest.raises(MarketDataError,match='DATA_STATE_REVIEW_REQUIRED'):p.capture_metadata(['a'],lease)
    assert not wire.calls;repo.close()


def test_snapshot_partial_page_or_unrequested_member_not_persisted(tmp_path):
    repo,store,_,lease=setup(tmp_path);p,_=provider(store);p.capture_metadata(['a'],lease)
    for body in [{'snapshots':{}},{'snapshots':{SYMBOL:{'greeks':GREEKS}},'next_page_token':'more'},
                 {'snapshots':{SYMBOL:{'greeks':GREEKS},'unexpected':{}}}]:
        with repo.transaction() as db:db.execute("UPDATE observed_paper_data_state SET payload=? WHERE name='metadata_cursor'",(json.dumps({'version':1,'after':SYMBOL,'kind':'terms'}),))
        p.metadata_transport=SimpleNamespace(get=lambda *_:DataResponse(200,{},body))
        with pytest.raises(MarketDataError,match='INVALID_PROVIDER_RESPONSE'):p.capture_metadata(['a'],lease)
    assert report(store,'a')['contracts'][0]['greeks'] is None;repo.close()
