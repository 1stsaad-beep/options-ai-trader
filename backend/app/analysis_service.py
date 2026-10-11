"""Authenticated synthetic analysis with immutable, account-scoped wave history.

This layer never imports execution lifecycle functions or calls submit/fill.
The source is an internal fixture; the API accepts no vendor endpoint or AI text.
"""
import json
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from math import sin
from .engines import Bar, aware
from .intelligence import analyze_shadow, WaveScenarioTracker
from .service import Rejected

SOURCE_VERSION = 'synthetic-ohlc-v1'


def analysis_fixture(symbol, now, start=None):
    # Every timestamp maps to the same explicit synthetic candle across scans.
    base = {'NVDA': 100, 'AAPL': 200, 'TSLA': 250}.get(symbol, 150)
    end = now.replace(second=0, microsecond=0) - timedelta(minutes=1)
    epoch = datetime(2026, 1, 1, tzinfo=timezone.utc)
    def price(i):
        return base + 3*sin(i/5) + 7*sin(i/20)
    result = []
    start = start or end - timedelta(minutes=179)
    count = int((end-start).total_seconds()/60)+1
    if not 35 <= count <= 10000:
        raise Rejected("Analysis history window requires an explicit archived session; history was not reset")
    for offset in range(count):
        stamp = start + timedelta(minutes=offset)
        i = int((stamp-epoch).total_seconds()/60)
        opening, close = price(i-1), price(i)
        result.append(Bar(stamp, opening, max(opening,close)+.4,
                          min(opening,close)-.4, close, 1000+(i%5)*200))
    return result


def _validate(service, db, account_id, symbol):
    service.account(db, account_id)
    watch = db.one('SELECT * FROM watchlist WHERE account_id=? AND symbol=?', (account_id, symbol))
    if not watch or not watch['verified']:
        raise Rejected('Analysis requires an explicitly qualified synthetic watch symbol')


def inspect_analysis(service, account_id, symbol):
    with service.repo.transaction() as db:
        _validate(service, db, account_id, symbol)
    now = service.now()
    result = analyze_shadow(analysis_fixture(symbol, now), as_of=now)
    return {**result, 'source': 'synthetic_fixture', 'account_id': account_id,
            'source_version': SOURCE_VERSION, 'symbol': symbol, 'timeframe': '1m', 'persisted': False}


def _saved_history(db, account_id, symbol):
    """Authenticate journal scope before selecting a checkpoint; never reset it."""
    rows = db.all("SELECT * FROM decision_snapshots WHERE account_id=? AND action='SHADOW_ANALYSIS' ORDER BY created DESC,id DESC", (account_id,))
    histories = {}
    selected = None
    try:
        for row in rows:
            if sha256(row['payload'].encode()).hexdigest() != row['digest']:
                raise ValueError('Wave journal payload digest mismatch')
            payload = json.loads(row['payload'])
            analysis = payload['analysis']
            if (row['account_id'] != account_id or type(payload['schema_version']) is not int
                    or payload['schema_version'] != 1 or payload['source'] != 'synthetic_mock'
                    or payload['rule_version'] != 'v1.0' or payload['timeframe'] != '1m'
                    or analysis['account_id'] != account_id or analysis['symbol'] != payload['symbol']
                    or analysis['timeframe'] != '1m' or analysis['source'] != 'synthetic_fixture'
                    or type(analysis['schema_version']) is not int or analysis['schema_version'] != 1
                    or analysis['mode'] != 'SHADOW' or analysis['executable'] is not False
                    or analysis['persisted'] is not True):
                raise ValueError('Wave journal identity mismatch')
            # The sole supported unversioned history is the frozen V1 synthetic
            # minute fixture. Its retained source hashes are checked on continuation.
            versions = (payload.get('source_version'), analysis.get('source_version'))
            if versions not in ((None, None), (SOURCE_VERSION, SOURCE_VERSION)):
                raise ValueError('Unsupported wave source version')
            histories[row['id']] = payload['symbol']
            if payload['symbol'] == symbol and selected is None:
                selected = payload
        for event in db.all("SELECT detail FROM audit WHERE account_id=? AND event='ANALYSIS_SNAPSHOT'", (account_id,)):
            detail = json.loads(event['detail'])
            if histories.get(detail['snapshot_id']) != detail['symbol']:
                raise ValueError('Previously saved wave journal is missing or misidentified')
        if selected is None:
            return WaveScenarioTracker(), None
        analysis = selected['analysis']
        state = selected['wave_tracker_state']
        tracker = WaveScenarioTracker.from_state(state)
        timestamps = analysis['timestamps']
        if (not isinstance(timestamps, list) or not timestamps
                or analysis['bar_count'] != len(timestamps)
                or list(state['source_hashes']) != timestamps
                or state['last_as_of'] != analysis['as_of']
                or analysis['last_bar_at'] != timestamps[-1]):
            raise ValueError('Incomplete wave history observation')
        start = datetime.fromisoformat(timestamps[0])
        aware(start)
        return tracker, start
    except (ValueError, TypeError, KeyError, AttributeError, IndexError, OverflowError) as exc:
        raise Rejected('Stored wave history failed validation; refusing reset') from exc


def snapshot_analysis(service, account_id, symbol):
    with service.repo.transaction() as db:
        _validate(service, db, account_id, symbol)
        tracker, start = _saved_history(db, account_id, symbol)
        now = service.now()
        try:
            result = analyze_shadow(analysis_fixture(symbol, now, start=start), as_of=now, tracker=tracker)
        except (ValueError, TypeError, KeyError) as exc:
            raise Rejected('Wave source history cannot be continued safely; refusing reset') from exc
        result = {**result, 'source': 'synthetic_fixture', 'account_id': account_id,
                  'source_version': SOURCE_VERSION, 'symbol': symbol, 'timeframe': '1m', 'persisted': True}
        identifier = service.decision(db, account_id, 'SHADOW_ANALYSIS', {
            'symbol': symbol, 'timeframe': '1m', 'source_version': SOURCE_VERSION, 'analysis': result,
            'wave_tracker_state': tracker.to_state()})
        service.audit(db, account_id, 'ANALYSIS_SNAPSHOT', {'snapshot_id': identifier,
                      'symbol': symbol, 'source': 'synthetic_fixture', 'execution_authority': False})
        return {'snapshot_id': identifier, 'analysis': result}
