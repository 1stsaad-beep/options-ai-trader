"""Real local persistence/streaming exports; synthetic provider responses only."""
from copy import deepcopy
from hashlib import sha256
import json
import sqlite3
from unittest.mock import patch
import pytest
from app import market_archive as archive, market_data_journal as journal, market_segments as segments, market_runtime as rt
from app.repository import Repository
from app.service import TradingService
from test_market_runtime import Clock, runtime_fixture, enable, collect_cycle


@pytest.fixture
def setup(tmp_path, monkeypatch):
    clock = Clock()
    monkeypatch.setattr(journal, 'utc_now', clock.now)
    source = Repository('sqlite:///' + str(tmp_path/'source.db'))
    c, wire = runtime_fixture(source, clock)
    account = enable(c.service)
    # The identity backup predates market observations. Financial/account state
    # is restored with the existing DB backup, never manufactured by this format.
    target_path = tmp_path/'restored.db'
    backup = sqlite3.connect(target_path)
    source.connection.backup(backup)
    backup.close()
    target = Repository('sqlite:///' + str(target_path), invalidate_accounts=False)
    restored = TradingService(target, now=clock.now)
    rt.configure(restored, account, expected_version=1, enabled=False,
                 strategies={'breakout': True, 'pullback': False})
    collect_cycle(c)
    rt.acknowledge(c.service, account, rt.events(c.service, account)['items'][0]['id'])
    yield c.service, restored, account, tmp_path, clock
    target.close()
    source.close()


def test_roundtrip_original_rows_hashes_events_ack_audit_and_idempotent_restore(setup):
    s, restored, a, root, _ = setup
    path = root/'market.jsonl'
    report = archive.export(s, a, path)
    assert path.stat().st_mode & 0o777 == 0o600
    assert report == archive.verify(path, expected_sha256=report['sha256'])
    before = restored.rows(a, 'orders')
    imported = archive.restore(restored, a, path, expected_sha256=report['sha256'], trusted_archive=True)
    assert imported['added']['market_data_journal'] == 3
    with s.repo.transaction() as db:
        originals = db.all('SELECT * FROM market_data_journal ORDER BY sequence')
    with restored.repo.transaction() as db:
        assert db.all('SELECT * FROM market_data_journal ORDER BY sequence') == originals
        assert not rt.config_in(db, a)['enabled']
    assert restored.rows(a, 'orders') == before == []
    again = archive.restore(restored, a, path, expected_sha256=report['sha256'], trusted_archive=True)
    assert all(n == 0 for n in again['added'].values())
    assert journal.replay(restored, a, originals[0]['id']) == journal.replay(s, a, originals[0]['id'])


def test_more_than_1000_originals_roll_over_without_loss(setup):
    s, _, a, _, clock = setup
    with s.repo.transaction() as db:
        value = json.loads(db.one('SELECT payload FROM market_data_journal ORDER BY sequence LIMIT 1')['payload'])['observation']
    # A fixture envelope for each new request; no network.
    provider = type('Fixture', (), {'option_chain': lambda self, _: deepcopy(value)})()
    for i in range(1000):
        journal.capture(s, a, {'kind': 'option_chain', 'symbol': 'AAPL', 'request_key': 'long-run:' + str(i)}, provider)
    with s.repo.transaction() as db:
        stats = segments.stats(db, a)
        assert stats['records'] == 1003 and stats['segments'] == 2
        assert db.one('SELECT sealed FROM market_journal_segments WHERE number=1')['sealed'] == 1
        assert db.one('SELECT COUNT(*) AS n FROM market_data_journal')['n'] == 1003
    with pytest.raises(sqlite3.IntegrityError, match='immutable'):
        with s.repo.transaction() as db:
            db.execute('UPDATE market_journal_segments SET size_bytes=0 WHERE number=1')


def test_byte_threshold_rotates_without_evicting_originals(setup, monkeypatch):
    s, _, a, _, _ = setup
    with s.repo.transaction() as db:
        original = db.one('SELECT * FROM market_data_journal ORDER BY sequence LIMIT 1')
        used = segments.stats(db, a)['bytes']
    monkeypatch.setattr(segments, 'SEGMENT_BYTES', used + 1)
    value = json.loads(original['payload'])['observation']
    provider = type('Fixture', (), {'option_chain': lambda self, _: value})()
    journal.capture(s, a, {'kind': 'option_chain', 'symbol': 'AAPL', 'request_key': 'byte-rollover'}, provider)
    with s.repo.transaction() as db:
        assert segments.stats(db, a)['segments'] == 2
        assert db.one('SELECT * FROM market_data_journal WHERE id=?', (original['id'],)) == original


