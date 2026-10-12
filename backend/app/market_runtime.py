"""Persistent read-only market collector, independent of phone and Demo worker.

Basic indicative options NEVER authorize simulated or external fills. This is
the collection/analysis foundation, not an accepted market-priced trade ledger.
No SDK, order submission, synthetic quote or broker dependency belongs here.
"""
from copy import deepcopy
from dataclasses import asdict
from datetime import timedelta
from hashlib import sha256
import base64
import json
import uuid

from . import market_data_journal as journal
from . import market_segments
from .engines import AnalysisPipeline, Bar
from .market_data import MarketDataError, INDICATIVE_REASON, MODE, timestamp
from .market_sessions import evaluate_session, US_EQUITY_OPTIONS_POLICY

LEASE_SECONDS = 120
INTERVALS = {'stock_snapshot': 60, 'stock_bars': 300, 'option_chain': 300}
STRATEGIES = {'breakout', 'pullback'}
AUTHORITY = {'schema_version': 1, 'mode': MODE, 'virtual_fills_enabled': False,
             'external_orders_enabled': False, 'new_risk_allowed': False,
             'execution_block_reason': INDICATIVE_REASON,
             'stop_loss_execution_assumed': False}


def config_in(db, account_id):
    row = db.one('SELECT * FROM market_runtime_config WHERE account_id=?', (account_id,))
    return ({'version': row['version'], **json.loads(row['payload'])} if row else
            {'version': 0, 'enabled': False, 'strategies': {s: False for s in sorted(STRATEGIES)}})


def event_in(db, account_id, key, now, kind, detail):
    existing = db.one('SELECT id FROM market_runtime_events WHERE account_id=? AND event_key=?', (account_id, key))
    if existing:
        return existing['id']
    event_id = str(uuid.uuid4())
    payload = journal.canonical({'id': event_id, 'account_id': account_id, 'created': journal.utc(now),
                                 'kind': kind, 'detail': detail, **AUTHORITY})
    db.execute('INSERT INTO market_runtime_events VALUES(?,?,?,?,?,?)',
               (event_id, account_id, key, journal.utc(now), payload, sha256(payload.encode()).hexdigest()))
    return event_id


def configure(service, account_id, *, expected_version, enabled, strategies):
    if (type(expected_version) is not int or expected_version < 0 or type(enabled) is not bool
            or not isinstance(strategies, dict) or set(strategies) != STRATEGIES
            or any(type(v) is not bool for v in strategies.values())):
        raise journal.JournalError('INVALID_RUNTIME_CONFIG', 422)
    with service.repo.transaction() as db:
        service.account(db, account_id)
        current = config_in(db, account_id)
        value = {'enabled': enabled, 'strategies': strategies}
        if current['version'] != expected_version:
            # Repeated identical control after a lost response is harmless.
            if expected_version == current['version'] - 1 and all(current[k] == v for k, v in value.items()):
                return {'account_id': account_id, **current, **AUTHORITY}
            raise journal.JournalError('RUNTIME_CONFIG_VERSION_CONFLICT')
        version = current['version'] + 1
        db.execute('INSERT INTO market_runtime_config VALUES(?,?,?) ON CONFLICT(account_id) DO UPDATE SET version=excluded.version,payload=excluded.payload',
                   (account_id, version, journal.canonical(value)))
        event_in(db, account_id, 'config:' + str(version), service.now(), 'CONFIG_CHANGED', value)
        return {'account_id': account_id, 'version': version, **value, **AUTHORITY}


def coordinator_in(db):
    row = db.one("SELECT payload FROM market_runtime_coordinator WHERE name='collector'")
    return json.loads(row['payload']) if row else {'owner': None, 'lease_until': None,
        'requests': [], 'retry_at': None, 'failures': 0, 'auth_blocked': False, 'last_clock': None}


def save_coordinator(db, value):
    db.execute("INSERT INTO market_runtime_coordinator VALUES('collector',?) ON CONFLICT(name) DO UPDATE SET payload=excluded.payload",
               (journal.canonical(value),))


def assert_owner(db, owner, now):
    state = coordinator_in(db)
    if state['owner'] != owner or not state['lease_until'] or timestamp(state['lease_until']) <= now:
        raise MarketDataError('COLLECTOR_LEASE_LOST')
    if state['last_clock'] and timestamp(state['last_clock']) > now:
        raise MarketDataError('COLLECTOR_CLOCK_MOVED_BACKWARDS')
    return state


