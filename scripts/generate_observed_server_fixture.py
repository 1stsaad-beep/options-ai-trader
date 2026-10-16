"""Reproducible original server events; synthetic fixtures never claim OPRA access."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
from copy import deepcopy

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from app.observed_paper import DEFAULTS
from app.observed_paper_v1 import DEFAULTS as V1_DEFAULTS
from app.observed_paper_store import ObservedPaperStore
from app.observed_option_replay import iso
from app.repository import Repository


def generate(version='observed-paper-ledger-v1'):
    at=datetime(2026,10,13,15,tzinfo=timezone.utc)
    repo=Repository(invalidate_accounts=False);store=ObservedPaperStore(repo,lambda:at)
    call='NVDA261023C00150000'
    try:
        store.create('server-one','Server fixture',10000000,'fixture',version=version)
        defaults=V1_DEFAULTS if version=='observed-paper-ledger-v1' else DEFAULTS
        store.command('server-one','config',{'kind':'CONFIGURE','config':deepcopy(defaults)|{'quantity':3,'contracts':{'NVDA':{'CALL':call}}}})
        store.command('server-one','enable',{'kind':'ENABLE','enabled':True})
        rows=json.loads((ROOT/'mobile/test/fixtures/market_strategy_v1.json').read_text())['cases'][2]['bars']
        observation={'source':'fixture','capturedAt':iso(at),'stockFeed':'iex','bars':{'NVDA':rows},
            'quotes':[{'contract':call,'feed':'opra','at':iso(at),'bid':100,'ask':105,'bidSize':40,'askSize':40}]}
        store.command('server-one','open',{'kind':'CYCLE','observation':observation},expected_version=2,lease=store.acquire('fixture'))
        assert store.snapshot('server-one')['state']['positions']['NVDA']['quantity']==3
        at+=timedelta(seconds=1)
        store.command('server-one','stop',{'kind':'ENABLE','enabled':False})
        events=store.events('server-one')
        result={'accounts':{'mode':'observed_market_virtual','externalOrder':False,'accounts':['server-one']},
            'status':{'mode':'observed_market_virtual','externalOrder':False,'serverTime':iso(at),'heartbeatFresh':False,
                'state':'WORKER_UNAVAILABLE','newMarketEntryAllowed':False,'entryBlockReason':'CONTRACT_ELIGIBILITY_UNVERIFIED','processed':0,'blocked':0},
            'snapshot':store.snapshot('server-one',full=True),
            'events':{'account':'server-one','mode':'observed_market_virtual','externalOrder':False,'events':events,'nextAfter':events[-1]['version']}}
        if version!='observed-paper-ledger-v1':result['performance']=store.performance('server-one')
        return result
    finally:repo.close()


if __name__=='__main__':
    (ROOT/'mobile/test/fixtures/observed_server_v1.json').write_text(json.dumps(generate(),ensure_ascii=False,indent=2)+'\n')
    (ROOT/'mobile/test/fixtures/observed_server_v2.json').write_text(json.dumps(generate('observed-paper-ledger-v2'),ensure_ascii=False,indent=2)+'\n')
