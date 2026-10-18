/// Defensive JSON helpers shared by all HTTP adapters. Any unexpected shape
/// becomes BrokerErrorCode.invalidResponse instead of a raw TypeError.
library;

import 'dart:convert';

import 'broker_adapter.dart';

dynamic jDecode(String body) {
  try {
    return jsonDecode(body);
  } on FormatException {
    throw const BrokerException(BrokerErrorCode.invalidResponse, 'Response is not JSON');
  }
}

Map<String, dynamic> jMap(dynamic v) {
  if (v is Map<String, dynamic>) return v;
  if (v is Map) return v.cast<String, dynamic>();
  throw BrokerException(BrokerErrorCode.invalidResponse, 'Expected object, got ${v.runtimeType}');
}

List<dynamic> jList(dynamic v) {
  if (v is List) return v;
  throw BrokerException(BrokerErrorCode.invalidResponse, 'Expected array, got ${v.runtimeType}');
}

double jNum(dynamic v) {
  if (v is num) return v.toDouble();
  if (v is String) {
    final d = double.tryParse(v);
    if (d != null) return d;
  }
  throw BrokerException(BrokerErrorCode.invalidResponse, 'Expected number, got $v');
}

int jCents(dynamic v) => (jNum(v) * 100).round();

String isoDate(DateTime d) =>
    '${d.year.toString().padLeft(4, '0')}-${d.month.toString().padLeft(2, '0')}-${d.day.toString().padLeft(2, '0')}';
