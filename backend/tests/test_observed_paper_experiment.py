from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy

from fastapi.testclient import TestClient
import pytest

from app.main import create_app
from app.observed_paper_experiment import STRATEGIES
from app.observed_paper_store import LedgerConflict, ObservedPaperStore
from app.repository import Repository, Session
from test_alpaca_market_api import HEADERS, TOKEN
from test_observed_paper import Clock, CALL, observation


def test_four_accounts_have_independent_cash_config_and_idempotent_restart(tmp_path):
    url = 'sqlite:///' + str(tmp_path / 'experiment.db')
    repo = Repository(url, invalidate_accounts=False)
    store = ObservedPaperStore(repo, Clock())
    created = store.experiment('fixture')
    assert created['created'] and created['externalOrder'] is False
    states = [s['state'] for s in created['accounts']]
    assert [s['config']['strategy'] for s in states] == list(STRATEGIES)
    assert all(s['cash'] == s['initialCash'] == 100000 and not s['enabled'] for s in states)
    account = states[0]['id']
    config = deepcopy(states[0]['config'])
    config['contracts'] = {'NVDA': {'CALL': CALL}}
    store.command(account, 'configure', {'kind': 'CONFIGURE', 'config': config})
    store.command(account, 'enable', {'kind': 'ENABLE', 'enabled': True})
    store.command(account, 'fill', {'kind': 'CYCLE', 'observation': observation(bid=30, ask=35)},
        expected_version=3, lease=store.acquire('worker'))
    before = [store.snapshot(s['id']) for s in states]
    assert before[0]['state']['cash'] == 96330
    assert all(s['state']['cash'] == 100000 and not s['state']['enabled'] for s in before[1:])
    repo.close()
    reopened = Repository(url, invalidate_accounts=False)
    try:
        result = ObservedPaperStore(reopened, Clock()).experiment('fixture')
        assert not result['created'] and result['accounts'] == before
        with reopened.transaction() as db:
            assert db.one('SELECT COUNT(*) AS n FROM accounts')['n'] == 0
            assert db.one('SELECT COUNT(*) AS n FROM orders')['n'] == 0
    finally:
        reopened.close()


@pytest.mark.parametrize('count', [1, 4])
def test_existing_accounts_are_never_adopted_or_overwritten(count):
    repo = Repository(); store = ObservedPaperStore(repo, Clock())
    for strategy in STRATEGIES[:count]:
        store.create('experiment_alpaca_' + strategy, 'Existing', 100000, 'alpaca')
    before = [store.snapshot(a) for a in store.accounts()]
    with pytest.raises(LedgerConflict): store.experiment()
    assert [store.snapshot(a, full=True) for a in store.accounts()] == before
    repo.close()


def test_mid_batch_write_failure_rolls_back_all_four_accounts(monkeypatch):
    repo = Repository(); store = ObservedPaperStore(repo, Clock())
    original = store._append
    def failure(*args, **kwargs):
        result = original(*args, **kwargs)
        if args[1].endswith('pullback'): raise OSError('injected disk failure')
        return result
    monkeypatch.setattr(store, '_append', failure)
    with pytest.raises(OSError): store.experiment()
    with repo.transaction() as db:
        for table in ('observed_paper_accounts', 'observed_paper_events', 'observed_paper_segments'):
            assert db.one('SELECT COUNT(*) AS n FROM ' + table)['n'] == 0
    monkeypatch.setattr(store, '_append', original)
    assert store.experiment()['created']
    repo.close()


def test_simultaneous_connections_create_only_one_experiment(tmp_path):
    url = 'sqlite:///' + str(tmp_path / 'race.db')
    repositories = [Repository(url, invalidate_accounts=False) for _ in range(2)]
    try:
        stores = [ObservedPaperStore(r, Clock()) for r in repositories]
        with ThreadPoolExecutor(2) as workers:
            results = list(workers.map(lambda s: s.experiment(), stores))
        assert sorted(r['created'] for r in results) == [False, True]
        assert results[0]['accounts'] == results[1]['accounts']
        assert len(stores[0].accounts()) == 4
        assert all(len(stores[1].events(a)) == 2 for a in stores[0].accounts())
    finally:
        for repo in repositories: repo.close()


