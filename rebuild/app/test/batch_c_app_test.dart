import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:options_ai_trader_app/screens/account_detail_screen.dart';
import 'package:options_ai_trader_app/screens/activity_log_screen.dart';
import 'package:options_ai_trader_app/screens/positions_tab.dart';
import 'package:options_ai_trader_app/services/app_controller.dart';
import 'package:options_ai_trader_app/services/background_service.dart';
import 'package:options_ai_trader_app/widgets/safety_widgets.dart';
import 'package:trader_core/trader_core.dart';

import 'app_smoke_test.dart' show MemoryRepository;
import 'chart_account_test.dart' show MemorySecrets;

Widget host(Widget child) => MaterialApp(
    home: Directionality(textDirection: TextDirection.rtl, child: Scaffold(body: child)));

List<CycleRecord> sampleCycles() {
  final t = DateTime.utc(2026, 10, 19, 14, 30);
  return [
    CycleRecord(cycle: 1, start: t)
      ..marketPhase = 'closed'
      ..marketSummaryAr = 'السوق مغلق',
    CycleRecord(cycle: 2, start: t.add(const Duration(minutes: 1)))
      ..marketPhase = 'open'
      ..symbols['AAPL'] = CycleSymbolNote('AAPL', score: 72, bias: 'bullish', action: 'entry', reasonAr: 'اتجاه صاعد قوي')
      ..symbols['MSFT'] = CycleSymbolNote('MSFT', score: 20, bias: 'neutral', action: 'skip', reasonAr: 'النتيجة أقل من الحد')
      ..orders.add('entry شراء 1× AAPL261120C00200000 بحد 3.10\$ (filled)')
      ..fills = 1,
    CycleRecord(cycle: 3, start: t.add(const Duration(minutes: 2)))
      ..marketPhase = 'open'
      ..symbols['MSFT'] = CycleSymbolNote('MSFT', action: 'error', reasonAr: 'timeout')
      ..errors.add('MSFT: timeout'),
  ];
}

