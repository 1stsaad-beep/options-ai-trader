/// US equity/options market calendar: New York time, NYSE holidays and early
/// closes, regular trading hours (RTH) and session phases.
///
/// * **Time zone**: America/New_York is computed from the US DST rule in force
///   since 2007 (DST from the 2nd Sunday of March 02:00 local to the 1st Sunday
///   of November 02:00 local; UTC−4 in DST, UTC−5 otherwise). This is exact for
///   2007+ and needs no tz database on the phone. Tested across both
///   transitions.
/// * **Holidays / early closes**: the official NYSE table for 2026–2028
///   (nyse.com "Holidays & Trading Hours", fetched 2026-10-18) is authoritative;
///   other years use the NYSE rules (observance shifts, Good Friday from Easter,
///   Juneteenth from 2022, no Friday observance for a Saturday New Year). The
///   rules reproduce the 2026–2028 table (tested). Unscheduled closures cannot
///   be predicted — the broker clock (`/v2/clock`) covers those when available.
/// * **Sessions** (ET): pre-market 04:00–09:30, regular 09:30–16:00 (13:00 on
///   early-close days), post-market until 20:00 (17:00 on early-close days).
///   Options trade in RTH only; the app uses 13:00 on early-close days even
///   though some options close at 13:15 (conservative).
/// * **13:15 ET nuance** (documented, deliberately not used): on early-close
///   days equity options stop at 13:00 ET, but broad-based index options
///   (e.g. SPX/XSP/NDX/RUT on Cboe) and some ETF options (e.g. SPY/QQQ/IWM on
///   several venues) keep trading until 13:15 ET — mirroring the normal
///   16:00 vs 16:15 split. The engine stops opening/closing at 13:00 for every
///   symbol: the last 15 minutes are thin, and a uniform cut-off can never send
///   an order after a venue has closed. Positions still open then are handled
///   on the next session (or by the broker's own expiry processing).
library;

import '../brokers/broker_adapter.dart';
import '../models.dart';

/// Wall-clock conversion for America/New_York.
class NewYorkTime {
  NewYorkTime._();

  /// n-th [weekday] (1=Mon..7=Sun) of [month] in [year].
  static DateTime _nthWeekday(int year, int month, int weekday, int n) {
    final first = DateTime.utc(year, month, 1);
    final delta = (weekday - first.weekday + 7) % 7;
    return DateTime.utc(year, month, 1 + delta + 7 * (n - 1));
  }

  /// UTC instant DST starts in [year] (2nd Sunday of March, 02:00 EST = 07:00 UTC).
  static DateTime dstStartUtc(int year) => _nthWeekday(year, 3, DateTime.sunday, 2).add(const Duration(hours: 7));

  /// UTC instant DST ends in [year] (1st Sunday of November, 02:00 EDT = 06:00 UTC).
  static DateTime dstEndUtc(int year) => _nthWeekday(year, 11, DateTime.sunday, 1).add(const Duration(hours: 6));

  static bool isDst(DateTime instant) {
    final u = instant.toUtc();
    return !u.isBefore(dstStartUtc(u.year)) && u.isBefore(dstEndUtc(u.year));
  }

  /// UTC offset of New York at [instant]: −4 h in DST, −5 h otherwise.
  static Duration offsetAt(DateTime instant) => Duration(hours: isDst(instant) ? -4 : -5);

  /// New York wall-clock fields of [instant], returned as a UTC-flagged
  /// DateTime whose fields read as New York local time (use only its fields).
  static DateTime wall(DateTime instant) {
    final u = instant.toUtc();
    return u.add(offsetAt(u));
  }

  /// UTC instant of New York wall time [y]-[m]-[d] [h]:[min]. Wall times are
  /// assumed to exist (market hours never fall in the 02:00–03:00 gap).
  static DateTime toUtc(int y, int m, int d, [int h = 0, int min = 0]) {
    final naive = DateTime.utc(y, m, d, h, min);
    // Try EST first; if that instant is in DST, the EDT reading applies.
    final est = naive.add(const Duration(hours: 5));
    return isDst(est.subtract(const Duration(hours: 1))) ? naive.add(const Duration(hours: 4)) : est;
  }

