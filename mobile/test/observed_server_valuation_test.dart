import 'dart:convert';
import 'dart:io';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:options_ai_trader/api.dart';
import 'package:options_ai_trader/observed_server.dart';
import 'package:options_ai_trader/observed_server_valuation.dart';

List<dynamic> cases() => (jsonDecode(File('test/fixtures/observed_valuation_v1.json').readAsStringSync()) as Map)['cases'] as List;
Map<String, dynamic> scenario(String name) => cases().singleWhere((c) => c['name'] == name) as Map<String, dynamic>;

void main() {
  for (final name in ['cash', 'quoted', 'stale', 'liquidity', 'delivery', 'stopped_partial']) {
    test('actual SQL $name valuation matches independent Dart arithmetic and source', () {
      final c = scenario(name), saved = ObservedServerAccount.parse(c['snapshot'], 'valuation');
      final result = parseObservedValuation(c['valuation'], saved);
      expect(result, c['valuation']);
      expect(result['complete'], ['cash', 'quoted'].contains(name));
      c['valuation']['cashCents'] = 0;
      expect(result['cashCents'], saved.state['cash']);
    });
  }
  for (final field in ['source', 'version', 'eventHash', 'cashCents', 'liquidationEquityCents', 'unrealizedPnlCents', 'complete', 'externalOrder']) {
    test('rejects forged or stale valuation $field', () {
      final c = scenario('quoted');
      c['valuation'][field] = switch (field) {'source' => 'alpaca', 'eventHash' => 'invalid', 'complete' => false, 'externalOrder' => true, _ => 999};
      expect(() => parseObservedValuation(c['valuation'], ObservedServerAccount.parse(c['snapshot'], 'valuation')), throwsFormatException);
    });
  }
  for (final mutation in ['quote', 'capture', 'amount', 'missing', 'duplicate', 'fraction']) {
    test('rejects altered original quote or leg $mutation', () {
      final c = scenario('quoted'), r = c['valuation'], leg = r['options'][0];
      switch (mutation) {
        case 'quote': leg['quote']['bid'] += 1; break;
        case 'capture': leg['capturedAt'] = '2026-10-13T15:01:00Z'; break;
        case 'amount': leg['valueCents'] += 1; break;
        case 'missing': r['options'] = []; break;
        case 'duplicate': r['options'].add(leg); break;
        case 'fraction': leg['quantity'] = (leg['quantity'] as int).toDouble(); break;
      }
      expect(() => parseObservedValuation(r, ObservedServerAccount.parse(c['snapshot'], 'valuation')), throwsFormatException);
    });
  }
  for (final brightness in Brightness.values) {
    testWidgets('360px RTL $brightness incomplete valuation labels missing stock prices', (tester) async {
      tester.view.physicalSize = const Size(360, 800); tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize); addTearDown(tester.view.resetDevicePixelRatio);
      final c = scenario('delivery'), report = parseObservedValuation(c['valuation'], ObservedServerAccount.parse(c['snapshot'], 'valuation'));
      await tester.pumpWidget(MaterialApp(theme: ThemeData(brightness: brightness), home: ObservedValuationScreen(report: report)));
      await tester.pumpAndSettle();
      expect(find.textContaining('بيانات اختبار مصطنعة'), findsOneWidget);
      expect(find.text('قيمة المحفظة بالنموذج: غير متاح'), findsOneWidget);
      await tester.scrollUntilVisible(find.textContaining('أسهم تسليم'), 160);
      expect(find.textContaining('عرض السهم المؤهل غير متاح'), findsOneWidget);
      expect(tester.takeException(), null);
    });
  }
  testWidgets('server valuation action is authenticated GET only and version-bound', (tester) async {
    final c = scenario('cash'), calls = <http.Request>[];
    final api = TraderApi(baseUrl: 'https://server.invalid', token: 'fixture-owner', client: MockClient((request) async {
      calls.add(request); expect(request.method, 'GET'); expect(request.headers['authorization'], 'Bearer fixture-owner');
      final end = request.url.path.split('/').last;
      final response = switch (end) {
        'accounts' => {'mode': 'observed_market_virtual', 'externalOrder': false, 'accounts': ['valuation']},
        'status' => {'mode': 'observed_market_virtual', 'externalOrder': false, 'newMarketEntryAllowed': false,
          'heartbeatFresh': false, 'serverTime': '2026-10-13T15:00:00Z', 'state': 'WORKER_UNAVAILABLE'},
        'state' => c['snapshot'], 'valuation' => c['valuation'], _ => throw StateError('Unexpected request'),
      };
      return http.Response(jsonEncode(response), 200);
    }));
    addTearDown(api.close);
    await tester.pumpWidget(MaterialApp(home: ObservedServerScreen(api: api))); await tester.pumpAndSettle();
    await tester.scrollUntilVisible(find.byKey(const Key('observed-valuation')), 180);
    await tester.tap(find.byKey(const Key('observed-valuation'))); await tester.pumpAndSettle();
    expect(find.byType(ObservedValuationScreen), findsOneWidget);
    expect(calls.length, 4); expect(tester.takeException(), null);
  });
}
