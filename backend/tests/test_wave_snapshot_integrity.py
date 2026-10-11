"""Saved account-scoped wave evidence cannot silently restart after corruption."""
from copy import deepcopy
from datetime import timedelta
from hashlib import sha256
import json
import uuid

import pytest

from app.analysis_service import snapshot_analysis
from app.service import Rejected
from test_rc2_safety import DurableWorld


@pytest.fixture
def world(tmp_path):
    value = DurableWorld(tmp_path / 'wave-journal.db')
    yield value
    value.repo.close()


def saved(world, identifier):
    with world.repo.transaction() as db:
        return db.one('SELECT * FROM decision_snapshots WHERE id=?', (identifier,))


@pytest.mark.parametrize('corruption', ['digest', 'account', 'symbol', 'source', 'schema',
    'authority', 'missing_tracker', 'missing_timestamps', 'future_version', 'missing_journal'])
def test_corrupted_wave_history_fails_closed_without_new_snapshot(world, corruption):
    original = snapshot_analysis(world.service, world.account, 'NVDA')
    row = saved(world, original['snapshot_id'])
    payload = json.loads(row['payload'])
    world.time += timedelta(minutes=1)
    if corruption == 'account':
        payload['analysis']['account_id'] = 'another-account'
    elif corruption == 'symbol':
        payload['analysis']['symbol'] = 'AAPL'
    elif corruption == 'source':
        payload['analysis']['source'] = 'unverified'
    elif corruption == 'schema':
        payload['analysis']['schema_version'] = 2
    elif corruption == 'authority':
        payload['analysis']['executable'] = True
    elif corruption == 'missing_tracker':
        del payload['wave_tracker_state']
    elif corruption == 'missing_timestamps':
        payload['analysis']['timestamps'] = []
    elif corruption == 'future_version':
        payload['source_version'] = payload['analysis']['source_version'] = 'synthetic-ohlc-v2'
    identifier = str(uuid.uuid4())
    encoded = json.dumps(payload, sort_keys=True)
    digest = '0'*64 if corruption == 'digest' else sha256(encoded.encode()).hexdigest()
    with world.repo.transaction() as db:
        if corruption != 'missing_journal':
            # A restored/imported damaged checkpoint; historical rows stay immutable.
            db.execute('INSERT INTO decision_snapshots VALUES(?,?,?,?,?,?,?,?)',
                (identifier, world.account, None, None, 'SHADOW_ANALYSIS', encoded, digest, world.time.isoformat()))
        world.service.audit(db, world.account, 'ANALYSIS_SNAPSHOT',
            {'snapshot_id': identifier, 'symbol': 'NVDA', 'source': 'synthetic_fixture', 'execution_authority': False})
    before = world.service.rows(world.account, 'decision_snapshots')
    with pytest.raises(Rejected, match='refusing reset'):
        snapshot_analysis(world.service, world.account, 'NVDA')
    assert world.service.rows(world.account, 'decision_snapshots') == before
    assert saved(world, original['snapshot_id']) == row
    assert not world.service.rows(world.account, 'orders')


def test_restart_and_future_append_preserve_original_wave_generations(world):
    first = snapshot_analysis(world.service, world.account, 'NVDA')
    first_row = saved(world, first['snapshot_id'])
    initial = json.loads(first_row['payload'])['wave_tracker_state']
    world.time += timedelta(minutes=15)
    second = snapshot_analysis(world.service, world.account, 'NVDA')
    state = json.loads(saved(world, second['snapshot_id'])['payload'])['wave_tracker_state']
    world.reopen()
    world.time += timedelta(minutes=15)
    third = snapshot_analysis(world.service, world.account, 'NVDA')
    final = json.loads(saved(world, third['snapshot_id'])['payload'])['wave_tracker_state']
    assert first['analysis']['bar_count'] == 180
    assert second['analysis']['bar_count'] == 195
    assert third['analysis']['bar_count'] == 210
    assert state['events'][:len(initial['events'])] == initial['events']
    assert final['events'][:len(state['events'])] == state['events']
    assert all(final['source_hashes'][stamp] == value for stamp, value in initial['source_hashes'].items())
    assert saved(world, first['snapshot_id']) == first_row
    assert third['analysis']['source_version'] == 'synthetic-ohlc-v1'


def test_known_unversioned_fixture_history_is_preserved(world):
    original_save = world.service.decision
    def legacy_save(db, account_id, action, facts, order_id=None, intent_id=None):
        facts = deepcopy(facts)
        facts.pop('source_version', None)
        if action == 'SHADOW_ANALYSIS':
            facts['analysis'].pop('source_version', None)
        return original_save(db, account_id, action, facts, order_id, intent_id)
    world.service.decision = legacy_save
    first = snapshot_analysis(world.service, world.account, 'NVDA')
    legacy = saved(world, first['snapshot_id'])
    world.service.decision = original_save
    world.time += timedelta(minutes=1)
    continued = snapshot_analysis(world.service, world.account, 'NVDA')
    assert continued['analysis']['bar_count'] == 181
    assert saved(world, first['snapshot_id']) == legacy


def test_nonempty_wave_event_generations_survive_database_restart(world, monkeypatch):
    from app import analysis_service
    from test_intelligence_v1 import bars
    # A deterministic completed-bar fixture that actually contains wave counts;
    # the ordinary oscillating demo window may correctly produce zero events.
    data = bars(130, slope=.2)
    monkeypatch.setattr(analysis_service, 'analysis_fixture',
        lambda symbol, now, start=None: tuple(bar for bar in data if bar.timestamp < now))
    world.time = data[99].timestamp + timedelta(minutes=1)
    first = snapshot_analysis(world.service, world.account, 'NVDA')
    first_row = saved(world, first['snapshot_id'])
    initial = json.loads(first_row['payload'])['wave_tracker_state']['events']
    assert initial
    world.reopen()
    world.time = data[114].timestamp + timedelta(minutes=1)
    next_snapshot = snapshot_analysis(world.service, world.account, 'NVDA')
    continued = json.loads(saved(world, next_snapshot['snapshot_id'])['payload'])['wave_tracker_state']['events']
    assert len(continued) > len(initial)
    assert continued[:len(initial)] == initial
    assert [event['sequence'] for event in continued] == list(range(1, len(continued)+1))
    assert saved(world, first['snapshot_id']) == first_row
