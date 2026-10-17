import 'dart:convert';
import 'package:crypto/crypto.dart';
import 'package:flutter/material.dart';
import 'api.dart';
import 'bounded_json.dart';
import 'observed_server.dart';
import 'paper_time.dart';
import 'option_greeks.dart';

bool _same(dynamic a, dynamic b) {
  if (a is Map && b is Map) {
    return a.length == b.length && a.keys.every((k) => b.containsKey(k) && _same(a[k], b[k]));
  }
  if (a is List && b is List) {
    return a.length == b.length && List.generate(a.length, (i) => i).every((i) => _same(a[i], b[i]));
  }
  return a == b;
}
dynamic _sorted(dynamic v) {
  if (v is Map) {
    final keys = v.keys.cast<String>().toList()..sort();
    return {for (final k in keys) k: _sorted(v[k])};
  }
  if (v is List) return v.map(_sorted).toList();
  return v;
}
String _hash(dynamic value) => sha256.convert(utf8.encode(jsonEncode(_sorted(value)))).toString();
BigInt _decimal(dynamic raw) {
  if (raw is! String || !RegExp(r'^[0-9]{1,12}(\.[0-9]{1,8})?$').hasMatch(raw)) {
    throw const FormatException('Invalid contract decimal');
  }
  final parts = raw.split('.');
  return BigInt.parse(parts.first) * BigInt.from(100000000) + BigInt.parse(parts.length == 1 ? '0' : parts[1].padRight(8, '0'));
}
bool _uuid(dynamic v) => v is String && RegExp(r'^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$').hasMatch(v);
bool _ticker(dynamic v) => v is String && RegExp(r'^[A-Z][A-Z0-9.]{0,9}$').hasMatch(v);

