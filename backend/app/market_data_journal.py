"""Immutable, account-scoped observations. No broker, analysis or fill imports.

Capture is explicit: ordinary market-data GETs still do not write the database.
Only the server provider supplies the observation. Replay reads saved bytes and
never refreshes them. Provider event times are not a historical availability
claim: this service first knew the record at recorded_at, including old bars.
"""
from datetime import datetime, timezone
from hashlib import sha256
import hmac
import json
import re
import uuid

from .market_data import MODE, OPTION, TIMEFRAMES, symbol, timestamp

MAX_RECORD_BYTES = 2 * 1024 * 1024
MAX_ACCOUNT_BYTES = 64 * 1024 * 1024
MAX_ACCOUNT_RECORDS = 1000
KINDS = {'stock_snapshot': 'iex', 'stock_bars': 'iex',
         'option_chain': 'indicative', 'option_bars': 'historical_options'}


class JournalError(ValueError):
    def __init__(self, code, status=409):
        self.code, self.status = code, status
        super().__init__(code)


def utc_now():
    return datetime.now(timezone.utc)


def utc(value):
    return timestamp(value).isoformat(timespec='microseconds')


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)


def normalize_request(body):
    kind, key = body['kind'], body['request_key']
    if kind not in KINDS or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}', key):
        raise JournalError('INVALID_JOURNAL_REQUEST', 422)
    result = {'kind': kind, 'symbol': symbol(body['symbol'])}
    if kind.endswith('_bars'):
        start, end = timestamp(body.get('start')), timestamp(body.get('end'))
        timeframe = body.get('timeframe') or '1Day'
        if timeframe not in TIMEFRAMES or start >= end or end > timestamp(utc_now()):
            raise JournalError('INVALID_JOURNAL_HISTORY_RANGE', 422)
        result.update(start=utc(start), end=utc(end), timeframe=timeframe)
    elif any(body.get(k) is not None for k in ('start', 'end', 'timeframe')):
        raise JournalError('INVALID_JOURNAL_REQUEST', 422)
    if kind == 'option_bars':
        contract = symbol(body.get('contract'), option=True)
        root = OPTION.fullmatch(contract)[1]
        if root != result['symbol'] and root not in [result['symbol'] + str(n) for n in range(1, 10)]:
            raise JournalError('INVALID_JOURNAL_CONTRACT', 422)
        result['contract'] = contract
    elif body.get('contract') is not None:
        raise JournalError('INVALID_JOURNAL_REQUEST', 422)
    return key, result


def _capacity(db, account_id, additional=0):
    row = db.one('SELECT COUNT(*) AS n, COALESCE(SUM(size_bytes),0) AS size FROM market_data_journal WHERE account_id=?', (account_id,))
    if row['n'] >= MAX_ACCOUNT_RECORDS or row['size'] + additional > MAX_ACCOUNT_BYTES:
        raise JournalError('JOURNAL_CAPACITY_REACHED', 503)


def _existing(db, account_id, key, fingerprint):
    row = db.one('SELECT * FROM market_data_journal WHERE account_id=? AND request_key=?', (account_id, key))
    if row is not None:
        if row['fingerprint'] != fingerprint:
            raise JournalError('JOURNAL_REQUEST_KEY_CONFLICT')
        return _decode(row)
    return None


def _decode(row):
    try:
        raw = row['payload'].encode('utf-8')
        if len(raw) != row['size_bytes'] or not hmac.compare_digest(sha256(raw).hexdigest(), row['digest']):
            raise ValueError()
        result = json.loads(raw)
        for field in ('id', 'account_id', 'sequence', 'request_key', 'recorded_at'):
            if result[field] != row[field]:
                raise ValueError()
        if (result['request']['kind'] != row['kind'] or result['request']['symbol'] != row['symbol']
                or sha256(canonical(result['request']).encode()).hexdigest() != row['fingerprint']):
            raise ValueError()
    except (ValueError, TypeError, KeyError, UnicodeError):
        raise JournalError('JOURNAL_INTEGRITY_FAILED', 503) from None
    return {**result, 'sha256': row['digest'], 'replay': True,
            'freshness_fields_are_as_recorded': True, 'virtual_fills_enabled': False,
            'external_orders_enabled': False, 'point_in_time_backtest_verified': False}


def _provider_observation(provider, request):
    kind, ticker = request['kind'], request['symbol']
    if kind in ('stock_snapshot', 'option_chain'):
        return getattr(provider, kind)(ticker)
    return getattr(provider, kind)(request.get('contract', ticker),
        timestamp(request['start']), timestamp(request['end']), request['timeframe'])


def _validate_observation(value, account_id, request, recorded):
    # The provider is a server dependency, never user-uploaded JSON. Bind its
    # envelope conservatively; storage cannot create an entitlement/permission.
    expected_symbol = request.get('contract', request['symbol'])
    try:
        if (value['schema_version'] != 1 or value['provider'] != 'alpaca'
                or value['mode'] != MODE or value['feed'] != KINDS[request['kind']]
                or value['data']['symbol'] != expected_symbol
                or value['virtual_fills_enabled'] is not False
                or value['external_orders_enabled'] is not False
                or value['point_in_time_backtest_verified'] is not False
                or not value['usage'] or not value['usage_url']
                or not (timestamp(value['captured_at']) <= timestamp(value['last_page_captured_at'])
                        <= timestamp(value['served_at']) <= recorded)):
            raise ValueError()
        if request['kind'].endswith('_bars') and value['data']['timeframe'] != request['timeframe']:
            raise ValueError()
    except (ValueError, TypeError, KeyError):
        raise JournalError('JOURNAL_PROVIDER_CONTRACT_INVALID', 503) from None
    return {**value, 'account_id': account_id}


