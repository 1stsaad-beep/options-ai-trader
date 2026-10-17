import 'dart:convert';
import 'dart:io';
import 'package:flutter_test/flutter_test.dart';
import 'package:options_ai_trader/option_greeks.dart';

void main() {
  final cases = (jsonDecode(File('test/fixtures/option_greeks_quality_v1.json').readAsStringSync()) as Map)['cases'] as List;
  for (final c in cases) {
    test('shared provider value ${c['name']}', () {
      if (c['valid'] != true) {
        expect(() => providerGreeks(c['raw'], c['right'] as String), throwsFormatException);
      } else {
        final report = providerGreeksQuality(providerGreeks(c['raw'], c['right'] as String));
        expect(report['valuesStatus'], c['status']);
        expect(report['freshnessVerified'], false); expect(report['entryEligible'], false);
        expect(report['reasons'], contains('GREEKS_PROVIDER_TIME_UNAVAILABLE'));
      }
    });
  }
  test('nonfinite sensitivities are not observations', () {
    for (final value in [double.nan, double.infinity, double.negativeInfinity]) {
      expect(() => providerGreeks({'theta': value}, 'C'), throwsFormatException);
    }
  });
}
