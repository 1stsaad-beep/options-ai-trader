from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
import json
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app import migrations
from app.main import create_app
from app.market_data import MarketDataError
from app.observed_paper_alerts import page, acknowledge, ZERO
from app.observed_paper_runtime import ObservedPaperRuntime
from app.observed_paper_store import ObservedPaperStore, LedgerConflict
from app.repository import Repository, Session
from test_observed_paper import stored, iso
from test_alpaca_market_api import TOKEN, HEADERS


def failing(store, code='DATA_RATE_LIMITED', owner='worker'):
    def capture(*_): raise MarketDataError(code)
    return ObservedPaperRuntime(store, SimpleNamespace(source='fixture', capture=capture), owner=owner)


def test_fault_dedup_recovery_redaction_and_exact_lost_ack_retry(tmp_path):
    repo, store, clock = stored(tmp_path); before = store.snapshot('a', full=True)
    runtime = failing(store, 'secret provider body'); runtime.tick()
    first = page(store); event = first['events'][0]
    assert event['active'] == event['raised'] == ['DATA_UNAVAILABLE'] and not event['resolved']
    assert event['previousHash'] == ZERO and event['sequence'] == 1
    for _ in range(20): runtime.tick()
    assert page(store) == first and 'secret' not in json.dumps(first)
    result = acknowledge(store, 1, event['eventHash'], 0)
    assert acknowledge(store, 1, event['eventHash'], 0) == result
    assert not page(store)['events']
    runtime.tick(); assert not page(store)['events']  # ACK never clears the active condition
    runtime.provider = None; runtime.tick()
    resolved = page(store)['events'][0]
    assert resolved['resolved'] == event['active'] and not resolved['active']
    assert resolved['previousHash'] == event['eventHash']
    acknowledge(store, 2, resolved['eventHash'], 1)
    assert acknowledge(store, 1, event['eventHash'], 0)['acknowledged']['sequence'] == 2
    assert store.snapshot('a', full=True) == before
    repo.close()


def test_pinned_pages_survive_new_events_restart_and_clock_regression(tmp_path):
    repo, store, clock = stored(tmp_path); runtime = failing(store)
    runtime.tick(); runtime.close(); runtime.tick()
    original = page(store, after=0); first = page(store, after=0, limit=2)
    assert first['hasMore'] and first['through'] == 3
    clock.step(-5); runtime.close()
    repo.close(); repo = Repository('sqlite:///' + str(tmp_path/'observed.db'), invalidate_accounts=False)
    store = ObservedPaperStore(repo, clock)
    last = page(store, after=2, limit=2, through=first['through'])
    assert first['events'] + last['events'] == original['events']
    assert last['throughHash'] == original['throughHash'] and not last['hasMore']
    assert page(store, after=3)['events'][0]['sequence'] == 4
    repo.close()


def test_stale_heartbeat_detected_at_recovery_not_backdated_and_old_owner_fenced(tmp_path):
    repo, store, clock = stored(tmp_path)
    old = ObservedPaperRuntime(store, owner='reused'); old.tick()
    assert page(store)['events'][0]['active'] == []
    clock.step(61)
    successor = ObservedPaperRuntime(store, owner='reused'); successor.tick()
    result = page(store)
    assert [e['active'] for e in result['events']] == [[], ['WORKER_UNAVAILABLE'], []]
    assert result['events'][1]['detectedAt'] == iso(clock())
    old.close(); assert page(store) == result
    repo.close()


def test_expired_capture_cannot_publish_alerts(tmp_path):
    repo, store, clock = stored(tmp_path)
    def capture(*_): clock.step(31); raise MarketDataError('DATA_RATE_LIMITED')
    runtime = ObservedPaperRuntime(store, SimpleNamespace(source='fixture',capture=capture))
    runtime.tick()
    assert page(store)['through'] == 0
    repo.close()


def test_alert_failure_rolls_back_heartbeat_and_shutdown_lease(tmp_path, monkeypatch):
    repo, store, clock = stored(tmp_path); runtime = ObservedPaperRuntime(store); runtime.tick()
    before = page(store)
    with repo.transaction() as db:
        health = db.one("SELECT * FROM runtime_health WHERE name='observed_paper'")
        lease = db.one("SELECT * FROM observed_paper_lease WHERE name='worker'")
    original = Session.execute
    def fail(self, sql, parameters=()):
        if sql.startswith('INSERT INTO observed_alert_events'): raise sqlite3.OperationalError('disk unavailable')
        return original(self, sql, parameters)
    monkeypatch.setattr(Session, 'execute', fail)
    with pytest.raises(sqlite3.OperationalError): runtime.close()
    with repo.transaction() as db:
        assert db.one("SELECT * FROM runtime_health WHERE name='observed_paper'") == health
        assert db.one("SELECT * FROM observed_paper_lease WHERE name='worker'") == lease
    assert page(store) == before
    monkeypatch.setattr(Session, 'execute', original); runtime.close()
    assert page(store)['events'][-1]['active'] == ['WORKER_UNAVAILABLE']
    repo.close()


@pytest.mark.parametrize('args', [{'after':-1}, {'limit':0}, {'limit':101}, {'limit':True}, {'through':1}, {'after':1}])
def test_invalid_or_future_page_does_not_write(tmp_path,args):
    repo, store, _ = stored(tmp_path)
    with pytest.raises(ValueError): page(store, **args)
    assert page(store)['through'] == 0
    repo.close()


