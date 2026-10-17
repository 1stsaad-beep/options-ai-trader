import 'dart:convert';
import 'dart:math' as math;
import 'package:flutter/material.dart';
import 'api.dart';
import 'market_paper_policy.dart';
import 'observed_server.dart';
import 'paper_time.dart';

DateTime _date(String value) {
  if (!RegExp(r'^\d{4}-\d{2}-\d{2}$').hasMatch(value)) throw const FormatException('Invalid report date');
  final day = DateTime.parse('${value}T00:00:00Z');
  if (paperDate(day) != value || ![2026, 2027].contains(day.year)) throw const FormatException('Unsupported report date');
  return day;
}

List<PaperSession> dailySessions(String start, String end, DateTime now) {
  final first = _date(start), last = _date(end), days = last.difference(first).inDays;
  if (days < 0 || days >= 366) throw const FormatException('Report range exceeds bounds');
  final result = <PaperSession>[];
  for (var i = 0; i <= days; i++) {
    final session = paperSession(first.add(Duration(days: i, hours: 12)));
    if (session.status == 'NO_SESSION') continue;
    if (session.closes == null || session.closes!.isAfter(now.toUtc())) throw const FormatException('Session not complete');
    result.add(session);
  }
  return result;
}

/// Recomputes authenticated summary arithmetic/calendar. This does not attest
/// provider observations or replace a complete original-ledger replay.
Map<String, dynamic> parseObservedDaily(dynamic raw, ObservedServerAccount saved,
    String start, String end, DateTime now) {
  final r = observedObject(raw), points = r['points'], schedule = dailySessions(start, end, now);
  if (r['contract'] != 'observed-paper-daily-v1' || r['account'] != saved.state['id'] ||
      r['source'] != saved.state['source'] || r['start'] != start || r['end'] != end ||
      r['calendarVersion'] != paperCalendarVersion || !observedInteger(r['throughVersion']) ||
      r['throughVersion'] != saved.version || r['throughEventHash'] != saved.eventHash ||
      r['externalOrder'] != false || r['executionAllowed'] != false || r['newEntryAllowed'] != false ||
      r['sampling'] != 'LAST_MICROSECOND_BEFORE_MODELED_SESSION_CLOSE' || !observedHash(r['reportHash']) ||
      points is! List || points.length != schedule.length) throw const FormatException('Invalid daily report');
  final initial = saved.state['initialCash'] as int, values = <int?>[];
  var previousVersion = -1, fees = 0;
  Map<String, dynamic>? previous;
  for (var i = 0; i < points.length; i++) {
    final p = observedObject(points[i]), close = schedule[i].closes!;
    if (p['sessionDate'] != schedule[i].date || observationStamp(p['sessionClose']) != close ||
        observationStamp(p['asOf']) != close.subtract(const Duration(microseconds: 1)) || p['incompleteReasons'] is! List) {
      throw const FormatException('Incorrect daily sample time');
    }
    final reasons = p['incompleteReasons'] as List;
    if (p['status'] == 'ACCOUNT_NOT_CREATED') {
      if (previousVersion >= 0 || p['complete'] != false || p['stateVersion'] != null || p['stateEventHash'] != null ||
          reasons.length != 1 || reasons.single != 'ACCOUNT_NOT_CREATED' ||
          ['cashCents', 'feesCents', 'realizedPnlCents', 'ownedBasisCents', 'liquidationEquityCents',
            'unrealizedPnlCents', 'totalPnlCents'].any((key) => p[key] != null)) throw const FormatException('Invalid pre-genesis sample');
      values.add(null); continue;
    }
    for (final key in ['stateVersion', 'cashCents', 'feesCents', 'ownedBasisCents']) {
      if (!observedInteger(p[key])) throw const FormatException('Invalid daily integer');
    }
    for (final key in ['realizedPnlCents', 'liquidationEquityCents', 'unrealizedPnlCents', 'totalPnlCents']) {
      if ((key == 'realizedPnlCents' || p[key] != null) && !observedInteger(p[key], minimum: -9007199254740991)) {
        throw const FormatException('Invalid daily amount');
      }
    }
    final version = p['stateVersion'] as int, equity = p['liquidationEquityCents'] as int?;
    if (version < previousVersion || version > saved.version || !observedHash(p['stateEventHash']) ||
        version == saved.version && p['stateEventHash'] != saved.eventHash || p['feesCents'] < fees ||
        BigInt.from(p['cashCents'] as int) + BigInt.from(p['ownedBasisCents'] as int) !=
          BigInt.from(initial) + BigInt.from(p['realizedPnlCents'] as int) ||
        version == previousVersion && previous != null && ['stateEventHash', 'cashCents', 'feesCents',
          'ownedBasisCents', 'realizedPnlCents'].any((key) => p[key] != previous![key])) {
      throw const FormatException('Inconsistent daily state');
    }
    if (reasons.toSet().length != reasons.length || reasons.any((x) => ![
        'QUALIFIED_ORIGINAL_QUOTE_UNAVAILABLE', 'INSUFFICIENT_REMAINING_LIQUIDITY',
        'QUALIFIED_STOCK_QUOTE_UNAVAILABLE'].contains(x))) throw const FormatException('Invalid daily gap');
    if (equity == null) {
      if (p['status'] != 'INCOMPLETE' || p['complete'] != false || reasons.isEmpty ||
          p['totalPnlCents'] != null || p['unrealizedPnlCents'] != null) throw const FormatException('Hidden daily gap');
    } else if (p['complete'] != true || !['CASH_ONLY', 'OBSERVED_MODEL'].contains(p['status']) || reasons.isNotEmpty ||
        p['totalPnlCents'] != equity - initial || p['unrealizedPnlCents'] != equity - p['cashCents'] - p['ownedBasisCents'] ||
        p['status'] == 'CASH_ONLY' && (p['ownedBasisCents'] != 0 || equity != p['cashCents'])) {
      throw const FormatException('Incorrect daily valuation');
    }
    values.add(equity); previousVersion = version; fees = p['feesCents'] as int; previous = p;
  }
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
  String reason;
  if (values.isEmpty) { reason = 'NO_SESSIONS'; }
  else if (!complete) { reason = 'MISSING_DAILY_VALUATION'; }
  else if (!allReturns) { reason = 'NONPOSITIVE_RETURN_BASE'; }
  else if (valid.length < 20) { reason = 'INSUFFICIENT_DAILY_RETURNS'; }
  else {
    final average = valid.reduce((a, b) => a + b) / valid.length;
    final variance = valid.map((v) => math.pow(v - average, 2).toDouble()).reduce((a, b) => a + b) / (valid.length - 1);
    reason = variance == 0 ? 'ZERO_RETURN_VARIANCE' : 'MODELED_DAILY_RETURNS';
    if (variance > 0) sharpe = average / math.sqrt(variance) * math.sqrt(252);
  }
  bool equalNumber(dynamic actual, num? expected) => expected == null ? actual == null :
    actual is num && actual.isFinite && (actual - expected).abs() <= 1e-10 * math.max(1, expected.abs());
  final p = observedObject(r['performance']), daily = p['dailyReturns'];
  if (p['complete'] != complete || !observedInteger(p['returnSamples']) || p['returnSamples'] != valid.length ||
      p['maximumDailyDrawdownCents'] != (complete ? drawdown : null) ||
      p['maximumDailyDrawdownCents'] != null && !observedInteger(p['maximumDailyDrawdownCents']) ||
      !equalNumber(p['maximumDailyDrawdownFraction'], complete && peak! > 0 ? fraction : null) ||
      !equalNumber(p['totalReturn'], allReturns && values.length > 1 && values.first! > 0 ? values.last! / values.first! - 1 : null) ||
      !equalNumber(p['sharpe'], sharpe) || p['sharpeStatus'] != reason ||
      !observedInteger(p['annualizationSessions']) || p['annualizationSessions'] != 252 ||
      !observedInteger(p['annualRiskFreeRate']) || p['annualRiskFreeRate'] != 0 ||
      !observedInteger(p['minimumSharpeReturns']) || p['minimumSharpeReturns'] != 20 ||
      p['standardDeviation'] != 'SAMPLE_DDOF_1' || daily is! List || daily.length != returns.length) {
    throw const FormatException('Incorrect daily performance');
  }
  for (var i = 0; i < returns.length; i++) {
    if (!equalNumber(daily[i], returns[i])) throw const FormatException('Incorrect daily return');
  }
  return jsonDecode(jsonEncode(r)) as Map<String, dynamic>;
}

