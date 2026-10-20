/// "Capitulation Rebound" (ارتداد ما بعد الانهيار) — the only research rule that survived real option prices
/// (rebuild/research/report10, rounds 10-11). Pure functions; the TradingEngine wires them in when an account
/// uses `EntryStrategy.capitulationRebound`.
///
/// RULE (evaluated once per day, 15:45-15:57 New York, i.e. ~10 minutes before the close):
///   bbwPct   = percentile rank of today's Bollinger BandWidth(20, 2) among the previous 125 values
///              (126-value window, research `rolling_percentile`), BandWidth = 4·σ / SMA20 (σ population)  > 0.80
///   roc20    = price / close[20 sessions ago] − 1                                                         < −0.10
///   spyRoc5  = SPY price / SPY close[5 sessions ago] − 1                                                  < −0.03
///   "today" uses the current price as today's close (the research used 15:50 prices).
/// TRADE: buy a ~0.50-delta CALL, nearest expiry with ≥ 4 calendar days; time exit at 15:50 New York on the
///   SECOND trading session after the entry session. No stop and no profit target (the edge is a 2-day rebound).
/// RISK (account preset): ≤ ~0.8 % of equity premium per trade, ≤ 5 open positions, ≤ 5 % total premium open.
library;

import 'dart:math' as math;

import '../brokers/broker_adapter.dart' show BarTimeframe;
import '../market/market_calendar.dart';
import '../models.dart';
import '../trading/decision_engine.dart';

class CapitulationParams {
  final int bbPeriod;
  final double bbK;
  final int pctWindow; // values in the percentile window, today included (research: 126)
  final double bbwPctMin;
  final int rocDays;
  final double rocMax;
  final int spyRocDays;
  final double spyRocMax;
  final int holdSessions;

  /// Entry window in New York wall time (minutes after midnight), inclusive start, exclusive end.
  final int entryFromMin;
  final int entryToMin;

  /// Time exit (New York minutes after midnight) on the exit session.
  final int exitAtMin;

  const CapitulationParams({
    this.bbPeriod = 20,
    this.bbK = 2.0,
    this.pctWindow = 126,
    this.bbwPctMin = 0.80,
    this.rocDays = 20,
    this.rocMax = -0.10,
    this.spyRocDays = 5,
    this.spyRocMax = -0.03,
    this.holdSessions = 2,
    this.entryFromMin = 15 * 60 + 45,
    this.entryToMin = 15 * 60 + 57,
    this.exitAtMin = 15 * 60 + 50,
  });

  /// Daily closes needed before today.
  int get closesNeeded => bbPeriod + pctWindow - 1 + 1;
}

class CapitulationSignal {
  final bool fire;
  final double bbwPct;
  final double roc;
  final double spyRoc;
  final String reasonAr;
  const CapitulationSignal(this.fire, this.bbwPct, this.roc, this.spyRoc, this.reasonAr);

  Map<String, Object?> toJson() => {
        'fire': fire,
        'bbwPct': double.parse(bbwPct.toStringAsFixed(4)),
        'roc20': double.parse(roc.toStringAsFixed(4)),
        'spyRoc5': double.parse(spyRoc.toStringAsFixed(4)),
      };
}

/// Bollinger BandWidth series (4σ/SMA, population σ) for every index ≥ period−1; NaN before.
List<double> bandWidthSeries(List<double> c, {int period = 20, double k = 2.0}) {
  final out = List<double>.filled(c.length, double.nan);
  for (var i = period - 1; i < c.length; i++) {
    var sum = 0.0;
    for (var j = i - period + 1; j <= i; j++) {
      sum += c[j];
    }
    final m = sum / period;
    var ss = 0.0;
    for (var j = i - period + 1; j <= i; j++) {
      ss += (c[j] - m) * (c[j] - m);
    }
    final sd = math.sqrt(ss / period);
    out[i] = 2 * k * sd / m;
  }
  return out;
}

/// Share of the previous (window−1) values strictly below the last value (research `rolling_percentile`).
double percentileOfLast(List<double> s, int window) {
  if (s.length < window) return double.nan;
  final last = s.last;
  if (last.isNaN) return double.nan;
  var below = 0, n = 0;
  for (var j = s.length - window; j < s.length - 1; j++) {
    if (s[j].isNaN) return double.nan;
    n++;
    if (s[j] < last) below++;
  }
  return n == 0 ? double.nan : below / n;
}

