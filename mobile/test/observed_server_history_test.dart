import 'dart:convert';
import 'dart:io';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:options_ai_trader/api.dart';
import 'package:options_ai_trader/observed_server.dart';
import 'package:options_ai_trader/observed_server_history.dart';

Map<String, dynamic> scenario(String name) => ((jsonDecode(File('test/fixtures/observed_history_v1.json').readAsStringSync()) as Map)['cases'] as List)
  .singleWhere((c) => c['name'] == name) as Map<String, dynamic>;

void main() {
  for (final name in ['complete', 'gap', 'liquidity', 'pages']) {
    test('SQL $name history validates independently across bounded pages', () {
      final c = scenario(name), saved = ObservedServerAccount.parse(c['snapshot'], 'history');
      final cursor = ObservedHistoryCursor(saved);
      for (final page in c['pages'] as List) { expect(cursor.accept(page), page); }
      expect(cursor.after, saved.version);
      expect(cursor.missing > 0, name != 'complete');
    });
  }
  for (final mutation in ['source', 'anchor', 'duplicate', 'future', 'equity', 'fraction', 'drawdown', 'gap', 'cursor', 'order', 'fees', 'prefix']) {
    test('rejects $mutation without advancing cursor', () {
      final c = scenario('gap'), cursor = ObservedHistoryCursor(ObservedServerAccount.parse(c['snapshot'], 'history'));
      final page = c['pages'][0], p = page['points'][3];
      switch (mutation) {
        case 'source': page['source'] = 'alpaca'; break;
        case 'anchor': page['throughEventHash'] = '0' * 64; break;
        case 'duplicate': p['version'] = 2; break;
        case 'future': p['asOf'] = '2026-10-13T16:00:00Z'; break;
        case 'equity': p['liquidationEquityCents'] += 100; break;
        case 'fraction': p['feesCents'] = (p['feesCents'] as int).toDouble(); break;
        case 'drawdown': p['prefix']['maximumSampledDrawdownCents'] = 0; break;
        case 'gap': page['points'][4]['prefix']['maximumSampledDrawdownCents'] = 2520; break;
        case 'cursor': page['nextAfter'] = 0; break;
        case 'order': page['externalOrder'] = true; break;
        case 'fees': page['points'][4]['feesCents'] = 0; break;
        case 'prefix': p['prefix']['eventSamples'] = 4.0; break;
      }
      expect(() => cursor.accept(page), throwsFormatException);
      expect(cursor.after, -1); expect(cursor.missing, 0); expect(cursor.time, null);
      expect(cursor.accept(scenario('gap')['pages'][0])['hasMore'], false);
    });
  }
  test('cannot skip a page or replay a duplicate page', () {
    final c = scenario('pages'), cursor = ObservedHistoryCursor(ObservedServerAccount.parse(c['snapshot'], 'history'));
    expect(() => cursor.accept(c['pages'][1]), throwsFormatException);
    cursor.accept(c['pages'][0]);
    expect(() => cursor.accept(c['pages'][0]), throwsFormatException);
    cursor.accept(c['pages'][1]); expect(cursor.after, c['snapshot']['version']);
  });
  for (final brightness in Brightness.values) {
    testWidgets('360px RTL $brightness GET pagination retains one page and retry cursor', (tester) async {
      tester.view.physicalSize = const Size(360, 800); tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize); addTearDown(tester.view.resetDevicePixelRatio);
      final c = scenario('pages'), calls = <int>[]; var fail = true;
      final api = TraderApi(baseUrl: 'https://server.invalid', token: 'fixture-owner', client: MockClient((request) async {
        expect(request.method, 'GET'); expect(request.headers['authorization'], 'Bearer fixture-owner');
        expect(request.url.path, '/api/observed-paper/accounts/history/valuation-history');
        expect(request.url.queryParameters['through'], '${c['snapshot']['version']}');
        expect(request.url.queryParameters['limit'], '25');
        final after = int.parse(request.url.queryParameters['after']!); calls.add(after);
        if (after == 24 && fail) { fail = false; return http.Response('{}', 503); }
        return http.Response(jsonEncode(c['pages'][after == -1 ? 0 : 1]), 200);
      }));
      addTearDown(api.close);
      await tester.pumpWidget(MaterialApp(theme: ThemeData(brightness: brightness),
        home: ObservedHistoryScreen(api: api, saved: ObservedServerAccount.parse(c['snapshot'], 'history'))));
      await tester.pumpAndSettle(); expect(find.textContaining('بيانات اختبار مصطنعة'), findsOneWidget);
      await tester.scrollUntilVisible(find.byKey(const Key('history-next')), 600);
      await tester.tap(find.byKey(const Key('history-next'))); await tester.pumpAndSettle();
      expect(calls, [-1, 24]);
      expect(find.text('إعادة محاولة القراءة'), findsOneWidget);
      expect(find.byKey(const Key('history-error')), findsOneWidget);
      await tester.tap(find.byKey(const Key('history-next'))); await tester.pumpAndSettle();
      expect(calls, [-1, 24, 24]);
      await tester.drag(find.byType(ListView), const Offset(0, 10000)); await tester.pumpAndSettle();
      expect(find.byKey(const Key('history-equity-0')), findsNothing);
      expect(find.textContaining('نقاط تقييم ناقصة'), findsOneWidget);
      expect(tester.takeException(), null);
    });
  }
}
