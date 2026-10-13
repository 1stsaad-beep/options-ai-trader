import 'dart:convert';
import 'direct_alpaca.dart';

Map<String, dynamic> copyPaper(Map<String, dynamic> value) =>
    jsonDecode(jsonEncode(value)) as Map<String, dynamic>;

/// Stable comparison across JSON encoders with different map insertion order.
String paperBytes(Object? value) {
  Object? normalize(Object? item) {
    if (item is Map) {
      final keys = item.keys.cast<String>().toList()..sort();
      return {for (final key in keys) key: normalize(item[key])};
    }
    if (item is List) return item.map(normalize).toList();
    return item;
  }
  return jsonEncode(normalize(value));
}

void validatePaper(Map<String, dynamic> book) {
  Never invalid() => throw const FormatException('Invalid Market Paper ledger');
  bool integer(Object? value, int minimum, int maximum) =>
      value is int && value >= minimum && value <= maximum;
  bool text(Object? value) => value is String && value.trim().isNotEmpty;
  bool timestamp(Object? value) => value is String &&
      (value.endsWith('Z') || RegExp(r'[+-]\d\d:\d\d$').hasMatch(value)) &&
      DateTime.tryParse(value) != null;
  final symbol = RegExp(r'^[A-Z][A-Z0-9.]{0,9}$');
  const maxMoney = 9007199254740991;
  if (book['version'] != 1 || book['accounts'] is! List || book['journal'] is! List) invalid();
  final ids = <String>{};
  for (final raw in book['accounts'] as List) {
    if (raw is! Map) invalid();
    final a = raw;
    if (!text(a['id']) || !ids.add(a['id'] as String) || !text(a['name']) ||
        !integer(a['cash'], 0, maxMoney) || !integer(a['initialCash'], 1, maxMoney) ||
        a['enabled'] is! bool || a['addEnabled'] is! bool ||
        a['positions'] is! Map || a['contracts'] is! Map || a['lastSignal'] is! Map ||
        !integer(a['quantity'], 1, 10)) {
      invalid();
    }
    for (final field in ['riskPercent', 'stopPercent', 'takePercent', 'trailPercent']) {
      if (!integer(a[field], 1, 50)) invalid();
    }
    for (final entry in (a['contracts'] as Map).entries) {
      if (entry.key is! String || entry.value is! String) invalid();
      final match = OptionQuote.pattern.firstMatch(entry.value as String);
      if (match == null) invalid();
      final direction = match[5] == 'C' ? 'CALL' : 'PUT';
      if (entry.key != '${match[1]}:$direction') invalid();
      final expiry = DateTime.utc(2000 + int.parse(match[2]!), int.parse(match[3]!), int.parse(match[4]!));
      if (expiry.month != int.parse(match[3]!) || expiry.day != int.parse(match[4]!) || int.parse(match[6]!) <= 0) invalid();
    }
    for (final entry in (a['lastSignal'] as Map).entries) {
      if (entry.key is! String || !symbol.hasMatch(entry.key as String) || !text(entry.value)) invalid();
    }
    for (final entry in (a['positions'] as Map).entries) {
      if (entry.key is! String || !symbol.hasMatch(entry.key as String) || entry.value is! Map) invalid();
      final p = entry.value as Map;
      if (p['contract'] is! String) invalid();
      final match = OptionQuote.pattern.firstMatch(p['contract'] as String);
      if (match == null || match[1] != entry.key ||
          p['direction'] != (match[5] == 'C' ? 'CALL' : 'PUT') ||
          !integer(p['quantity'], 1, 1000000) || !integer(p['cost'], 1, maxMoney) ||
          !integer(p['highBid'], 1, maxMoney) || p['added'] is! bool || !timestamp(p['opened'])) {
        invalid();
      }
    }
  }
  for (final raw in book['journal'] as List) {
    if (raw is! Map || !ids.contains(raw['account']) ||
        raw['symbol'] is! String || !symbol.hasMatch(raw['symbol'] as String) ||
        !text(raw['decision']) || !timestamp(raw['at'])) {
      invalid();
    }
    if (raw.containsKey('quote')) {
      final q = raw['quote'];
      if (q is! Map || q['contract'] is! String ||
          OptionQuote.pattern.firstMatch(q['contract'] as String)?.group(1) != raw['symbol'] ||
          q['feed'] != 'opra' || !timestamp(q['at']) ||
          !integer(q['bid'], 1, maxMoney) || !integer(q['ask'], 1, maxMoney) || q['ask'] < q['bid']) {
        invalid();
      }
    }
  }
}
