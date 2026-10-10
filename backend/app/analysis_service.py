"""Authenticated synthetic analysis with immutable, account-scoped wave history.

This layer never imports execution lifecycle functions or calls submit/fill.
The source is an internal fixture; the API accepts no vendor endpoint or AI text.
"""
import json
from datetime import datetime, timedelta, timezone
from math import sin
from .engines import Bar
from .intelligence import analyze_shadow, WaveScenarioTracker
from .service import Rejected



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
            'symbol': symbol, 'timeframe': '1m', 'persisted': False}


def snapshot_analysis(service, account_id, symbol):
    with service.repo.transaction() as db:
        _validate(service, db, account_id, symbol)
        rows = db.all("SELECT payload FROM decision_snapshots WHERE account_id=? AND action='SHADOW_ANALYSIS' ORDER BY created DESC,id DESC", (account_id,))
        tracker = WaveScenarioTracker()
        start = None
        for row in rows:
            payload = json.loads(row['payload'])
            if payload.get('symbol') == symbol and payload.get('timeframe') == '1m':
                try:
                    tracker = WaveScenarioTracker.from_state(payload['wave_tracker_state'])
                    start = datetime.fromisoformat(payload['analysis']['timestamps'][0])
                except (ValueError, TypeError, KeyError) as exc:
                    raise Rejected('Stored wave history failed validation; refusing reset') from exc
                break
        now = service.now()
        result = analyze_shadow(analysis_fixture(symbol, now, start=start), as_of=now, tracker=tracker)
        result = {**result, 'source': 'synthetic_fixture', 'account_id': account_id,
                  'symbol': symbol, 'timeframe': '1m', 'persisted': True}
        identifier = service.decision(db, account_id, 'SHADOW_ANALYSIS', {
            'symbol': symbol, 'timeframe': '1m', 'analysis': result,
            'wave_tracker_state': tracker.to_state()})
        service.audit(db, account_id, 'ANALYSIS_SNAPSHOT', {'snapshot_id': identifier,
                      'symbol': symbol, 'source': 'synthetic_fixture', 'execution_authority': False})
        return {'snapshot_id': identifier, 'analysis': result}
