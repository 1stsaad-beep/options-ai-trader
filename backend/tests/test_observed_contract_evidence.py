from datetime import timedelta
import sqlite3
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.market_data import DataCredentials, MarketDataError
from app.option_metadata import AlpacaMetadataTransport, allowed_metadata_query, MAX_RESPONSE_BYTES, TERMS_PREFIX, SNAPSHOTS
from app.observed_contract_evidence import append, report
from app.observed_paper_store import ObservedPaperStore, LedgerConflict
from app.repository import Repository, Session
from app.observed_paper import DEFAULTS
from test_option_eligibility import raw, GREEKS, NOW, SYMBOL
from test_alpaca_market_api import TOKEN, HEADERS


def setup(tmp_path, *, source='alpaca', path='metadata.db'):
    repo = Repository('sqlite:///' + str(tmp_path / path), invalidate_accounts=False)
    clock = [NOW]
    store = ObservedPaperStore(repo, lambda: clock[0])
    store.create('a', 'A', source=source)
    store.command('a', 'cfg', {'kind': 'CONFIGURE', 'config': DEFAULTS | {'contracts': {'AAPL': {'CALL': SYMBOL}}}})
    lease = store.acquire('worker')
    return repo, store, clock, lease


def save(store, lease, kind='terms', value=None):
    return append(store, lease, kind, SYMBOL, raw() if value is None else value, store.now().isoformat(), ['a'])


def test_exact_originals_roundtrip_restart_no_financial_write(tmp_path):
    repo, store, clock, lease = setup(tmp_path)
    before = store.snapshot('a', full=True)
    first = save(store, lease)
    second = save(store, lease, 'greeks', {'greeks': GREEKS, 'latestQuote': {'t': NOW.isoformat()}})
    value = report(store, 'a')['contracts'][0]
    assert value['terms']['data'] == first['data'] and value['greeks']['data'] == second['data']
    assert value['qualification']['standardDeliverableObserved']
    assert value['qualification']['reasons'] == ['GREEKS_PROVIDER_TIME_UNAVAILABLE']
    assert not value['qualification']['entryEligible'] and not value['qualification']['settlementEligible']
    assert value['greeks']['data']['providerTimestamp'] is None
    assert value['terms']['bindings'] == [{'account':'a','version':before['version'],'eventHash':before['eventHash']}]
    assert store.snapshot('a', full=True) == before
    expected = report(store, 'a'); repo.close()
    repo = Repository('sqlite:///' + str(tmp_path/'metadata.db'), invalidate_accounts=False)
    assert report(ObservedPaperStore(repo, lambda:clock[0]), 'a') == expected
    repo.close()


@pytest.mark.parametrize('kind,value', [('terms', {'password':'private'}), ('greeks', {'api_key':'private'}),
    ('greeks', {'greeks':GREEKS | {'gamma':float('inf')}}), ('greeks', {'greeks':GREEKS | {'delta':True}}),
    ('unknown', {}), ('terms', raw() | {'deliverables': []})])
def test_invalid_metadata_writes_nothing(tmp_path, kind, value):
    repo, store, _, lease = setup(tmp_path)
    with pytest.raises((ValueError, MarketDataError)): save(store, lease, kind, value)
    assert report(store, 'a')['contracts'][0]['throughSequence'] == 0
    repo.close()


def test_stale_future_capture_fencing_and_lost_owner(tmp_path):
    repo, store, clock, lease = setup(tmp_path)
    for captured in [NOW + timedelta(microseconds=1), NOW - timedelta(seconds=9)]:
        with pytest.raises(ValueError): append(store,lease,'terms',SYMBOL,raw(),captured.isoformat(),['a'])
    clock[0] += timedelta(seconds=31); successor = store.acquire('worker')
    with pytest.raises(LedgerConflict): save(store,lease)
    save(store,successor); clock[0] += timedelta(days=2)
    value = report(store,'a')['contracts'][0]
    assert 'CONTRACT_TERMS_STALE_OR_FUTURE' in value['qualification']['reasons']
    assert not value['qualification']['standardDeliverableObserved']
    clock[0] = NOW
    with pytest.raises(LedgerConflict): report(store,'a')
    repo.close()


def test_demand_source_and_account_binding_cannot_be_forged(tmp_path):
    repo, store, _, lease = setup(tmp_path,source='fixture')
    with pytest.raises(ValueError,match='demand'): save(store,lease)
    repo.close(); repo, store, _, lease = setup(tmp_path,path='another.db')
    store.command('a','remove',{'kind':'CONFIGURE','config':DEFAULTS})
    with pytest.raises(ValueError,match='demand'): save(store,lease)
    repo.close()