class CoordinatedTransport:
    """Every HTTP attempt spends the same persisted budget, including retries.

    This cannot see another application's consumption. No WebSocket is opened.
    Uncertainty or 429 from the shared account is a reason to back off, not to
    discover/modify the other application or use its credentials.
    """
    def __init__(self, repo, owner, inner, now, requests_per_minute=10):
        if type(requests_per_minute) is not int or not 1 <= requests_per_minute <= 30:
            raise ValueError('Collector budget must be 1..30 requests/minute')
        self.repo, self.owner, self.inner, self.now = repo, owner, inner, now
        self.limit = requests_per_minute

    def get(self, path, params):
        now = timestamp(self.now())
        with self.repo.transaction() as db:
            state = assert_owner(db, self.owner, now)
            if state['auth_blocked']:
                raise MarketDataError('DATA_AUTH_OR_ENTITLEMENT_DENIED')
            if state['retry_at'] and timestamp(state['retry_at']) > now:
                raise MarketDataError('COLLECTOR_BACKOFF')
            recent = [t for t in state['requests'] if timestamp(t) > now - timedelta(seconds=60)]
            if len(recent) >= self.limit:
                raise MarketDataError('COLLECTOR_REQUEST_BUDGET')
            state.update(requests=recent + [journal.utc(now)], last_clock=journal.utc(now),
                         lease_until=journal.utc(now + timedelta(seconds=LEASE_SECONDS)))
            save_coordinator(db, state)
        response = self.inner.get(path, params)
        # Persist provider throttling before returning: a process restart cannot
        # erase the server's Retry-After or an authentication/entitlement denial.
        headers = {k.lower(): str(v) for k, v in response.headers.items()}
        if response.status in (401, 403, 429) or headers.get('x-ratelimit-remaining') == '0':
            from email.utils import parsedate_to_datetime
            import math
            now = timestamp(self.now())
            retry = 60.0
            try:
                raw = headers.get('retry-after', '60')
                retry = float(raw) if raw.isdigit() else (parsedate_to_datetime(raw) - now).total_seconds()
                retry = max(retry, float(headers.get('x-ratelimit-reset', '0')) - now.timestamp(), 1)
                if not math.isfinite(retry):
                    retry = 60
            except (ValueError, TypeError, OverflowError):
                retry = 60
            with self.repo.transaction() as db:
                state = assert_owner(db, self.owner, now)
                state.update(auth_blocked=response.status in (401, 403) or state['auth_blocked'],
                             retry_at=journal.utc(now + timedelta(seconds=min(retry, 86400))))
                save_coordinator(db, state)
        return response


def observation_state(kind, value, now):
    if not value.get('complete'):
        return 'INCOMPLETE_OBSERVATION'
    if kind == 'option_chain':
        return INDICATIVE_REASON
    if kind == 'stock_snapshot':
        trade = value['data'].get('trade')
        if not trade or trade.get('p') is None:
            return 'NO_VALID_TRADE'
        age = (now - timestamp(trade['timestamp'])).total_seconds()
        return 'FRESH_IEX_TRADE' if 0 <= age <= 60 else 'STALE_OR_FUTURE_DATA'
    bars = value['data']['bars']
    if not bars:
        return 'NO_COMPLETED_BARS'
    age = (now - timestamp(bars[-1]['closed_at'])).total_seconds()
    return 'FRESH_COMPLETED_BARS' if 0 <= age <= 180 else 'STALE_OR_FUTURE_DATA'


def analyze(value, now, strategies):
    """Use completion times and existing causal pipeline; never manufacture Greeks."""
    try:
        if value.get('complete') is not True:
            raise ValueError('Incomplete observation')
        bars = [Bar(timestamp(b['closed_at']), b['o'], b['h'], b['l'], b['c'], b['v'])
                for b in value['data']['bars']]
        result = AnalysisPipeline().analyze(bars, now)
        data = asdict(result)
        data['signals'] = [{**asdict(s), 'timestamp': journal.utc(s.timestamp)} for s in result.signals
                           if strategies.get(s.strategy) is True]
        return {'state': 'PROPOSAL_ONLY', 'analysis': data, 'strategies': strategies}
    except (ValueError, MarketDataError):
        return {'state': 'ANALYSIS_UNAVAILABLE', 'reason': 'Completed, contiguous, fresh bars required',
                'strategies': strategies, 'signals': []}


