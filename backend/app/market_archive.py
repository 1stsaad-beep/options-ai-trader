"""Streaming, data-only exports. Originals remain in the append-only database.

No SQL, keys, account balances, execution permissions or broker operations in
this format. Restore requires a trusted file and its independently checked hash,
an existing matching account identity, and disabled runtime for that account.
"""
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import stat

from . import market_data_journal as journal, market_segments

FORMAT = 'oat-market-archive-v1'
MAX_LINE = 8 * 1024 * 1024
TABLES = {
    'market_data_journal': ('id account_id sequence request_key fingerprint kind symbol recorded_at payload digest size_bytes'.split(), 'sequence'),
    'market_runtime_events': ('id account_id event_key created payload digest'.split(), 'id'),
    'market_runtime_ack': ('account_id event_id acknowledged_at'.split(), 'event_id'),
    'audit': ('id account_id event detail created'.split(), 'id'),
}


class ArchiveError(ValueError):
    pass


def _open(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise ArchiveError('ARCHIVE_REGULAR_FILE_REQUIRED')
        return os.fdopen(fd, 'rb')
    except BaseException:
        os.close(fd)
        raise


def _row(table, value, account, cutoff):
    columns, _ = TABLES[table]
    if set(value) != set(columns) or value.get('account_id') != account:
        raise ArchiveError('ARCHIVE_ACCOUNT_OR_SCHEMA_MISMATCH')
    for field in columns:
        if field not in ('sequence', 'size_bytes') and not isinstance(value[field], str):
            raise ArchiveError('ARCHIVE_INVALID_ROW')
    if table == 'market_data_journal':
        if any(type(value[k]) is not int or value[k] < 1 for k in ('sequence', 'size_bytes')):
            raise ArchiveError('ARCHIVE_INVALID_ROW')
        original = journal._decode(value)
        if original['observation'].get('account_id') != account:
            raise ArchiveError('ARCHIVE_OBSERVATION_ACCOUNT_MISMATCH')
        at = journal.timestamp(original['recorded_at'])
        if at > cutoff or value['size_bytes'] > journal.MAX_RECORD_BYTES:
            raise ArchiveError('ARCHIVE_INVALID_OBSERVATION_TIME_OR_SIZE')
        journal._validate_observation(original['observation'], account, original['request'], at)
    elif table == 'market_runtime_events':
        if sha256(value['payload'].encode()).hexdigest() != value['digest']:
            raise ArchiveError('ARCHIVE_EVENT_DIGEST_MISMATCH')
        original = json.loads(value['payload'])
        if any(original[k] != value[k] for k in ('id', 'account_id', 'created')) or any(
                original.get(k) is not False for k in ('external_orders_enabled', 'virtual_fills_enabled')):
            raise ArchiveError('ARCHIVE_EVENT_METADATA_MISMATCH')
        if journal.timestamp(value['created']) > cutoff:
            raise ArchiveError('ARCHIVE_FUTURE_EVENT')
    elif table == 'audit':
        if value['event'] != 'MARKET_DATA_OBSERVATION_SAVED' or journal.timestamp(value['created']) > cutoff:
            raise ArchiveError('ARCHIVE_AUDIT_SCOPE')
        json.loads(value['detail'])
    else:
        if journal.timestamp(value['acknowledged_at']) > cutoff:
            raise ArchiveError('ARCHIVE_FUTURE_ACK')


def _walk(handle, consumer=None):
    body_hash, file_hash = sha256(), sha256()
    counts = {t: 0 for t in TABLES}
    header = None
    seen_group = -1
    previous = {}
    last_time = None
    for raw in iter(lambda: handle.readline(MAX_LINE + 1), b''):
        if len(raw) > MAX_LINE or not raw.endswith(b'\n'):
            raise ArchiveError('ARCHIVE_INVALID_LINE')
        file_hash.update(raw)
        item = json.loads(raw)
        if header is None:
            if set(item) != {'format', 'account_id', 'created_at', 'counts'} or item['format'] != FORMAT:
                raise ArchiveError('ARCHIVE_FORMAT_UNSUPPORTED')
            if not isinstance(item['account_id'], str) or not 1 <= len(item['account_id']) <= 128:
                raise ArchiveError('ARCHIVE_INVALID_ACCOUNT')
            if set(item['counts']) != set(TABLES) or any(type(n) is not int or n < 0 for n in item['counts'].values()):
                raise ArchiveError('ARCHIVE_INVALID_COUNTS')
            header = item
            cutoff = journal.timestamp(header['created_at'])
        elif set(item) == {'end', 'body_sha256'}:
            if item['end'] is not True or item['body_sha256'] != body_hash.hexdigest() or counts != header['counts'] or handle.read(1):
                raise ArchiveError('ARCHIVE_DIGEST_COUNT_OR_TRAILING_DATA')
            return {**header, 'sha256': file_hash.hexdigest(), 'verified': True}
        else:
            if set(item) != {'table', 'row'} or item['table'] not in TABLES:
                raise ArchiveError('ARCHIVE_INVALID_TABLE')
            table, row = item['table'], item['row']
            index = list(TABLES).index(table)
            if index < seen_group:
                raise ArchiveError('ARCHIVE_INVALID_ORDER')
            seen_group = index
            _row(table, row, header['account_id'], cutoff)
            order = row[TABLES[table][1]]
            if table in previous and order <= previous[table]:
                raise ArchiveError('ARCHIVE_DUPLICATE_OR_UNSORTED_ROW')
            previous[table] = order
            counts[table] += 1
            if table == 'market_data_journal':
                at = journal.timestamp(row['recorded_at'])
                if order != counts[table] or (last_time is not None and at < last_time):
                    raise ArchiveError('ARCHIVE_GAP_OR_CLOCK_ROLLBACK')
                last_time = at
            if consumer is not None:
                consumer(table, row)
        body_hash.update(raw)
    raise ArchiveError('ARCHIVE_INCOMPLETE')


def verify(path, *, expected_sha256=None):
    try:
        with _open(path) as handle:
            result = _walk(handle)
        if expected_sha256 is not None and result['sha256'] != expected_sha256:
            raise ArchiveError('ARCHIVE_FILE_DIGEST_MISMATCH')
        return result
    except ArchiveError:
        raise
    except (OSError, ValueError, TypeError, KeyError, RecursionError):
        raise ArchiveError('ARCHIVE_INVALID_OR_UNREADABLE') from None


def export(service, account_id, destination):
    """Consistent streaming snapshot, serialized with writers; never overwrite.

    Schedule large full exports in a maintenance window. All original rows stay
    online; copies can be moved to encrypted/off-host storage by the operator.
    A failed export is retained but has no valid footer and cannot be restored.
    """
    destination = Path(destination)
    descriptor = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, 'wb') as handle, service.repo.transaction() as db:
        service.account(db, account_id)
        counts = {}
        for table in TABLES:
            where = " AND event='MARKET_DATA_OBSERVATION_SAVED'" if table == 'audit' else ''
            counts[table] = db.one('SELECT COUNT(*) AS n FROM ' + table + ' WHERE account_id=?' + where, (account_id,))['n']
        cutoff = journal.utc(journal.utc_now())
        header = {'format': FORMAT, 'account_id': account_id, 'created_at': cutoff, 'counts': counts}
        digest = sha256()
        def write(value):
            raw = (journal.canonical(value) + '\n').encode()
            handle.write(raw)
            digest.update(raw)
        write(header)
        for table, (_, order) in TABLES.items():
            where = " AND event='MARKET_DATA_OBSERVATION_SAVED'" if table == 'audit' else ''
            cursor = db.execute('SELECT * FROM ' + table + ' WHERE account_id=?' + where + ' ORDER BY ' + order, (account_id,))
            for raw in cursor:
                row = dict(raw)
                _row(table, row, account_id, journal.timestamp(cutoff))
                write({'table': table, 'row': row})
        handle.write((journal.canonical({'end': True, 'body_sha256': digest.hexdigest()}) + '\n').encode())
        handle.flush()
        os.fsync(handle.fileno())
    directory = os.open(destination.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
    return verify(destination)


def restore(service, account_id, path, *, expected_sha256, trusted_archive=False):
    if not trusted_archive or not re.fullmatch(r'[0-9a-f]{64}', expected_sha256 or ''):
        raise ArchiveError('TRUSTED_ARCHIVE_AND_DIGEST_REQUIRED')
    result = verify(path, expected_sha256=expected_sha256)
    if result['account_id'] != account_id:
        raise ArchiveError('ARCHIVE_ACCOUNT_MISMATCH')
    added = {table: 0 for table in TABLES}
    from .market_runtime import config_in
    try:
        with service.repo.transaction() as db:
            service.account(db, account_id)
            if config_in(db, account_id)['enabled']:
                raise ArchiveError('DISABLE_ACCOUNT_RUNTIME_BEFORE_RESTORE')
            def insert(table, row):
                columns, key = TABLES[table]
                existing = db.one('SELECT * FROM ' + table + ' WHERE account_id=? AND ' + key + '=?', (account_id, row[key]))
                if existing is not None:
                    if existing != row:
                        raise ArchiveError('ARCHIVE_EXISTING_ROW_CONFLICT')
                    return
                db.execute('INSERT INTO ' + table + '(' + ','.join(columns) + ') VALUES(' + ','.join('?' for _ in columns) + ')', tuple(row[k] for k in columns))
                if table == 'market_data_journal':
                    market_segments.append(db, account_id, row['sequence'], row['size_bytes'], row['digest'])
                added[table] += 1
            # Revalidate the bytes actually inserted, inside the same transaction.
            with _open(path) as handle:
                checked = _walk(handle, insert)
            if checked != result:
                raise ArchiveError('ARCHIVE_CHANGED_DURING_RESTORE')
    except ArchiveError:
        raise
    except Exception:
        raise ArchiveError('ARCHIVE_RESTORE_ROLLED_BACK') from None
    return {**result, 'added': added, 'runtime_enabled': False, 'external_orders_enabled': False,
            'virtual_fills_enabled': False, 'original_availability_preserved': True}