Map<String, dynamic> parseObservedContracts(dynamic raw, ObservedServerAccount saved) {
  final r = observedObject(raw), payload = r['reportPayload'];
  if (payload is! String || !observedHash(r['reportHash']) ||
      sha256.convert(utf8.encode(payload)).toString() != r['reportHash']) {
    throw const FormatException('Contract report hash mismatch');
  }
  final original = decodeBoundedJson(payload, maxBytes: 2 * 1024 * 1024, maxNodes: 100000, maxDepth: 20);
  final body = Map<String, dynamic>.from(r)..remove('reportHash')..remove('reportPayload');
  final at = observationStamp(r['asOf']);
  if (!_same(original, body) || r['contract'] != 'observed-contract-report-v1' ||
      r['account'] != saved.state['id'] || r['source'] != saved.state['source'] ||
      r['version'] != saved.version || r['eventHash'] != saved.eventHash || r['externalOrder'] != false ||
      r['entryEligible'] != false || r['settlementEligible'] != false || r['contracts'] is! List) {
    throw const FormatException('Mismatched contract source or authority');
  }
  final positions = observedObject(saved.state['positions']);
  final owned = positions.values.map((p) => p['contract']).toSet();
  final expected = <dynamic>{...owned};
  for (final choices in observedObject(saved.state['config']['contracts']).values) {
    expected.addAll(observedObject(choices).values);
  }
  final seen = <String>{};
  final hundred = BigInt.from(10000000000);
  for (final item in r['contracts'] as List) {
    final leg = observedObject(item), symbol = leg['symbol'];
    final match = symbol is String ? RegExp(r'^([A-Z][A-Z0-9.]{0,9})(\d{2})(\d{2})(\d{2})([CP])(\d{8})$').firstMatch(symbol) : null;
    if (match == null || !expected.contains(symbol) || !seen.add(symbol as String) ||
        !observedInteger(leg['throughSequence']) || !observedHash(leg['throughHash'])) {
      throw const FormatException('Invalid contract identity');
    }
    final expiry = DateTime.utc(2000 + int.parse(match[2]!), int.parse(match[3]!), int.parse(match[4]!));
    final expiryText = '${2000 + int.parse(match[2]!)}-${match[3]}-${match[4]}';
    if (expiry.toIso8601String().substring(0, 10) != expiryText || int.parse(match[6]!) <= 0) {
      throw const FormatException('Invalid contract expiry');
    }
    Map<String, dynamic>? evidence(String kind) {
      if (leg[kind] == null) return null;
      final e = observedObject(leg[kind]);
      if (!observedInteger(e['sequence'], minimum: 1) || e['sequence'] > leg['throughSequence'] ||
          !observedHash(e['eventHash']) || e['bindings'] is! List ||
          observationStamp(e['capturedAt']).isAfter(at)) {
        throw const FormatException('Invalid evidence origin');
      }
      var bound = false;
      final accounts = <String>{};
      for (final rawBinding in e['bindings'] as List) {
        final b = observedObject(rawBinding);
        if (b['account'] is! String || !accounts.add(b['account'] as String) ||
            !observedInteger(b['version']) || !observedHash(b['eventHash'])) {
          throw const FormatException('Invalid evidence binding');
        }
        if (b['account'] == saved.state['id']) {
          if (b['version'] > saved.version || b['version'] == saved.version && b['eventHash'] != saved.eventHash) {
            throw const FormatException('Mismatched ledger origin');
          }
          bound = true;
        }
      }
      if (!bound || accounts.length > 100 || e['data'] is! Map || e['data']['capturedAt'] != e['capturedAt']) {
        throw const FormatException('Unbound contract evidence');
      }
      return observedObject(e['data']);
    }
    final t = evidence('terms'), g = evidence('greeks');
    Map<String, dynamic>? values;
    if (g != null) {
      if (g['providerTimestamp'] != null || g['freshnessVerified'] != false || g['feed'] != 'opra' || !observedHash(g['rawHash'])) {
        throw const FormatException('Unsupported Greek time');
      }
      values = providerGreeks(g['values'], match[5]!);
      if (!_same(values, g['values'])) throw const FormatException('Invalid Greek fields');
    }
    final status = values == null ? 'MISSING' : greekFields.any((k) => values![k] == null) ? 'PARTIAL' : 'VALUES_ONLY';
    final reasons = <String>[if (status != 'VALUES_ONLY') 'GREEKS_$status', 'GREEKS_PROVIDER_TIME_UNAVAILABLE'];
    var standard = false;
    String? termsHash;
    if (t == null) {
      reasons.add('CONTRACT_TERMS_UNAVAILABLE');
    } else {
      final terms = observedObject(t['terms']);
      if (t['contract'] != 'alpaca-contract-terms-v1' || t['provider'] != 'alpaca' || t['source'] != 'GET_OPTION_CONTRACT' ||
          t['providerEffectiveAt'] != null || !observedHash(t['rawHash']) || _hash(terms) != t['termsHash'] ||
          terms['symbol'] != symbol || terms['root'] != match[1] || terms['expiry'] != expiryText ||
          terms['right'] != match[5] || terms['strikeMillis'] != int.parse(match[6]!) || !observedInteger(terms['strikeMillis'], minimum: 1) ||
          !_ticker(terms['underlying']) || !_uuid(terms['id']) || !_uuid(terms['underlyingAssetId']) ||
          !['active', 'inactive'].contains(terms['status']) || terms['tradable'] is! bool ||
          !['american', 'european'].contains(terms['style']) || terms['deliverables'] is! List ||
          (terms['deliverables'] as List).isEmpty || (terms['deliverables'] as List).length > 16 ||
          _decimal(terms['multiplier']) <= BigInt.zero || _decimal(terms['size']) <= BigInt.zero) {
        throw const FormatException('Invalid contract terms');
      }
      termsHash = t['termsHash'] as String;
      final deliveries = (terms['deliverables'] as List).map(observedObject).toList();
      for (final d in deliveries) {
        if (!['cash', 'equity'].contains(d['type']) || !_ticker(d['symbol']) || d['delayedSettlement'] is! bool ||
            !['T+0', 'T+1', 'T+2', 'T+3', 'T+4', 'T+5'].contains(d['settlementType']) ||
            !['BTOB', 'CADF', 'CAFX', 'CCC'].contains(d['settlementMethod']) ||
            (d['type'] == 'equity' ? !_uuid(d['assetId']) : d['assetId'] != null) ||
            _decimal(d['allocationPercentage']) > hundred || d['amount'] == null && d['delayedSettlement'] != true) {
          throw const FormatException('Invalid deliverable');
        }
        if (d['amount'] != null) _decimal(d['amount']);
      }
      final age = at.difference(observationStamp(t['capturedAt']));
      if (age > const Duration(hours: 24)) {
        reasons.add('CONTRACT_TERMS_STALE_OR_FUTURE');
      } else if (terms['status'] != 'active' || terms['tradable'] != true) {
        reasons.add('CONTRACT_NOT_TRADABLE');
      } else if (!expiry.isAfter(DateTime.utc(at.year, at.month, at.day))) {
        reasons.add('CONTRACT_EXPIRY_CLOSE_ONLY');
      } else if (deliveries.any((d) => d['delayedSettlement'] != false)) {
        reasons.add('CONTRACT_DELIVERY_DELAYED');
      } else {
        final d = deliveries.first;
        standard = terms['root'] == terms['underlying'] && terms['style'] == 'american' &&
            _decimal(terms['multiplier']) == hundred && _decimal(terms['size']) == hundred &&
            (terms['strikeMillis'] as int) % 10 == 0 && deliveries.length == 1 && d['type'] == 'equity' &&
            d['symbol'] == terms['underlying'] && d['assetId'] == terms['underlyingAssetId'] &&
            _decimal(d['amount']) == hundred && _decimal(d['allocationPercentage']) == hundred &&
            d['settlementType'] == 'T+1' && ['BTOB', 'CCC'].contains(d['settlementMethod']);
        if (!standard) reasons.add('ADJUSTED_OR_UNSUPPORTED_CONTRACT');
      }
    }
    if (owned.contains(symbol)) reasons.addAll(['LEGACY_LOT_TERMS_UNVERIFIED', 'LOT_EFFECTIVE_TERMS_UNVERIFIED']);
    final q = {'contract': 'option-eligibility-v1', 'symbol': symbol, 'provider': 'alpaca', 'termsHash': termsHash,
      'standardDeliverableObserved': standard, 'greeksStatus': status, 'greeksProviderTimestamp': null,
      'greeksFreshnessVerified': false, 'entryEligible': false, 'settlementEligible': false, 'externalOrder': false,
      'reasons': reasons};
    if (!_same(q, leg['qualification'])) throw const FormatException('Incorrect contract qualification');
  }
  if (seen.length != expected.length) throw const FormatException('Missing contract evidence');
  return jsonDecode(jsonEncode(r)) as Map<String, dynamic>;
}

