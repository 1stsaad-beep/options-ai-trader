"""Opt-in Linux archive cycle. No provider, pruning, account creation or restore.

A completed receipt describes independently consistent account snapshots; it is
not a portfolio-wide snapshot or a replacement for a full database backup.
"""
import fcntl
import json
import os
from pathlib import Path
import shutil
import stat
import uuid

from . import market_archive as archive


class CycleError(ValueError):
    pass


def _space(directory, reserve):
    if shutil.disk_usage(directory).free < reserve:
        raise CycleError('ARCHIVE_FREE_SPACE_BELOW_RESERVE')


def run_cycle(service, accounts, destination, *, reserve_bytes=512 * 1024 * 1024):
    if not accounts or len(accounts) != len(set(accounts)) or any(
            not isinstance(a, str) or not 1 <= len(a) <= 128 for a in accounts):
        raise CycleError('EXPLICIT_UNIQUE_ACCOUNTS_REQUIRED')
    if type(reserve_bytes) is not int or reserve_bytes < 1:
        raise CycleError('POSITIVE_FREE_SPACE_RESERVE_REQUIRED')
    root = Path(destination).absolute()
    info = root.lstat()
    if (not stat.S_ISDIR(info.st_mode) or root.resolve() != root or
            info.st_uid != os.getuid() or info.st_mode & 0o077):
        raise CycleError('PRIVATE_OWNED_DIRECTORY_REQUIRED')
    descriptor = os.open(root / '.archive-cycle.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise CycleError('PRIVATE_REGULAR_LOCK_REQUIRED')
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise CycleError('ARCHIVE_CYCLE_ALREADY_RUNNING') from None
        # Validate every identity before creating any export. No implicit "all".
        with service.repo.transaction() as db:
            for account in accounts:
                service.account(db, account)
        _space(root, reserve_bytes)
        run = root / ('cycle-' + uuid.uuid4().hex)
        run.mkdir(mode=0o700)
        receipts = []
        for index, account in enumerate(accounts):
            _space(root, reserve_bytes)
            path = run / f'account-{index + 1:04d}.jsonl'
            result = archive.export(service, account, path)
            verified = archive.verify(path, expected_sha256=result['sha256'])
            if result != verified:
                raise CycleError('ARCHIVE_RECEIPT_CHANGED')
            receipts.append({'file': path.name, **verified})
            _space(root, reserve_bytes)
        manifest = {'format': 'oat-market-archive-cycle-v1', 'verified': True,
                    'accounts': receipts, 'originals_retained': True,
                    'external_copy_verified': False, 'full_database_backup': False}
        # A partial run has no completed.json. Retain it for investigation.
        pending = run / 'receipt.pending'
        with os.fdopen(os.open(pending, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), 'w') as handle:
            json.dump(manifest, handle, ensure_ascii=False, sort_keys=True)
            handle.write('\n')
            handle.flush()
            os.fsync(handle.fileno())
        os.link(pending, run / 'completed.json')
        for directory in (run, root):
            fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        return {'directory': str(run), **manifest}
    finally:
        os.close(descriptor)
