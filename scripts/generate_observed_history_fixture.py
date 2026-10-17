"""Disposable SQL fixture for causal historical summary and page validation."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from app.repository import Repository
from app.observed_paper_store import ObservedPaperStore
from observed_paper_check import seed, observation


def generate():
    cases=[]
    for name in ('complete','gap','liquidity','pages'):
        repo=Repository(); clock=[datetime(2026,10,13,15,tzinfo=timezone.utc)]
        store=ObservedPaperStore(repo,lambda:clock[0]);seed(store,'history')
        if name=='pages':
            for i in range(27):store.command('history','wait'+str(i),{'kind':'ENABLE','enabled':True})
        version=store.snapshot('history')['version']
        store.command('history','open',{'kind':'CYCLE','observation':observation(clock[0],size=12 if name=='liquidity' else 40)},
            expected_version=version,lease=store.acquire('fixture'))
        clock[0]+=timedelta(seconds=31 if name in ('gap','pages') else 1)
        store.command('history','stop',{'kind':'ENABLE','enabled':False})
        store.command('history','close',{'kind':'REQUEST_CLOSE','symbol':'NVDA'})
        version=store.snapshot('history')['version']
        store.command('history','finish',{'kind':'CYCLE','observation':observation(clock[0],bid=70,ask=74)},
            expected_version=version,lease=store.acquire('fixture'))
        pages=[];after=-1
        while True:
            page=store.valuation_history('history',after=after,limit=25)
            pages.append(page)
            if not page['hasMore']:break
            after=page['nextAfter']
        cases.append({'name':name,'snapshot':store.snapshot('history',full=True),'pages':pages})
        repo.close()
    return {'contract':'observed-history-fixture-v1','source':'synthetic_fixture','cases':cases}


if __name__=='__main__':
    (ROOT/'mobile/test/fixtures/observed_history_v1.json').write_text(json.dumps(generate(),indent=2)+'\n')
