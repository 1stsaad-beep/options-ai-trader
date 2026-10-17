import 'dart:convert';
import 'package:crypto/crypto.dart';
import 'package:flutter/material.dart';
import 'api.dart';
import 'observed_server.dart';
import 'observed_server_status.dart';
import 'paper_time.dart';

const alertZeroHash = '0000000000000000000000000000000000000000000000000000000000000000';

void alertAuthority(Map<String, dynamic> value) {
  if (value['contractVersion'] != 'observed-alert-inbox-v1' || value['mode'] != 'observed_market_virtual' ||
      value['externalOrder'] != false || value['executionAllowed'] != false ||
      value['delivery'] != 'OWNER_POLL_AT_LEAST_ONCE' || value['scope'] != 'WORKER_OBSERVATIONS_NOT_EXTERNAL_PUSH') {
    throw const FormatException('Invalid alert authority');
  }
}
Map<String, dynamic> alertAck(dynamic raw) {
  final ack = observedObject(raw);
  if (!observedInteger(ack['sequence']) || !observedHash(ack['eventHash']) ||
      (ack['sequence'] == 0) != (ack['eventHash'] == alertZeroHash)) {
    throw const FormatException('Invalid acknowledgement');
  }
  return ack;
}

/// One immutable page at a time. GET validation never acknowledges an event.
class ObservedAlertCursor {
  int? after, through;
  String? afterHash, throughHash;
  Map<String, dynamic> acknowledged = {'sequence': 0, 'eventHash': alertZeroHash};
  List<String>? active;

  Map<String, dynamic> accept(dynamic raw, {int limit = 25}) {
    final value = observedObject(raw); alertAuthority(value);
    final ack = alertAck(value['acknowledged']), events = value['events'];
    for (final key in ['after', 'through', 'nextAfter']) {
      if (!observedInteger(value[key])) throw const FormatException('Invalid alert range');
    }
    if (!observedHash(value['afterHash']) || !observedHash(value['throughHash']) ||
        value['after'] > value['through'] || ack['sequence'] > value['through'] || ack['sequence'] < acknowledged['sequence'] ||
        events is! List || events.length > limit ||
        after == null && (value['after'] != ack['sequence'] || value['afterHash'] != ack['eventHash']) ||
        after != null && (value['after'] != after || value['afterHash'] != afterHash ||
          value['through'] != through || value['throughHash'] != throughHash) ||
        (value['through'] == 0) != (value['throughHash'] == alertZeroHash)) {
      throw const FormatException('Inconsistent alert page');
    }
    var sequence = value['after'] as int, previous = value['afterHash'] as String;
    var previousActive = active;
    for (final rawEvent in events) {
      final event = observedObject(rawEvent);
      if (event.length != 7 || !observedInteger(event['sequence'], minimum: 1) ||
          event['sequence'] != ++sequence || sequence > value['through'] ||
          event['previousHash'] != previous || !observedHash(event['eventHash'])) {
        throw const FormatException('Invalid alert chain');
      }
      observationStamp(event['detectedAt']); // Sequence, not wall time, orders clock regressions.
      final lists = <String, List<String>>{};
      for (final key in ['active', 'raised', 'resolved']) {
        final codes = event[key];
        if (codes is! List || codes.length > observedAlertLabels.length ||
            codes.any((c) => c is! String || !observedAlertLabels.containsKey(c))) {
          throw const FormatException('Unknown alert code');
        }
        final sorted = codes.cast<String>().toSet().toList()..sort();
        if (jsonEncode(sorted) != jsonEncode(codes)) throw const FormatException('Unordered alert codes');
        lists[key] = sorted;
      }
      final current = lists['active']!, raised = lists['raised']!, resolved = lists['resolved']!;
      final prior = previousActive ?? [...current.where((c) => !raised.contains(c)), ...resolved];
      final expectedRaised = current.where((c) => !prior.contains(c)).toList()..sort();
      final expectedResolved = prior.where((c) => !current.contains(c)).toList()..sort();
      if (jsonEncode(raised) != jsonEncode(expectedRaised) || jsonEncode(resolved) != jsonEncode(expectedResolved) ||
          sequence == 1 && (resolved.isNotEmpty || jsonEncode(raised) != jsonEncode(current))) {
        throw const FormatException('Inconsistent alert transition');
      }
      final keys = ['active', 'detectedAt', 'previousHash', 'raised', 'resolved', 'sequence'];
      final hash = sha256.convert(utf8.encode(jsonEncode({for (final k in keys) k: event[k]}))).toString();
      if (hash != event['eventHash']) throw const FormatException('Corrupt alert event');
      previous = hash; previousActive = current;
    }
    final expectedEnd = (value['after'] as int) + limit < value['through'] ? value['after'] + limit : value['through'];
    if (sequence != expectedEnd || value['nextAfter'] != sequence || value['hasMore'] != (sequence < value['through']) ||
        sequence == value['through'] && previous != value['throughHash']) {
      throw const FormatException('Incomplete alert page');
    }
    final copy = jsonDecode(jsonEncode(value)) as Map<String, dynamic>;
    after = sequence; afterHash = previous; through = value['through'] as int; throughHash = value['throughHash'] as String;
    acknowledged = ack; active = previousActive;
    return copy;
  }

