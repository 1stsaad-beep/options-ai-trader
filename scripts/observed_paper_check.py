"""Two-connection observed-paper acceptance on disposable SQLite/PostgreSQL."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sys
import threading
from types import SimpleNamespace
from urllib.parse import urlparse
import uuid

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from app.repository import Repository
from app.observed_paper import DEFAULTS
from app.observed_paper import canonical
from app.observed_paper_store import ObservedPaperStore, LedgerConflict
from app.observed_option_replay import iso
from app.observed_paper_runtime import ObservedPaperRuntime
from app.runtime_health import heartbeat_valid
from app.observed_paper_status import status as runtime_status
from app.observed_paper_data import ObservedPaperData
from app.observed_paper_alerts import page as alert_page, acknowledge as alert_ack
from app.market_data import DataResponse


def seed(store,account):
    store.create(account,'Observed fixture',10000000,'fixture')
    config=deepcopy(DEFAULTS)|{'quantity':3,'contracts':{'NVDA':{'CALL':'NVDA261023C00150000'}}}
    store.command(account,'config',{'kind':'CONFIGURE','config':config})
    store.command(account,'enable',{'kind':'ENABLE','enabled':True})
    return store.snapshot(account)


def observation(now,bid=100,ask=105,size=40):
    fixtures=json.loads((Path(__file__).resolve().parents[1]/'mobile/test/fixtures/market_strategy_v1.json').read_text())
    bars=deepcopy(fixtures['cases'][2]['bars'])
    offset=now-datetime(2026,10,13,15,tzinfo=timezone.utc)
    for b in bars: b['at']=iso(datetime.fromisoformat(b['at'])+offset)
    return {'source':'fixture','capturedAt':iso(now),'stockFeed':'iex','bars':{'NVDA':bars},
        'quotes':[{'contract':'NVDA261023C00150000','feed':'opra','at':iso(now),
                   'bid':bid,'ask':ask,'bidSize':size,'askSize':size}]}


def check(repositories):
    clock=[datetime(2026,10,13,15,tzinfo=timezone.utc)]
    stores=[ObservedPaperStore(repo,lambda:clock[0]) for repo in repositories]
    account='observed-'+uuid.uuid4().hex; other=account+'-other'
    seed(stores[0],account); stores[0].create(other,'Other fixture')
    barrier=threading.Barrier(2)
    def claim(i):
        barrier.wait(timeout=10); return stores[i].acquire('observed-worker-'+str(i))
    with ThreadPoolExecutor(max_workers=2) as pool: leases=list(pool.map(claim,range(2)))
    assert sum(x is not None for x in leases)==1
    owner=next(i for i,x in enumerate(leases) if x); store=stores[owner]; lease=leases[owner]
    event=store.command(account,'open',{'kind':'CYCLE','observation':observation(clock[0])},expected_version=2,lease=lease)
    assert event['facts']['fills'][0]['execution']['quantity']==3
    valuation=stores[1-owner].valuation(account)
    assert valuation['complete'] and valuation['liquidationEquityCents']==9997480
    assert valuation['unrealizedPnlCents']==-2520 and valuation['version']==event['version']
    assert valuation['eventHash']==event['eventHash'] and not valuation['executionAllowed']
    assert stores[1-owner].valuation(account)==valuation
    stores[1-owner].command(account,'close',{'kind':'REQUEST_CLOSE','symbol':'NVDA'})
    stores[1-owner].command(account,'stop',{'kind':'ENABLE','enabled':False})
    clock[0]+=timedelta(seconds=1)
    command={'kind':'CYCLE','observation':observation(clock[0],bid=110,ask=115,size=4)}
    partial=store.command(account,'partial',command,expected_version=5,lease=lease)
    assert stores[1-owner].command(account,'partial',command,expected_version=5,lease=lease)==partial
    state=stores[1-owner].snapshot(account,full=True)
    assert state['state']['positions']['NVDA']['closeIntent']['quantity']==2
    # Server-side SQL guards and FK constraints, including cross-mode IDs.
    for statement in ('UPDATE observed_paper_events SET payload=payload WHERE account_id=?',
                      'DELETE FROM observed_paper_events WHERE account_id=?'):
        try:
            with repositories[1-owner].transaction() as db: db.execute(statement,(account,))
        except Exception as exc: assert 'immutable' in str(exc)
        else: raise AssertionError('Immutable event guard missing')
    store.release(lease); clock[0]+=timedelta(seconds=1)
    lease2=stores[1-owner].acquire('replacement')
    try:
        store.command(account,'fenced',{'kind':'CYCLE','observation':observation(clock[0])},expected_version=6,lease=lease)
    except LedgerConflict: pass
    else: raise AssertionError('Former owner was not fenced')
    stores[1-owner].command(account,'finish',{'kind':'CYCLE','observation':observation(clock[0],bid=110,ask=115)},expected_version=6,lease=lease2)
    final=stores[0].snapshot(account,full=True)
    assert not final['state']['positions'] and not final['state']['enabled']
    assert stores[0].snapshot(other)['state']['cash']==1000000
    history=stores[0].valuation_history(account,through=3)
    assert history['points'][-1]['liquidationEquityCents']==9997480
    assert history['points'][-1]['prefix']['maximumSampledDrawdownCents']==2520
    assert history['throughEventHash']==event['eventHash']
    first=stores[0].valuation_history(account,limit=2,through=3)
    second=stores[1].valuation_history(account,after=first['nextAfter'],limit=2,through=3)
    assert first['points']+second['points']==history['points'] and not second['hasMore']
    assert stores[0].snapshot(account,full=True)==final
    for i in range(260): stores[0].command(other,'toggle'+str(i),{'kind':'ENABLE','enabled':bool(i%2)})
    assert stores[1].snapshot(other,full=True)['version']==260
    with repositories[0].transaction() as db:
        assert db.one('SELECT COUNT(*) AS n FROM observed_paper_segments WHERE account_id=?',(other,))['n']==2
    stores[1-owner].release(lease2)
    before=stores[0].snapshot(account,full=True)
    first=ObservedPaperRuntime(stores[0],owner='reused-worker')
    assert first.tick()['state']=='DISABLED'
    clock[0]+=timedelta(seconds=31)
    first.close()
    with repositories[1].transaction() as db:
        stopped=db.one("SELECT * FROM runtime_health WHERE name='observed_paper'")
        assert json.loads(stopped['payload'])['state']=='STOPPED'
        assert not heartbeat_valid(stopped,'observed_paper',clock[0])
    first.tick();clock[0]+=timedelta(seconds=31)
    successor=ObservedPaperRuntime(stores[1],owner='reused-worker')
    successor.tick()
    with repositories[1].transaction() as db:
        healthy=db.one("SELECT * FROM runtime_health WHERE name='observed_paper'")
    first.close()
    with repositories[0].transaction() as db:
        assert db.one("SELECT * FROM runtime_health WHERE name='observed_paper'")==healthy
        assert heartbeat_valid(healthy,'observed_paper',clock[0])
    successor.close();successor.close()
    assert stores[0].snapshot(account,full=True)==before
    inbox=alert_page(stores[0],after=0,limit=1)
    event=inbox['events'][0]
    acknowledgement=alert_ack(stores[1],event['sequence'],event['eventHash'],0)
    assert alert_ack(stores[0],event['sequence'],event['eventHash'],0)==acknowledgement
    remaining=alert_page(stores[1],through=inbox['through'])
    assert remaining['after']==event['sequence'] and remaining['throughHash']==inbox['throughHash']
    assert remaining['events'][0]['previousHash']==event['eventHash']
    for sql in ('UPDATE observed_alert_events SET payload=payload','DELETE FROM observed_alert_events'):
        try:
            with repositories[0].transaction() as db: db.execute(sql)
        except Exception as exc: assert 'immutable' in str(exc)
        else: raise AssertionError('Alert event guard missing')
    demand=[{'enabled':False,'positions':{'NVDA':{'contract':'NVDA261023C'+str(150000+i).zfill(8)}},
        'config':{'contracts':{}}} for i in range(40)]
    requested=[]
    def quote_fixture(path,params):
        assert path=='/v1beta1/options/quotes/latest' and params['feed']=='opra'
        requested.append(set(params['symbols'].split(',')))
        return DataResponse(200,{}, {'quotes':{}})  # No fabricated qualified result or ledger cycle.
    for s in stores:
        data=ObservedPaperData(s,SimpleNamespace(get=quote_fixture))
        capture_lease=s.acquire('coverage-worker')
        assert data.capture(demand,capture_lease)['quotes']==[] and data.coverage_limited
        s.release(capture_lease)
    assert len(requested)==2 and all(len(batch)==30 for batch in requested) and len(set.union(*requested))==40
    capacity_account=account+'-capacity'
    stores[0].create(capacity_account,'Large original offline fixture')
    large={'source':'fixture','capturedAt':iso(clock[0]),'stockFeed':'iex','quotes':[],
        'bars':{'X'*190000:[]}}  # Invalid optional evidence, no quote/fill invented.
    capacity_lease=stores[0].acquire('capacity-worker')
    for i in range(12):
        stores[0].command(capacity_account,'large'+str(i),{'kind':'CYCLE','observation':large},
            expected_version=i,lease=capacity_lease)
    page_one=stores[1].events(capacity_account,after=0,limit=100)
    page_two=stores[0].events(capacity_account,after=page_one[-1]['version'],limit=100)
    assert len(page_one)<12 and len(canonical(page_one).encode())<4*1024*1024
    assert len(canonical(page_two).encode())<4*1024*1024
    assert [r['version'] for r in page_one+page_two]==list(range(1,13))
    assert stores[1].snapshot(capacity_account,full=True)['state']['cash']==1000000
    stores[0].release(capacity_lease)
    with repositories[0].transaction() as db:
        ObservedPaperData._save(db,{'calls':[iso(clock[0])],'authBlocked':True,
            'retryAt':iso(clock[0]+timedelta(seconds=60)),'failures':1})
    read=runtime_status(stores[1])
    assert read['dataAccess']['authBlocked'] is True and read['dataAccess']['chargedRequestsLastMinute']==1
    assert read['alerts']==['WORKER_UNAVAILABLE','DATA_AUTH_OR_ENTITLEMENT_DENIED','DATA_BACKOFF']
    assert not read['newMarketEntryAllowed']
    assert stores[0].snapshot(account,full=True)==before
    daily_clock=lambda:datetime(2026,10,13,20,tzinfo=timezone.utc)
    daily=ObservedPaperStore(repositories[0],daily_clock).daily_performance(account,'2026-10-13','2026-10-13')
    assert daily['points'][0]['liquidationEquityCents']==before['state']['cash']
    assert daily['points'][0]['status']=='CASH_ONLY' and daily['performance']['sharpe'] is None
    assert ObservedPaperStore(repositories[1],daily_clock).daily_performance(account,'2026-10-13','2026-10-13',
        through=daily['throughVersion'])==daily
    assert stores[0].snapshot(account,full=True)==before
    return {'status':'passed','source':'synthetic_fixture','externalOrder':False,'checks':[
        'two_connections_single_lease','owned_opra_fixture_fill','partial_close_restart','lost_ack_exactly_once',
        'native_update_delete_guards','lease_generation_fencing','independent_account_balances',
        'sealed_segment_rotation','streamed_full_replay','expired_owner_shutdown_health',
        'same_owner_successor_generation_fencing','shutdown_preserves_original_ledger',
        'read_only_version_bound_net_valuation','causal_history_two_connection_pagination','read_only_durable_diagnostics_across_connections',
        'alert_inbox_cross_connection_pinned_pages','alert_ack_lost_response_retry','alert_native_immutable_guards',
        'bounded_owned_quote_rotation_across_connections','large_original_receipts_streamed_without_page_loss',
        'causal_daily_net_valuation_across_connections','pinned_daily_report_hash_restart_and_no_financial_writes']}


def run():
    url=os.getenv('TEST_DATABASE_URL','')
    if (os.getenv('TEST_DATABASE_ALLOW_DISPOSABLE')!='1' or not url.startswith(('postgresql://','postgres://'))
            or urlparse(url).hostname not in {'localhost','127.0.0.1','::1','postgres'}):
        raise SystemExit('Explicit local disposable PostgreSQL required')
    repositories=[Repository(url,invalidate_accounts=False) for _ in range(2)]
    try:
        result=check(repositories)
        from app.observed_paper_watchdog import observe, stop_health
        now=datetime.now(timezone.utc)
        with repositories[0].transaction() as db:
            before={table:db.all('SELECT * FROM '+table+' ORDER BY 1') for table in
                ('observed_paper_accounts','observed_paper_events','observed_paper_lease','observed_paper_data_state')}
        assert 'WORKER_UNAVAILABLE' in observe(url,now,'pg-monitor')['alerts']
        store=ObservedPaperStore(repositories[1],lambda:now)
        first=alert_page(store)
        observe(url,now,'pg-successor');stop_health(url,'pg-monitor')
        assert alert_page(store)==first
        with repositories[1].transaction() as db:
            row=db.one("SELECT * FROM runtime_health WHERE name='observed_watchdog'")
            assert heartbeat_valid(row,'observed_watchdog',now)
            assert before=={table:db.all('SELECT * FROM '+table+' ORDER BY 1') for table in before}
        stop_health(url,'pg-successor')
        with repositories[1].transaction() as db:
            assert not heartbeat_valid(db.one("SELECT * FROM runtime_health WHERE name='observed_watchdog'"),'observed_watchdog',now)
        result['checks']+=['independent_watchdog_existing_database_outage','watchdog_dedup_and_successor_shutdown',
            'watchdog_preserves_accounts_events_leases_and_provider_state']
        from contract_evidence_check import check as metadata_check
        result['checks'] += metadata_check(repositories)
        from alert_delivery_check import check as notification_check
        result['checks'] += notification_check(repositories)
        print(json.dumps(result,sort_keys=True))
    finally:
        for repo in repositories: repo.close()


if __name__=='__main__': run()
