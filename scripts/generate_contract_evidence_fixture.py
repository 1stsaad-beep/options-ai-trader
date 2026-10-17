"""Offline SQL-generated metadata cases, never actual provider evidence."""
from datetime import timedelta
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
sys.path.insert(0,str(ROOT/'backend/tests'))
from app.repository import Repository
from app.observed_paper_store import ObservedPaperStore
from app.observed_paper import DEFAULTS
from app.observed_contract_evidence import append, report
from test_option_eligibility import raw, SYMBOL, NOW, GREEKS


def generate():
    cases=[]
    for name in ('missing','terms','complete','adjusted','delayed','stale','partial','tiny'):
        repo=Repository();clock=[NOW];store=ObservedPaperStore(repo,lambda:clock[0])
        store.create('metadata','Offline metadata fixture',source='alpaca')
        store.command('metadata','cfg',{'kind':'CONFIGURE','config':DEFAULTS | {'contracts':{'AAPL':{'CALL':SYMBOL}}}})
        lease=store.acquire('fixture');value=raw()
        if name=='adjusted':value['deliverables'][0]['amount']='150'
        if name=='delayed':value['deliverables'][0].update(delayed_settlement=True,amount=None)
        if name!='missing':append(store,lease,'terms',SYMBOL,value,clock[0].isoformat(),['metadata'])
        if name not in ('missing','terms'):
            values=GREEKS | ({'gamma':1e-7,'rho':-0.0} if name=='tiny' else {'rho':None} if name=='partial' else {})
            append(store,lease,'greeks',SYMBOL,{'greeks':values},clock[0].isoformat(),['metadata'])
        if name=='stale':clock[0]+=timedelta(days=2)
        cases.append({'name':name,'snapshot':store.snapshot('metadata',full=True),'report':report(store,'metadata')})
        repo.close()
    return {'contract':'contract-evidence-fixture-v1','source':'synthetic_fixture','cases':cases}


if __name__=='__main__':
    (ROOT/'mobile/test/fixtures/contract_evidence_v1.json').write_text(json.dumps(generate(),indent=2)+'\n')
