"""New York time + NYSE calendar. Port of trader_core/lib/src/market/market_calendar.dart (same rules, same
official tables); shared vectors in tests/vectors/guard_vectors.json."""
from __future__ import annotations
import datetime as dt
from dataclasses import dataclass
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
UTC = dt.timezone.utc


def utc(y, m, d, h=0, mi=0, s=0) -> dt.datetime:
    return dt.datetime(y, m, d, h, mi, s, tzinfo=UTC)


def wall(instant: dt.datetime) -> dt.datetime:
    return instant.astimezone(NY)


def to_utc(y, m, d, h=0, mi=0) -> dt.datetime:
    return dt.datetime(y, m, d, h, mi, tzinfo=NY).astimezone(UTC)


def offset_hours(instant: dt.datetime) -> int:
    return int(wall(instant).utcoffset().total_seconds() // 3600)


def date_key(instant: dt.datetime) -> str:
    return wall(instant).strftime("%Y-%m-%d")


def hm(instant: dt.datetime) -> str:
    return wall(instant).strftime("%H:%M")


def _nth(y, m, weekday, n):           # weekday: Mon=0
    d = dt.date(y, m, 1)
    d += dt.timedelta(days=(weekday - d.weekday()) % 7)
    return d + dt.timedelta(weeks=n - 1)


def dst_start_utc(y):
    d = _nth(y, 3, 6, 2); return dt.datetime(d.year, d.month, d.day, 7, tzinfo=UTC)


def dst_end_utc(y):
    d = _nth(y, 11, 6, 1); return dt.datetime(d.year, d.month, d.day, 6, tzinfo=UTC)


OFFICIAL_HOLIDAYS = {
    dt.date(2026, 1, 1): "رأس السنة", dt.date(2026, 1, 19): "يوم مارتن لوثر كينغ", dt.date(2026, 2, 16): "يوم الرؤساء",
    dt.date(2026, 4, 3): "الجمعة العظيمة", dt.date(2026, 5, 25): "يوم الذكرى", dt.date(2026, 6, 19): "جونتينث",
    dt.date(2026, 7, 3): "عيد الاستقلال (بديل)", dt.date(2026, 9, 7): "عيد العمال", dt.date(2026, 11, 26): "عيد الشكر",
    dt.date(2026, 12, 25): "عيد الميلاد",
    dt.date(2027, 1, 1): "رأس السنة", dt.date(2027, 1, 18): "يوم مارتن لوثر كينغ", dt.date(2027, 2, 15): "يوم الرؤساء",
    dt.date(2027, 3, 26): "الجمعة العظيمة", dt.date(2027, 5, 31): "يوم الذكرى", dt.date(2027, 6, 18): "جونتينث (بديل)",
    dt.date(2027, 7, 5): "عيد الاستقلال (بديل)", dt.date(2027, 9, 6): "عيد العمال", dt.date(2027, 11, 25): "عيد الشكر",
    dt.date(2027, 12, 24): "عيد الميلاد (بديل)",
    dt.date(2028, 1, 17): "يوم مارتن لوثر كينغ", dt.date(2028, 2, 21): "يوم الرؤساء", dt.date(2028, 4, 14): "الجمعة العظيمة",
    dt.date(2028, 5, 29): "يوم الذكرى", dt.date(2028, 6, 19): "جونتينث", dt.date(2028, 7, 4): "عيد الاستقلال",
    dt.date(2028, 9, 4): "عيد العمال", dt.date(2028, 11, 23): "عيد الشكر", dt.date(2028, 12, 25): "عيد الميلاد",
}
OFFICIAL_EARLY = {dt.date(2026, 11, 27), dt.date(2026, 12, 24), dt.date(2027, 11, 26), dt.date(2028, 7, 3), dt.date(2028, 11, 24)}
OFFICIAL_YEARS = {2026, 2027, 2028}


def _easter(y):
    a, b, c = y % 19, y // 100, y % 100
    d, e, f = b // 4, b % 4, (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return dt.date(y, month, day)


def _observed(d):
    return d - dt.timedelta(days=1) if d.weekday() == 5 else (d + dt.timedelta(days=1) if d.weekday() == 6 else d)


def _last(y, m, weekday):
    d = dt.date(y + (m == 12), m % 12 + 1, 1) - dt.timedelta(days=1)
    while d.weekday() != weekday: d -= dt.timedelta(days=1)
    return d


def rule_holidays(y):
    out = {}
    ny = dt.date(y, 1, 1)
    if ny.weekday() != 5: out[_observed(ny)] = "رأس السنة"
    out[_nth(y, 1, 0, 3)] = "يوم مارتن لوثر كينغ"
    out[_nth(y, 2, 0, 3)] = "يوم الرؤساء"
    out[_easter(y) - dt.timedelta(days=2)] = "الجمعة العظيمة"
    out[_last(y, 5, 0)] = "يوم الذكرى"
    if y >= 2022:
        j = dt.date(y, 6, 19); out[_observed(j)] = "جونتينث (بديل)" if j.weekday() >= 5 else "جونتينث"
    jul = dt.date(y, 7, 4); out[_observed(jul)] = "عيد الاستقلال (بديل)" if jul.weekday() >= 5 else "عيد الاستقلال"
    out[_nth(y, 9, 0, 1)] = "عيد العمال"
    out[_nth(y, 11, 3, 4)] = "عيد الشكر"
    x = dt.date(y, 12, 25); out[_observed(x)] = "عيد الميلاد (بديل)" if x.weekday() >= 5 else "عيد الميلاد"
    return out


def rule_early_closes(y):
    out = {_nth(y, 11, 3, 4) + dt.timedelta(days=1)}
    hol = set(rule_holidays(y))
    for d in (dt.date(y, 12, 24), dt.date(y, 7, 3)):
        if d.weekday() <= 3 and d not in hol: out.add(d)
    return out


def holiday_name(d: dt.date):
    return OFFICIAL_HOLIDAYS.get(d) if d.year in OFFICIAL_YEARS else rule_holidays(d.year).get(d)


def is_early_close(d: dt.date):
    return d in OFFICIAL_EARLY if d.year in OFFICIAL_YEARS else d in rule_early_closes(d.year)


def is_trading_day(d: dt.date):
    return d.weekday() <= 4 and holiday_name(d) is None


@dataclass(frozen=True)
class Session:
    date: dt.date
    open_utc: dt.datetime
    close_utc: dt.datetime
    early_close: bool

    @property
    def pre_open_utc(self): return to_utc(self.date.year, self.date.month, self.date.day, 4)

    @property
    def post_close_utc(self): return self.close_utc + dt.timedelta(hours=4)


def session(d: dt.date):
    if not is_trading_day(d): return None
    early = is_early_close(d)
    return Session(d, to_utc(d.year, d.month, d.day, 9, 30), to_utc(d.year, d.month, d.day, 13 if early else 16), early)


def next_session_closing_after(instant: dt.datetime) -> Session:
    d = wall(instant).date()
    for _ in range(15):
        s = session(d)
        if s and s.close_utc > instant: return s
        d += dt.timedelta(days=1)
    raise RuntimeError("no session within 15 days")


def next_trading_day(d: dt.date) -> dt.date:
    d += dt.timedelta(days=1)
    while not is_trading_day(d): d += dt.timedelta(days=1)
    return d


@dataclass(frozen=True)
class Status:
    at: dt.datetime
    phase: str                    # closed | preMarket | open | postMarket
    today: Session | None
    next_open: dt.datetime
    next_close: dt.datetime
    closed_reason_ar: str | None = None
    source: str = "calendar"      # calendar | broker
    note_ar: str | None = None

    @property
    def is_open(self): return self.phase == "open"


def status_at(instant: dt.datetime) -> Status:
    u = instant.astimezone(UTC)
    today_d = wall(u).date()
    today = session(today_d)
    nxt = next_session_closing_after(u)
    if today is None: phase = "closed"
    elif today.open_utc <= u < today.close_utc: phase = "open"
    elif today.pre_open_utc <= u < today.open_utc: phase = "preMarket"
    elif today.close_utc <= u < today.post_close_utc: phase = "postMarket"
    else: phase = "closed"
    if phase == "open":
        next_open = next_session_closing_after(today.close_utc).open_utc
    else:
        next_open = nxt.open_utc if nxt.open_utc > u else next_session_closing_after(nxt.close_utc).open_utc
    reason = (holiday_name(today_d) or "عطلة نهاية الأسبوع") if today is None else None
    return Status(u, phase, today, next_open, nxt.close_utc, reason)


@dataclass
class BrokerClock:
    is_open: bool
    next_open: dt.datetime
    next_close: dt.datetime


class MarketHoursGate:
    """Open only when the calendar AND the broker clock (when available) say open; broker failure -> calendar."""

    def __init__(self, clock_source=None):
        self.clock_source = clock_source      # callable -> BrokerClock (may raise)
        self.last_broker_error = None

    def status(self, now: dt.datetime) -> Status:
        off = status_at(now)
        if self.clock_source is None: return off
        try:
            c = self.clock_source()
            self.last_broker_error = None
        except Exception as e:     # noqa: BLE001 — any broker failure falls back to the calendar
            self.last_broker_error = str(e)
            return off
        from dataclasses import replace
        if c.is_open == off.is_open: return replace(off, source="broker")
        if c.is_open and not off.is_open:
            return replace(off, source="broker", note_ar="الوسيط يقول إن السوق مفتوح والتقويم يقول مغلق — اعتُبر مغلقًا")
        return replace(off, phase="closed", source="broker", next_open=c.next_open,
                       note_ar="الوسيط يقول إن السوق مغلق والتقويم يقول مفتوح — اعتُبر مغلقًا")