  /// `yyyy-mm-dd` of the New York date at [instant].
  static String dateKey(DateTime instant) {
    final w = wall(instant);
    return '${w.year.toString().padLeft(4, '0')}-${w.month.toString().padLeft(2, '0')}-${w.day.toString().padLeft(2, '0')}';
  }

  /// `HH:mm` New York time.
  static String hm(DateTime instant) {
    final w = wall(instant);
    return '${w.hour.toString().padLeft(2, '0')}:${w.minute.toString().padLeft(2, '0')}';
  }
}

enum MarketPhase {
  closed,
  preMarket,
  open,
  postMarket;

  String get arabic => switch (this) {
        MarketPhase.closed => 'مغلق',
        MarketPhase.preMarket => 'قبل الافتتاح',
        MarketPhase.open => 'مفتوح',
        MarketPhase.postMarket => 'بعد الإغلاق',
      };
}

/// One regular session (UTC instants).
class TradingSession {
  final DateTime date; // New York calendar date (UTC midnight, fields only)
  final DateTime openUtc;
  final DateTime closeUtc;
  final bool earlyClose;
  const TradingSession(this.date, this.openUtc, this.closeUtc, this.earlyClose);

  DateTime get preOpenUtc => NewYorkTime.toUtc(date.year, date.month, date.day, 4);
  DateTime get postCloseUtc => closeUtc.add(const Duration(hours: 4));
}

enum StatusSource { calendar, broker }

class MarketStatus {
  final DateTime at;
  final MarketPhase phase;

  /// Today's (New York date) regular session, if it is a trading day.
  final TradingSession? today;
  final DateTime nextOpen;

  /// Close of the current session when open, else of the next session.
  final DateTime nextClose;

  /// Arabic reason when closed all day (weekend / holiday name).
  final String? closedReasonAr;
  final StatusSource source;

  /// Set when the broker clock disagreed with the calendar (conservative AND used).
  final String? noteAr;

  const MarketStatus({
    required this.at,
    required this.phase,
    required this.today,
    required this.nextOpen,
    required this.nextClose,
    this.closedReasonAr,
    this.source = StatusSource.calendar,
    this.noteAr,
  });

  bool get isOpen => phase == MarketPhase.open;

  MarketStatus copyWith({MarketPhase? phase, StatusSource? source, String? noteAr, DateTime? nextOpen, DateTime? nextClose}) =>
      MarketStatus(
        at: at,
        phase: phase ?? this.phase,
        today: today,
        nextOpen: nextOpen ?? this.nextOpen,
        nextClose: nextClose ?? this.nextClose,
        closedReasonAr: closedReasonAr,
        source: source ?? this.source,
        noteAr: noteAr ?? this.noteAr,
      );

  /// Short Arabic line, e.g. "مفتوح — يغلق 16:00 ET".
  String summaryAr() {
    final early = today?.earlyClose == true ? ' (إغلاق مبكر)' : '';
    return switch (phase) {
      MarketPhase.open => 'السوق مفتوح — يغلق ${NewYorkTime.hm(nextClose)} ET$early',
      _ => 'السوق ${phase.arabic}${closedReasonAr != null ? ' ($closedReasonAr)' : ''} — يفتح '
          '${NewYorkTime.dateKey(nextOpen)} ${NewYorkTime.hm(nextOpen)} ET',
    };
  }
}

class MarketCalendar {
  const MarketCalendar();