/// Evaluates the rule. [dailyCloses] / [spyCloses] are COMPLETED sessions before today (oldest first);
/// [price] / [spyPrice] are the current prices used as today's close.
CapitulationSignal evaluateCapitulation({
  required List<double> dailyCloses,
  required double price,
  required List<double> spyCloses,
  required double spyPrice,
  CapitulationParams p = const CapitulationParams(),
}) {
  final c = [...dailyCloses, price];
  final s = [...spyCloses, spyPrice];
  if (c.length < p.bbPeriod + p.pctWindow - 1 || c.length <= p.rocDays || s.length <= p.spyRocDays) {
    return const CapitulationSignal(false, double.nan, double.nan, double.nan, 'بيانات يومية غير كافية لقاعدة الارتداد');
  }
  final bbw = bandWidthSeries(c, period: p.bbPeriod, k: p.bbK);
  final pct = percentileOfLast(bbw, p.pctWindow);
  final roc = price / c[c.length - 1 - p.rocDays] - 1;
  final spyRoc = spyPrice / s[s.length - 1 - p.spyRocDays] - 1;
  final ok1 = pct > p.bbwPctMin, ok2 = roc < p.rocMax, ok3 = spyRoc < p.spyRocMax;
  String f(double v) => '${(v * 100).toStringAsFixed(1)}%';
  final reason = 'ارتداد ما بعد الانهيار: ترتيب عرض البولنجر ${f(pct)} (${ok1 ? '✓' : '✗'} > ${f(p.bbwPctMin)})، '
      'تغير ${p.rocDays} يومًا ${f(roc)} (${ok2 ? '✓' : '✗'} < ${f(p.rocMax)})، '
      'SPY ${p.spyRocDays} أيام ${f(spyRoc)} (${ok3 ? '✓' : '✗'} < ${f(p.spyRocMax)})';
  return CapitulationSignal(ok1 && ok2 && ok3, pct, roc, spyRoc, reason);
}

/// True when [now] is inside the daily entry window of a regular session.
bool inEntryWindow(DateTime now, MarketCalendar cal, {CapitulationParams p = const CapitulationParams()}) {
  final w = NewYorkTime.wall(now);
  final day = DateTime.utc(w.year, w.month, w.day);
  final sess = cal.session(day);
  if (sess == null || sess.earlyClose) return false; // early-close days: skip (research had no 13:00 cases)
  final m = w.hour * 60 + w.minute;
  return m >= p.entryFromMin && m < p.entryToMin;
}

/// Instant of the time exit: [p.exitAtMin] New York on the [p.holdSessions]-th trading session after the
/// session of [entryTime] (an early-close exit day exits 10 minutes before its 13:00 close).
DateTime capitulationExitDue(DateTime entryTime, MarketCalendar cal, {CapitulationParams p = const CapitulationParams()}) {
  final w = NewYorkTime.wall(entryTime);
  var d = DateTime.utc(w.year, w.month, w.day);
  var n = 0;
  for (var k = 0; k < 20 && n < p.holdSessions; k++) {
    d = d.add(const Duration(days: 1));
    if (cal.isTradingDay(d)) n++;
  }
  final sess = cal.session(d)!;
  if (sess.earlyClose) return sess.closeUtc.subtract(const Duration(minutes: 10));
  return NewYorkTime.toUtc(d.year, d.month, d.day, p.exitAtMin ~/ 60, p.exitAtMin % 60);
}

/// Completed daily closes (sessions strictly before today's New York date), oldest first.
/// Uses the calendar's bar-completion rule, so today's still-forming daily bar is dropped.
List<double> closesBeforeToday(List<Candle> daily, DateTime now, MarketCalendar cal) =>
    [for (final b in cal.completedBars(daily, BarTimeframe.d1, now)) b.close];

/// Exit rule of the strategy: (1) expiry guard (urgent) when [exitDaysBeforeExpiry] is reached, (2) the time exit
/// once [capitulationExitDue] has passed. Never a stop, target, trailing stop or signal exit.
ExitDecision? capitulationExit({
  required Position position,
  required PositionMeta meta,
  required DateTime now,
  required int exitDaysBeforeExpiry,
  MarketCalendar cal = const MarketCalendar(),
  CapitulationParams p = const CapitulationParams(),
}) {
  final dte = position.contract.daysToExpiry(now);
  if (dte <= exitDaysBeforeExpiry) {
    return ExitDecision(position, position.quantity, ExitKind.expiry, 'اقتراب الانتهاء: $dte يوم متبقٍ', urgent: true);
  }
  final due = capitulationExitDue(meta.entryTime, cal, p: p);
  if (!now.isBefore(due)) {
    return ExitDecision(position, position.quantity, ExitKind.maxHolding,
        'خروج زمني لاستراتيجية الارتداد: انتهت مدة الاحتفاظ (${p.holdSessions} جلسة تداول بعد الدخول، ${NewYorkTime.hm(due)} نيويورك)',
        urgent: false);
  }
  return null;
}