def test_failure_rolls_back_original_and_head(tmp_path,monkeypatch):
    repo, store, _, lease=setup(tmp_path); old=Session.execute
    def fail(self, sql, params=()):
        if sql.startswith('INSERT INTO observed_contract_heads'): raise sqlite3.OperationalError('disk full')
        return old(self,sql,params)
    monkeypatch.setattr(Session,'execute',fail)
    with pytest.raises(sqlite3.OperationalError): save(store,lease)
    monkeypatch.setattr(Session,'execute',old)
    assert report(store,'a')['contracts'][0]['throughSequence']==0
    save(store,lease); repo.close()


@pytest.mark.parametrize('target',['payload','head','binding','tail'])
def test_corruption_rejected_including_later_tail(tmp_path,target):
    repo, store, _, lease=setup(tmp_path); save(store,lease); save(store,lease,'greeks',{'greeks':GREEKS})
    with repo.transaction() as db:
        if target=='head': db.execute('UPDATE observed_contract_heads SET event_hash=?',('f'*64,))
        elif target=='binding':
            db.execute('DROP TRIGGER immutable_observed_paper_event_update')
            db.execute('UPDATE observed_paper_events SET digest=? WHERE sequence=1',('f'*64,))
        else:
            db.execute('DROP TRIGGER immutable_contract_evidence_update')
            db.execute('UPDATE observed_contract_evidence SET payload=? WHERE sequence=?',('{}',1 if target=='payload' else 2))
    with pytest.raises(LedgerConflict): report(store,'a')
    repo.close()


def test_immutable_original_guards_and_read_api(tmp_path):
    repo,store,_,lease=setup(tmp_path);save(store,lease);before=store.snapshot('a',full=True)
    for sql in ['DELETE FROM observed_contract_evidence','UPDATE observed_contract_evidence SET payload=payload']:
        with pytest.raises(sqlite3.IntegrityError),repo.transaction() as db:db.execute(sql)
    with TestClient(create_app(repo,TOKEN)) as client:
        client.app.state.observed_paper.now = store.now
        url='/api/observed-paper/accounts/a/contract-evidence'
        assert client.get(url).status_code==401 and client.post(url,headers=HEADERS,json={}).status_code==405
        result=client.get(url,headers=HEADERS)
        assert result.status_code==200 and result.json()['version']==before['version']
        assert client.get(url,headers=HEADERS).json()==result.json()
    assert store.snapshot('a',full=True)==before;repo.close()


@pytest.mark.parametrize('path,params',[
    ('/v2/orders',{}),('/v2/account',{}),('/v2/options/contracts',{}),
    (TERMS_PREFIX+SYMBOL+'?bad=1',{}),(TERMS_PREFIX+SYMBOL,{'redirect':'x'}),
    ('https://elsewhere/'+SYMBOL,{}),(SNAPSHOTS,{'symbols':SYMBOL,'feed':'indicative'}),
    (SNAPSHOTS,{'symbols':SYMBOL+','+SYMBOL,'feed':'opra'}),
    (SNAPSHOTS,{'symbols':SYMBOL,'feed':'opra','updated_since':NOW.isoformat()}),
])
def test_route_denied_before_socket_or_credentials(monkeypatch,path,params):
    def forbidden(*a,**k):raise AssertionError('Network must not be opened')
    monkeypatch.setattr('app.option_metadata.http.client.HTTPSConnection',forbidden)
    assert not allowed_metadata_query(path,params)
    with pytest.raises(MarketDataError,match='DATA_ROUTE_FORBIDDEN'):
        AlpacaMetadataTransport(DataCredentials('fixture-id','fixture-secret')).get(path,params)


@pytest.mark.parametrize('path,params,host',[(TERMS_PREFIX+SYMBOL,{},'paper-api.alpaca.markets'),
    (SNAPSHOTS,{'symbols':SYMBOL,'feed':'opra'},'data.alpaca.markets')])