class _SavedObservation:
    def __init__(self, value):
        self.value = value

    def stock_snapshot(self, *_):
        return deepcopy(self.value)

    stock_bars = stock_snapshot
    option_chain = stock_snapshot


class MarketCollector:
    def __init__(self, service, provider, *, owner=None, now=None):
        self.service, self.repo, self.provider = service, service.repo, provider
        self.owner = owner or str(uuid.uuid4())
        self.now = now or service.now

    def _demand(self, db):
        result = {}
        for row in db.all('SELECT account_id FROM market_runtime_config'):
            account = row['account_id']
            config = config_in(db, account)
            if config['enabled']:
                for watch in db.all('SELECT symbol FROM watchlist WHERE account_id=?', (account,)):
                    result.setdefault(watch['symbol'], {})[account] = config
        return result

    def _health(self, db, state, now, demand, error=None):
        previous = db.one("SELECT payload FROM runtime_health WHERE name='market_collector'")
        previous = json.loads(previous['payload']) if previous else {}
        payload = {'state': state, 'heartbeat_at': journal.utc(now), 'owner': self.owner,
                   'symbols': len(demand), 'error': error, 'stream_connections': 0, **AUTHORITY}
        db.execute("INSERT INTO runtime_health VALUES('market_collector',?,?) ON CONFLICT(name) DO UPDATE SET updated_at=excluded.updated_at,payload=excluded.payload",
                   (journal.utc(now), journal.canonical(payload)))
        active = {'WAITING', 'COLLECTING_ANALYSIS_ONLY'}
        prior_group = 'ACTIVE' if previous.get('state') in active else previous.get('state')
        group = 'ACTIVE' if state in active else state
        if (prior_group, previous.get('error')) != (group, error):
            for account in sorted({a for accounts in demand.values() for a in accounts}):
                event_in(db, account, 'health:' + str(uuid.uuid4()), now, 'COLLECTOR_STATE',
                         {'state': state, 'error': error, 'stop_loss_execution_assumed': False})
        return payload

    def tick(self):
        now = timestamp(self.now())
        with self.repo.transaction() as db:
            state, demand = coordinator_in(db), self._demand(db)
            if state['last_clock'] and timestamp(state['last_clock']) > now:
                return {**AUTHORITY, 'state': 'COLLECTOR_CLOCK_MOVED_BACKWARDS'}
            if state['owner'] != self.owner and state['lease_until'] and timestamp(state['lease_until']) > now:
                return {**AUTHORITY, 'state': 'STANDBY'}
            state.update(owner=self.owner, lease_until=journal.utc(now + timedelta(seconds=LEASE_SECONDS)),
                         last_clock=journal.utc(now))
            save_coordinator(db, state)
            reason = ('DISABLED' if not self.provider.status()['connection_enabled'] else
                      'NO_ACTIVE_DEMAND' if not demand else
                      'DEMAND_LIMIT_REACHED' if len(demand) > 30 else
                      'AUTH_BLOCKED' if state['auth_blocked'] else
                      'BACKOFF' if state['retry_at'] and timestamp(state['retry_at']) > now else
                      'SESSION_CLOSED' if not evaluate_session(now, US_EQUITY_OPTIONS_POLICY).fill_allowed else None)
            if reason:
                return self._health(db, reason, now, demand)
            for ticker in sorted(demand):
                for kind in INTERVALS:
                    db.execute('INSERT INTO market_runtime_tasks VALUES(?,?,?) ON CONFLICT(symbol,kind) DO NOTHING',
                               (ticker, kind, journal.utc(now)))
            tasks = db.all('SELECT * FROM market_runtime_tasks WHERE next_due<=? ORDER BY next_due,symbol,kind', (journal.utc(now),))
            task = next((t for t in tasks if t['symbol'] in demand), None)
            if task is None:
                return self._health(db, 'WAITING', now, demand)
        ticker, kind = task['symbol'], task['kind']
        body = {'symbol': ticker, 'kind': kind, 'request_key': 'runtime:' + str(uuid.uuid4())}
        if kind == 'stock_bars':
            body.update(start=journal.utc(now - timedelta(minutes=35)), end=journal.utc(now), timeframe='1Min')
        try:
            value = journal._provider_observation(self.provider, body)
            for account, config in demand[ticker].items():
                def guard(db, account=account, config=config):
                    assert_owner(db, self.owner, timestamp(self.now()))
                    current = config_in(db, account)
                    if not current['enabled'] or current['version'] != config['version']:
                        raise MarketDataError('RUNTIME_CONFIG_CHANGED')
                try:
                    receipt = journal.capture(self.service, account, body, _SavedObservation(value), commit_guard=guard)
                    with self.repo.transaction() as db:
                        guard(db)
                        if not db.one('SELECT symbol FROM watchlist WHERE account_id=? AND symbol=?', (account, ticker)):
                            continue
                        current_time = timestamp(self.now())
                        status = observation_state(kind, value, current_time)
                        db.execute('INSERT INTO market_runtime_latest VALUES(?,?,?,?,?) ON CONFLICT(account_id,symbol,kind) DO UPDATE SET observation_id=excluded.observation_id,state=excluded.state',
                                   (account, ticker, kind, receipt['id'], status))
                        detail = {'symbol': ticker, 'kind': kind, 'state': status,
                                  'observation_id': receipt['id'], 'sha256': receipt['sha256'],
                                  'config_version': config['version']}
                        if kind == 'stock_bars':
                            detail.update(analyze(value, current_time, config['strategies']))
                        event_in(db, account, 'observation:' + receipt['id'], current_time, 'OBSERVATION_ANALYZED', detail)
                except (journal.JournalError, MarketDataError) as exc:
                    if getattr(exc, 'code', '') in ('COLLECTOR_LEASE_LOST', 'COLLECTOR_CLOCK_MOVED_BACKWARDS'):
                        raise
                    with self.repo.transaction() as db:
                        assert_owner(db, self.owner, timestamp(self.now()))
                        # Deduplicate persistent capacity/config failures, rather than growing an outage log each tick.
                        event_in(db, account, 'account-failure:' + exc.code + ':' + str(config['version']),
                                 timestamp(self.now()), 'ACCOUNT_COLLECTION_BLOCKED', {'code': exc.code})
            with self.repo.transaction() as db:
                state = assert_owner(db, self.owner, timestamp(self.now()))
                state.update(failures=0)
                save_coordinator(db, state)
                db.execute('UPDATE market_runtime_tasks SET next_due=? WHERE symbol=? AND kind=?',
                           (journal.utc(timestamp(self.now()) + timedelta(seconds=INTERVALS[kind])), ticker, kind))
                return self._health(db, 'COLLECTING_ANALYSIS_ONLY', timestamp(self.now()), demand)
        except (MarketDataError, journal.JournalError, OSError, ValueError):
            # Never persist raw exception/HTTP text: it could contain credentials or provider bodies.
            with self.repo.transaction() as db:
                state = coordinator_in(db)
                if state['owner'] != self.owner or timestamp(state['lease_until']) <= timestamp(self.now()):
                    return {**AUTHORITY, 'state': 'COLLECTOR_LEASE_LOST'}
                failures = min(state['failures'] + 1, 10)
                provider_state = self.provider.status().get('connection_state', '')
                retry = timestamp(self.now()) + timedelta(seconds=min(300, 5 * 2 ** (failures-1)))
                if state['retry_at']:
                    retry = max(retry, timestamp(state['retry_at']))
                state.update(failures=failures,
                    auth_blocked=state['auth_blocked'] or provider_state == 'DATA_AUTH_OR_ENTITLEMENT_DENIED',
                    retry_at=journal.utc(retry))
                save_coordinator(db, state)
                return self._health(db, 'DATA_UNAVAILABLE', timestamp(self.now()), demand, 'PROVIDER_OR_STORAGE_UNAVAILABLE')

    def release(self):
        with self.repo.transaction() as db:
            state = coordinator_in(db)
            if state['owner'] == self.owner:
                state.update(owner=None, lease_until=None)
                save_coordinator(db, state)


