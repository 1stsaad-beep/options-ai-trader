import 'dart:convert';
import 'package:crypto/crypto.dart';
import 'package:flutter/material.dart';
import 'observed_server.dart';
import 'observed_option_replay.dart';
import 'paper_execution.dart';

Map<String, dynamic> parseObservedValuation(dynamic raw, ObservedServerAccount saved) {
  final r = observedObject(raw), state = saved.state;
  void integers(Map value, List<String> keys) {
    for (final key in keys) {
      if (value[key] != null && !observedInteger(value[key], minimum: -9007199254740991)) {
        throw const FormatException('Noninteger valuation amount');
      }
    }
  }
  integers(r, ['version', 'cashCents', 'ownedBasisCents', 'liquidationEquityCents', 'unrealizedPnlCents', 'totalPnlCents']);
  final at = observationStamp(r['asOf']);
  if (r['contract'] != 'observed-paper-valuation-v1' || r['account'] != state['id'] || r['source'] != state['source'] ||
      r['version'] != saved.version || r['eventHash'] != saved.eventHash || r['externalOrder'] != false ||
      r['executionAllowed'] != false || r['newEntryAllowed'] != false || r['cashCents'] != state['cash'] ||
      r['options'] is! List || r['deliveries'] is! List ||
      (state['lastAt'] != null && at.isBefore(observationStamp(state['lastAt'])))) {
    throw const FormatException('Mismatched valuation');
  }
  final positions = observedObject(state['positions']), deliveries = observedObject(state['deliveries']);
  final seen = <String>{};
  var basis = 0, amount = 0, complete = true;
  if ((r['options'] as List).length != positions.length || (r['deliveries'] as List).length != deliveries.length) {
    throw const FormatException('Missing valuation leg');
  }
  for (final item in r['options'] as List) {
    final leg = observedObject(item), symbol = leg['symbol'], p = positions[symbol];
    integers(leg, ['quantity', 'basisCents', 'valueCents', 'unrealizedPnlCents', 'modeledExitFeeCents', 'modeledAvailableQuantity']);
    if (symbol is! String || !seen.add(symbol) || p is! Map || leg['contract'] != p['contract'] ||
        leg['quantity'] != p['quantity'] || leg['basisCents'] != p['cost']) {
      throw const FormatException('Mismatched owned option');
    }
    basis += p['cost'] as int;
    int? value, fee;
    var quantity = 0;
    if (leg['quote'] != null) {
      final q = observedObject(leg['quote']);
      final origin = {'account': state['id'], 'source': state['source'], 'capturedAt': leg['capturedAt'], 'quote': q};
      final observed = readOptionObservation(origin);
      readOptionObservation({...origin, 'capturedAt': r['asOf']});
      final keys = q.keys.toList()..sort();
      final hash = sha256.convert(utf8.encode(jsonEncode({for (final k in keys) k: q[k]}))).toString();
      final prior = observedObject(state['consumption'])[p['contract']];
      final newerFill = prior is Map && observationStamp(prior['at']).isAfter(observationStamp(p['markAt']));
      final expectedAt = newerFill ? prior['at'] : p['markAt'], expectedHash = newerFill ? prior['identity'] : p['markIdentity'];
      if (q['contract'] != p['contract'] || q['at'] != expectedAt || hash != expectedHash || observed.captured.isAfter(at)) {
        throw const FormatException('Quote differs from accepted original');
      }
      final consumed = prior is Map && prior['at'] == q['at'] && prior['identity'] == hash ? prior['quantity'] : 0;
      if (!observedInteger(consumed)) throw const FormatException('Invalid consumption');
      final model = projectOptionExecution(q, 'SELL_TO_CLOSE', p['quantity'] as int, consumed as int, at);
      quantity = model['quantity'] as int;
      if (quantity == p['quantity'] && model['cashDeltaCents'] != null) {
        value = model['cashDeltaCents'] as int; fee = model['feeCents'] as int;
      }
    } else if (leg['capturedAt'] != null) {
      throw const FormatException('Capture without quote');
    }
    final status = value != null ? 'OBSERVED_MODEL' : leg['quote'] == null ? 'QUALIFIED_ORIGINAL_QUOTE_UNAVAILABLE' : 'INSUFFICIENT_REMAINING_LIQUIDITY';
    if (leg['status'] != status || leg['valueCents'] != value || leg['modeledExitFeeCents'] != fee ||
        leg['modeledAvailableQuantity'] != quantity || leg['unrealizedPnlCents'] != (value == null ? null : value - (p['cost'] as int))) {
      throw const FormatException('Incorrect liquidation arithmetic');
    }
    if (value == null) { complete = false; } else { amount += value; }
  }
  seen.clear();
  for (final item in r['deliveries'] as List) {
    final leg = observedObject(item), symbol = leg['symbol'], p = deliveries[symbol];
    integers(leg, ['quantity', 'basisCents', 'valueCents']);
    if (symbol is! String || !seen.add(symbol) || p is! Map || leg['quantity'] != p['quantity'] ||
        leg['basisCents'] != p['cost'] || leg['status'] != 'QUALIFIED_STOCK_QUOTE_UNAVAILABLE' || leg['valueCents'] != null) {
      throw const FormatException('Unqualified delivery valuation');
    }
    basis += p['cost'] as int; complete = false;
  }
  final equity = complete ? (state['cash'] as int) + amount : null;
  final status = complete ? (positions.isEmpty ? 'CASH_ONLY' : 'OBSERVED_MODEL') : 'INCOMPLETE';
  if (!observedInteger(basis) || !observedInteger(amount) || (equity != null && !observedInteger(equity)) ||
      r['complete'] != complete || r['status'] != status || r['ownedBasisCents'] != basis ||
      r['liquidationEquityCents'] != equity || r['unrealizedPnlCents'] != (complete ? amount - basis : null) ||
      r['totalPnlCents'] != (equity == null ? null : equity - (state['initialCash'] as int))) {
    throw const FormatException('Incomplete or inconsistent portfolio value');
  }
  return jsonDecode(jsonEncode(r)) as Map<String, dynamic>;
}

