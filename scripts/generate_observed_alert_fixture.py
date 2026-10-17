"""Actual disposable SQL alert transitions, explicitly synthetic/offline."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
import json
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from app.repository import Repository
from app.market_data import MarketDataError
from app.observed_paper_store import ObservedPaperStore
from app.observed_paper_runtime import ObservedPaperRuntime
from app.observed_paper_alerts import page, acknowledge
from observed_paper_check import seed


def generate():
    repo=Repository(); clock=[datetime(2026,10,13,15,tzinfo=timezone.utc)]
    store=ObservedPaperStore(repo,lambda:clock[0]);seed(store,'alerts')
    empty=page(store)
    def fail(*_): raise MarketDataError('DATA_RATE_LIMITED')
    provider=SimpleNamespace(source='fixture',capture=fail)
    runtime=ObservedPaperRuntime(store,owner='fixture')
    for i in range(30):
        runtime.provider=provider if i%2 else None
        runtime.tick();clock[0]+=timedelta(seconds=1)
    pages=[]; acknowledgements=[]
    for after in (0,25):
        p=page(store,after=after,limit=25,through=30);pages.append(p)
        event=p['events'][-1]
        acknowledgements.append(acknowledge(store,event['sequence'],event['eventHash'],p['after']))
    result={'contract':'observed-alert-fixture-v1','source':'synthetic_fixture','empty':empty,
        'pages':pages,'acks':acknowledgements,'read':page(store)}
    repo.close()
    return result


if __name__=='__main__':
    (ROOT/'mobile/test/fixtures/observed_alert_v1.json').write_text(json.dumps(generate(),indent=2)+'\n')
