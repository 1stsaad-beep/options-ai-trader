from copy import deepcopy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import pytest
from app.option_eligibility import normalize_terms, qualify, ContractTermsAdapter, QualificationError, _hash
from test_alpaca_market_data import adapter, chain

NOW=datetime(2026,10,12,15,tzinfo=timezone.utc)
SYMBOL='AAPL261120C00200000'
ASSET='00000000-0000-4000-8000-000000000001'
GREEKS=dict(delta=.5,gamma=.01,theta=-.1,vega=.2,rho=.01)


def raw():
    # Offline schema fixture; not a fetched provider observation or market price.
    return {'id':'00000000-0000-4000-8000-000000000002','symbol':SYMBOL,
        'root_symbol':'AAPL','underlying_symbol':'AAPL','underlying_asset_id':ASSET,
        'expiration_date':'2026-11-20','type':'call','style':'american',
        'strike_price':'200','status':'active','tradable':True,'size':'100','multiplier':'100',
        'deliverables':[{'type':'equity','symbol':'AAPL','amount':'100','allocation_percentage':'100',
            'settlement_type':'T+1','settlement_method':'BTOB','delayed_settlement':False,'asset_id':ASSET}]}


def terms(value=None):
    return normalize_terms(raw() if value is None else value,SYMBOL,NOW.isoformat())


def test_standard_observation_stays_locked_without_independent_greek_time():
    original=raw();saved=deepcopy(original);t=terms(original)
    q=qualify(SYMBOL,GREEKS,NOW,terms=t)
    assert original==saved and t['termsHash']==_hash(t['terms'])
    assert q['standardDeliverableObserved'] and q['greeksStatus']=='VALUES_ONLY'
    assert q['reasons']==['GREEKS_PROVIDER_TIME_UNAVAILABLE']
    assert q['greeksProviderTimestamp'] is None
    assert not any(q[k] for k in ['greeksFreshnessVerified','entryEligible','settlementEligible','externalOrder'])
    original['deliverables'][0]['amount']='1'
    assert t['terms']['deliverables'][0]['amount']=='100'


@pytest.mark.parametrize('field,value',[('symbol','MSFT261120C00200000'),('root_symbol','AAPL1'),
    ('expiration_date','2026-11-21'),('type','put'),('strike_price','201')])
def test_identity_matches_every_provider_field(field,value):
    r=raw();r[field]=value
    with pytest.raises(QualificationError):terms(r)


@pytest.mark.parametrize('value',[None,True,100,float('nan'),'1e2','NaN','-100','9'*1000,'0'])
def test_multiplier_never_defaults_or_rounds(value):
    r=raw();r['multiplier']=value
    with pytest.raises(QualificationError):terms(r)


@pytest.mark.parametrize('value',[None,[],{},[{}]*17])
def test_missing_or_unbounded_deliverables(value):
    r=raw();r['deliverables']=value
    with pytest.raises(QualificationError,match='DELIVERABLES_UNAVAILABLE'):terms(r)


@pytest.mark.parametrize('amount',[None,'0','100'])
def test_delayed_delivery_never_means_known_zero_or_standard(amount):
    r=raw();r['deliverables'][0].update(amount=amount,delayed_settlement=True)
    q=qualify(SYMBOL,GREEKS,NOW,terms=terms(r))
    assert not q['standardDeliverableObserved'] and 'CONTRACT_DELIVERY_DELAYED' in q['reasons']


@pytest.mark.parametrize('change',[{'amount':'150'},{'symbol':'MSFT'},{'allocation_percentage':'50'},
    {'settlement_type':'T+2'},{'settlement_method':'CAFX'},
    {'asset_id':'00000000-0000-4000-8000-000000000099'},{'type':'cash','symbol':'USD','amount':'100'}])
def test_adjusted_delivery_preserved_and_locked(change):
    r=raw();r['deliverables'][0].update(change)
    q=qualify(SYMBOL,GREEKS,NOW,terms=terms(r))
    assert not q['standardDeliverableObserved'] and 'ADJUSTED_OR_UNSUPPORTED_CONTRACT' in q['reasons']