def status(service, account_id):
    now = timestamp(service.now())
    with service.repo.transaction() as db:
        service.account(db, account_id)
        config = config_in(db, account_id)
        row = db.one("SELECT * FROM runtime_health WHERE name='market_collector'")
        heartbeat = json.loads(row['payload']) if row else None
        healthy = row is not None and 0 <= (now - timestamp(row['updated_at'])).total_seconds() <= 30
        links = db.all('SELECT l.*,j.payload,j.digest,j.size_bytes,j.request_key,j.fingerprint,j.sequence,j.recorded_at,j.id FROM market_runtime_latest l JOIN market_data_journal j ON l.observation_id=j.id JOIN watchlist w ON w.account_id=l.account_id AND w.symbol=l.symbol WHERE l.account_id=?', (account_id,))
        latest = []
        for link in links:
            record = journal._decode(link)
            observation = record['observation']
            data = observation['data']
            trade = data.get('trade') if link['kind'] == 'stock_snapshot' else None
            latest.append({'symbol': link['symbol'], 'kind': link['kind'], 'observation_id': link['id'],
                           'recorded_at': link['recorded_at'],
                           'state_now': observation_state(link['kind'], observation, now),
                           'feed': observation['feed'], 'captured_at': observation['captured_at'],
                           'price': trade.get('p') if trade else None,
                           'market_time': trade.get('timestamp') if trade else None,
                           'sha256': record['sha256']})
        capacity = market_segments.stats(db, account_id)
    return {'account_id': account_id, 'server_time': journal.utc(now), 'config': config, 'heartbeat_fresh': healthy,
            'collector': heartbeat, 'latest': latest, 'archive': capacity,
            'collection_block_reason': None,
            'state': 'WORKER_UNAVAILABLE' if not healthy else heartbeat['state'], **AUTHORITY}


