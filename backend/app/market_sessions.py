"""Versioned, offline session policy; no broker, network, or execution authority.

The US policy deliberately uses the conservative equity-option window, including
for fixture ETFs. It does not model product-specific late closes or trading halts.
"""
from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


SYNTHETIC_POLICY = 'synthetic_24x7'
US_EQUITY_OPTIONS_POLICY = 'us_equity_options_2026_2027'
SESSION_POLICIES = frozenset({SYNTHETIC_POLICY, US_EQUITY_OPTIONS_POLICY})
CALENDAR_VERSION = 'us-equity-options-2026-2027-v1'
VERIFIED_ON = '2026-10-11'
SOURCE_URLS = (
    'https://www.nyse.com/trade/hours-calendars',
    'https://www.nasdaqtrader.com/Trader.aspx?id=Calendar',
    'https://www.nasdaqtrader.com/Trader.aspx?id=optionshours',
)
_HOLIDAYS = frozenset(date.fromisoformat(value) for value in (
    '2026-01-01', '2026-01-19', '2026-02-16', '2026-04-03', '2026-05-25',
    '2026-06-19', '2026-07-03', '2026-09-07', '2026-11-26', '2026-12-25',
    '2027-01-01', '2027-01-18', '2027-02-15', '2027-03-26', '2027-05-31',
    '2027-06-18', '2027-07-05', '2027-09-06', '2027-11-25', '2027-12-24',
))
_EARLY_CLOSES = frozenset(date.fromisoformat(value) for value in (
    '2026-11-27', '2026-12-24', '2027-11-26',
))


def _aware(value, name):
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f'{name} must be a timezone-aware datetime')


@dataclass(frozen=True)
class SessionStatus:
    policy: str
    status: str
    session_date: str | None
    entry_allowed: bool
    fill_allowed: bool
    exit_due: bool
    opens_at: datetime | None
    closes_at: datetime | None
    exit_at: datetime | None
    calendar_version: str
    verified_on: str | None
    source_urls: tuple[str, ...]
    reason: str

    def as_dict(self):
        """A new JSON-safe snapshot, suitable for immutable decision/audit facts."""
        result = asdict(self)
        for field in ('opens_at', 'closes_at', 'exit_at'):
            result[field] = result[field].isoformat() if result[field] else None
        result['source_urls'] = list(self.source_urls)
        return result


def unavailable_session(policy, status='CALENDAR_UNAVAILABLE'):
    """Fail-closed fallback for a caller that catches an unexpected calendar error."""
    return SessionStatus(policy, status, None, False, False, False,
                         None, None, None, CALENDAR_VERSION, VERIFIED_ON,
                         SOURCE_URLS, 'Calendar unavailable; entries and fills blocked')


def evaluate_session(now, policy=SYNTHETIC_POLICY, exit_buffer_minutes=15):
    """Evaluate an explicit instant; never read the wall clock or fetch a calendar.

    Configuration/input errors raise ValueError. Missing timezone data and dates
    outside the verified years return an untrusted, non-executable state instead
    of raising through the caller's independent protective-exit evaluation.
    """
    _aware(now, 'now')
    if not isinstance(policy, str) or policy not in SESSION_POLICIES:
        raise ValueError('Unknown session policy')
    if type(exit_buffer_minutes) is not int or not 1 <= exit_buffer_minutes <= 120:
        raise ValueError('session_exit_buffer_minutes must be an integer in [1, 120]')
    now = now.astimezone(timezone.utc)
    if policy == SYNTHETIC_POLICY:
        return SessionStatus(
            policy, 'SYNTHETIC_24X7', now.date().isoformat(), True, True, False,
            None, None, None, 'synthetic-24x7-v1', None, (),
            'Explicit synthetic fixture clock; no exchange-session claim',
        )

    def unavailable(status, session_date, reason):
        return SessionStatus(policy, status, session_date, False, False, False,
                             None, None, None, CALENDAR_VERSION, VERIFIED_ON,
                             SOURCE_URLS, reason)

    try:
        eastern = ZoneInfo('America/New_York')
    except ZoneInfoNotFoundError:
        return unavailable('TIMEZONE_UNAVAILABLE', None, 'America/New_York timezone data unavailable')
    local_date = now.astimezone(eastern).date()
    day = local_date.isoformat()
    if local_date.year not in (2026, 2027):
        return unavailable('UNSUPPORTED_DATE', day, 'Calendar verified only for 2026 and 2027')
    if local_date.weekday() >= 5:
        return unavailable('WEEKEND', day, 'Weekend: no modeled regular session')
    if local_date in _HOLIDAYS:
        return unavailable('HOLIDAY', day, 'Published full-day market holiday')
    opens_at = datetime.combine(local_date, time(9, 30), eastern).astimezone(timezone.utc)
    early_close = local_date in _EARLY_CLOSES
    closes_at = datetime.combine(local_date, time(13 if early_close else 16), eastern).astimezone(timezone.utc)
    exit_at = closes_at - timedelta(minutes=exit_buffer_minutes)
    fill_allowed = opens_at <= now < closes_at
    entry_allowed = opens_at <= now < exit_at
    exit_due = now >= exit_at
    status = ('PREOPEN' if now < opens_at else 'OPEN' if now < exit_at else
              'EXIT_WINDOW' if now < closes_at else 'CLOSED')
    reason = 'Published early close; conservative 13:00 ET cutoff' if early_close else 'Conservative regular equity-option session'
    return SessionStatus(policy, status, day, entry_allowed, fill_allowed, exit_due,
                         opens_at, closes_at, exit_at, CALENDAR_VERSION, VERIFIED_ON,
                         SOURCE_URLS, reason)


def prior_session_position(opened_at, now):
    """Whether an intraday position predates the current New York calendar date.

    An overdue position can then close when a modeled session is executable. If
    timezone data is unavailable, return True conservatively: the caller may
    retain a protective close intent, while evaluate_session still forbids fills.
    This helper itself neither permits execution nor models settlement dates.
    """
    _aware(opened_at, 'opened_at')
    _aware(now, 'now')
    if opened_at > now:
        raise ValueError('Position opening time cannot be in the future')
    try:
        eastern = ZoneInfo('America/New_York')
    except ZoneInfoNotFoundError:
        return True
    return opened_at.astimezone(eastern).date() < now.astimezone(eastern).date()