def test_adjusted_root_cannot_be_silently_mapped():
    r=raw();r.update(symbol='AAPL1261120C00200000',root_symbol='AAPL1')
    t=normalize_terms(r,r['symbol'],NOW.isoformat())
    q=qualify(r['symbol'],GREEKS,NOW,terms=t)
    assert not q['standardDeliverableObserved'] and not q['entryEligible']


@pytest.mark.parametrize('seconds,expected',[(-1,False),(0,True),(86400,True),(86401,False)])
def test_receipt_age_and_no_refresh_by_read(seconds,expected):
    t=terms();q=qualify(SYMBOL,GREEKS,NOW+timedelta(seconds=seconds),terms=t)
    assert q['standardDeliverableObserved'] is expected
    assert t['capturedAt']==NOW.isoformat() and t['providerEffectiveAt'] is None


@pytest.mark.parametrize('field,value',[('provider','fixture'),('source','user'),('contract','future-v2'),
    ('providerEffectiveAt',NOW.isoformat()),('termsHash','0'*64),('rawHash','not-a-hash')])
def test_unverified_source_or_corruption(field,value):
    t=terms();t[field]=value
    assert not qualify(SYMBOL,GREEKS,NOW,terms=t)['standardDeliverableObserved']


def test_legacy_lots_not_migrated_or_backdated():
    t=terms()
    for old,code in [('', 'LEGACY_LOT_TERMS_UNVERIFIED'),('0'*64,'LOT_TERMS_CHANGED'),
                     (t['termsHash'],'LOT_EFFECTIVE_TERMS_UNVERIFIED')]:
        q=qualify(SYMBOL,GREEKS,NOW,terms=t,lot_terms_hash=old)
        assert code in q['reasons'] and not q['settlementEligible']


@pytest.mark.parametrize('changes',[{'timestamp':NOW.isoformat()},{'updated_since':NOW.isoformat()},
    {'asof':NOW.isoformat()},{'freshnessVerified':True}])
def test_unspecified_fields_cannot_attest_greek_time(changes):
    q=qualify(SYMBOL,GREEKS|changes,NOW,terms=terms())
    assert not q['greeksFreshnessVerified'] and not q['entryEligible']


def test_get_adapter_exact_symbol_no_credentials_or_order_routes():
    class Transport:
        def __init__(self):self.calls=[]
        def get(self,path,params):
            self.calls.append((path,params));return SimpleNamespace(status=200,body=raw())
    transport=Transport();p=ContractTermsAdapter(transport,lambda:NOW)
    assert p.read(SYMBOL)==terms()
    assert transport.calls==[('/v2/options/contracts/'+SYMBOL,{})]
    for name in ['../orders',SYMBOL+'?x=1','AAPL261332C00200000']:
        with pytest.raises(QualificationError):p.read(name)
    assert len(transport.calls)==1


@pytest.mark.parametrize('status',[401,403,429,500])
def test_fixed_errors_without_provider_body(status):
    p=ContractTermsAdapter(SimpleNamespace(get=lambda *_:SimpleNamespace(status=status,body={'secret':'private'})),lambda:NOW)
    with pytest.raises(QualificationError,match='^CONTRACT_DATA_UNAVAILABLE$'):p.read(SYMBOL)


def test_existing_chain_integration_preserves_old_quality():
    provider,transport,_=adapter(chain({'greeks':GREEKS},contract=SYMBOL))
    item=provider.option_chain('AAPL')['data']['contracts'][0]
    assert item['eligibility']['reasons']==['GREEKS_PROVIDER_TIME_UNAVAILABLE','CONTRACT_TERMS_UNAVAILABLE']
    assert item['greeks_quality']['contract']=='option-greeks-quality-v1'
    assert len(transport.calls)==1 and not item['eligibility']['entryEligible']


def test_adapter_sanitizes_network_failure_and_rejects_naive_clock_before_request():
    class Transport:
        def get(self,*_):raise RuntimeError('private-provider-body')
    with pytest.raises(QualificationError,match='^CONTRACT_DATA_UNAVAILABLE$'):
        ContractTermsAdapter(Transport(),lambda:NOW).read(SYMBOL)
    with pytest.raises(QualificationError,match='^INVALID_CONTRACT_TIME$'):
        ContractTermsAdapter(Transport(),lambda:NOW.replace(tzinfo=None)).read(SYMBOL)
