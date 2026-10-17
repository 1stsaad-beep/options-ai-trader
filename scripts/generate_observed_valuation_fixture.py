"""Original disposable SQL snapshots for independent Dart valuation checks."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'backend'))
from app.repository import Repository
from app.observed_paper_store import ObservedPaperStore
from app.observed_option_replay import iso
from observed_paper_check import seed, observation


def generate():
    cases = []
    for name in ('cash', 'quoted', 'stale', 'liquidity', 'delivery', 'stopped_partial'):
        repo = Repository(); clock = [datetime(2026, 10, 13, 15, tzinfo=timezone.utc)]
        store = ObservedPaperStore(repo, lambda: clock[0]); seed(store, 'valuation')
        if name != 'cash':
            lease = store.acquire('fixture')
            store.command('valuation', 'open', {'kind':'CYCLE', 'observation':observation(clock[0],size=12 if name=='liquidity' else 40)},
                expected_version=2, lease=lease)
        if name == 'stale': clock[0] += timedelta(seconds=31)
        if name == 'stopped_partial':
            store.command('valuation', 'close', {'kind':'REQUEST_CLOSE','symbol':'NVDA'})
            store.command('valuation', 'stop', {'kind':'ENABLE','enabled':False})
            clock[0] += timedelta(seconds=1)
            store.command('valuation', 'partial', {'kind':'CYCLE','observation':observation(clock[0],bid=110,ask=115,size=4)},
                expected_version=5,lease=lease)
        if name == 'delivery':
            store.command('valuation', 'stop', {'kind':'ENABLE', 'enabled':False})
            store.command('valuation', 'exercise', {'kind':'SETTLE', 'request':{
                'id':'fixture-exercise', 'action':'EXERCISE', 'contract':'NVDA261023C00150000',
                'quantity':1, 'feeCents':0, 'underlyingCents':16000, 'effectiveAt':iso(clock[0]),
                'recordedAt':iso(clock[0]), 'source':'fixture', 'reference':'explicit synthetic exercise'}})
        cases.append({'name':name, 'snapshot':store.snapshot('valuation',full=True), 'valuation':store.valuation('valuation')})
        repo.close()
    return {'contract':'observed-valuation-fixture-v1', 'source':'synthetic_fixture', 'cases':cases}


if __name__ == '__main__':
    (ROOT/'mobile/test/fixtures/observed_valuation_v1.json').write_text(json.dumps(generate(),indent=2)+'\n')
