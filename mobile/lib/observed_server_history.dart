import 'dart:convert';
import 'dart:math' as math;
import 'package:flutter/material.dart';
import 'api.dart';
import 'observed_server.dart';
import 'paper_time.dart';

/// Validates authenticated summary arithmetic; it does not attest provider data.
/// Only one page is retained. Failed validation cannot advance this cursor.
class ObservedHistoryCursor {
  final ObservedServerAccount saved;
  int after = -1, missing = 0, peak = 0, drawdown = 0, fees = 0;
  DateTime? time;
  ObservedHistoryCursor(this.saved);
  Map<String, dynamic> accept(dynamic raw, {int limit = 25}) {
    final r = observedObject(raw), points = r['points'];
    if (r['contract'] != 'observed-paper-history-v1' || r['account'] != saved.state['id'] ||
        r['source'] != saved.state['source'] || !observedInteger(r['throughVersion']) || r['throughVersion'] != saved.version ||
        r['throughEventHash'] != saved.eventHash || r['externalOrder'] != false ||
        r['executionAllowed'] != false || r['sampling'] != 'AFTER_RECORDED_EVENT' || r['sharpe'] != null ||
        points is! List || points.length > limit || points.isEmpty && after < saved.version) {
      throw const FormatException('Invalid historical envelope');
    }
    var sequence = after, gaps = missing, high = peak, decline = drawdown, lastFees = fees;
    var previous = time;
    final initial = saved.state['initialCash'] as int;
    for (final rawPoint in points) {
      final p = observedObject(rawPoint), prefix = observedObject(p['prefix']);
      for (final key in ['version', 'cashCents', 'feesCents', 'ownedBasisCents']) {
        if (!observedInteger(p[key])) throw const FormatException('Invalid history integer');
      }
      for (final key in ['realizedPnlCents', 'liquidationEquityCents', 'totalPnlCents', 'unrealizedPnlCents']) {
        if ((key == 'realizedPnlCents' || p[key] != null) && !observedInteger(p[key], minimum: -9007199254740991)) {
          throw const FormatException('Invalid history amount');
        }
      }
      final at = observationStamp(p['asOf']);
      if (p['version'] != ++sequence || sequence > saved.version || !observedHash(p['eventHash']) ||
          sequence == saved.version && p['eventHash'] != saved.eventHash ||
          previous != null && at.isBefore(previous) || p['feesCents'] < lastFees ||
          BigInt.from(p['cashCents'] as int) + BigInt.from(p['ownedBasisCents'] as int) !=
              BigInt.from(initial) + BigInt.from(p['realizedPnlCents'] as int) || p['incompleteReasons'] is! List) {
        throw const FormatException('Noncausal or inconsistent history');
      }
      final reasons = p['incompleteReasons'] as List, equity = p['liquidationEquityCents'];
      if (reasons.toSet().length != reasons.length || reasons.any((x) => ![
        'QUALIFIED_ORIGINAL_QUOTE_UNAVAILABLE', 'INSUFFICIENT_REMAINING_LIQUIDITY',
        'QUALIFIED_STOCK_QUOTE_UNAVAILABLE'].contains(x))) { throw const FormatException('Invalid gap reason'); }
      if (equity == null) {
        if (p['complete'] != false || p['status'] != 'INCOMPLETE' || reasons.isEmpty ||
            p['totalPnlCents'] != null || p['unrealizedPnlCents'] != null) { throw const FormatException('Hidden missing mark'); }
        gaps++;
      } else {
        if (p['complete'] != true || reasons.isNotEmpty || !['CASH_ONLY', 'OBSERVED_MODEL'].contains(p['status']) ||
            p['totalPnlCents'] != equity - initial ||
            p['unrealizedPnlCents'] != equity - p['cashCents'] - p['ownedBasisCents'] ||
            p['status'] == 'CASH_ONLY' && (p['ownedBasisCents'] != 0 || equity != p['cashCents'])) {
          throw const FormatException('Invalid historical valuation');
        }
        if (gaps == 0) { high = math.max(high, equity as int); decline = math.max(decline, high - equity); }
      }
      if (!observedInteger(prefix['eventSamples']) || !observedInteger(prefix['incompleteSamples']) ||
          prefix['maximumSampledDrawdownCents'] != null && !observedInteger(prefix['maximumSampledDrawdownCents']) ||
          prefix['eventSamples'] != sequence + 1 || prefix['incompleteSamples'] != gaps ||
          prefix['complete'] != (gaps == 0) || prefix['maximumSampledDrawdownCents'] != (gaps == 0 ? decline : null)) {
        throw const FormatException('Invalid historical drawdown');
      }
      if (sequence == 0 && (p['status'] != 'CASH_ONLY' || equity != initial || p['feesCents'] != 0)) {
        throw const FormatException('Invalid historical genesis');
      }
      previous = at; lastFees = p['feesCents'] as int;
    }
    if (!observedInteger(r['nextAfter'], minimum: -1) || r['nextAfter'] != sequence || r['hasMore'] != (sequence < saved.version)) throw const FormatException('Invalid next cursor');
    final copy = jsonDecode(jsonEncode(r)) as Map<String, dynamic>;
    after = sequence; missing = gaps; peak = high; drawdown = decline; time = previous; fees = lastFees;
    return copy;
  }
}

