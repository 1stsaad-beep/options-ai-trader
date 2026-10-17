"""Durable, owner-polled runtime transitions; no external notification sender.

Writes share the fenced worker heartbeat transaction. A stopped process cannot
observe its own outage: late-heartbeat evidence is recorded on the next owned
tick with the detection time, never an invented time of failure. Reads and ACKs
cannot reset credentials, clear a fault, start a worker, or change a ledger.
"""
import json
import re

from .observed_paper import canonical, digest
from .observed_option_replay import iso
from .observed_paper_status import DIAGNOSTICS, read_status
from .observed_paper_store import LedgerConflict
from .paper_settlement import stamp

VERSION = 'observed-alert-inbox-v1'
ZERO = '0' * 64
MAX_SEQUENCE = 2**53 - 1
CODES = DIAGNOSTICS | {'WORKER_UNAVAILABLE', 'LEDGER_REVIEW_REQUIRED', 'DATA_BACKOFF', 'DATA_STATE_REVIEW_REQUIRED'}
AUTHORITY = {'contractVersion': VERSION, 'mode': 'observed_market_virtual',
    'externalOrder': False, 'executionAllowed': False, 'delivery': 'OWNER_POLL_AT_LEAST_ONCE',
    'scope': 'WORKER_OBSERVATIONS_NOT_EXTERNAL_PUSH'}


def integer(value, low=0, high=MAX_SEQUENCE):
    if type(value) is not int or not low <= value <= high:
        raise ValueError('Invalid alert cursor')
    return value


def fingerprint(value):
    if not isinstance(value, str) or re.fullmatch('[a-f0-9]{64}', value) is None:
        raise ValueError('Invalid alert fingerprint')
    return value


def decode(row):
    try:
        event = json.loads(row['payload'])
        if (not isinstance(event, dict) or set(event) != {'sequence', 'detectedAt', 'active', 'raised', 'resolved', 'previousHash'}
                or event['sequence'] != integer(row['sequence'], 1)
                or type(event['sequence']) is not int
                or event['previousHash'] != fingerprint(row['previous_hash'])
                or digest(event) != fingerprint(row['digest'])):
            raise ValueError()
        stamp(event['detectedAt'])
        for key in ('active', 'raised', 'resolved'):
            values = event[key]
            if (not isinstance(values, list) or any(not isinstance(v, str) or v not in CODES for v in values)
                    or values != sorted(set(values))):
                raise ValueError()
        if not set(event['raised']) <= set(event['active']) or set(event['resolved']) & set(event['active']):
            raise ValueError()
        return event | {'eventHash': row['digest']}
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError):
        raise LedgerConflict('Alert journal requires review') from None


def latest(db):
    row = db.one('SELECT * FROM observed_alert_events ORDER BY sequence DESC LIMIT 1')
    return decode(row) if row else None


def record(db, now):
    """Caller must hold the serialized alert transaction. A worker also needs
    current ownership; the independent watchdog only projects current status."""
    active = sorted(read_status(db, now)['alerts'])
    old = latest(db)
    prior = old['active'] if old else []
    if old and active == prior:
        return  # No heartbeat spam, including an acknowledged persistent fault.
    event = {'sequence': integer(old['sequence'] + 1 if old else 1, 1),
        'detectedAt': iso(now), 'active': active,
        'raised': sorted(set(active) - set(prior)), 'resolved': sorted(set(prior) - set(active)),
        'previousHash': old['eventHash'] if old else ZERO}
    db.execute('INSERT INTO observed_alert_events VALUES(?,?,?,?)',
        (event['sequence'], canonical(event), digest(event), event['previousHash']))


def acknowledgement(db):
    row = db.one("SELECT * FROM observed_alert_ack WHERE name='owner'")
    if row is None:
        return {'sequence': 0, 'eventHash': ZERO}
    source = db.one('SELECT * FROM observed_alert_events WHERE sequence=?', (row['sequence'],))
    if source is None or decode(source)['eventHash'] != row['digest']:
        raise LedgerConflict('Alert acknowledgement requires review')
    return {'sequence': row['sequence'], 'eventHash': row['digest']}


def page(store, after=None, limit=25, through=None):
    integer(limit, 1, 100)
    with store.repo.transaction() as db:
        ack = acknowledgement(db)
        start = ack['sequence'] if after is None else integer(after)
        head = latest(db)
        end = (head['sequence'] if head else 0) if through is None else integer(through)
        if not start <= end <= (head['sequence'] if head else 0):
            raise ValueError('Invalid alert range')
        def anchor(sequence):
            if sequence == 0: return ZERO
            row = db.one('SELECT * FROM observed_alert_events WHERE sequence=?', (sequence,))
            if row is None: raise LedgerConflict('Alert journal requires review')
            return decode(row)['eventHash']
        before_hash, end_hash = anchor(start), anchor(end)
        previous = before_hash
        events = []
        for row in db.all('SELECT * FROM observed_alert_events WHERE sequence>? AND sequence<=? ORDER BY sequence LIMIT ?', (start, end, limit)):
            event = decode(row)
            if event['sequence'] != start + len(events) + 1 or event['previousHash'] != previous:
                raise LedgerConflict('Alert journal requires review')
            events.append(event); previous = event['eventHash']
        cursor = events[-1]['sequence'] if events else start
        if cursor != min(start + limit, end) or (cursor == end and previous != end_hash):
            raise LedgerConflict('Alert journal requires review')
        return AUTHORITY | {'after': start, 'afterHash': before_hash, 'through': end, 'throughHash': end_hash,
            'acknowledged': ack, 'events': events, 'nextAfter': cursor, 'hasMore': cursor < end}


def acknowledge(store, sequence, event_hash, expected_ack):
    integer(sequence, 1); fingerprint(event_hash); integer(expected_ack)
    if expected_ack > sequence: raise ValueError('Invalid acknowledgement range')
    with store.repo.transaction() as db:
        row = db.one('SELECT * FROM observed_alert_events WHERE sequence=?', (sequence,))
        if row is None or decode(row)['eventHash'] != event_hash:
            raise LedgerConflict('Alert acknowledgement does not match original event')
        current = acknowledgement(db)
        # An exact retry after a lost response never reverses a newer ACK.
        if sequence > current['sequence']:
            if current['sequence'] != expected_ack:
                raise LedgerConflict('Alert acknowledgement changed; reload inbox')
            db.execute("INSERT INTO observed_alert_ack VALUES('owner',?,?) ON CONFLICT(name) DO UPDATE SET sequence=excluded.sequence,digest=excluded.digest",
                (sequence, event_hash))
            current = {'sequence': sequence, 'eventHash': event_hash}
        return AUTHORITY | {'acknowledged': current}
