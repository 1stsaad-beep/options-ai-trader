"""Offline, close-only expiry guard for nominal Friday synthetic contracts.

This policy does not qualify real contracts, exercise options, assign stock,
settle cash, or authorize an order. Its permissions are additional constraints:
the current session, ownership, prices and independent risk gates still apply.
"""
from datetime import date, datetime, time, timedelta, timezone

from .market_sessions import CALENDAR_VERSION, US_EQUITY_OPTIONS_POLICY, evaluate_session


POLICY_VERSION = 'us-close-only-expiry-v1'
_NO_SESSION = frozenset({'WEEKEND', 'HOLIDAY'})


def evaluate_expiration(expiry: date, now: datetime):
    """Return JSON-safe expiry facts without reading a clock or making I/O.

    The nominal date is kept unchanged. The modeled cutoff is the closing time
    of the last published regular session on/before that date. An unavailable
    calendar preserves close intentions but permits no entry or actual fill.
    """
    if type(expiry) is not date:
        raise ValueError('expiry must be a date, not a datetime or string')
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError('now must be a timezone-aware datetime')
    result = {
        'status': 'CALENDAR_UNAVAILABLE',
        'nominal_expiry': expiry.isoformat(),
        'last_trading_date': None,
        'cutoff_at': None,
        'current_date': None,
        'days_to_last_trade': None,
        'entry_allowed': False,
        'close_intent_allowed': True,
        'close_fill_allowed': False,
        'review_required': True,
        'policy_version': POLICY_VERSION,
        'calendar_version': CALENDAR_VERSION,
    }
    try:
        current = evaluate_session(now, US_EQUITY_OPTIONS_POLICY)
        if current.status not in {'PREOPEN', 'OPEN', 'EXIT_WINDOW', 'CLOSED', *_NO_SESSION}:
            return result
        current_date = date.fromisoformat(current.session_date)
        result['current_date'] = current_date.isoformat()
        if expiry.year not in (2026, 2027):
            return result
        last = None
        # Noon UTC is 07:00/08:00 New York and unambiguously the same date.
        # At most seven prior dates; unknown calendar days are never skipped.
        for days_back in range(8):
            candidate = expiry - timedelta(days=days_back)
            probe = datetime.combine(candidate, time(12), timezone.utc)
            session = evaluate_session(probe, US_EQUITY_OPTIONS_POLICY)
            if session.status in _NO_SESSION:
                continue
            if session.status not in {'PREOPEN', 'OPEN', 'EXIT_WINDOW', 'CLOSED'}:
                return result
            if session.session_date != candidate.isoformat():
                return result
            if any(not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None
                   for value in (session.opens_at, session.closes_at)):
                return result
            if session.opens_at >= session.closes_at:
                return result
            last = session
            break
        if last is None:
            return result
        last_date = date.fromisoformat(last.session_date)
        cutoff = last.closes_at.astimezone(timezone.utc)
        before_cutoff = now < cutoff
        entry_allowed = before_cutoff and current_date < last_date
        result.update(
            status=('EXPIRY_REVIEW_REQUIRED' if not before_cutoff else
                    'ACTIVE' if entry_allowed else 'CLOSE_ONLY'),
            last_trading_date=last_date.isoformat(),
            cutoff_at=cutoff.isoformat(),
            days_to_last_trade=(last_date - current_date).days,
            entry_allowed=entry_allowed,
            close_intent_allowed=before_cutoff,
            close_fill_allowed=before_cutoff,
            review_required=not before_cutoff,
        )
        return result
    except Exception:
        # Never substitute UTC dates, reveal exception details, or let a broken
        # optional calendar suppress independent protective-intent recording.
        return result