  /// Official NYSE holidays (nyse.com, fetched 2026-10-18).
  static final Map<DateTime, String> officialHolidays = {
    DateTime.utc(2026, 1, 1): 'رأس السنة',
    DateTime.utc(2026, 1, 19): 'يوم مارتن لوثر كينغ',
    DateTime.utc(2026, 2, 16): 'يوم الرؤساء',
    DateTime.utc(2026, 4, 3): 'الجمعة العظيمة',
    DateTime.utc(2026, 5, 25): 'يوم الذكرى',
    DateTime.utc(2026, 6, 19): 'جونتينث',
    DateTime.utc(2026, 7, 3): 'عيد الاستقلال (بديل)',
    DateTime.utc(2026, 9, 7): 'عيد العمال',
    DateTime.utc(2026, 11, 26): 'عيد الشكر',
    DateTime.utc(2026, 12, 25): 'عيد الميلاد',
    DateTime.utc(2027, 1, 1): 'رأس السنة',
    DateTime.utc(2027, 1, 18): 'يوم مارتن لوثر كينغ',
    DateTime.utc(2027, 2, 15): 'يوم الرؤساء',
    DateTime.utc(2027, 3, 26): 'الجمعة العظيمة',
    DateTime.utc(2027, 5, 31): 'يوم الذكرى',
    DateTime.utc(2027, 6, 18): 'جونتينث (بديل)',
    DateTime.utc(2027, 7, 5): 'عيد الاستقلال (بديل)',
    DateTime.utc(2027, 9, 6): 'عيد العمال',
    DateTime.utc(2027, 11, 25): 'عيد الشكر',
    DateTime.utc(2027, 12, 24): 'عيد الميلاد (بديل)',
    DateTime.utc(2028, 1, 17): 'يوم مارتن لوثر كينغ',
    DateTime.utc(2028, 2, 21): 'يوم الرؤساء',
    DateTime.utc(2028, 4, 14): 'الجمعة العظيمة',
    DateTime.utc(2028, 5, 29): 'يوم الذكرى',
    DateTime.utc(2028, 6, 19): 'جونتينث',
    DateTime.utc(2028, 7, 4): 'عيد الاستقلال',
    DateTime.utc(2028, 9, 4): 'عيد العمال',
    DateTime.utc(2028, 11, 23): 'عيد الشكر',
    DateTime.utc(2028, 12, 25): 'عيد الميلاد',
  };

  /// Official 13:00 ET early closes (equities and equity options; some index /
  /// ETF options run to 13:15 ET — the app still uses 13:00, see library docs).
  static final Set<DateTime> officialEarlyCloses = {
    DateTime.utc(2026, 11, 27),
    DateTime.utc(2026, 12, 24),
    DateTime.utc(2027, 11, 26),
    DateTime.utc(2028, 7, 3),
    DateTime.utc(2028, 11, 24),
  };

  static const officialYears = {2026, 2027, 2028};

  static DateTime _d(DateTime t) => DateTime.utc(t.year, t.month, t.day);

  // ------------------------------------------------------------ rule engine

  static DateTime _easter(int y) {
    // Anonymous Gregorian algorithm.
    final a = y % 19, b = y ~/ 100, c = y % 100, d = b ~/ 4, e = b % 4, f = (b + 8) ~/ 25, g = (b - f + 1) ~/ 3;
    final h = (19 * a + b - d - g + 15) % 30, i = c ~/ 4, k = c % 4, l = (32 + 2 * e + 2 * i - h - k) % 7;
    final m = (a + 11 * h + 22 * l) ~/ 451;
    final month = (h + l - 7 * m + 114) ~/ 31, day = ((h + l - 7 * m + 114) % 31) + 1;
    return DateTime.utc(y, month, day);
  }

  static DateTime _observed(DateTime d) => switch (d.weekday) {
        DateTime.saturday => d.subtract(const Duration(days: 1)),
        DateTime.sunday => d.add(const Duration(days: 1)),
        _ => d,
      };

  static DateTime _nth(int y, int m, int weekday, int n) => NewYorkTime._nthWeekday(y, m, weekday, n);

  static DateTime _last(int y, int m, int weekday) {
    var d = DateTime.utc(y, m + 1, 0);
    while (d.weekday != weekday) {
      d = d.subtract(const Duration(days: 1));
    }
    return d;
  }