class ObservedHistoryScreen extends StatefulWidget {
  final TraderApi api;
  final ObservedServerAccount saved;
  const ObservedHistoryScreen({super.key, required this.api, required this.saved});
  @override State<ObservedHistoryScreen> createState() => _ObservedHistoryScreenState();
}
class _ObservedHistoryScreenState extends State<ObservedHistoryScreen> {
  late ObservedHistoryCursor cursor;
  Map<String, dynamic>? page;
  bool busy = false;
  String? error;
  @override void initState() { super.initState(); cursor = ObservedHistoryCursor(widget.saved); load(); }
  Future<void> load() async {
    if (busy) return;
    setState(() { busy = true; error = null; });
    try {
      final id = Uri.encodeComponent(widget.saved.state['id'] as String);
      final raw = await widget.api.request('GET', '/api/observed-paper/accounts/$id/valuation-history?after=${cursor.after}&limit=25&through=${widget.saved.version}');
      final result = cursor.accept(raw);
      if (mounted) setState(() => page = result);
    } catch (_) {
      if (mounted) setState(() => error = 'تعذر التحقق من صفحة التاريخ. أعد المحاولة؛ لم يتقدم مؤشر القراءة.');
    } finally { if (mounted) setState(() => busy = false); }
  }
  String money(dynamic value) => value == null ? 'غير متاح' : '${(value / 100).toStringAsFixed(2)} USD';
  @override Widget build(BuildContext context) => Directionality(textDirection: TextDirection.rtl,
    child: Scaffold(appBar: AppBar(title: const Text('تاريخ قيمة المحفظة')),
      bottomNavigationBar: page == null || page!['hasMore'] == true || error != null ? SafeArea(
        child: Padding(padding: const EdgeInsets.all(12), child: Column(mainAxisSize: MainAxisSize.min, children: [
          if (error != null) Text(error!, key: const Key('history-error')),
          OutlinedButton(key: const Key('history-next'), onPressed: busy ? null : load,
            child: Text(error != null ? 'إعادة محاولة القراءة' : 'الصفحة التالية')),
        ]))) : null, body: ListView(padding: const EdgeInsets.all(16), children: [
      Text(widget.saved.state['source'] == 'fixture' ? 'بيانات اختبار مصطنعة • ليست رصد سوق' : 'ملخص أحداث Alpaca المحفوظة على الخادم'),
      const Text('تقييم بعد الأحداث المسجلة فقط. لا أسعار بين الأحداث ولا ملء للفجوات. التراجع أدناه ليس تراجعًا يوميًا أو ضمان تنفيذ. Sharpe غير متاح.'),
      Text('قراءة مثبتة عند الحدث ${widget.saved.version}؛ لمراجعة أحداث أحدث ارجع وحدّث الحساب.'),
      if (busy) const LinearProgressIndicator(),
      if (page != null) ...[
        Text('التراجع عند الأحداث منذ البداية: ${money((page!['points'] as List).lastOrNull?['prefix']['maximumSampledDrawdownCents'])}'),
        if (cursor.missing > 0) Text('نقاط تقييم ناقصة منذ البداية: ${cursor.missing}؛ لا يُعرض تراجع كامل من تاريخ ناقص.'),
        for (final p in page!['points'] as List) Card(child: Padding(padding: const EdgeInsets.all(12), child: Column(
          crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text('#${p['version']} • ${p['asOf']}'),
            Text('قيمة المحفظة: ${money(p['liquidationEquityCents'])}', key: Key('history-equity-${p['version']}')),
            Text('الربح المحقق: ${money(p['realizedPnlCents'])} • الرسوم: ${money(p['feesCents'])}'),
            if (p['complete'] != true) const Text('عرض مؤهل أو سيولة كافية غير متاحين؛ لم تُفترض قيمة للمركز.'),
          ]))),
      ],
    ])));
}
