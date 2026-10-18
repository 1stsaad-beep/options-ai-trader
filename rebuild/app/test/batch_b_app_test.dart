import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:options_ai_trader_app/services/app_controller.dart';
import 'package:options_ai_trader_app/widgets/market_status_card.dart';
import 'package:trader_core/trader_core.dart';

import 'app_smoke_test.dart' show MemoryRepository;
import 'chart_account_test.dart' show MemorySecrets;

void main() {
  test('AccountLock runs tasks one at a time in call order', () async {
    final lock = AccountLock();
    final log = <String>[];
    var running = 0, maxRunning = 0;
    Future<int> task(String name, int ms) => lock.run(() async {
          running++;
          maxRunning = running > maxRunning ? running : maxRunning;
          log.add('start $name');
          await Future<void>.delayed(Duration(milliseconds: ms));
          log.add('end $name');
          running--;
          return ms;
        });
    final a = task('refresh', 30), b = task('cycle', 5), c = task('refresh2', 1);
    expect(lock.isBusy, isTrue);
    expect(await Future.wait([a, b, c]), [30, 5, 1]);
    expect(maxRunning, 1);
    expect(log, ['start refresh', 'end refresh', 'start cycle', 'end cycle', 'start refresh2', 'end refresh2']);
    expect(lock.isBusy, isFalse);
  });

  test('AccountLock keeps working after a task throws', () async {
    final lock = AccountLock();
    await expectLater(lock.run<void>(() async => throw StateError('x')), throwsStateError);
    expect(await lock.run(() async => 7), 7);
  });

  test('controller market status falls back to the NYSE calendar', () {
    final c = AppController(repo: MemoryRepository(), cycleEvery: const Duration(hours: 1));
    expect(c.marketStatus(now: DateTime.utc(2026, 10, 19, 15)).isOpen, isTrue);
    final hol = c.marketStatus(now: DateTime.utc(2026, 12, 25, 15));
    expect(hol.phase, MarketPhase.closed);
    expect(hol.closedReasonAr, 'عيد الميلاد');
  });

  Future<void> pumpCard(WidgetTester tester, DateTime now) async {
    final c = AppController(repo: MemoryRepository(), cycleEvery: const Duration(hours: 1));
    await tester.pumpWidget(MaterialApp(
        home: Directionality(
            textDirection: TextDirection.rtl,
            child: Scaffold(body: MarketStatusCard(controller: c, clock: () => now)))));
  }

  testWidgets('market card: open with close time in ET', (tester) async {
    await pumpCard(tester, DateTime.utc(2026, 10, 19, 15));
    expect(find.text('السوق الأمريكي: مفتوح'), findsOneWidget);
    expect(find.textContaining('يغلق الاثنين 10-19 16:00 ET'), findsOneWidget);
    expect(find.textContaining('الآن 11:00 ET'), findsOneWidget);
  });

  testWidgets('market card: pre-market, post-market, weekend and early close', (tester) async {
    await pumpCard(tester, DateTime.utc(2026, 10, 19, 12));
    expect(find.text('السوق الأمريكي: قبل الافتتاح'), findsOneWidget);
    expect(find.textContaining('يفتح الاثنين 10-19 09:30 ET'), findsOneWidget);
    await pumpCard(tester, DateTime.utc(2026, 10, 19, 21));
    expect(find.text('السوق الأمريكي: بعد الإغلاق'), findsOneWidget);
    await pumpCard(tester, DateTime.utc(2026, 10, 17, 15));
    expect(find.text('السوق الأمريكي: مغلق'), findsOneWidget);
    expect(find.textContaining('عطلة نهاية الأسبوع'), findsOneWidget);
    expect(find.textContaining('يفتح الاثنين 10-19 09:30 ET'), findsOneWidget);
    await pumpCard(tester, DateTime.utc(2026, 11, 27, 15));
    expect(find.textContaining('إغلاق مبكر 13:00 ET'), findsOneWidget);
    expect(find.textContaining('يغلق الجمعة 11-27 13:00 ET'), findsOneWidget);
  });

  test('concurrent refresh, cycle and chart load share one adapter and all complete', () async {
    final c = AppController(repo: MemoryRepository(), secrets: MemorySecrets(), cycleEvery: const Duration(hours: 1));
    await c.load();
    final p = await c.addAccount(name: 'sim', broker: BrokerKind.simulator, credentials: const {});
    await c.updateProfile(p.copyWith(enabled: true, watchlist: ['AAPL']));
    final results = await Future.wait<Object?>([
      c.refresh(p.id),
      c.chartBars(p.id, 'AAPL', BarTimeframe.m15),
      c.runCycle(p.id),
      c.refresh(p.id),
    ]).timeout(const Duration(seconds: 20));
    expect(results[1], isA<List<Candle>>());
    expect(c.account(p.id)!.broker, isNotNull);
    expect(c.account(p.id)!.lock.isBusy, isFalse);
    c.dispose();
  });
}
