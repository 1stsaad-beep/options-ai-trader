import 'dart:convert';
import 'dart:io';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:options_ai_trader/api.dart';
import 'package:options_ai_trader/observed_server.dart';
import 'package:options_ai_trader/observed_server_daily.dart';

Map<String, dynamic> scenario(String name) => ((jsonDecode(File('test/fixtures/observed_daily_v1.json').readAsStringSync()) as Map)['cases'] as List)
    .singleWhere((c) => c['name'] == name) as Map<String, dynamic>;
Map<String, dynamic> parse(Map<String, dynamic> c) => parseObservedDaily(c['report'],
    ObservedServerAccount.parse(c['snapshot'], 'daily'), c['start'] as String, c['end'] as String, DateTime.parse(c['now'] as String));

void main() {
  for (final name in ['cash', 'complete', 'gap', 'liquidity', 'calendar']) {
    test('actual SQL $name daily report arithmetic and calendar agree', () {
      final c = scenario(name), result = parse(c);
      expect(result, c['report']);
      if (name == 'complete') expect(result['performance']['sharpe'], isNotNull);
      if (name == 'gap' || name == 'liquidity') expect(result['performance']['sharpe'], isNull);
      (result['points'] as List).clear();
      expect(c['report']['points'], isNotEmpty); // Returned data is detached.
    });
  }
  for (final mutation in ['account', 'source', 'anchor', 'range', 'sample', 'close', 'missing-session',
    'duplicate-session', 'future-version', 'hash', 'cash', 'fraction', 'missing-mark', 'drawdown',
    'return', 'total-return', 'sharpe', 'nan', 'rate', 'sessions', 'gap-return', 'order']) {
    test('refuses $mutation report without displaying financial claims', () {
      final c = scenario(mutation == 'gap-return' ? 'gap' : 'complete'), r = c['report'];
      final p = r['points'][0], perf = r['performance'];
      switch (mutation) {
        case 'account': r['account'] = 'other'; break;
        case 'source': r['source'] = 'alpaca'; break;
        case 'anchor': r['throughEventHash'] = '0' * 64; break;
        case 'range': r['start'] = '2026-09-18'; break;
        case 'sample': p['asOf'] = p['sessionClose']; break;
        case 'close': p['sessionClose'] = '2026-09-17T21:00:00Z'; break;
        case 'missing-session': r['points'].removeAt(0); break;
        case 'duplicate-session': r['points'][1] = p; break;
        case 'future-version': p['stateVersion'] = c['snapshot']['version'] + 1; break;
        case 'hash': r['reportHash'] = 'bad'; break;
        case 'cash': p['cashCents'] += 1; break;
        case 'fraction': p['feesCents'] = 0.0; break;
        case 'missing-mark': p['liquidationEquityCents'] = null; break;
        case 'drawdown': perf['maximumDailyDrawdownCents'] += 1; break;
        case 'return': perf['dailyReturns'][1] = 0.1; break;
        case 'total-return': perf['totalReturn'] = 1; break;
        case 'sharpe': perf['sharpe'] = 100; break;
        case 'nan': perf['sharpe'] = double.nan; break;
        case 'rate': perf['annualRiskFreeRate'] = 0.05; break;
        case 'sessions': perf['annualizationSessions'] = 365; break;
        case 'gap-return': perf['sharpe'] = 0; break;
        case 'order': r['newEntryAllowed'] = true; break;
      }
      expect(() => parse(c), throwsFormatException);
    });
  }
  test('range and unsupported future sessions fail closed', () {
    final now = DateTime.utc(2026, 10, 17);
    for (final dates in [['2026-02-30', '2026-03-01'], ['2026-01-01', '2027-01-02'],
      ['2026-10-17', '2026-10-16'], ['2025-12-31', '2026-01-02'], ['2026-10-19', '2026-10-19']]) {
      expect(() => dailySessions(dates[0], dates[1], now), throwsFormatException);
    }
    expect(dailySessions('2026-10-10', '2026-10-11', now), isEmpty);
    final dst = dailySessions('2026-03-06', '2026-03-09', now);
    expect(dst.map((s) => s.closes!.hour).toList(), [21, 20]);
  });
  for (final brightness in Brightness.values) {
    testWidgets('360px RTL $brightness daily GET retry pins range and hides invalid numbers', (tester) async {
      tester.view.physicalSize = const Size(360, 800); tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize); addTearDown(tester.view.resetDevicePixelRatio);
      final c = scenario('gap'); var calls = 0;
      final api = TraderApi(baseUrl: 'https://server.invalid', token: 'fixture-owner', client: MockClient((request) async {
        expect(request.method, 'GET'); expect(request.headers['authorization'], 'Bearer fixture-owner');
        expect(request.url.path, '/api/observed-paper/accounts/daily/daily-performance');
        expect(request.url.queryParameters, {'start': c['start'], 'end': c['end'], 'through': '${c['snapshot']['version']}'});
        calls++;
        if (calls == 1) {
          final bad = scenario('gap')['report']; bad['performance']['sharpe'] = 999;
          return http.Response(jsonEncode(bad), 200);
        }
        return http.Response(jsonEncode(c['report']), 200);
      }));
      addTearDown(api.close);
      await tester.pumpWidget(MaterialApp(theme: ThemeData(brightness: brightness),
        home: ObservedDailyScreen(api: api, saved: ObservedServerAccount.parse(c['snapshot'], 'daily'), now: () => DateTime.utc(2026, 10, 17, 22))));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('daily-error')), findsOneWidget);
      expect(find.byKey(const Key('daily-sharpe')), findsNothing);
      await tester.ensureVisible(find.byKey(const Key('daily-retry')));
      await tester.tap(find.byKey(const Key('daily-retry'))); await tester.pumpAndSettle();
      expect(calls, 2); expect(find.byKey(const Key('daily-error')), findsNothing);
      await tester.scrollUntilVisible(find.byKey(const Key('daily-sharpe')), 250);
      expect(find.text('Sharpe بالنموذج: غير متاح'), findsOneWidget);
      await tester.scrollUntilVisible(find.byKey(const Key('daily-equity-2026-10-13')), 600);
      expect(find.text('NAV بالنموذج: غير متاح'), findsOneWidget);
      expect(tester.takeException(), null);
    });
  }
}