def events(service, account_id, *, limit=50, before=None):
    if type(limit) is not int or not 1 <= limit <= 100:
        raise journal.JournalError('INVALID_RUNTIME_PAGE', 422)
    cutoff = journal.utc(service.now())
    cursor = None
    if before is not None:
        try:
            if not isinstance(before, str) or len(before) > 1024:
                raise ValueError()
            cursor = json.loads(base64.urlsafe_b64decode(before.encode()))
            if set(cursor) != {'account_id', 'as_of', 'created', 'id'} or cursor['account_id'] != account_id:
                raise ValueError()
            if not isinstance(cursor['id'], str) or not 1 <= len(cursor['id']) <= 128:
                raise ValueError()
            if timestamp(cursor['created']) > timestamp(cursor['as_of']) or timestamp(cursor['as_of']) > timestamp(cutoff):
                raise ValueError()
            cutoff = journal.utc(cursor['as_of'])
        except (ValueError, TypeError, KeyError, MarketDataError):
            raise journal.JournalError('INVALID_RUNTIME_CURSOR', 422) from None
    with service.repo.transaction() as db:
        service.account(db, account_id)
        where = ' AND (e.created<? OR (e.created=? AND e.id<?))' if cursor else ''
        args = (account_id, cutoff) + ((cursor['created'], cursor['created'], cursor['id']) if cursor else ()) + (limit + 1,)
        rows = db.all('SELECT e.*,a.acknowledged_at FROM market_runtime_events e LEFT JOIN market_runtime_ack a ON a.event_id=e.id WHERE e.account_id=? AND e.created<=?' + where + ' ORDER BY e.created DESC,e.id DESC LIMIT ?', args)
    result = []
    for row in rows[:limit]:
        if sha256(row['payload'].encode()).hexdigest() != row['digest']:
            raise journal.JournalError('RUNTIME_EVENT_INTEGRITY_FAILED', 503)
        result.append({**json.loads(row['payload']), 'sha256': row['digest'], 'acknowledged_at': row['acknowledged_at']})
    next_before = None
    if len(rows) > limit:
        last = rows[limit-1]
        next_before = base64.urlsafe_b64encode(journal.canonical({'account_id': account_id,
            'as_of': cutoff, 'created': last['created'], 'id': last['id']}).encode()).decode()
    return {'account_id': account_id, 'as_of': cutoff, 'items': result, 'next_before': next_before,
            'delivery': 'DURABLE_API_INBOX_ONLY', **AUTHORITY}


def acknowledge(service, account_id, event_id):
    with service.repo.transaction() as db:
        service.account(db, account_id)
        if not db.one('SELECT id FROM market_runtime_events WHERE account_id=? AND id=?', (account_id, event_id)):
            raise journal.JournalError('RUNTIME_EVENT_NOT_FOUND', 404)
        db.execute('INSERT INTO market_runtime_ack VALUES(?,?,?) ON CONFLICT(event_id) DO NOTHING',
                   (account_id, event_id, journal.utc(service.now())))
    return {'account_id': account_id, 'acknowledged': True, **AUTHORITY}
