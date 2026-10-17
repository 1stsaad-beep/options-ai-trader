/// Daily NAV, drawdown and Sharpe on the phone (B13), contract `daily-nav-v1`.
///
/// Sampling: the latest *complete* valuation observed during a regular session
/// (shared calendar) becomes that New York session date's pre-close NAV. Only the
/// current session date can be updated; earlier dates are frozen. Incomplete
/// valuations are never recorded as numbers. Metrics use the same rules as the
/// server's observed daily report: simple daily returns, max drawdown on daily NAV,
/// Sharpe = mean / sample stdev (ddof 1) * sqrt(252), risk-free 0, at least 20
/// consecutive complete returns; a missing trading day blocks Sharpe.
library;

import 'dart:convert';
import 'dart:math' as math;

import 'market_paper_policy.dart';

const dailyNavContract = 'daily-nav-v1';
const dailyNavMaxDays = 3650;

bool _tradingDay(String date) {
  final d = DateTime.parse('${date}T15:00:00Z');
  final s = paperSession(d);
  return s.status != 'NO_SESSION' && s.status != 'UNSUPPORTED_DATE';
}

/// Returns an updated copy, or null when nothing changes (outside a session,
/// incomplete valuation, or an unchanged value).
Map<String, dynamic>? updateDailyNav(Object? existing, int? navCents, DateTime now) {
  if (navCents == null) return null;
  final s = paperSession(now);
  if (!s.fill) return null;
  final days = existing is Map ? Map<String, dynamic>.from(existing) : <String, dynamic>{};
  final today = days[s.date];
  // Unchanged value: no rewrite, so an otherwise no-op commit leaves the ledger byte-identical.
  // `samples` therefore counts distinct value changes within the session date.
  if (today is Map && today['navCents'] == navCents) return null;
  if (!days.containsKey(s.date) && days.length >= dailyNavMaxDays) return null; // bounded; never drops history
  days[s.date] = {'navCents': navCents, 'at': now.toUtc().toIso8601String(),
    'samples': today is Map ? (today['samples'] as int) + 1 : 1, 'contract': dailyNavContract};
  return days;
}

/// Shape check used by ledger validation.
bool validDailyNav(Object? value) {
  if (value is! Map || value.length > dailyNavMaxDays) return false;
  for (final e in value.entries) {
    final v = e.value;
    if (e.key is! String || !RegExp(r'^\d{4}-\d\d-\d\d$').hasMatch(e.key as String) || v is! Map ||
        v['navCents'] is! int || v['samples'] is! int || (v['samples'] as int) < 1 ||
        v['at'] is! String || DateTime.tryParse(v['at'] as String) == null) {
      return false;
    }
  }
  return true;
}

class DailyPerformance {
  final List<String> dates; // trading days from first sample to the last completed one
  final List<int?> nav;
  final bool complete;
  final int returnSamples;
  final int? maxDrawdownCents;
  final double? maxDrawdownFraction, totalReturn, sharpe;
  final String sharpeStatus;
  final String? provisionalDate; // today's still-open session (excluded from metrics)
  const DailyPerformance(this.dates, this.nav, this.complete, this.returnSamples, this.maxDrawdownCents,
      this.maxDrawdownFraction, this.totalReturn, this.sharpe, this.sharpeStatus, this.provisionalDate);
}

