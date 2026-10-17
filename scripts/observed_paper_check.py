"""Two-connection observed-paper acceptance on disposable SQLite/PostgreSQL."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sys
import threading
from urllib.parse import urlparse
import uuid

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from app.repository import Repository
from app.observed_paper import DEFAULTS
from app.observed_paper_store import ObservedPaperStore, LedgerConflict
from app.observed_option_replay import iso
from app.observed_paper_runtime import ObservedPaperRuntime
from app.runtime_health import heartbeat_valid


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
    return {'status':'passed','source':'synthetic_fixture','externalOrder':False,'checks':[
        'two_connections_single_lease','owned_opra_fixture_fill','partial_close_restart','lost_ack_exactly_once',
        'native_update_delete_guards','lease_generation_fencing','independent_account_balances',
        'sealed_segment_rotation','streamed_full_replay','expired_owner_shutdown_health',
        'same_owner_successor_generation_fencing','shutdown_preserves_original_ledger',
        'read_only_version_bound_net_valuation']}


def run():
    url=os.getenv('TEST_DATABASE_URL','')
    if (os.getenv('TEST_DATABASE_ALLOW_DISPOSABLE')!='1' or not url.startswith(('postgresql://','postgres://'))
            or urlparse(url).hostname not in {'localhost','127.0.0.1','::1','postgres'}):
        raise SystemExit('Explicit local disposable PostgreSQL required')
    repositories=[Repository(url,invalidate_accounts=False) for _ in range(2)]
    try: print(json.dumps(check(repositories),sort_keys=True))
    finally:
        for repo in repositories: repo.close()


if __name__=='__main__': run()