  /// NYSE holidays of [year] from the rules.
  static Map<DateTime, String> ruleHolidays(int year) {
    final out = <DateTime, String>{};
    final ny = DateTime.utc(year, 1, 1);
    if (ny.weekday != DateTime.saturday) out[_observed(ny)] = 'رأس السنة'; // Saturday: not observed
    out[_nth(year, 1, DateTime.monday, 3)] = 'يوم مارتن لوثر كينغ';
    out[_nth(year, 2, DateTime.monday, 3)] = 'يوم الرؤساء';
    out[_easter(year).subtract(const Duration(days: 2))] = 'الجمعة العظيمة';
    out[_last(year, 5, DateTime.monday)] = 'يوم الذكرى';
    if (year >= 2022) {
      final j = DateTime.utc(year, 6, 19);
      out[_observed(j)] = j.weekday >= 6 ? 'جونتينث (بديل)' : 'جونتينث';
    }
    final jul = DateTime.utc(year, 7, 4);
    out[_observed(jul)] = jul.weekday >= 6 ? 'عيد الاستقلال (بديل)' : 'عيد الاستقلال';
    out[_nth(year, 9, DateTime.monday, 1)] = 'عيد العمال';
    out[_nth(year, 11, DateTime.thursday, 4)] = 'عيد الشكر';
    final xmas = DateTime.utc(year, 12, 25);
    out[_observed(xmas)] = xmas.weekday >= 6 ? 'عيد الميلاد (بديل)' : 'عيد الميلاد';
    return out;
  }

  /// 13:00 early closes of [year] from the rules: day after Thanksgiving;
  /// Dec 24 when it is a Mon–Thu trading day; July 3 when it is a Mon–Thu
  /// trading day.
  static Set<DateTime> ruleEarlyCloses(int year) {
    final out = <DateTime>{_nth(year, 11, DateTime.thursday, 4).add(const Duration(days: 1))};
    final hol = ruleHolidays(year).keys.toSet();
    for (final d in [DateTime.utc(year, 12, 24), DateTime.utc(year, 7, 3)]) {
      if (d.weekday <= DateTime.thursday && !hol.contains(d)) out.add(d);
    }
    return out;
  }

  // ------------------------------------------------------------ queries

  /// Holiday name on New York date [date], or null.
  String? holidayName(DateTime date) {
    final d = _d(date);
    return officialYears.contains(d.year) ? officialHolidays[d] : ruleHolidays(d.year)[d];
  }

  bool isEarlyClose(DateTime date) {
    final d = _d(date);
    return officialYears.contains(d.year) ? officialEarlyCloses.contains(d) : ruleEarlyCloses(d.year).contains(d);
  }

  bool isTradingDay(DateTime date) {
    final d = _d(date);
    return d.weekday <= DateTime.friday && holidayName(d) == null;
  }

  /// Regular session on New York date [date], or null if closed all day.
  TradingSession? session(DateTime date) {
    final d = _d(date);
    if (!isTradingDay(d)) return null;
    final early = isEarlyClose(d);
    return TradingSession(
      d,
      NewYorkTime.toUtc(d.year, d.month, d.day, 9, 30),
      NewYorkTime.toUtc(d.year, d.month, d.day, early ? 13 : 16),
      early,
    );
  }

  /// First session whose close is after [instant] (the current one if open).
  TradingSession nextSessionClosingAfter(DateTime instant) {
    final w = NewYorkTime.wall(instant);
    var d = DateTime.utc(w.year, w.month, w.day);
    for (var k = 0; k < 15; k++) {
      final s = session(d);
      if (s != null && s.closeUtc.isAfter(instant)) return s;
      d = d.add(const Duration(days: 1));
    }
    throw StateError('No session within 15 days of $instant');
  }

  MarketStatus statusAt(DateTime instant) {
    final u = instant.toUtc();
    final w = NewYorkTime.wall(u);
    final todayDate = DateTime.utc(w.year, w.month, w.day);
    final today = session(todayDate);
    final next = nextSessionClosingAfter(u);
    MarketPhase phase;
    if (today == null) {
      phase = MarketPhase.closed;
    } else if (!u.isBefore(today.openUtc) && u.isBefore(today.closeUtc)) {
      phase = MarketPhase.open;
    } else if (!u.isBefore(today.preOpenUtc) && u.isBefore(today.openUtc)) {
      phase = MarketPhase.preMarket;
    } else if (!u.isBefore(today.closeUtc) && u.isBefore(today.postCloseUtc)) {
      phase = MarketPhase.postMarket;
    } else {
      phase = MarketPhase.closed;
    }
    final nextOpen = phase == MarketPhase.open
        ? nextSessionClosingAfter(today!.closeUtc).openUtc
        : (next.openUtc.isAfter(u) ? next.openUtc : nextSessionClosingAfter(next.closeUtc).openUtc);
    String? reason;
    if (today == null) reason = holidayName(todayDate) ?? 'عطلة نهاية الأسبوع';
    return MarketStatus(
      at: u,
      phase: phase,
      today: today,
      nextOpen: nextOpen,
      nextClose: next.closeUtc,
      closedReasonAr: reason,
    );
  }

