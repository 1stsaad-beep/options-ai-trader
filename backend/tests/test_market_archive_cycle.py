"""Real disposable DB/files; no market transport or user financial data."""
import fcntl
import json
import os
from unittest.mock import Mock
import pytest
from app import market_archive_cycle as cycle, market_archive as archive
from test_market_archive import setup


def private(root):
    path = root / 'copies'
    path.mkdir(mode=0o700)
    return path


def test_repeated_cycles_preserve_originals_and_old_copies_and_restore(setup):
    service, target, account, root, _ = setup
    destination = private(root)
    with service.repo.transaction() as db:
        before = {t: db.all('SELECT * FROM ' + t) for t in ('accounts', 'orders', 'positions', 'audit', 'market_data_journal', 'market_runtime_config')}
    one = cycle.run_cycle(service, [account], destination, reserve_bytes=1)
    files = {p: p.read_bytes() for p in destination.rglob('*') if p.is_file()}
    two = cycle.run_cycle(service, [account], destination, reserve_bytes=1)
    assert one['directory'] != two['directory']
    assert all(p.read_bytes() == raw for p, raw in files.items())
    assert not one['external_copy_verified'] and not one['full_database_backup']
    receipt = one['accounts'][0]
    imported = archive.restore(target, account, os.path.join(one['directory'], receipt['file']), expected_sha256=receipt['sha256'], trusted_archive=True)
    assert imported['added']['market_data_journal'] == 3
    with service.repo.transaction() as db:
        assert before == {t: db.all('SELECT * FROM ' + t) for t in before}
    assert json.loads((destination / one['directory'] / 'completed.json').read_text())['verified']


def test_low_space_does_not_create_cycle_or_modify_originals(setup, monkeypatch):
    s, _, a, root, _ = setup
    destination = private(root)
    monkeypatch.setattr(cycle.shutil, 'disk_usage', lambda _: type('Usage', (), {'free': 0})())
    with pytest.raises(cycle.CycleError, match='RESERVE'):
        cycle.run_cycle(s, [a], destination)
    assert list(destination.glob('cycle-*')) == []


def test_concurrent_cycle_rejected_without_truncating_lock(setup):
    s, _, a, root, _ = setup
    destination = private(root)
    lock = destination / '.archive-cycle.lock'
    fd = os.open(lock, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        os.write(fd, b'retained')
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(cycle.CycleError, match='ALREADY_RUNNING'):
            cycle.run_cycle(s, [a], destination, reserve_bytes=1)
        assert lock.read_bytes() == b'retained'
        assert list(destination.glob('cycle-*')) == []
    finally:
        os.close(fd)


@pytest.mark.parametrize('failure', ['export', 'verify', 'space_after_export'])
def test_failed_cycle_retains_files_without_completion_receipt(setup, monkeypatch, failure):
    s, _, a, root, _ = setup
    destination = private(root)
    if failure == 'export':
        def failed_export(service, account, path):
            path.write_bytes(b'partial-fixture')
            raise OSError('disk full fixture')
        monkeypatch.setattr(archive, 'export', failed_export)
    elif failure == 'verify':
        original = archive.verify
        calls = 0
        def failed_verify(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise archive.ArchiveError('changed fixture')
            return original(*args, **kwargs)
        monkeypatch.setattr(archive, 'verify', failed_verify)
    else:
        monkeypatch.setattr(cycle, '_space', Mock(side_effect=[None, None, cycle.CycleError('space')]))
    with pytest.raises((OSError, ValueError)):
        cycle.run_cycle(s, [a], destination, reserve_bytes=1)
    assert len(list(destination.glob('cycle-*/account-*.jsonl'))) == 1
    assert list(destination.glob('cycle-*/completed.json')) == []


@pytest.mark.parametrize('invalid', ['empty', 'duplicate', 'missing', 'public', 'symlink'])
def test_scope_and_private_destination_guards(setup, invalid):
    s, _, a, root, _ = setup
    destination = private(root)
    accounts = [a]
    if invalid == 'empty': accounts = []
    if invalid == 'duplicate': accounts = [a, a]
    if invalid == 'missing': accounts = [a, 'not-an-account']
    if invalid == 'public': destination.chmod(0o755)
    if invalid == 'symlink':
        linked = root / 'linked'
        linked.symlink_to(destination, target_is_directory=True)
        destination = linked
    with pytest.raises(ValueError):
        cycle.run_cycle(s, accounts, destination, reserve_bytes=1)
    assert list(destination.glob('cycle-*')) == []


def test_cli_requires_explicit_database_and_redacts_connection_failures(setup, monkeypatch, capsys):
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location('archive_cycle_cli', Path(__file__).resolve().parents[2] / 'scripts/market_archive_cycle.py')
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    _, _, account, root, _ = setup
    destination = private(root)
    monkeypatch.delenv('DATABASE_URL', raising=False)
    assert cli.main([str(destination), '--account-id', account]) == 2
    monkeypatch.setenv('DATABASE_URL', 'private-fixture-not-a-connection')
    monkeypatch.setattr(cli, 'Repository', Mock(side_effect=RuntimeError('DO_NOT_EXPOSE_CREDENTIAL_FIXTURE')))
    assert cli.main([str(destination), '--account-id', account]) == 1
    assert 'DO_NOT_EXPOSE' not in capsys.readouterr().out


def test_cli_export_does_not_invalidate_demo_accounts(setup, monkeypatch, capsys):
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location('archive_cycle_cli', Path(__file__).resolve().parents[2] / 'scripts/market_archive_cycle.py')
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    service, _, account, root, _ = setup
    destination = private(root)
    with service.repo.transaction() as db:
        before = db.all('SELECT * FROM accounts')
    monkeypatch.setenv('DATABASE_URL', 'sqlite:///' + str(root / 'source.db'))
    assert cli.main([str(destination), '--account-id', account, '--reserve-mib', '1']) == 0
    assert json.loads(capsys.readouterr().out)['verified'] is True
    with service.repo.transaction() as db:
        assert db.all('SELECT * FROM accounts') == before