def test_experiment_checks_capacity_before_any_write():
    repo = Repository(); store = ObservedPaperStore(repo, Clock())
    for i in range(97): store.create('a' + str(i), 'A')
    with pytest.raises(LedgerConflict, match='limit'): store.experiment()
    assert len(store.accounts()) == 97
    repo.close()


def test_comparison_preserves_versions_sources_and_missing_market_values(monkeypatch):
    repo = Repository(); store = ObservedPaperStore(repo, Clock())
    result = store.experiment('fixture'); ids = [s['state']['id'] for s in result['accounts']]
    old = Session.all
    def bounded(self, sql, *args):
        assert 'observed_paper_events' not in sql
        return old(self, sql, *args)
    monkeypatch.setattr(Session, 'all', bounded)
    report = store.comparison(ids)
    assert report['source'] == 'fixture' and report['threeSessionAcceptance'] == 'NOT_RUN'
    for original, row in zip(result['accounts'], report['accounts']):
        p = row['performance']
        assert row['initialCashCents'] == 100000 and p['cashCents'] == 100000
        assert p['version'] == original['version'] and p['eventHash'] == original['eventHash']
        assert p['liquidationEquityCents'] is None and p['quoteWinRatePercent'] is None
    assert store.experiment('fixture')['accounts'] == result['accounts']
    store.create('market', 'Market', source='alpaca')
    with pytest.raises(ValueError, match='cannot be combined'): store.comparison([ids[0], 'market'])
    repo.close()


@pytest.mark.parametrize('accounts', [[], ['x', 'x'], ['x'] * 5, ['../x'], [1], 'x'])
def test_invalid_comparison_has_no_mutation(accounts):
    repo = Repository(); store = ObservedPaperStore(repo, Clock())
    with pytest.raises(ValueError): store.comparison(accounts)
    assert store.accounts() == []
    repo.close()


def test_api_setup_and_comparison_are_authenticated_bounded_and_read_only():
    repo = Repository()
    with TestClient(create_app(repo, TOKEN)) as client:
        setup = '/api/observed-paper/experiment'; compare = '/api/observed-paper/comparison'
        assert client.post(setup, json={}).status_code == 401
        assert client.get(compare, params={'accounts': 'x'}).status_code == 401
        for bad in ({'source': 'live'}, {'initial_cash_cents': 200000}, {'enabled': True}, {'source': 'fixture', 'prices': {}}):
            assert client.post(setup, headers=HEADERS, json=bad).status_code == 422
        response = client.post(setup, headers=HEADERS, json={})
        assert response.status_code == 200
        body = response.json(); ids = [s['state']['id'] for s in body['accounts']]
        assert body['source'] == 'alpaca' and body['created']
        assert client.post(setup, headers=HEADERS, json={}).json()['created'] is False
        report = client.get(compare, headers=HEADERS, params={'accounts': ','.join(ids)}).json()
        assert len(report['accounts']) == 4 and report['externalOrder'] is False
        assert client.get(compare, headers=HEADERS, params={'accounts': ','.join(ids + ids)}).status_code == 422
        assert client.get(compare, headers=HEADERS, params={'accounts': 'missing'}).status_code == 409
        assert client.get('/api/observed-paper/status', headers=HEADERS).json()['newMarketEntryAllowed'] is False
    repo.close()


def test_disposable_postgres_acceptance_contract_on_sqlite(tmp_path):
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parents[2] / 'scripts'))
    from observed_experiment_check import check
    url = 'sqlite:///' + str(tmp_path / 'acceptance.db')
    repositories = [Repository(url, invalidate_accounts=False) for _ in range(2)]
    try:
        assert len(check(repositories)['checks']) == 4
    finally:
        for repo in repositories: repo.close()
