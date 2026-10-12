"""Append-only journal segmentation; no eviction or total account record cap."""
from hashlib import sha256

SEGMENT_RECORDS = 1000
SEGMENT_BYTES = 64 * 1024 * 1024


def append(db, account_id, sequence, size, digest):
    last = db.one('SELECT * FROM market_journal_segments WHERE account_id=? ORDER BY number DESC LIMIT 1', (account_id,))
    if sequence != (last['last_sequence'] + 1 if last else 1):
        raise ValueError('Journal segment sequence mismatch')
    if size > SEGMENT_BYTES:
        raise ValueError('Record exceeds segment size')
    if last and (last['record_count'] >= SEGMENT_RECORDS or last['size_bytes'] + size > SEGMENT_BYTES):
        db.execute('UPDATE market_journal_segments SET sealed=1 WHERE account_id=? AND number=?', (account_id, last['number']))
        last = None
    if last is None:
        previous = db.one('SELECT COALESCE(MAX(number),0) AS n FROM market_journal_segments WHERE account_id=?', (account_id,))['n']
        db.execute('INSERT INTO market_journal_segments VALUES(?,?,?,?,?,?,?,0,?)',
                   (account_id, previous + 1, sequence, sequence, 1, size, digest, digest))
    else:
        chain = sha256((last['chain_sha256'] + ':' + digest).encode()).hexdigest()
        db.execute('UPDATE market_journal_segments SET last_sequence=?,record_count=record_count+1,size_bytes=size_bytes+?,chain_sha256=? WHERE account_id=? AND number=?',
                   (sequence, size, chain, account_id, last['number']))


def stats(db, account_id):
    totals = db.one('SELECT COUNT(*) AS segments,COALESCE(SUM(record_count),0) AS records,COALESCE(SUM(size_bytes),0) AS bytes FROM market_journal_segments WHERE account_id=?', (account_id,))
    latest = db.one('SELECT number,record_count,size_bytes,sealed FROM market_journal_segments WHERE account_id=? ORDER BY number DESC LIMIT 1', (account_id,))
    return {**totals, 'active_segment': latest, 'segment_max_records': SEGMENT_RECORDS,
            'segment_max_bytes': SEGMENT_BYTES, 'total_record_limit': None,
            'retention': 'append_only_no_eviction', 'storage': 'database_requires_disk_monitoring'}