class ObservedValuationScreen extends StatelessWidget {
  final Map<String, dynamic> report;
  const ObservedValuationScreen({super.key, required this.report});
  String money(dynamic cents) => cents == null ? 'غير متاح' : '${(cents / 100).toStringAsFixed(2)} USD';
  @override Widget build(BuildContext context) => Directionality(textDirection: TextDirection.rtl,
    child: Scaffold(appBar: AppBar(title: const Text('تقييم العروض المحفوظة')), body: ListView(padding: const EdgeInsets.all(16), children: [
      Text(report['source'] == 'fixture' ? 'بيانات اختبار مصطنعة • ليست رصد سوق' : 'مصدر Alpaca محفوظ • قراءة فقط'),
      Text('وقت التقييم: ${report['asOf']}'),
      const Text('تقدير صافي التصفية بعد الانزلاق والرسوم وبحد السيولة المتبقية. لا يرسل أمرًا أو يضمن التعبئة أو يمنح أهلية دخول.'),
      Text('النقد: ${money(report['cashCents'])}'),
      Text('قيمة المحفظة بالنموذج: ${money(report['liquidationEquityCents'])}', key: const Key('observed-valuation-equity')),
      Text('الربح غير المحقق: ${money(report['unrealizedPnlCents'])}'),
      Text('الربح الكلي بالنموذج: ${money(report['totalPnlCents'])}'),
      if (report['complete'] != true) const Text('التقييم غير مكتمل؛ لا تُستبدل البيانات الناقصة بصفر أو بسعر السهم أو بأساس التكلفة.'),
      for (final leg in report['options'] as List) Card(child: Padding(padding: const EdgeInsets.all(12), child: Column(
        crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text('${leg['contract']} • ${leg['quantity']} عقود', textDirection: TextDirection.ltr),
          Text('صافي القيمة: ${money(leg['valueCents'])}'),
          Text(leg['status'] == 'OBSERVED_MODEL' ? 'عرض خيار أصلي صالح وقت التقييم' :
            leg['status'] == 'INSUFFICIENT_REMAINING_LIQUIDITY' ? 'السيولة المتبقية لا تكفي للحجم كله' : 'العرض الأصلي المؤهل غير متاح أو قديم'),
        ]))),
      for (final leg in report['deliveries'] as List) Text('${leg['symbol']} • ${leg['quantity']} أسهم تسليم: عرض السهم المؤهل غير متاح'),
      const Text('هذا التقييم في لحظة واحدة لا يثبت تراجع المحفظة التاريخي أو Sharpe أو قبول ثلاث جلسات.'),
    ])));
}