/// Same arithmetic and status codes as the server daily report verifier.
({bool complete, int samples, int? drawdown, double? fraction, double? total, double? sharpe, String status})
    dailyMetrics(List<int?> values) {
  final returns = <double?>[];
  for (var i = 0; i < values.length; i++) {
    final before = i > 0 ? values[i - 1] : null, current = values[i];
    returns.add(before != null && before > 0 && current != null ? current / before - 1 : null);
  }
  final complete = values.isNotEmpty && values.every((v) => v != null);
  final valid = returns.skip(1).whereType<double>().toList();
  final allReturns = complete && valid.length == values.length - 1;
  int? peak;
  var drawdown = 0, fraction = 0.0;
  if (complete) {
    for (final value in values.cast<int>()) {
      peak = peak == null ? value : math.max(peak, value);
      drawdown = math.max(drawdown, peak - value);
      if (peak > 0) fraction = math.max(fraction, (peak - value) / peak);
    }
  }
  double? sharpe;
  String status;
  if (values.isEmpty) {
    status = 'NO_SESSIONS';
  } else if (!complete) {
    status = 'MISSING_DAILY_VALUATION';
  } else if (!allReturns) {
    status = 'NONPOSITIVE_RETURN_BASE';
  } else if (valid.length < 20) {
    status = 'INSUFFICIENT_DAILY_RETURNS';
  } else {
    final average = valid.reduce((a, b) => a + b) / valid.length;
    final variance = valid.map((v) => math.pow(v - average, 2).toDouble()).reduce((a, b) => a + b) / (valid.length - 1);
    status = variance == 0 ? 'ZERO_RETURN_VARIANCE' : 'MODELED_DAILY_RETURNS';
    if (variance > 0) sharpe = average / math.sqrt(variance) * math.sqrt(252);
  }
  return (complete: complete, samples: valid.length, drawdown: complete ? drawdown : null,
    fraction: complete && peak! > 0 ? fraction : null,
    total: allReturns && values.length > 1 && values.first! > 0 ? values.last! / values.first! - 1 : null,
    sharpe: sharpe, status: status);
}

DailyPerformance dailyPerformance(Object? daily, DateTime now) {
  final days = daily is Map ? daily : const {};
  final recorded = days.keys.cast<String>().toList()..sort();
  final session = paperSession(now);
  final provisional = session.fill && days.containsKey(session.date) ? session.date : null;
  final closed = recorded.where((d) => d != provisional).toList();
  final dates = <String>[];
  if (closed.isNotEmpty) {
    var d = DateTime.parse('${closed.first}T12:00:00Z');
    final last = DateTime.parse('${closed.last}T12:00:00Z');
    while (!d.isAfter(last)) {
      final text = paperDate(d);
      if (_tradingDay(text)) dates.add(text);
      d = d.add(const Duration(days: 1));
    }
  }
  final nav = [for (final d in dates) (days[d] as Map?)?['navCents'] as int?];
  final m = dailyMetrics(nav);
  return DailyPerformance(dates, nav, m.complete, m.samples, m.drawdown, m.fraction, m.total, m.sharpe, m.status, provisional);
}

String dailyPerformanceText(DailyPerformance p, String Function(int?) money) {
  String pct(double? v) => v == null ? 'غير متاح' : '${(v * 100).toStringAsFixed(2)}%';
  return 'NAV اليومي: ${p.dates.length} جلسة مكتملة${p.provisionalDate == null ? '' : ' + جلسة اليوم (مؤقتة)'}'
      '${p.complete ? '' : ' • أيام ناقصة'}\n'
      'العائد ${pct(p.totalReturn)} • أقصى تراجع يومي ${money(p.maxDrawdownCents)} (${pct(p.maxDrawdownFraction)})\n'
      'Sharpe ${p.sharpe?.toStringAsFixed(3) ?? 'غير متاح'} (${p.sharpeStatus})';
}

/// Per-account daily NAV for Broker Paper accounts, in the secure key-value store.
class DailyNavStore {
  final Future<String?> Function(String key) read;
  final Future<void> Function(String key, String value) write;
  final String key;
  DailyNavStore(this.read, this.write, this.key);

  Future<Map<String, dynamic>> load() async {
    final text = await read(key);
    if (text == null) return {};
    final j = jsonDecode(text);
    if (j is! Map || j['contract'] != dailyNavContract || !validDailyNav(j['days'])) throw const FormatException('DAILY_NAV_CORRUPT');
    return Map<String, dynamic>.from(j['days'] as Map);
  }

  /// Records a complete NAV sample; returns the (possibly unchanged) days.
  Future<Map<String, dynamic>> sample(int? navCents, DateTime now) async {
    final days = await load();
    final next = updateDailyNav(days, navCents, now);
    if (next == null) return days;
    final text = jsonEncode({'contract': dailyNavContract, 'days': next});
    await write(key, text);
    if (await read(key) != text) throw const FormatException('DAILY_NAV_WRITE_UNCONFIRMED');
    return next;
  }
}
