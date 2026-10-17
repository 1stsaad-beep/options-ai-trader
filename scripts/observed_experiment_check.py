"""Four-account atomicity across two disposable PostgreSQL connections."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import json
import os
import sys
import threading
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from app.observed_paper_store import ObservedPaperStore
from app.repository import Repository


def check(repositories):
    stores = [ObservedPaperStore(repo) for repo in repositories]
    barrier = threading.Barrier(2)
    def setup(index):
        barrier.wait(timeout=10)
        return stores[index].experiment('fixture')
    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(setup, range(2)))
    assert sorted(r['created'] for r in results) == [False, True]
    assert results[0]['accounts'] == results[1]['accounts']
    ids = [s['state']['id'] for s in results[0]['accounts']]
    stores[0].command(ids[0], 'experiment-enable', {'kind': 'ENABLE', 'enabled': True}, expected_version=1)
    retried = stores[1].experiment('fixture')
    assert not retried['created'] and retried['accounts'][0]['state']['enabled']
    assert all(not s['state']['enabled'] for s in retried['accounts'][1:])
    report = stores[1].comparison(ids)
    assert [a['performance']['version'] for a in report['accounts']] == [2, 1, 1, 1]
    assert all(a['performance']['cashCents'] == 100000 for a in report['accounts'])
    stores[0].command(ids[0], 'experiment-stop', {'kind': 'ENABLE', 'enabled': False}, expected_version=2)
    return {'status': 'passed', 'source': 'synthetic_fixture', 'externalOrder': False,
            'checks': ['concurrent_atomic_four_account_setup', 'idempotent_retry_after_control',
                       'independent_controls_and_capital', 'snapshot_bound_receipt_comparison']}


def run():
    url = os.getenv('TEST_DATABASE_URL', '')
    if (os.getenv('TEST_DATABASE_ALLOW_DISPOSABLE') != '1'
            or not url.startswith(('postgresql://', 'postgres://'))
            or urlparse(url).hostname not in {'localhost', '127.0.0.1', '::1', 'postgres'}):
        raise SystemExit('Explicit local disposable PostgreSQL required')
    repositories = [Repository(url, invalidate_accounts=False) for _ in range(2)]
    try:
        print(json.dumps(check(repositories), sort_keys=True))
    finally:
        for repo in repositories: repo.close()


if __name__ == '__main__': run()
