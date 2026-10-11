"""Calendar-based expiry eligibility only; no exercise or broker simulation."""
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
import json
from zoneinfo import ZoneInfoNotFoundError

import pytest

from app import market_sessions, option_expiration
from app.market_sessions import evaluate_session, US_EQUITY_OPTIONS_POLICY
from app.option_expiration import evaluate_expiration


def instant(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00'))


def policy(expiry, now):
    return evaluate_expiration(date.fromisoformat(expiry), instant(now))


@pytest.mark.parametrize('expiry,last_date,cutoff', [
    ('2026-04-03', '2026-04-02', '2026-04-02T20:00:00+00:00'),
    ('2026-06-19', '2026-06-18', '2026-06-18T20:00:00+00:00'),
    ('2026-07-03', '2026-07-02', '2026-07-02T20:00:00+00:00'),
    ('2026-11-27', '2026-11-27', '2026-11-27T18:00:00+00:00'),
    ('2026-12-25', '2026-12-24', '2026-12-24T18:00:00+00:00'),
    ('2027-01-01', '2026-12-31', '2026-12-31T21:00:00+00:00'),
    ('2027-06-18', '2027-06-17', '2027-06-17T20:00:00+00:00'),
    ('2027-11-26', '2027-11-26', '2027-11-26T18:00:00+00:00'),
    ('2027-12-24', '2027-12-23', '2027-12-23T21:00:00+00:00'),
])
def test_published_holidays_and_early_closes_bound_nominal_fixture_expiry(expiry, last_date, cutoff):
    result = policy(expiry, last_date + 'T15:00:00Z')
    assert result['nominal_expiry'] == expiry
    assert result['last_trading_date'] == last_date
    assert result['cutoff_at'] == cutoff
    assert result['status'] == 'CLOSE_ONLY'
    assert not result['entry_allowed'] and result['close_intent_allowed'] and result['close_fill_allowed']
    assert result['days_to_last_trade'] == 0 and not result['review_required']


@pytest.mark.parametrize('now,status,entry,close,review', [
    ('2026-10-15T19:59:59Z', 'ACTIVE', True, True, False),
    ('2026-10-16T03:59:59Z', 'ACTIVE', True, True, False),
    ('2026-10-16T04:00:00Z', 'CLOSE_ONLY', False, True, False),
    ('2026-10-16T13:30:00Z', 'CLOSE_ONLY', False, True, False),
    ('2026-10-16T19:59:59Z', 'CLOSE_ONLY', False, True, False),
    ('2026-10-16T20:00:00Z', 'EXPIRY_REVIEW_REQUIRED', False, False, True),
    ('2026-10-19T13:30:00Z', 'EXPIRY_REVIEW_REQUIRED', False, False, True),
])
def test_last_day_is_close_only_and_cutoff_is_strict(now, status, entry, close, review):
    result = policy('2026-10-16', now)
    assert result['status'] == status
    assert result['entry_allowed'] is entry
    assert result['close_intent_allowed'] is close
    assert result['close_fill_allowed'] is close
    assert result['review_required'] is review


def test_early_close_partial_remainder_requires_review_at_one_pm_not_four():
    before = policy('2026-12-25', '2026-12-24T17:59:59Z')
    cutoff = policy('2026-12-25', '2026-12-24T18:00:00Z')
    assert before['close_fill_allowed']
    assert cutoff['review_required'] and not cutoff['close_fill_allowed']


@pytest.mark.parametrize('expiry,cutoff', [
    ('2026-03-06', '2026-03-06T21:00:00+00:00'),
    ('2026-03-13', '2026-03-13T20:00:00+00:00'),
    ('2026-10-30', '2026-10-30T20:00:00+00:00'),
    ('2026-11-06', '2026-11-06T21:00:00+00:00'),
    ('2027-03-12', '2027-03-12T21:00:00+00:00'),
    ('2027-03-19', '2027-03-19T20:00:00+00:00'),
    ('2027-11-05', '2027-11-05T20:00:00+00:00'),
    ('2027-11-12', '2027-11-12T21:00:00+00:00'),
])
def test_dst_adjusts_expiry_cutoff(expiry, cutoff):
    assert policy(expiry, expiry + 'T15:00:00Z')['cutoff_at'] == cutoff


def test_current_date_is_new_york_date_and_non_utc_instants_are_equivalent():
    now = instant('2026-10-16T00:30:00Z')
    result = evaluate_expiration(date(2026, 10, 16), now)
    assert result['current_date'] == '2026-10-15'
    assert result['days_to_last_trade'] == 1
    assert result == evaluate_expiration(date(2026, 10, 16), now.astimezone(timezone(timedelta(hours=3))))


def test_expiry_permission_alone_cannot_grant_out_of_session_execution():
    now = instant('2026-10-16T12:00:00Z')
    assert evaluate_expiration(date(2026, 10, 16), now)['close_fill_allowed']
    assert not evaluate_session(now, US_EQUITY_OPTIONS_POLICY).fill_allowed


@pytest.mark.parametrize('expiry,now', [
    ('2025-12-26', '2026-01-02T15:00:00Z'),
    ('2028-01-07', '2027-12-31T15:00:00Z'),
    ('2026-10-16', '2025-12-31T15:00:00Z'),
    ('2027-12-31', '2028-01-03T15:00:00Z'),
    # The holiday requires backtracking into an unsupported year.
    ('2026-01-01', '2026-01-01T15:00:00Z'),
])
def test_unsupported_calendar_dates_never_guess_a_cutoff(expiry, now):
    result = policy(expiry, now)
    assert result['status'] == 'CALENDAR_UNAVAILABLE'
    assert result['last_trading_date'] is None and result['cutoff_at'] is None
    assert not result['entry_allowed'] and not result['close_fill_allowed']
    assert result['close_intent_allowed'] and result['review_required']


def test_missing_timezone_fails_closed_without_using_utc_date(monkeypatch):
    def missing(_):
        raise ZoneInfoNotFoundError('fixture failure')
    monkeypatch.setattr(market_sessions, 'ZoneInfo', missing)
    result = policy('2026-10-16', '2026-10-16T00:30:00Z')
    assert result['status'] == 'CALENDAR_UNAVAILABLE'
    assert result['current_date'] is None and result['cutoff_at'] is None
    assert not result['entry_allowed'] and not result['close_fill_allowed']
    assert result['close_intent_allowed']


@pytest.mark.parametrize('fail_call', [1, 2, 3])
def test_exception_during_current_or_expiry_calendar_lookup_never_authorizes_execution(monkeypatch, fail_call):
    calls = 0
    def failing(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == fail_call:
            raise RuntimeError('fixture internal diagnostic must not be exposed')
        return evaluate_session(*args, **kwargs)
    monkeypatch.setattr(option_expiration, 'evaluate_session', failing)
    result = policy('2026-12-25', '2026-12-24T15:00:00Z')
    assert result['status'] == 'CALENDAR_UNAVAILABLE'
    assert not result['entry_allowed'] and not result['close_fill_allowed']
    assert result['close_intent_allowed'] and result['review_required']
    assert 'diagnostic' not in json.dumps(result)


def test_backtracking_is_bounded_and_does_not_use_calendar_fallback(monkeypatch):
    calls = 0
    def closed(*args, **kwargs):
        nonlocal calls
        calls += 1
        session = evaluate_session(*args, **kwargs)
        return replace(session, status='HOLIDAY', opens_at=None, closes_at=None) if calls > 1 else session
    monkeypatch.setattr(option_expiration, 'evaluate_session', closed)
    result = policy('2026-10-16', '2026-10-12T15:00:00Z')
    assert calls == 9  # Current instant plus expiry and seven prior dates.
    assert result['status'] == 'CALENDAR_UNAVAILABLE'


@pytest.mark.parametrize('change', [
    {'closes_at': None}, {'closes_at': datetime(2026, 10, 16, 20)},
    {'session_date': '2026-10-15'}, {'opens_at': instant('2026-10-16T21:00:00Z')},
])
def test_malformed_calendar_window_is_not_treated_as_trusted(monkeypatch, change):
    calls = 0
    def malformed(*args, **kwargs):
        nonlocal calls
        calls += 1
        session = evaluate_session(*args, **kwargs)
        return replace(session, **change) if calls > 1 else session
    monkeypatch.setattr(option_expiration, 'evaluate_session', malformed)
    result = policy('2026-10-16', '2026-10-12T15:00:00Z')
    assert result['status'] == 'CALENDAR_UNAVAILABLE' and not result['close_fill_allowed']


@pytest.mark.parametrize('expiry', ['2026-10-16', None, datetime(2026, 10, 16)])
def test_untyped_expiry_rejected(expiry):
    with pytest.raises(ValueError, match='expiry must be a date'):
        evaluate_expiration(expiry, instant('2026-10-12T15:00:00Z'))


def test_naive_now_is_not_silently_assumed_utc():
    with pytest.raises(ValueError, match='timezone-aware'):
        evaluate_expiration(date(2026, 10, 16), datetime(2026, 10, 12))


def test_result_is_json_safe_repeatable_and_carries_policy_version():
    first = policy('2026-10-16', '2026-10-12T15:00:00Z')
    second = policy('2026-10-16', '2026-10-12T15:00:00Z')
    assert first == json.loads(json.dumps(second))
    assert first['policy_version'] == 'us-close-only-expiry-v1'
    assert first['calendar_version'] == market_sessions.CALENDAR_VERSION
    first['entry_allowed'] = False
    assert second['entry_allowed']
