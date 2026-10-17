import 'dart:convert';
import 'dart:io';
import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:options_ai_trader/brokers/broker_models.dart';
import 'package:options_ai_trader/brokers/broker_portfolio_screen.dart';
import 'package:options_ai_trader/brokers/broker_store.dart';
import 'package:options_ai_trader/daily_nav.dart';
import 'package:options_ai_trader/market_paper_validation.dart';

// 2026-10-19..23 Mon..Fri; 15:00Z = 11:00 New York (EDT), regular session.
DateTime day(int d, {int hour = 15}) => DateTime.utc(2026, 10, d, hour);

void main() {
  test('metrics match the server (Python) daily report on all shared fixture cases', () {
    final cases = (jsonDecode(File('test/fixtures/observed_daily_v1.json').readAsStringSync()) as Map)['cases'] as List;
    for (final c in cases) {
      final report = c['report'] as Map, p = report['performance'] as Map;
      final values = [for (final point in report['points'] as List) (point as Map)['liquidationEquityCents'] as int?];
      final m = dailyMetrics(values);
      expect(m.status, p['sharpeStatus'], reason: c['name'] as String);
      expect(m.samples, p['returnSamples']);
      expect(m.drawdown, p['maximumDailyDrawdownCents']);
      expect(m.complete, p['complete']);
      for (final (actual, expected) in [(m.sharpe, p['sharpe']), (m.fraction, p['maximumDailyDrawdownFraction']),
          (m.total, p['totalReturn'])]) {
        if (expected == null) {
          expect(actual, isNull);
        } else {
          expect((actual! - (expected as num)).abs(), lessThanOrEqualTo(1e-10 * math.max(1, expected.abs())));
        }
      }
    }
  });

  test('hand-computed reference: drawdown, total return and Sharpe', () {
    // 21 alternating +1 % / -0.5 % days from 100000.
    final values = <int?>[100000];
    for (var i = 0; i < 21; i++) {
      values.add((values.last! * (i.isEven ? 1.01 : 0.995)).round());
    }
    final m = dailyMetrics(values);
    final r = [for (var i = 1; i < values.length; i++) values[i]! / values[i - 1]! - 1];
    final mean = r.reduce((a, b) => a + b) / r.length;
    final sd = math.sqrt(r.map((x) => (x - mean) * (x - mean)).reduce((a, b) => a + b) / (r.length - 1));
    expect(m.status, 'MODELED_DAILY_RETURNS');
    expect((m.sharpe! - mean / sd * math.sqrt(252)).abs(), lessThan(1e-12));
    var peak = values.first!, dd = 0;
    for (final v in values) {
      peak = math.max(peak, v!);
      dd = math.max(dd, peak - v);
    }
    expect(m.drawdown, dd);
    expect(dd, values[19]! - values[20]!); // compounding: the latest peak gives the largest drop
    expect(dailyMetrics([100000, 90000, 95000]).drawdown, 10000);
    expect(dailyMetrics([100000, 90000, 95000]).status, 'INSUFFICIENT_DAILY_RETURNS');
    expect(dailyMetrics([]).status, 'NO_SESSIONS');
    expect(dailyMetrics([100000, null, 100500]).status, 'MISSING_DAILY_VALUATION');
  });

  test('sampling: session only, latest complete value per date, earlier dates frozen', () {
    Map<String, dynamic>? days = updateDailyNav(null, 100000, day(19));
    expect(days!['2026-10-19']['navCents'], 100000);
    expect(updateDailyNav(days, 100000, day(19, hour: 16)), isNull); // unchanged value: no rewrite
    expect(updateDailyNav(days, null, day(19, hour: 16)), isNull); // incomplete valuation never recorded
    expect(updateDailyNav(days, 100500, day(18)), isNull); // Sunday: no session
    expect(updateDailyNav(days, 100500, day(19, hour: 21)), isNull); // after close
    days = updateDailyNav(days, 100700, day(19, hour: 19))!;
    expect([days['2026-10-19']['navCents'], days['2026-10-19']['samples']], [100700, 2]);
    days = updateDailyNav(days, 101000, day(20))!;
    expect(days['2026-10-19']['navCents'], 100700); // frozen
    expect(validDailyNav(days), isTrue);
    expect(validDailyNav({'2026-10-19': {'navCents': 'x'}}), isFalse);
  });

  test('performance: today is provisional; a missing trading day blocks Sharpe', () {
    var days = <String, dynamic>{};
    for (final d in [19, 20, 21]) {
      days = updateDailyNav(days, 100000 + d * 100, day(d))!;
    }
    var p = dailyPerformance(days, day(21, hour: 17));
    expect(p.provisionalDate, '2026-10-21');
    expect(p.dates, ['2026-10-19', '2026-10-20']);
    p = dailyPerformance(days, day(22, hour: 12));
    expect(p.dates.length, 3);
    expect(p.complete, isTrue);
    days.remove('2026-10-20');
    p = dailyPerformance(days, day(22, hour: 12));
    expect([p.dates.length, p.complete, p.sharpeStatus], [3, false, 'MISSING_DAILY_VALUATION']);
    expect(dailyPerformanceText(p, (c) => '$c'), contains('أيام ناقصة'));
  });

  test('Market Paper ledger accepts dailyNav and rejects malformed values', () {
    Map<String, dynamic> book(Object? nav) => {'version': 1, 'journal': [], 'accounts': [{
      'id': 'a', 'name': 'A', 'cash': 100000, 'initialCash': 100000, 'enabled': false, 'addEnabled': false,
      'positions': {}, 'contracts': {}, 'lastSignal': {}, 'quantity': 1, 'riskPercent': 10, 'stopPercent': 20,
      'takePercent': 40, 'trailPercent': 15, 'dailyNav': nav}]};
    expect(() => validatePaper(book(updateDailyNav(null, 100000, day(19)))), returnsNormally);
    expect(() => validatePaper(book({'bad': 1})), throwsFormatException);
  });

  test('Broker Paper store: append-or-update today only, verified write', () async {
    final mem = MemorySecureKeyValue();
    final s = DailyNavStore(mem.read, mem.write, 'oat.brokers.nav.v1.acc');
    await s.sample(100000, day(19));
    await s.sample(null, day(20));
    final days = await s.sample(99000, day(20));
    expect(days.keys, ['2026-10-19', '2026-10-20']);
    mem.data['oat.brokers.nav.v1.acc'] = '{"contract":"other"}';
    await expectLater(s.load(), throwsFormatException);
  });

  testWidgets('broker portfolio refresh records the reported equity once per session date', (tester) async {
    final mem = MemorySecureKeyValue();
    final reg = BrokerAccountRegistry(mem);
    final a = await reg.add(broker: BrokerKind.alpaca, label: 'A', values: {'keyId': 'PKFIXTURE1', 'secretKey': 'fixturesecret1'});
    final client = MockClient((r) async => http.Response(jsonEncode(r.url.path == '/v2/account'
        ? {'account_number': 'PA3FIXTURE', 'currency': 'USD', 'cash': '9876.54', 'equity': '10012.34', 'buying_power': '1', 'status': 'ACTIVE'}
        : []), 200));
    await tester.pumpWidget(MaterialApp(home: BrokerPortfolioScreen(account: a, registry: reg, client: client, clock: () => day(19))));
    for (var i = 0; i < 6; i++) {
      await tester.runAsync(() => Future<void>.delayed(const Duration(milliseconds: 10)));
      await tester.pump(const Duration(milliseconds: 50));
    }
    final stored = jsonDecode(mem.data['oat.brokers.nav.v1.${a.id}']!) as Map;
    expect(stored['days']['2026-10-19']['navCents'], 1001234);
    expect(mem.data['oat.brokers.nav.v1.${a.id}'], isNot(contains('fixturesecret1')));
    await tester.scrollUntilVisible(find.byKey(const ValueKey('broker-daily-nav')), 200);
    expect(find.byKey(const ValueKey('broker-daily-nav')), findsOneWidget);
  });
}
