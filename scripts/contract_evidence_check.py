"""Isolated metadata acceptance; all provider data below is a declared fixture."""
from datetime import datetime, timezone
import uuid

from app.observed_contract_evidence import append, report
from app.observed_paper import DEFAULTS
from app.observed_paper_store import ObservedPaperStore

SYMBOL = 'AAPL261120C00200000'
AT = datetime(2026,10,13,15,tzinfo=timezone.utc)


def seed(store, account, lease):
    store.create(account,'Offline contract fixture',source='alpaca')
    store.command(account,'config',{'kind':'CONFIGURE','config':DEFAULTS | {'contracts':{'AAPL':{'CALL':SYMBOL}}}})
    asset='00000000-0000-4000-8000-000000000001'
    raw={'id':'00000000-0000-4000-8000-000000000002','symbol':SYMBOL,
        'root_symbol':'AAPL','underlying_symbol':'AAPL','underlying_asset_id':asset,
        'expiration_date':'2026-11-20','type':'call','style':'american','strike_price':'200',
        'status':'active','tradable':True,'size':'100','multiplier':'100',
        'deliverables':[{'type':'equity','symbol':'AAPL','amount':'100','allocation_percentage':'100',
            'settlement_type':'T+1','settlement_method':'BTOB','delayed_settlement':False,'asset_id':asset}]}
    append(store,lease,'terms',SYMBOL,raw,store.now().isoformat(),[account])
    append(store,lease,'greeks',SYMBOL,{'greeks':{'delta':.5,'gamma':.01,'theta':-.1,'vega':.2,'rho':.01}},store.now().isoformat(),[account])
    return report(store,account)


def check(repositories):
    # Disposable database only; the caller owns environment authorization.
    stores=[ObservedPaperStore(repo,lambda:AT) for repo in repositories]
    with repositories[0].transaction() as db:
        row=db.one("SELECT expires_at FROM observed_paper_lease WHERE name='worker'")
    from app.paper_settlement import stamp
    now=max(AT,stamp(row['expires_at'])) if row else AT
    for store in stores:store.now=lambda:now
    lease=stores[0].acquire('metadata-fixture-'+uuid.uuid4().hex)
    account='metadata-'+uuid.uuid4().hex
    result=seed(stores[0],account,lease)
    before=stores[0].snapshot(account,full=True)
    assert report(stores[1],account)==result
    for statement in ('UPDATE observed_contract_evidence SET payload=payload','DELETE FROM observed_contract_evidence'):
        try:
            with repositories[1].transaction() as db:db.execute(statement)
        except Exception: pass
        else: raise AssertionError('Immutable metadata guard failed')
    assert stores[1].snapshot(account,full=True)==before
    assert report(stores[1],account)==result
    stores[0].release(lease)
    return ['metadata_originals_cross_connection_binding','metadata_native_immutable_guards','metadata_no_financial_write_or_eligibility']