  Map<String, dynamic> acknowledgementRequest() {
    if (after == null || after == 0 || after! <= acknowledged['sequence']) throw const FormatException('No unread page');
    return {'sequence': after, 'event_hash': afterHash, 'expected_ack': acknowledged['sequence']};
  }
  void acceptAcknowledgement(dynamic raw, Map<String, dynamic> request) {
    final value = observedObject(raw); alertAuthority(value);
    final ack = alertAck(value['acknowledged']);
    if (ack['sequence'] != request['sequence'] || ack['eventHash'] != request['event_hash']) {
      throw const FormatException('Concurrent acknowledgement; reload inbox');
    }
    acknowledged = ack;
  }
}

class ObservedAlertsScreen extends StatefulWidget {
  final TraderApi api;
  const ObservedAlertsScreen({super.key, required this.api});
  @override State<ObservedAlertsScreen> createState() => _ObservedAlertsScreenState();
}
class _ObservedAlertsScreenState extends State<ObservedAlertsScreen> {
  ObservedAlertCursor cursor = ObservedAlertCursor();
  Map<String, dynamic>? page, pendingAck;
  bool busy = false;
  String? error;
  @override void initState() { super.initState(); load(); }
  Future<void> load({bool restart = false}) async {
    if (busy) return;
    setState(() { busy = true; error = null; });
    final candidate = restart ? ObservedAlertCursor() : cursor;
    try {
      final query = candidate.after == null ? 'limit=25' : 'limit=25&after=${candidate.after}&through=${candidate.through}';
      final result = candidate.accept(await widget.api.request('GET', '/api/observed-paper/alerts?$query'));
      if (mounted) setState(() { cursor = candidate; page = result; pendingAck = null; });
    } catch (_) {
      if (mounted) setState(() => error = 'تعذر التحقق من صفحة التنبيهات. لم يُرسل إقرار قراءة.');
    } finally { if (mounted) setState(() => busy = false); }
  }
  Future<void> acknowledge() async {
    if (busy) return;
    setState(() { busy = true; error = null; });
    try {
      pendingAck ??= cursor.acknowledgementRequest();
      final response = await widget.api.request('POST', '/api/observed-paper/alerts/ack', pendingAck);
      cursor.acceptAcknowledgement(response, pendingAck!);
      if (mounted) setState(() => pendingAck = null);
    } catch (_) {
      if (mounted) setState(() => error = 'لم يتأكد إقرار القراءة. يمكنك إعادة نفس الإقرار أو تحديث الصندوق؛ لا يتغير العطل بإقرار القراءة.');
    } finally { if (mounted) setState(() => busy = false); }
  }
  @override Widget build(BuildContext context) {
    final unread = cursor.after != null && cursor.after! > cursor.acknowledged['sequence'];
    return Directionality(textDirection: TextDirection.rtl, child: Scaffold(
      appBar: AppBar(title: const Text('سجل تنبيهات الخادم'), actions: [IconButton(key: const Key('alerts-refresh'),
        onPressed: busy ? null : () => load(restart: true), icon: const Icon(Icons.refresh))]),
      bottomNavigationBar: SafeArea(child: Padding(padding: const EdgeInsets.all(12), child: Column(mainAxisSize: MainAxisSize.min, children: [
        if (error != null) Text(error!, key: const Key('alerts-error')),
        if (unread) OutlinedButton(key: const Key('alerts-ack'), onPressed: busy ? null : acknowledge,
          child: Text(pendingAck == null ? 'اطلعت على التنبيهات حتى #${cursor.after}' : 'إعادة نفس إقرار القراءة')),
        if (!unread && (page == null || page!['hasMore'] == true)) OutlinedButton(key: const Key('alerts-next'),
          onPressed: busy ? null : () => load(), child: const Text('قراءة الصفحة التالية')),
      ]))), body: ListView(padding: const EdgeInsets.all(16), children: [
        const Text('سجل تشغيل عام للخادم، منفصل عن أرصدة الحسابات. قراءة يدوية وإقرار مشترك للمالك؛ لا توجد خدمة دفع خارجية.'),
        const Text('الوقت هو وقت اكتشاف الحالة. عند توقف العامل المفاجئ يُسجل الانقطاع بعد استئنافه. راجع نبض العامل الحالي أيضًا.'),
        const Text('إقرار القراءة لا يعني حل العطل ولا يفتح التداول.'),
        if (busy) const LinearProgressIndicator(),
        if (page != null && (page!['events'] as List).isEmpty) const Text('لا توجد تنبيهات غير مقروءة في هذه القراءة.'),
        if (page != null) for (final event in page!['events'] as List) Card(key: Key('alert-event-${event['sequence']}'),
          child: Padding(padding: const EdgeInsets.all(12), child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text('#${event['sequence']} • ${event['detectedAt']}'),
            for (final code in event['raised'] as List) Text('ظهر: ${observedAlertLabels[code]}'),
            for (final code in event['resolved'] as List) Text('انتهى في هذه الرصدة: ${observedAlertLabels[code]}'),
            if ((event['active'] as List).isEmpty) const Text('لا عطل مسجل في هذه الرصدة؛ ليست شهادة استمرار التشغيل.'),
          ]))),
      ])));
  }
}