def capture(service, account_id, body, provider):
    key, request = normalize_request(body)
    fingerprint = sha256(canonical(request).encode()).hexdigest()
    with service.repo.transaction() as db:
        service.account(db, account_id)
        existing = _existing(db, account_id, key, fingerprint)
        if existing is not None:
            return existing  # Lost response recovery needs no provider/permission.
        if db.one('SELECT symbol FROM watchlist WHERE account_id=? AND symbol=?', (account_id, request['symbol'])) is None:
            raise JournalError('JOURNAL_SYMBOL_NOT_WATCHED')
        _capacity(db, account_id)
    # Never hold a trading database transaction across the read-only HTTP call.
    value = _provider_observation(provider, request)
    with service.repo.transaction() as db:
        service.account(db, account_id)
        existing = _existing(db, account_id, key, fingerprint)
        if existing is not None:
            return existing  # Concurrent identical request already committed.
        if db.one('SELECT symbol FROM watchlist WHERE account_id=? AND symbol=?', (account_id, request['symbol'])) is None:
            raise JournalError('JOURNAL_SYMBOL_NOT_WATCHED')
        recorded = timestamp(utc_now())
        previous = db.one('SELECT MAX(recorded_at) AS at, COALESCE(MAX(sequence),0) AS seq FROM market_data_journal WHERE account_id=?', (account_id,))
        if previous['at'] is not None and recorded < timestamp(previous['at']):
            raise JournalError('JOURNAL_CLOCK_MOVED_BACKWARDS', 503)
        record = {'schema_version': 1, 'id': str(uuid.uuid4()), 'account_id': account_id,
                  'sequence': previous['seq'] + 1, 'request_key': key, 'request': request,
                  'recorded_at': utc(recorded), 'availability_basis': 'server_recorded_at_not_market_event_time',
                  'observation': _validate_observation(value, account_id, request, recorded)}
        try:
            payload = canonical(record)
        except (ValueError, TypeError, OverflowError, RecursionError):
            raise JournalError('JOURNAL_PROVIDER_CONTRACT_INVALID', 503) from None
        size = len(payload.encode())
        if size > MAX_RECORD_BYTES:
            raise JournalError('JOURNAL_RECORD_TOO_LARGE', 503)
        _capacity(db, account_id, size)
        digest = sha256(payload.encode()).hexdigest()
        db.execute('INSERT INTO market_data_journal VALUES(?,?,?,?,?,?,?,?,?,?,?)', (
            record['id'], account_id, record['sequence'], key, fingerprint, request['kind'],
            request['symbol'], record['recorded_at'], payload, digest, size))
        service.audit(db, account_id, 'MARKET_DATA_OBSERVATION_SAVED', {
            'observation_id': record['id'], 'kind': request['kind'], 'symbol': request['symbol'],
            'sha256': digest, 'mode': MODE})
        return _decode(db.one('SELECT * FROM market_data_journal WHERE id=?', (record['id'],)))


def _as_of(value):
    now = timestamp(utc_now())
    at = now if value is None else timestamp(value)
    if at > now:
        raise JournalError('INVALID_JOURNAL_FUTURE_AS_OF', 422)
    return utc(at)


def replay(service, account_id, observation_id, as_of=None):
    cutoff = _as_of(as_of)
    with service.repo.transaction() as db:
        service.account(db, account_id)
        row = db.one('SELECT * FROM market_data_journal WHERE account_id=? AND id=? AND recorded_at<=?',
                     (account_id, observation_id, cutoff))
        if row is None:
            raise JournalError('JOURNAL_OBSERVATION_NOT_AVAILABLE', 404)
        return _decode(row)


def list_records(service, account_id, *, as_of=None, before_sequence=None, limit=20):
    cutoff = _as_of(as_of)
    if type(limit) is not int or not 1 <= limit <= 50 or (before_sequence is not None and
            (type(before_sequence) is not int or not 1 <= before_sequence <= 2147483647)):
        raise JournalError('INVALID_JOURNAL_PAGE', 422)
    with service.repo.transaction() as db:
        service.account(db, account_id)
        rows = db.all('SELECT id,sequence,kind,symbol,recorded_at,digest FROM market_data_journal WHERE account_id=? AND recorded_at<=? AND sequence<? ORDER BY sequence DESC LIMIT ?',
            (account_id, cutoff, before_sequence or 2147483647, limit + 1))
    return {'schema_version': 1, 'account_id': account_id, 'mode': MODE,
            'as_of': cutoff, 'items': rows[:limit],
            'next_before_sequence': rows[limit-1]['sequence'] if len(rows) > limit else None,
            'virtual_fills_enabled': False, 'external_orders_enabled': False,
            'point_in_time_backtest_verified': False}