class ObservedDailyScreen extends StatefulWidget {
  final TraderApi api;
  final ObservedServerAccount saved;
  final DateTime Function()? now;
  const ObservedDailyScreen({super.key, required this.api, required this.saved, this.now});
  @override State<ObservedDailyScreen> createState() => _ObservedDailyScreenState();
}

class _ObservedDailyScreenState extends State<ObservedDailyScreen> {
  late String start, end;
  Map<String, dynamic>? report;
  bool busy = false;
  String? error;
  DateTime clock() => (widget.now?.call() ?? DateTime.now()).toUtc();
  @override void initState() {
    super.initState();
    final yesterday = clock().subtract(const Duration(days: 1));
    final last = yesterday.isAfter(DateTime.utc(2027, 12, 31)) ? DateTime.utc(2027, 12, 31) : yesterday;
    final first = last.subtract(const Duration(days: 29));
    start = paperDate(first.isBefore(DateTime.utc(2026)) ? DateTime.utc(2026) : first);
    end = paperDate(last);
    load();
  }
  Future<void> load() async {
    if (busy) return;
    setState(() { busy = true; error = null; report = null; });
    try {
      dailySessions(start, end, clock());
      final id = Uri.encodeComponent(widget.saved.state['id'] as String);
      final raw = await widget.api.request('GET', '/api/observed-paper/accounts/$id/daily-performance?start=$start&end=$end&through=${widget.saved.version}');
      final result = parseObservedDaily(raw, widget.saved, start, end, clock());
      if (mounted) setState(() => report = result);
    } catch (_) {
      if (mounted) setState(() => error = 'تعذر التحقق من التقرير اليومي. اختر جلسات مكتملة وأعد المحاولة؛ لم تتغير بيانات الحساب.');
    } finally { if (mounted) setState(() => busy = false); }
  }
  Future<void> choose() async {
    final range = await showDateRangePicker(context: context, firstDate: DateTime(2026),
      lastDate: DateTime(2027, 12, 31), helpText: 'اختر فترة لا تتجاوز 366 يومًا');
    if (!mounted || range == null) return;
    setState(() { start = paperDate(range.start); end = paperDate(range.end); });
    await load();
  }
  String money(dynamic value) => value == null ? 'غير متاح' : '${(value / 100).toStringAsFixed(2)} USD';
  String percent(dynamic value) => value == null ? 'غير متاح' : '${(value * 100).toStringAsFixed(2)}%';
  @override Widget build(BuildContext context) => Directionality(textDirection: TextDirection.rtl,
    child: Scaffold(appBar: AppBar(title: const Text('NAV اليومي قبل الإغلاق')), body: ListView(
      padding: const EdgeInsets.all(16), children: [
      Text(widget.saved.state['source'] == 'fixture' ? 'بيانات اختبار مصطنعة • ليست نتائج سوق' : 'تقرير من أصول Alpaca المحفوظة • قراءة فقط'),
      const Text('عينة قبل إغلاق الجلسة مباشرة وفق نموذج صافي التصفية والرسوم. ليست سعر الإغلاق الرسمي أو قيمة ما بعد التسوية. البيانات الناقصة تبقى غير متاحة.'),
      Text('$start — $end', key: const Key('daily-range')),
      Text('التقرير مثبت عند الحدث ${widget.saved.version}؛ حدّث الحساب من شاشته لقراءة أحداث أحدث.'),
      Wrap(spacing: 8, children: [
        OutlinedButton(key: const Key('daily-dates'), onPressed: busy ? null : choose, child: const Text('تغيير الفترة')),
        OutlinedButton(key: const Key('daily-retry'), onPressed: busy ? null : load, child: const Text('إعادة القراءة')),
      ]),
      if (busy) const LinearProgressIndicator(),
      if (error != null) Text(error!, key: const Key('daily-error')),
      if (report != null) ...[
        Text('العائد خلال الفترة: ${percent(report!['performance']['totalReturn'])}', key: const Key('daily-total-return')),
        Text('أقصى تراجع عند العينات اليومية: ${money(report!['performance']['maximumDailyDrawdownCents'])}'),
        Text('Sharpe بالنموذج: ${report!['performance']['sharpe']?.toStringAsFixed(4) ?? 'غير متاح'}', key: const Key('daily-sharpe')),
        const Text('Sharpe يتطلب 20 عائدًا يوميًا متتاليًا مكتملًا وتباينًا غير صفري. النموذج يستخدم 252 جلسة سنويًا وفائدة صفرية؛ لا يثبت ربحية مستقبلية.'),
        if ((report!['points'] as List).isEmpty) const Text('لا توجد جلسات سوق في الفترة المختارة.'),
        for (final p in report!['points'] as List) Card(child: Padding(padding: const EdgeInsets.all(12), child: Column(
          crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text('${p['sessionDate']} • ${p['asOf']}'),
          Text('NAV بالنموذج: ${money(p['liquidationEquityCents'])}', key: Key('daily-equity-${p['sessionDate']}')),
          Text('الربح المحقق: ${money(p['realizedPnlCents'])} • الرسوم: ${money(p['feesCents'])}'),
          if (p['status'] == 'ACCOUNT_NOT_CREATED') const Text('الحساب لم يكن منشأ عند هذه العينة.')
          else if (p['complete'] != true) const Text('تقييم ناقص: عرض مؤهل أو سيولة كافية غير متاحين.'),
        ]))),
      ],
    ])));
}