  /// When a bar that starts at [barStart] is complete. Intraday: start +
  /// length (capped at the session close). Daily: the close of that New York
  /// date's session (or the next midnight ET if it was not a session).
  DateTime barCompletesAt(DateTime barStart, BarTimeframe tf) {
    if (tf != BarTimeframe.d1) {
      final end = barStart.add(tf.duration);
      final s = session(NewYorkTime.wall(barStart));
      if (s != null && barStart.isBefore(s.closeUtc) && end.isAfter(s.closeUtc)) return s.closeUtc;
      return end;
    }
    // Alpaca daily bars are stamped at 00:00 ET (04:00/05:00 UTC) of the date.
    final w = NewYorkTime.wall(barStart.add(const Duration(hours: 6)));
    final s = session(DateTime.utc(w.year, w.month, w.day));
    return s?.closeUtc ?? NewYorkTime.toUtc(w.year, w.month, w.day + 1);
  }

  /// [bars] without the still-forming last bar(s) at [now]. Engines must only
  /// see completed bars; this keeps every decision reproducible.
  List<Candle> completedBars(List<Candle> bars, BarTimeframe tf, DateTime now) {
    var n = bars.length;
    while (n > 0 && barCompletesAt(bars[n - 1].time, tf).isAfter(now)) {
      n--;
    }
    return n == bars.length ? bars : bars.sublist(0, n);
  }
}

/// Broker market clock (e.g. Alpaca `/v2/clock`), used to confirm the calendar.
class BrokerMarketClock {
  final DateTime timestamp;
  final bool isOpen;
  final DateTime nextOpen;
  final DateTime nextClose;
  const BrokerMarketClock({required this.timestamp, required this.isOpen, required this.nextOpen, required this.nextClose});
}

/// Implemented by adapters that can report the exchange clock.
abstract interface class MarketClockSource {
  Future<BrokerMarketClock> marketClock();
}

/// Decides whether orders may be placed now: offline calendar, confirmed by
/// the broker clock when the adapter offers one. Open only when **both** say
/// open (conservative); the broker failing falls back to the calendar.
class MarketHoursGate {
  final MarketCalendar calendar;
  final MarketClockSource? clockSource;
  BrokerMarketClock? lastBrokerClock;
  String? lastBrokerError;

  MarketHoursGate({this.calendar = const MarketCalendar(), this.clockSource});

  Future<MarketStatus> status(DateTime now) async {
    final offline = calendar.statusAt(now);
    final src = clockSource;
    if (src == null) return offline;
    try {
      final c = await src.marketClock();
      lastBrokerClock = c;
      lastBrokerError = null;
      if (c.isOpen == offline.isOpen) return offline.copyWith(source: StatusSource.broker);
      if (c.isOpen && !offline.isOpen) {
        return offline.copyWith(
            source: StatusSource.broker, noteAr: 'الوسيط يقول إن السوق مفتوح والتقويم يقول مغلق — اعتُبر مغلقًا');
      }
      // Broker says closed (e.g. unscheduled closure): closed.
      return offline.copyWith(
        phase: MarketPhase.closed,
        source: StatusSource.broker,
        nextOpen: c.nextOpen,
        noteAr: 'الوسيط يقول إن السوق مغلق والتقويم يقول مفتوح — اعتُبر مغلقًا',
      );
    } catch (e) {
      lastBrokerError = '$e';
      return offline;
    }
  }
}
