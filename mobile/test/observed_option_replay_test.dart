import 'dart:convert';
import 'dart:io';
import 'package:flutter_test/flutter_test.dart';
import 'package:options_ai_trader/observed_option_replay.dart';

void main() {
  final cases=(jsonDecode(File('test/fixtures/observed_option_replay_v1.json').readAsStringSync()) as Map)['cases'] as List;
  for(final c in cases) {
    test(c['name'] as String,() {
      final query=c['query'] as Map<String,dynamic>,original=jsonEncode(query);
      expect(replayObservedOption(query),c['expected']);expect(jsonEncode(query),original);
    });
  }
  test('future extension never rewrites known horizon',() {
    final query=jsonDecode(jsonEncode(cases.first['query'])) as Map<String,dynamic>;
    final original=replayObservedOption(query);
    final later=jsonDecode(jsonEncode(query['observations'][0])) as Map<String,dynamic>;
    later['capturedAt']=later['quote']['at']='2026-10-13T15:07:00.000Z';
    later['quote']['bid']=1000;later['quote']['ask']=1100;
    (query['observations'] as List).add(later);expect(replayObservedOption(query),original);
  });
  test('explicit nulls cannot silently pick default costs',() {
    for(final field in ['horizonSeconds','slippageCents','feePerContractCents']) {
      final query=jsonDecode(jsonEncode(cases.first['query'])) as Map<String,dynamic>;
      query[field]=null;expect(replayObservedOption(query)['status'],'INVALID_QUERY');
    }
  });
}