void main() {
  late AppController c;
  late NoBackgroundRunner bg;
  late MemoryRepository repo;

  setUp(() {
    repo = MemoryRepository();
    bg = NoBackgroundRunner();
    c = AppController(repo: repo, secrets: MemorySecrets(), background: bg, cycleEvery: const Duration(hours: 1));
  });

  test('kill switch blocks auto and manual cycles, persists, and the notification button sets it', () async {
    await c.load();
    final p = await c.addAccount(name: 'sim', broker: BrokerKind.simulator, credentials: const {});
    await c.updateProfile(p.copyWith(enabled: true, watchlist: ['AAPL']));
    await c.setKillSwitch(true);
    expect(repo.app['killSwitch'], isTrue);
    await c.runAllCycles(force: true);
    final s = await c.runCycle(p.id);
    expect(s!.ran, isFalse);
    expect(s.noteAr, contains('الإيقاف الطارئ'));
    expect(c.account(p.id)!.state.cycle, 0);

    // A fresh controller reads the persisted kill switch.
    final c2 = AppController(repo: repo, secrets: MemorySecrets(), background: NoBackgroundRunner(), cycleEvery: const Duration(hours: 1));
    await c2.load();
    expect(c2.killSwitch, isTrue);
    c2.dispose();

    await c.setKillSwitch(false);
    await c.runAllCycles(force: true);
    expect(c.account(p.id)!.state.cycle, 1);
    expect(c.account(p.id)!.state.cycles.single.symbols.keys, contains('AAPL'));

    bg.send(BackgroundCommand.pauseAll);
    await Future<void>.delayed(Duration.zero);
    expect(c.killSwitch, isTrue);
    c.dispose();
  });

  test('background service: start/stop is user-controlled, persisted, ticks run cycles with a minimum gap', () async {
    await c.load();
    final p = await c.addAccount(name: 'sim', broker: BrokerKind.simulator, credentials: const {});
    await c.updateProfile(p.copyWith(enabled: true, watchlist: ['AAPL']));
    expect(await c.startBackground(), isNull);
    expect(bg.running, isTrue);
    expect(c.backgroundRunning, isTrue);
    expect(repo.app['background'], isTrue);
    bg.send(BackgroundCommand.tick);
    for (var k = 0; k < 50 && c.account(p.id)!.state.cycle == 0; k++) {
      await Future<void>.delayed(const Duration(milliseconds: 20));
    }
    expect(c.account(p.id)!.state.cycle, 1);
    await c.runAllCycles(); // within minCycleGap → skipped
    expect(c.account(p.id)!.state.cycle, 1);
    expect(bg.updates.last, contains('آخر دورة'));
    bg.send(BackgroundCommand.stopService);
    await Future<void>.delayed(const Duration(milliseconds: 10));
    expect(bg.running, isFalse);
    expect(repo.app['background'], isFalse);
    c.dispose();
  });

  test('a wanted background service is restarted on launch', () async {
    repo.app = {'background': true};
    await c.load();
    await Future<void>.delayed(const Duration(milliseconds: 10));
    expect(bg.running, isTrue);
    c.dispose();
  });

  test('activity log filters', () {
    final cs = sampleCycles();
    expect(filterCycles(cs, CycleFilter.all).map((x) => x.cycle), [3, 2, 1]);
    expect(filterCycles(cs, CycleFilter.orders).map((x) => x.cycle), [2]);
    expect(filterCycles(cs, CycleFilter.errors).map((x) => x.cycle), [3]);
    expect(filterCycles(cs, CycleFilter.closed).map((x) => x.cycle), [1]);
    expect(filterCycles(cs, CycleFilter.decisions).map((x) => x.cycle), [2]);
    expect(filterCycles(cs, CycleFilter.all, symbol: 'MSFT').map((x) => x.cycle), [3, 2]);
  });

  testWidgets('activity log screen shows cycles, details and filters', (tester) async {
    final rt = AccountRuntime(
        AccountProfile(id: 'a', name: 'x', broker: BrokerKind.simulator, mode: TradingMode.paper, createdAt: DateTime.utc(2026)),
        AccountState()..cycles.addAll(sampleCycles()));
    await tester.pumpWidget(host(ActivityLogTab(controller: c, rt: rt)));
    expect(find.textContaining('الدورة #3'), findsOneWidget);
    expect(find.textContaining('الدورة #2 — 2026-10-19 10:31 ET'), findsOneWidget);
    await tester.tap(find.byKey(const Key('filter-errors')));
    await tester.pump();
    expect(find.textContaining('الدورة #2'), findsNothing);
    expect(find.textContaining('الدورة #3'), findsOneWidget);
    await tester.tap(find.byKey(const Key('filter-all')));
    await tester.pump();
    await tester.tap(find.byKey(const Key('cycle-2')));
    await tester.pumpAndSettle();
    expect(find.textContaining('AAPL • النتيجة 72.0 • صاعد • القرار: دخول'), findsOneWidget);
    expect(find.text('اتجاه صاعد قوي'), findsOneWidget);
    expect(find.textContaining('AAPL261120C00200000'), findsOneWidget);
  });

  testWidgets('position card: P/L, Greeks, entry reason, invalidation, chart link', (tester) async {
    final contract = OptionContract(underlying: 'AAPL', right: OptionRight.call, expiry: DateTime.utc(2026, 11, 20), strikeCents: 20000);
    final pos = Position(contract: contract, quantity: 2, averageCostCents: 300, openedAt: DateTime.utc(2026, 10, 19, 14));
    final q = OptionQuote(
        contract: contract, bidCents: 340, askCents: 360, time: DateTime.utc(2026, 10, 19, 15),
        delta: 0.52, gamma: 0.031, theta: -0.045, vega: 0.12, impliedVolatility: 0.284);
    final m = PositionMeta(
        occSymbol: contract.occSymbol, entryTime: DateTime.utc(2026, 10, 19, 14), entryPremiumCents: 300,
        initialQuantity: 2, entryScore: 71.5, entryReasonAr: 'اختراق مقاومة', underlyingInvalidation: 195.5, underlyingTarget: 210);
    var opened = false;
    expect(positionPnl(pos, q)!.pnlCents, (350 - 300) * 2 * 100);
    await tester.pumpWidget(host(SingleChildScrollView(
        child: PositionCard(position: pos, quote: q, meta: m, onChart: () => opened = true))));
    expect(find.textContaining('(+16.7%)'), findsOneWidget);
    expect(find.textContaining('Δ دلتا 0.52'), findsOneWidget);
    expect(find.textContaining('IV 28.4%'), findsOneWidget);
    expect(find.text('اختراق مقاومة'), findsOneWidget);
    expect(find.textContaining('مستوى الإبطال للسهم: 195.50'), findsOneWidget);
    await tester.tap(find.text('شارت AAPL'));
    expect(opened, isTrue);
  });

  testWidgets('risk card lists safety limits; kill switch button toggles the banner', (tester) async {
    await tester.runAsync(c.load);
    final rt = AccountRuntime(
        AccountProfile(
            id: 'a', name: 'x', broker: BrokerKind.simulator, mode: TradingMode.paper, createdAt: DateTime.utc(2026),
            settings: const AccountSettings(maxOrdersPerDay: 4, symbolCooldownMinutes: 45, maxOpenPositions: 3)),
        AccountState());
    await tester.pumpWidget(host(ListenableBuilder(
      listenable: c,
      builder: (context, _) => Column(children: [
        KillSwitchButton(controller: c),
        KillSwitchBanner(controller: c),
        RiskSettingsCard(rt: rt, killSwitch: c.killSwitch),
      ]),
    )));
    expect(find.text('0 / 4'), findsOneWidget);
    expect(find.text('45 دقيقة بعد كل دخول/خروج'), findsOneWidget);
    expect(find.text('0 / 3'), findsOneWidget);
    expect(find.text('مقفل في هذه النسخة'), findsOneWidget);
    expect(find.byKey(const Key('kill-switch-banner')), findsNothing);
    await tester.runAsync(() async {
      await tester.tap(find.byKey(const Key('kill-switch')));
      await Future<void>.delayed(const Duration(milliseconds: 20));
    });
    await tester.pump();
    expect(c.killSwitch, isTrue);
    expect(find.byKey(const Key('kill-switch-banner')), findsOneWidget);
    expect(find.text('مفعّل — لا أوامر'), findsOneWidget);
    await tester.tap(find.byKey(const Key('kill-switch-resume')));
    await tester.pumpAndSettle();
    await tester.runAsync(() async {
      await tester.tap(find.widgetWithText(FilledButton, 'استئناف').last);
      await Future<void>.delayed(const Duration(milliseconds: 20));
    });
    await tester.pumpAndSettle();
    expect(c.killSwitch, isFalse);
  });

  testWidgets('account screen has positions and activity-log tabs and the risk card', (tester) async {
    late String id;
    await tester.runAsync(() async {
      await c.load();
      id = (await c.addAccount(name: 'sim', broker: BrokerKind.simulator, credentials: const {})).id;
      await c.refresh(id);
    });
    await tester.pumpWidget(MaterialApp(
        home: Directionality(textDirection: TextDirection.rtl, child: AccountDetailScreen(controller: c, accountId: id))));
    await tester.pump();
    expect(find.byKey(const Key('risk-card')), findsOneWidget);
    await tester.tap(find.text('المراكز'));
    await tester.pumpAndSettle();
    expect(find.text('لا توجد مراكز مفتوحة'), findsOneWidget);
    await tester.tap(find.text('سجل الدورات'));
    await tester.pumpAndSettle();
    expect(find.text('لا توجد دورات مطابقة'), findsOneWidget);
    c.dispose();
  });
}