def test_concurrent_ack_is_monotonic_across_connections(tmp_path):
    repo, store, clock = stored(tmp_path); runtime = failing(store); runtime.tick(); runtime.close()
    other = Repository('sqlite:///' + str(tmp_path/'observed.db'), invalidate_accounts=False)
    stores = [store, ObservedPaperStore(other,clock)]
    events = page(store)['events']
    def ack(i):
        event = events[i]
        try: return acknowledge(stores[i],event['sequence'],event['eventHash'],0)
        except LedgerConflict: return None
    with ThreadPoolExecutor(max_workers=2) as pool: results = list(pool.map(ack, range(2)))
    assert any(results)
    current = page(store)['acknowledged']['sequence']
    assert current in (1,2)
    if current == 1: acknowledge(stores[1],2,events[1]['eventHash'],1)
    assert page(store)['acknowledged']['sequence'] == 2
    with pytest.raises(LedgerConflict): acknowledge(store,2,ZERO,0)
    other.close(); repo.close()


def test_auth_api_read_only_retry_ack_and_no_financial_side_effect(tmp_path):
    repo, store, _ = stored(tmp_path); failing(store).tick(); before = store.snapshot('a', full=True)
    with TestClient(create_app(repo,TOKEN)) as client:
        path='/api/observed-paper/alerts'
        assert client.get(path).status_code == 401
        assert client.post(path+'/ack',json={}).status_code == 401
        body=client.get(path,headers=HEADERS).json()
        event=body['events'][0]
        request={'sequence':event['sequence'],'event_hash':event['eventHash'],'expected_ack':0}
        assert client.post(path+'/ack',headers=HEADERS,json=request|{'sequence':True}).status_code == 422
        assert client.post(path+'/ack',headers=HEADERS,json=request|{'ignored':'secret'}).status_code == 422
        assert client.post(path+'/ack',headers=HEADERS,json=request|{'event_hash':ZERO}).status_code == 409
        response=client.post(path+'/ack',headers=HEADERS,json=request)
        assert response.status_code == 200
        assert client.post(path+'/ack',headers=HEADERS,json=request).json() == response.json()
        assert not client.get(path,headers=HEADERS).json()['events']
        assert client.get(path+'?after=0',headers=HEADERS).json()['events'] == body['events']
    assert store.snapshot('a',full=True) == before
    repo.close()


def test_native_immutability_and_corruption_not_exposed(tmp_path):
    repo, store, _ = stored(tmp_path); failing(store).tick()
    for sql in ('UPDATE observed_alert_events SET payload=payload','DELETE FROM observed_alert_events'):
        with pytest.raises(sqlite3.IntegrityError,match='immutable'):
            with repo.transaction() as db: db.execute(sql)
    with repo.transaction() as db:
        db.execute('DROP TRIGGER immutable_observed_alert_update')
        db.execute("UPDATE observed_alert_events SET payload='secret corrupted payload'")
    with pytest.raises(LedgerConflict,match='requires review'): page(store)
    with TestClient(create_app(repo,TOKEN)) as client:
        result=client.get('/api/observed-paper/alerts',headers=HEADERS)
        assert result.status_code == 409 and 'secret' not in result.text
    repo.close()


def test_additive_upgrade_preserves_old_financial_events(tmp_path,monkeypatch):
    all_migrations=migrations.MIGRATIONS
    monkeypatch.setattr(migrations,'MIGRATIONS',all_migrations[:10])
    repo,store,clock=stored(tmp_path); before=store.snapshot('a',full=True); repo.close()
    monkeypatch.setattr(migrations,'MIGRATIONS',all_migrations)
    repo=Repository('sqlite:///'+str(tmp_path/'observed.db'),invalidate_accounts=False)
    store=ObservedPaperStore(repo,clock)
    assert store.snapshot('a',full=True)==before and page(store)['through']==0
    failing(store).tick(); assert page(store)['through']==1
    repo.close()


def test_sqlite_backup_restore_keeps_ack_and_unread_original_events(tmp_path):
    import sys
    from pathlib import Path
    sys.path.insert(0,str(Path(__file__).parents[2]/'scripts'))
    from backup_restore import backup, restore
    repo,store,clock=stored(tmp_path); runtime=failing(store); runtime.tick(); runtime.close()
    first=page(store)['events'][0]; acknowledge(store,1,first['eventHash'],0)
    original=page(store,after=0)
    backup(tmp_path/'observed.db',tmp_path/'copy.db'); restore(tmp_path/'copy.db',tmp_path/'restored.db')
    recovered=Repository('sqlite:///'+str(tmp_path/'restored.db'),invalidate_accounts=False)
    other=ObservedPaperStore(recovered,clock)
    assert page(other,after=0)==original and page(other)['after']==1
    assert other.snapshot('a',full=True)==store.snapshot('a',full=True)
    recovered.close(); repo.close()


def test_shared_mobile_fixture_is_exact_actual_sql_output():
    import sys
    from pathlib import Path
    root=Path(__file__).parents[2]
    sys.path.insert(0,str(root/'scripts'))
    from generate_observed_alert_fixture import generate
    assert json.loads((root/'mobile/test/fixtures/observed_alert_v1.json').read_text()) == generate()
