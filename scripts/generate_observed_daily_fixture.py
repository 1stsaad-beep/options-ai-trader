"""Deterministic, disposable SQL originals for phone daily report acceptance."""
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'backend'))
from app.repository import Repository
from app.observed_paper_store import ObservedPaperStore
from observed_paper_check import seed, observation


def generate():
    cases = []
    for name in ('cash', 'complete', 'gap', 'liquidity', 'calendar'):
        repo = Repository(); clock = [datetime(2026, 9, 1, 15, tzinfo=timezone.utc)]
        store = ObservedPaperStore(repo, lambda: clock[0]); seed(store, 'daily')
        if name in ('complete', 'gap', 'liquidity'):
            store.command('daily', 'stop-config', {'kind': 'ENABLE', 'enabled': False})
            config = deepcopy(store.snapshot('daily')['state']['config']); config['holdingMode'] = 'swing'
            store.command('daily', 'swing', {'kind': 'CONFIGURE', 'config': config})
            store.command('daily', 'enable-swing', {'kind': 'ENABLE', 'enabled': True})
            for key, at, bid, size in [('open', (13, 15, 0, 0), 100, 40),
                    ('mark', (13, 19, 59, 45), 100, 4 if name == 'liquidity' else 40),
                    ('close', (14, 15, 0, 0), 70, 40)]:
                if key == 'mark' and name == 'gap':
                    continue
                clock[0] = datetime(2026, 10, *at, tzinfo=timezone.utc)
                store.command('daily', key, {'kind': 'CYCLE', 'observation': observation(clock[0], bid=bid, ask=bid+5, size=size)},
                    expected_version=store.snapshot('daily')['version'], lease=store.acquire('fixture'))
        start, end = ('2026-11-25', '2026-11-30') if name == 'calendar' else ('2026-09-17', '2026-10-16')
        clock[0] = datetime(2026, 11, 30, 22, tzinfo=timezone.utc) if name == 'calendar' else datetime(2026, 10, 16, 22, tzinfo=timezone.utc)
        cases.append({'name': name, 'start': start, 'end': end, 'now': clock[0].isoformat(),
            'snapshot': store.snapshot('daily', full=True), 'report': store.daily_performance('daily', start, end)})
        repo.close()
    return {'contract': 'observed-daily-fixture-v1', 'source': 'synthetic_fixture', 'cases': cases}


if __name__ == '__main__':
    (ROOT/'mobile/test/fixtures/observed_daily_v1.json').write_text(json.dumps(generate(), indent=2)+'\n')
