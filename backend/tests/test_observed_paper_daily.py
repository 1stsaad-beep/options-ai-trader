from copy import deepcopy
from datetime import datetime, timedelta, timezone
from math import sqrt
from statistics import mean, stdev

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.observed_paper import digest
from app.observed_paper_daily import DailyProjection, performance, sessions
from app.observed_paper_store import ObservedPaperStore, LedgerConflict
from app.observed_option_replay import iso
from test_alpaca_market_api import TOKEN, HEADERS
from test_observed_paper import stored, observation, config


def instant(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00'))


def swing(tmp_path):
    repo, store, clock = stored(tmp_path)
    store.command('a', 'stop-for-config', {'kind': 'ENABLE', 'enabled': False})
    store.command('a', 'swing', {'kind': 'CONFIGURE', 'config': config(quantity=3, holdingMode='swing')})
    store.command('a', 'start-swing', {'kind': 'ENABLE', 'enabled': True})
    store.command('a', 'open', {'kind': 'CYCLE', 'observation': observation()},
        expected_version=5, lease=store.acquire('daily'))
    return repo, store, clock


def mark(store, clock, at, *, bid=100, size=40):
    clock.value = instant(at)
    before = store.snapshot('a')
    return store.command('a', 'mark'+str(before['version']),
        {'kind': 'CYCLE', 'observation': observation(clock(), bid=bid, ask=bid+5, size=size, bars=False)},
        expected_version=before['version'], lease=store.acquire('daily'))


def test_cash_daily_has_no_fabricated_market_marks_and_is_read_only(tmp_path):
    repo, store, clock = stored(tmp_path)
    before = store.snapshot('a', full=True)
    clock.value = instant('2026-10-16T20:00:00Z')
    report = store.daily_performance('a', '2026-10-13', '2026-10-16')
    assert len(report['points']) == 4
    assert all(p['status'] == 'CASH_ONLY' and p['liquidationEquityCents'] == 1000000 for p in report['points'])
    assert report['points'][0]['asOf'] == '2026-10-13T19:59:59.999999Z'
    assert report['points'][0]['sessionClose'] == '2026-10-13T20:00:00.000Z'
    assert report['performance']['dailyReturns'] == [None, 0, 0, 0]
    assert report['performance']['sharpeStatus'] == 'INSUFFICIENT_DAILY_RETURNS'
    assert not report['executionAllowed'] and not report['newEntryAllowed'] and not report['externalOrder']
    assert report['source'] == 'fixture'
    assert report['reportHash'] == digest({k: v for k, v in report.items() if k != 'reportHash'})
    assert store.snapshot('a', full=True) == before
    assert ObservedPaperStore(repo, clock).daily_performance('a', '2026-10-13', '2026-10-16') == report
    repo.close()


def test_fresh_original_held_option_daily_value_and_no_future_price_leak(tmp_path):
    repo, store, clock = swing(tmp_path)
    event = mark(store, clock, '2026-10-13T19:59:45Z')
    clock.value = instant('2026-10-13T20:00:00Z')
    report = store.daily_performance('a', '2026-10-13', '2026-10-13')
    point = report['points'][0]
    assert point['liquidationEquityCents'] == 997480 and point['totalPnlCents'] == -2520
    assert point['stateEventHash'] == event['eventHash'] and point['stateVersion'] == event['version']
    # New prices and a protective close on the next day must not rewrite day one.
    mark(store, clock, '2026-10-14T15:00:00Z', bid=70)
    clock.value = instant('2026-10-14T20:00:00Z')
    assert store.daily_performance('a', '2026-10-13', '2026-10-13', through=event['version']) == report
    current = store.daily_performance('a', '2026-10-13', '2026-10-14')
    assert current['points'][0] == point
    assert current['points'][1]['status'] == 'CASH_ONLY'
    assert current['performance']['maximumDailyDrawdownCents'] == 9000
    repo.close()


@pytest.mark.parametrize('seconds,fresh', [(30, True), (30.000001, False)])
def test_daily_freshness_microsecond_boundary(tmp_path, seconds, fresh):
    repo, store, clock = swing(tmp_path)
    sample = instant('2026-10-13T19:59:59.999999Z')
    mark(store, clock, iso(sample-timedelta(seconds=seconds)))
    clock.value = instant('2026-10-13T20:00:00Z')
    point = store.daily_performance('a', '2026-10-13', '2026-10-13')['points'][0]
    assert point['complete'] == fresh
    assert (point['liquidationEquityCents'] == 997480) if fresh else (point['liquidationEquityCents'] is None)
    repo.close()


def test_missing_day_breaks_returns_and_drawdown_without_interpolation(tmp_path):
    repo, store, clock = swing(tmp_path)
    mark(store, clock, '2026-10-13T19:59:45Z')
    mark(store, clock, '2026-10-15T15:00:00Z', bid=70)
    clock.value = instant('2026-10-15T20:00:00Z')
    report = store.daily_performance('a', '2026-10-13', '2026-10-15')
    assert [p['complete'] for p in report['points']] == [True, False, True]
    assert report['points'][1]['incompleteReasons'] == ['QUALIFIED_ORIGINAL_QUOTE_UNAVAILABLE']
    assert report['performance']['dailyReturns'] == [None, None, None]
    assert report['performance']['maximumDailyDrawdownCents'] is None
    assert report['performance']['sharpeStatus'] == 'MISSING_DAILY_VALUATION'
    repo.close()


def test_all_equal_sample_timestamps_included_but_exact_close_excluded(tmp_path):
    repo, store, clock = swing(tmp_path)
    mark(store, clock, '2026-10-13T19:59:59.999999Z')
    last = store.command('a', 'stop-at-sample', {'kind': 'ENABLE', 'enabled': False})
    clock.value = instant('2026-10-13T20:00:00Z')
    store.command('a', 'restart-at-close', {'kind': 'ENABLE', 'enabled': True})
    point = store.daily_performance('a', '2026-10-13', '2026-10-13')['points'][0]
    assert point['stateVersion'] == last['version'] and point['stateEventHash'] == last['eventHash']
    assert point['liquidationEquityCents'] == 997480
    repo.close()


def test_calendar_weekend_holiday_early_close_and_dst():
    now = instant('2027-12-31T23:00:00Z')
    assert sessions('2026-11-26', '2026-11-29', now)[0][1] == instant('2026-11-27T18:00:00Z')
    assert len(sessions('2026-11-26', '2026-11-29', now)) == 1
    march = sessions('2026-03-06', '2026-03-09', now)
    assert [s[1].hour for s in march] == [21, 20]
    assert sessions('2026-12-24', '2026-12-24', now)[0][1] == instant('2026-12-24T18:00:00Z')
    assert len(sessions('2026-01-01', '2026-12-31', now)) <= 366


@pytest.mark.parametrize('start,end', [('2025-12-31', '2026-01-01'), ('2027-12-31', '2028-01-01'),
    ('2026-10-14', '2026-10-13'), ('2026-01-01', '2027-01-02'), ('20261013', '2026-10-13'),
    ('2026-W42-2', '2026-10-13'), ('invalid', '2026-10-13'), (True, '2026-10-13')])
def test_date_range_bounds(start, end):
    with pytest.raises(ValueError): sessions(start, end, instant('2027-12-31T23:00:00Z'))


def test_incomplete_session_and_naive_clock_rejected():
    with pytest.raises(ValueError, match='completed'): sessions('2026-10-13', '2026-10-13', instant('2026-10-13T19:59:59Z'))
    with pytest.raises(ValueError, match='Aware'): sessions('2026-10-13', '2026-10-13', datetime(2026, 10, 14))


def test_no_sessions_and_pre_genesis_are_explicit(tmp_path):
    repo, store, clock = stored(tmp_path)
    clock.value = instant('2026-10-13T20:00:00Z')
    report = store.daily_performance('a', '2026-10-10', '2026-10-13')
    assert report['points'][0]['status'] == 'ACCOUNT_NOT_CREATED'
    assert report['points'][0]['liquidationEquityCents'] is None
    assert report['points'][1]['status'] == 'CASH_ONLY'
    weekend = store.daily_performance('a', '2026-10-10', '2026-10-11')
    assert weekend['points'] == [] and weekend['performance']['sharpeStatus'] == 'NO_SESSIONS'
    repo.close()


def test_delivery_shares_never_marked_with_cost_basis(tmp_path):
    repo, store, clock = stored(tmp_path)
    state = deepcopy(store.snapshot('a')['state'])
    state.update(deliveries={'NVDA': {'quantity': 100, 'cost': 1500000}})
    clock.value = instant('2026-10-13T20:00:00Z')
    projection = DailyProjection(sessions('2026-10-13', '2026-10-13', clock()), None)
    projection.observe({'sequence': 2, 'digest': 'fixture-only'},
        {'at': '2026-10-13T15:00:00Z', 'command': {'kind': 'ENABLE'}}, state)
    projection.flush(clock())
    assert projection.points[0]['incompleteReasons'] == ['QUALIFIED_STOCK_QUOTE_UNAVAILABLE']
    assert projection.points[0]['liquidationEquityCents'] is None
    repo.close()


def test_report_full_verification_still_rejects_corrupted_later_tail(tmp_path):
    repo, store, clock = stored(tmp_path)
    clock.value = instant('2026-10-14T20:00:00Z')
    store.command('a', 'later', {'kind': 'ENABLE', 'enabled': False})
    store.daily_performance('a', '2026-10-13', '2026-10-13', through=2)
    with repo.transaction() as db:
        db.execute('DROP TRIGGER immutable_observed_paper_event_update')
        db.execute("UPDATE observed_paper_events SET payload='private corrupt tail' WHERE account_id='a' AND sequence=3")
    with pytest.raises(LedgerConflict): store.daily_performance('a', '2026-10-13', '2026-10-13', through=2)
    with TestClient(create_app(repo, TOKEN)) as client:
        result = client.get('/api/observed-paper/accounts/a/daily-performance?start=2026-10-13&end=2026-10-13&through=2', headers=HEADERS)
        assert result.status_code == 409 and 'private' not in result.text and 'points' not in result.text


@pytest.mark.parametrize('through', [True, -1, 100, '2'])
def test_pinned_version_bounds(tmp_path, through):
    repo, store, clock = stored(tmp_path); clock.value = instant('2026-10-13T20:00:00Z')
    with pytest.raises(ValueError): store.daily_performance('a', '2026-10-13', '2026-10-13', through=through)
    repo.close()


def test_api_authentication_and_read_only_report(tmp_path):
    repo, store, _ = stored(tmp_path); before = store.snapshot('a', full=True)
    with TestClient(create_app(repo, TOKEN)) as client:
        path = '/api/observed-paper/accounts/a/daily-performance?start=2026-10-13&end=2026-10-13'
        assert client.get(path).status_code == 401
        result = client.get(path, headers=HEADERS)
        assert result.status_code == 200 and result.json()['points'][0]['status'] == 'CASH_ONLY'
        assert client.post(path, headers=HEADERS, json={}).status_code == 405
        assert client.get(path.replace('/a/', '/missing/'), headers=HEADERS).status_code == 409
        assert client.get(path.replace('start=2026-10-13', 'start=2025-10-13'), headers=HEADERS).status_code == 422
        assert store.snapshot('a', full=True) == before


def test_explicit_daily_sharpe_math_and_missing_series_rules():
    values = [100000 + i*137 + (i % 3)*250 for i in range(22)]
    points = [{'liquidationEquityCents': value} for value in values]
    returns = [b/a-1 for a, b in zip(values, values[1:])]
    result = performance(points)
    assert result['sharpe'] == pytest.approx(mean(returns)/stdev(returns)*sqrt(252))
    assert result['maximumDailyDrawdownCents'] == 363
    assert result['sharpeStatus'] == 'MODELED_DAILY_RETURNS'
    assert performance(points[:20])['sharpeStatus'] == 'INSUFFICIENT_DAILY_RETURNS'
    assert performance([{'liquidationEquityCents': 100}] * 21)['sharpeStatus'] == 'ZERO_RETURN_VARIANCE'
    points[4]['liquidationEquityCents'] = None
    assert performance(points)['sharpe'] is None
    assert performance(points)['dailyReturns'][4:6] == [None, None]
    assert performance([{'liquidationEquityCents': 0}, {'liquidationEquityCents': 100}])['sharpeStatus'] == 'NONPOSITIVE_RETURN_BASE'
