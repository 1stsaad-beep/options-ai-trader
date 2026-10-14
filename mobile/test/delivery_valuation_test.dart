import 'dart:convert';
import 'dart:io';
import 'package:flutter_test/flutter_test.dart';
import 'package:options_ai_trader/delivery_valuation.dart';
void main() {
  final cases=jsonDecode(File('test/fixtures/delivery_valuation_v1.json').readAsStringSync())['cases'] as List;
  for(final c in cases) {
    test('shared hand expected share mark: ${c['name']}',() {
      final before=jsonEncode(c);
      expect(valueDeliveries(c['deliveries'] as Map,c['observations'] as Map,DateTime.parse(c['now'] as String),c['source'] as String),c['expected']);
      expect(jsonEncode(c),before);
    });
  }
}
