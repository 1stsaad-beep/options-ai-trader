"""Offline schedule tests against published dates, not broker integration tests."""
from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone
import json
from zoneinfo import ZoneInfoNotFoundError

import pytest

from app import market_sessions
from app.market_sessions import (
    CALENDAR_VERSION, US_EQUITY_OPTIONS_POLICY, evaluate_session,
    prior_session_position, unavailable_session,
)


def instant(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00'))


def us(value, buffer=15):
    return evaluate_session(instant(value), US_EQUITY_OPTIONS_POLICY, buffer)


@pytest.mark.parametrize('day', [
    '2026-01-01', '2026-01-19', '2026-02-16', '2026-04-03', '2026-05-25',
    '2026-06-19', '2026-07-03', '2026-09-07', '2026-11-26', '2026-12-25',
    '2027-01-01', '2027-01-18', '2027-02-15', '2027-03-26', '2027-05-31',
    '2027-06-18', '2027-07-05', '2027-09-06', '2027-11-25', '2027-12-24',
])
def test_published_full_day_holidays_never_allow_entries_or_fills(day):
    session = us(day + 'T16:00:00Z')
    assert session.status == 'HOLIDAY'
    assert not session.entry_allowed and not session.fill_allowed
    assert session.opens_at is None and session.closes_at is None


@pytest.mark.parametrize('day', ['2026-11-27', '2026-12-24', '2027-11-26'])
def test_early_close_changes_both_entry_deadline_and_fill_deadline(day):
    before = us(day + 'T17:44:59Z')
    deadline = us(day + 'T17:45:00Z')
    closed = us(day + 'T18:00:00Z')
    assert before.entry_allowed and before.fill_allowed and not before.exit_due
    assert deadline.status == 'EXIT_WINDOW'
    assert not deadline.entry_allowed and deadline.fill_allowed and deadline.exit_due
    assert closed.status == 'CLOSED' and not closed.fill_allowed and closed.exit_due
    assert closed.closes_at == instant(day + 'T18:00:00Z')


@pytest.mark.parametrize('value,status,entry,fill,exit_due', [
    ('2026-10-12T13:29:59Z', 'PREOPEN', False, False, False),
    ('2026-10-12T13:30:00Z', 'OPEN', True, True, False),
    ('2026-10-12T19:44:59Z', 'OPEN', True, True, False),
    ('2026-10-12T19:45:00Z', 'EXIT_WINDOW', False, True, True),
    ('2026-10-12T19:59:59Z', 'EXIT_WINDOW', False, True, True),
    ('2026-10-12T20:00:00Z', 'CLOSED', False, False, True),
])
def test_regular_session_boundaries(value, status, entry, fill, exit_due):
    session = us(value)
    assert (session.status, session.entry_allowed, session.fill_allowed, session.exit_due) == (status, entry, fill, exit_due)


@pytest.mark.parametrize('day,open_utc,close_utc', [
    ('2026-03-06', '14:30', '21:00'), ('2026-03-09', '13:30', '20:00'),
    ('2026-10-30', '13:30', '20:00'), ('2026-11-02', '14:30', '21:00'),
    ('2027-03-12', '14:30', '21:00'), ('2027-03-15', '13:30', '20:00'),
    ('2027-11-05', '13:30', '20:00'), ('2027-11-08', '14:30', '21:00'),
])
def test_us_dst_changes_utc_session_without_changing_eastern_hours(day, open_utc, close_utc):
    session = us(day + 'T16:00:00Z')
    assert session.opens_at == instant(f'{day}T{open_utc}:00Z')
    assert session.closes_at == instant(f'{day}T{close_utc}:00Z')


@pytest.mark.parametrize('value', ['2026-10-10T16:00:00Z', '2026-10-11T16:00:00Z'])
def test_weekend_has_no_execution_window(value):
    session = us(value)
    assert session.status == 'WEEKEND'
    assert not session.entry_allowed and not session.fill_allowed


@pytest.mark.parametrize('day,close_utc', [
    ('2026-07-02', '20:00'), ('2027-07-02', '20:00'), ('2027-12-31', '21:00'),
])
def test_no_invented_early_close_or_observed_new_year_holiday(day, close_utc):
    session = us(day + 'T16:00:00Z')
    assert session.entry_allowed
    assert session.closes_at == instant(f'{day}T{close_utc}:00Z')


@pytest.mark.parametrize('value', ['2025-10-10T16:00:00Z', '2028-01-03T16:00:00Z'])
def test_unsupported_year_is_explicit_and_fail_closed(value):
    session = us(value)
    assert session.status == 'UNSUPPORTED_DATE'
    assert not session.entry_allowed and not session.fill_allowed
    assert session.closes_at is None


def test_same_instant_in_kuwait_matches_utc_and_calendar_date_is_new_york():
    value = instant('2026-10-12T19:45:00Z')
    assert evaluate_session(value, US_EQUITY_OPTIONS_POLICY) == evaluate_session(value.astimezone(timezone(timedelta(hours=3))), US_EQUITY_OPTIONS_POLICY)
    # UTC has rolled into Tuesday; New York is still Monday after close.
    session = us('2026-10-13T00:30:00Z')
    assert session.session_date == '2026-10-12' and session.status == 'CLOSED'


@pytest.mark.parametrize('buffer', [1, 120])
def test_buffer_configuration_uses_minutes_even_for_short_session(buffer):
    session = us('2026-11-27T16:00:00Z', buffer)
    assert session.exit_at == instant('2026-11-27T18:00:00Z') - timedelta(minutes=buffer)
    assert session.exit_at > session.opens_at


@pytest.mark.parametrize('buffer', [True, False, 0, -1, 121, 1.5, '15', None])
def test_malformed_buffer_cannot_create_an_execution_window(buffer):
    with pytest.raises(ValueError, match='session_exit_buffer_minutes'):
        us('2026-10-12T16:00:00Z', buffer)


@pytest.mark.parametrize('value', [None, '2026-10-12T16:00:00Z', datetime(2026, 10, 12, 16)])
def test_untrusted_clock_rejected(value):
    with pytest.raises(ValueError, match='timezone-aware'):
        evaluate_session(value, US_EQUITY_OPTIONS_POLICY)


@pytest.mark.parametrize('policy', ['nyse', '', None, [], True])
def test_unknown_policy_does_not_silently_fall_back_to_synthetic(policy):
    with pytest.raises(ValueError, match='Unknown session policy'):
        evaluate_session(instant('2026-10-12T16:00:00Z'), policy)


def test_missing_timezone_data_blocks_us_execution_without_blocking_synthetic(monkeypatch):
    def missing(_):
        raise ZoneInfoNotFoundError('test fixture: no timezone database')
    monkeypatch.setattr(market_sessions, 'ZoneInfo', missing)
    now = instant('2026-10-12T16:00:00Z')
    session = evaluate_session(now, US_EQUITY_OPTIONS_POLICY)
    assert session.status == 'TIMEZONE_UNAVAILABLE'
    assert session.session_date is None
    assert not session.entry_allowed and not session.fill_allowed
    assert evaluate_session(now).entry_allowed
    assert prior_session_position(now - timedelta(minutes=1), now)


@pytest.mark.parametrize('value', ['2025-01-01T00:00:00Z', '2026-10-10T23:00:00Z', '2030-01-01T00:00:00Z'])
def test_default_preserves_explicit_synthetic_fixture_clock(value):
    session = evaluate_session(instant(value))
    assert session.status == 'SYNTHETIC_24X7'
    assert session.entry_allowed and session.fill_allowed and not session.exit_due
    assert session.source_urls == () and session.verified_on is None


def test_session_audit_snapshot_is_json_safe_independent_and_immutable():
    session = us('2026-10-12T16:00:00Z')
    snapshot = json.loads(json.dumps(session.as_dict()))
    assert snapshot['calendar_version'] == CALENDAR_VERSION
    assert snapshot['verified_on'] == '2026-10-11'
    assert snapshot['opens_at'] == '2026-10-12T13:30:00+00:00'
    snapshot['source_urls'].clear()
    assert session.source_urls
    with pytest.raises(FrozenInstanceError):
        session.entry_allowed = False


def test_unexpected_calendar_failure_has_an_explicit_safe_fallback():
    session = unavailable_session(US_EQUITY_OPTIONS_POLICY)
    assert session.status == 'CALENDAR_UNAVAILABLE'
    assert not session.entry_allowed and not session.fill_allowed and not session.exit_due
    assert session.session_date is None


def test_intraday_carry_uses_new_york_date_not_utc_midnight():
    assert not prior_session_position(instant('2026-10-12T19:00:00Z'), instant('2026-10-13T00:30:00Z'))
    assert prior_session_position(instant('2026-10-09T19:00:00Z'), instant('2026-10-12T13:30:00Z'))
    with pytest.raises(ValueError, match='future'):
        prior_session_position(instant('2026-10-12T16:01:00Z'), instant('2026-10-12T16:00:00Z'))
    with pytest.raises(ValueError, match='timezone-aware'):
        prior_session_position(datetime(2026, 10, 12), instant('2026-10-12T16:00:00Z'))