def test_actual_total_exceeds_64_mib_without_account_cap(setup):
    s, _, a, _, _ = setup
    with s.repo.transaction() as db:
        original = db.one('SELECT * FROM market_data_journal ORDER BY sequence LIMIT 1')
    value = json.loads(original['payload'])['observation']
    value['usage'] = 'synthetic-storage-capacity-fixture:' + 'x' * 1990000
    provider = type('Fixture', (), {'option_chain': lambda self, _: value})()
    for i in range(34):
        journal.capture(s, a, {'kind': 'option_chain', 'symbol': 'AAPL', 'request_key': 'actual-bytes:' + str(i)}, provider)
    with s.repo.transaction() as db:
        info = segments.stats(db, a)
        assert info['bytes'] > 64 * 1024 * 1024 and info['segments'] == 2
        assert db.one('SELECT * FROM market_data_journal WHERE id=?', (original['id'],)) == original


def test_segment_write_failure_rolls_back_new_original(setup):
    s, _, a, _, _ = setup
    with s.repo.transaction() as db:
        value = json.loads(db.one('SELECT payload FROM market_data_journal ORDER BY sequence LIMIT 1')['payload'])['observation']
        before = segments.stats(db, a)
    provider = type('Fixture', (), {'option_chain': lambda self, _: value})()
    with patch.object(segments, 'append', side_effect=OSError('disk fixture')), pytest.raises(OSError):
        journal.capture(s, a, {'kind': 'option_chain', 'symbol': 'AAPL', 'request_key': 'disk-failure'}, provider)
    with s.repo.transaction() as db:
        assert segments.stats(db, a) == before
        assert db.one('SELECT COUNT(*) AS n FROM market_data_journal')['n'] == 3


@pytest.mark.parametrize('change', ['truncated', 'edited', 'extra', 'bad_digest', 'symlink'])
def test_invalid_archive_never_changes_target(setup, change):
    s, restored, a, root, _ = setup
    path = root/'archive.jsonl'
    result = archive.export(s, a, path)
    if change == 'truncated':
        path.write_bytes(path.read_bytes()[:-50])
    elif change == 'edited':
        path.write_bytes(path.read_bytes().replace(b'alpaca', b'forged', 1))
    elif change == 'extra':
        path.write_bytes(path.read_bytes()+b'{}\n')
    elif change == 'bad_digest':
        result['sha256'] = '0'*64
    else:
        linked = root/'alias'
        linked.symlink_to(path)
        path = linked
    with pytest.raises(archive.ArchiveError):
        archive.restore(restored, a, path, expected_sha256=result['sha256'], trusted_archive=True)
    assert journal.list_records(restored, a)['items'] == []


def test_late_conflict_rolls_back_earlier_insertions(setup):
    s, restored, a, root, clock = setup
    path = root/'archive.jsonl'
    info = archive.export(s, a, path)
    with s.repo.transaction() as db:
        event = db.one("SELECT * FROM market_runtime_events WHERE event_key NOT LIKE 'config:%' LIMIT 1")
    with restored.repo.transaction() as db:
        db.execute('INSERT INTO market_runtime_events VALUES(?,?,?,?,?,?)',
                   (event['id'], a, event['event_key'], event['created'], 'conflicting-existing-payload', 'bad'))
    with pytest.raises(archive.ArchiveError, match='CONFLICT'):
        archive.restore(restored, a, path, expected_sha256=info['sha256'], trusted_archive=True)
    assert journal.list_records(restored, a)['items'] == []
    with restored.repo.transaction() as db:
        assert segments.stats(db, a)['records'] == 0


def test_archive_identity_trust_enabled_runtime_and_overwrite_guards(setup):
    s, restored, a, root, _ = setup
    path = root/'archive.jsonl'
    info = archive.export(s, a, path)
    with pytest.raises(FileExistsError):
        archive.export(s, a, path)
    with pytest.raises(archive.ArchiveError, match='TRUSTED'):
        archive.restore(restored, a, path, expected_sha256=info['sha256'])
    with pytest.raises(archive.ArchiveError, match='ACCOUNT_MISMATCH'):
        archive.restore(restored, 'other-account', path, expected_sha256=info['sha256'], trusted_archive=True)
    with pytest.raises(archive.ArchiveError, match='DISABLE_ACCOUNT'):
        archive.restore(s, a, path, expected_sha256=info['sha256'], trusted_archive=True)


def test_file_change_during_restore_rolls_back(setup):
    s, restored, a, root, _ = setup
    path = root/'archive.jsonl'
    info = archive.export(s, a, path)
    original_open = archive._open
    count = [0]
    def changed(p):
        count[0] += 1
        if count[0] == 2:
            path.write_bytes(path.read_bytes()[:-20])
        return original_open(p)
    with patch.object(archive, '_open', changed), pytest.raises(archive.ArchiveError):
        archive.restore(restored, a, path, expected_sha256=info['sha256'], trusted_archive=True)
    assert journal.list_records(restored, a)['items'] == []