class ObservedContractsScreen extends StatefulWidget {
  final TraderApi api;
  final ObservedServerAccount saved;
  const ObservedContractsScreen({super.key, required this.api, required this.saved});
  @override State<ObservedContractsScreen> createState() => _ObservedContractsScreenState();
}
class _ObservedContractsScreenState extends State<ObservedContractsScreen> {
  Map<String, dynamic>? report;
  bool busy = false;
  String? error;
  @override void initState() { super.initState(); load(); }
  Future<void> load() async {
    if (busy) return;
    setState(() { busy = true; error = null; report = null; });
    try {
      final id = Uri.encodeComponent(widget.saved.state['id'] as String);
      final value = parseObservedContracts(await widget.api.request('GET', '/api/observed-paper/accounts/$id/contract-evidence'), widget.saved);
      if (mounted) setState(() => report = value);
    } catch (_) {
      if (mounted) setState(() => error = 'تعذر التحقق من أهلية مطابقة لإصدار الحساب. حدّث حالة الحساب إذا تغيّر إصدارها.');
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }
  @override Widget build(BuildContext context) => Directionality(textDirection: TextDirection.rtl, child: Scaffold(
    appBar: AppBar(title: const Text('أهلية العقود والمُسلَّمات')),
    bottomNavigationBar: SafeArea(child: Padding(padding: const EdgeInsets.all(12), child: Column(mainAxisSize: MainAxisSize.min, children: [
      if (error != null) Text(error!, key: const Key('contract-error'), semanticsLabel: error),
      OutlinedButton(key: const Key('contract-retry'), onPressed: busy ? null : load, child: const Text('إعادة قراءة الأدلة')),
    ]))),
    body: busy ? const Center(child: CircularProgressIndicator()) : ListView(padding: const EdgeInsets.all(16), children: [
      const Text('الدخول والتسوية غير مؤهلين. وجود قيم Greeks أو مُسلَّم قياسي لا يثبت زمن الحساب أو شروط الدفعة التاريخية.'),
      const Text('قراءة أصول محفوظة؛ لا اتصال بمزود أو إرسال أوامر. البصمات ليست توقيعًا من المزود.'),
      if (report != null) ...[
        Text('الحساب ${report!['account']} • الإصدار ${report!['version']}'),
        Text('وقت التقييم: ${report!['asOf']}'),
        if ((report!['contracts'] as List).isEmpty) const Text('لا عقود في إعدادات الحساب أو مراكزه.'),
        for (final leg in report!['contracts'] as List) Card(child: Padding(padding: const EdgeInsets.all(12), child: Column(
          crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(leg['symbol'] as String, key: Key('contract-${leg['symbol']}'), textDirection: TextDirection.ltr),
            Text(leg['qualification']['standardDeliverableObserved'] == true ? 'رُصد مُسلَّم قياسي؛ لا يمنح أهلية' : 'المُسلَّم القياسي غير مؤهل حاليًا'),
            Text('حالة قيم Greeks: ${leg['qualification']['greeksStatus']}'),
            const Text('الوقت المستقل لحساب Greeks: غير متاح'),
            if (leg['terms'] == null) const Text('لم تُحفظ شروط عقد مرتبطة بهذا الحساب') else ...[
              Text('وقت التقاط الشروط: ${leg['terms']['capturedAt']}'),
              Text('المضاعف: ${leg['terms']['data']['terms']['multiplier']}'),
              for (final d in leg['terms']['data']['terms']['deliverables'] as List)
                Text('${d['symbol']} • ${d['amount'] ?? 'غير محدد'} • ${d['settlementType']} • ${d['delayedSettlement'] == true ? 'تسليم مؤجل' : 'غير مؤجل'}'),
            ],
            if (leg['greeks'] != null) Text('وقت استلام قيم Greeks: ${leg['greeks']['capturedAt']}'),
            if (leg['greeks']?['data']?['values'] != null)
              for (final key in greekFields) Text('$key: ${leg['greeks']['data']['values'][key] ?? 'غير متاح'}', textDirection: TextDirection.ltr),
            Text((leg['qualification']['reasons'] as List).join(' • ')),
          ]))),
      ],
    ]),
  ));
}