def test_fixed_https_get_host_no_redirect_and_bounded_body(monkeypatch,path,params,host):
    calls=[]
    class Socket:
        def __init__(self,*a,**k):calls.append((a,k));self.status=200
        def request(self,*a,**k):calls.append((a,k))
        def getresponse(self):return self
        def getheaders(self):return [('Authorization','private'),('Retry-After','60')]
        def read(self,n):assert n==MAX_RESPONSE_BYTES+1;return b'{"ok":true}'
        def close(self):calls.append('closed')
    monkeypatch.setattr('app.option_metadata.http.client.HTTPSConnection',Socket)
    result=AlpacaMetadataTransport(DataCredentials('fixture-id','fixture-secret')).get(path,params)
    assert calls[0][0]==(host,443) and calls[1][0][0]=='GET' and calls[-1]=='closed'
    assert result.body=={'ok':True} and result.headers=={'retry-after':'60'}


@pytest.mark.parametrize('body,status,code',[(b'{}',302,None),(b'{"x":1,"x":2}',200,'INVALID_PROVIDER_RESPONSE'),
    (b'{"x":NaN}',200,'INVALID_PROVIDER_RESPONSE'),(b'x'*(MAX_RESPONSE_BYTES+1),200,'DATA_RESPONSE_TOO_LARGE')])
def test_transport_rejects_ambiguous_or_oversized_json_and_redirects(monkeypatch,body,status,code):
    closed=[]
    socket=SimpleNamespace(request=lambda *a,**k:None,close=lambda:closed.append(True),
        getresponse=lambda:SimpleNamespace(status=status,getheaders=lambda:[],read=lambda _:body))
    monkeypatch.setattr('app.option_metadata.http.client.HTTPSConnection',lambda *a,**k:socket)
    transport=AlpacaMetadataTransport(DataCredentials('fixture-id','fixture-secret'))
    if code:
        with pytest.raises(MarketDataError,match=code):transport.get(TERMS_PREFIX+SYMBOL,{})
    else: assert transport.get(TERMS_PREFIX+SYMBOL,{}).status==302
    assert closed==[True]


def test_sqlite_backup_and_migration_preserve_original_ledger(tmp_path, monkeypatch):
    from app import migrations
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parents[2]/'scripts'))
    from backup_restore import backup, restore
    original = migrations.MIGRATIONS
    monkeypatch.setattr(migrations,'MIGRATIONS',original[:11])
    repo, store, _, _ = setup(tmp_path)
    before = store.snapshot('a',full=True);repo.close()
    monkeypatch.setattr(migrations,'MIGRATIONS',original)
    repo=Repository('sqlite:///'+str(tmp_path/'metadata.db'),invalidate_accounts=False)
    store=ObservedPaperStore(repo,lambda:NOW)
    assert store.snapshot('a',full=True)==before
    save(store,store.acquire('worker'));expected=report(store,'a')
    backup(tmp_path/'metadata.db',tmp_path/'backup.db')
    restore(tmp_path/'backup.db',tmp_path/'restored.db')
    restored=Repository('sqlite:///'+str(tmp_path/'restored.db'),invalidate_accounts=False)
    assert report(ObservedPaperStore(restored,lambda:NOW),'a')==expected
    assert ObservedPaperStore(restored,lambda:NOW).snapshot('a',full=True)==before
    restored.close();repo.close()


def test_two_connection_acceptance_contract(tmp_path):
    import sys
    from pathlib import Path
    sys.path.insert(0,str(Path(__file__).parents[2]/'scripts'))
    from contract_evidence_check import check
    url='sqlite:///'+str(tmp_path/'two.db')
    repos=[Repository(url,invalidate_accounts=False) for _ in range(2)]
    try: assert len(check(repos))==3
    finally:
        for repo in repos:repo.close()


def test_later_other_account_metadata_cannot_hide_bound_original(tmp_path):
    repo,store,_,lease=setup(tmp_path);first=save(store,lease)
    store.create('b','B',source='alpaca')
    store.command('b','cfg',{'kind':'CONFIGURE','config':DEFAULTS | {'contracts':{'AAPL':{'CALL':SYMBOL}}}})
    changed=raw();changed['deliverables'][0]['amount']='150'
    append(store,lease,'terms',SYMBOL,changed,NOW.isoformat(),['b'])
    assert report(store,'a')['contracts'][0]['terms']['eventHash']==first['eventHash']
    assert not report(store,'b')['contracts'][0]['qualification']['standardDeliverableObserved']
    repo.close()


def test_shared_metadata_fixture_is_generated_by_actual_sql():
    from pathlib import Path
    import sys,json
    sys.path.insert(0,str(Path(__file__).parents[2]/'scripts'))
    from generate_contract_evidence_fixture import generate
    expected=json.loads((Path(__file__).parents[2]/'mobile/test/fixtures/contract_evidence_v1.json').read_text())
    assert generate()==expected
