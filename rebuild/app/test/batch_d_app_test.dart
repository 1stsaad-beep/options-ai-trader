import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:options_ai_trader_app/screens/activity_log_screen.dart';
import 'package:options_ai_trader_app/screens/live_mode_screen.dart';
import 'package:options_ai_trader_app/screens/reports_tab.dart';
import 'package:options_ai_trader_app/screens/settings_screen.dart';
import 'package:options_ai_trader_app/services/app_controller.dart';
import 'package:options_ai_trader_app/services/background_service.dart';
import 'package:options_ai_trader_app/services/notifier.dart';
import 'package:options_ai_trader_app/services/report_exporter.dart';
import 'package:trader_core/trader_core.dart';

import 'app_smoke_test.dart' show MemoryRepository;
import 'chart_account_test.dart' show MemorySecrets;

Widget host(Widget child) => MaterialApp(home: Directionality(textDirection: TextDirection.rtl, child: Scaffold(body: child)));

EngineSignal _sig(EngineId id) =>
    EngineSignal(engine: id, bias: Bias.bullish, strength: 1, pattern: 'TEST', reasonAr: 'إشارة اختبار', knownAtIndex: 0);

TradeRecord trade(DateTime exit, int entry, int exitP, List<String> engines) => TradeRecord(
    occSymbol: 'AAPL261120C00200000', underlying: 'AAPL', right: OptionRight.call,
    entryTime: exit.subtract(const Duration(hours: 1)), exitTime: exit, quantity: 1,
    entryPremiumCents: entry, exitPremiumCents: exitP, feesCents: 0, exitKind: 'takeProfit',
    entryReasonAr: 'سبب الدخول التجريبي', exitReasonAr: 'سبب الخروج التجريبي', engines: engines);

void main() {
  late Directory tmp;
  late MemoryRepository repo;
  late RecordingNotifier notes;
  late List<(List<File>, String)> shared;
  late AppController c;

  AppController make({bool bullishEngine = false}) => AppController(
        repo: repo,
        secrets: MemorySecrets(),
        background: NoBackgroundRunner(),
        notifier: notes,
        exporter: ReportExporter(dir: () async => tmp, share: (f, s) async => shared.add((f, s))),
        cycleEvery: const Duration(hours: 1),
        engineFactory: bullishEngine
            ? (rt, b) => TradingEngine(
                profile: rt.profile,
                broker: b,
                state: rt.state,
                analyzer: Analyzer(engines: {
                  EngineId.trend: (_) => [_sig(EngineId.trend)],
                  EngineId.momentum: (_) => [_sig(EngineId.momentum)],
                }))
            : null,
      );

  setUp(() {
    tmp = Directory.systemTemp.createTempSync('oat_d_');
    repo = MemoryRepository();
    notes = RecordingNotifier();
    shared = [];
    c = make();
  });
  tearDown(() => tmp.deleteSync(recursive: true));

  test('fill notifications after a cycle; engines recorded on the position', () async {
    c = make(bullishEngine: true);
    await c.load();
    final p = await c.addAccount(name: 'sim', broker: BrokerKind.simulator, credentials: const {}, startingCashCents: 100000000);
    await c.updateProfile(p.copyWith(
        enabled: true,
        watchlist: ['AAPL'],
        settings: const AccountSettings(riskPerTradePercent: 5, maxPositionPercent: 20, entryAggressiveness: 1, stopLossPercent: 50)));
    await c.runCycle(p.id); // order sent
    await c.runCycle(p.id); // fill picked up and notified
    final fills = notes.shown.where((n) => n.$1 == NotifyKind.fills).toList();
    expect(fills, isNotEmpty);
    expect(fills.first.$3, contains('AAPL'));
    final meta = c.account(p.id)!.state.metas.values.single;
    expect(meta.engines, containsAll(['trend', 'momentum']));
    c.dispose();
  });

  test('error notifications are rate-limited; switching a kind off silences it; prefs persist', () async {
    await c.load();
    final p = await c.addAccount(name: 'alp', broker: BrokerKind.alpaca, credentials: const {});
    await c.runCycle(p.id); // no keys → auth error
    await c.runCycle(p.id);
    expect(notes.shown.where((n) => n.$1 == NotifyKind.errors), hasLength(1));
    await c.setNotify(NotifyKind.killSwitch, false);
    await c.setKillSwitch(true);
    expect(notes.shown.where((n) => n.$1 == NotifyKind.killSwitch), isEmpty);
    await c.setNotify(NotifyKind.killSwitch, true);
    await c.setKillSwitch(false);
    expect(notes.shown.where((n) => n.$1 == NotifyKind.killSwitch).single.$2, 'تم استئناف التداول الآلي');
    await c.setNotify(NotifyKind.market, true);
    final c2 = make();
    await c2.load();
    expect(c2.notify[NotifyKind.market], isTrue);
    expect(c2.notify[NotifyKind.fills], isTrue);
    c.dispose();
    c2.dispose();
  });

  test('exports: CSV with BOM, JSON parses, files go to the share sheet', () async {
    final profile = AccountProfile(id: 'a', name: 'حسابي Paper', broker: BrokerKind.alpaca, mode: TradingMode.paper, createdAt: DateTime.utc(2026));
    final report = AccountReport.build([trade(DateTime.utc(2026, 10, 19, 15), 100, 150, ['trend'])], const [], unrealizedPnlCents: 0);
    final csv = await c.exporter.exportReport(profile, report, json: false, now: DateTime.utc(2026, 10, 19, 18));
    expect(csv.map((f) => f.uri.pathSegments.last), ['Paper_2026-10-19_trades.csv', 'Paper_2026-10-19_daily_weekly.csv']);
    final text = csv.first.readAsStringSync();
    expect(csv.first.readAsBytesSync().take(3), [0xEF, 0xBB, 0xBF]);
    expect(text, contains('سبب الدخول التجريبي'));
    final js = await c.exporter.exportReport(profile, report, json: true);
    final j = jsonDecode(js.single.readAsStringSync()) as Map<String, dynamic>;
    expect(j['summary']['wins'], 1);
    expect(j['account'], 'حسابي Paper');
    final act = await c.exporter.exportActivity(profile, [CycleRecord(cycle: 1, start: DateTime.utc(2026, 10, 19, 14))], json: false);
    expect(act.single.readAsStringSync(), contains('cycle,startUtc'));
    expect(shared, hasLength(3));
    expect(shared.first.$2, contains('تقرير أداء'));
  });

  testWidgets('reports tab: honest W/L/breakeven, daily and weekly, engines, export', (tester) async {
    await tester.runAsync(c.load);
    final rt = AccountRuntime(
        AccountProfile(id: 'a', name: 'x', broker: BrokerKind.alpaca, mode: TradingMode.paper, createdAt: DateTime.utc(2026)),
        AccountState(trades: [
          trade(DateTime.utc(2026, 10, 19, 15), 100, 150, ['trend', 'momentum']),
          trade(DateTime.utc(2026, 10, 20, 15), 100, 60, ['trend']),
          trade(DateTime.utc(2026, 10, 27, 15), 100, 100, const []),
        ]));
    await tester.pumpWidget(host(ReportsTab(controller: c, rt: rt)));
    expect(find.text('1 / 1 / 1'), findsOneWidget);
    expect(find.text('2026-10-20'), findsOneWidget);
    await tester.tap(find.text('أسبوعي'));
    await tester.pump();
    expect(find.text('أسبوع 2026-10-19'), findsOneWidget);
    expect(find.text('أسبوع 2026-10-26'), findsOneWidget);
    await tester.scrollUntilVisible(find.textContaining('صفقة بدون بيانات محركات'), 200);
    expect(find.text(EngineId.trend.arabic), findsWidgets);
    await tester.ensureVisible(find.byKey(const Key('export-csv')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('export-csv')));
    for (var k = 0; k < 40 && shared.isEmpty; k++) {
      await tester.runAsync(() => Future<void>.delayed(const Duration(milliseconds: 50)));
      await tester.pump();
    }
    expect(find.text('تم تجهيز 2 ملف للمشاركة'), findsOneWidget);
    expect(shared, hasLength(1));
    expect(shared.single.$1, hasLength(2));
  });

  testWidgets('activity log export menu shares the filtered cycles', (tester) async {
    await tester.runAsync(c.load);
    final rt = AccountRuntime(
        AccountProfile(id: 'a', name: 'x', broker: BrokerKind.alpaca, mode: TradingMode.paper, createdAt: DateTime.utc(2026)),
        AccountState()..cycles.add(CycleRecord(cycle: 7, start: DateTime.utc(2026, 10, 19, 14))));
    await tester.pumpWidget(host(ActivityLogTab(controller: c, rt: rt)));
    await tester.tap(find.byKey(const Key('export-activity')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('تصدير JSON'));
    await tester.pumpAndSettle();
    for (var k = 0; k < 40 && shared.isEmpty; k++) {
      await tester.runAsync(() => Future<void>.delayed(const Duration(milliseconds: 50)));
      await tester.pump();
    }
    expect(shared.single.$1.single.path, endsWith('_activity.json'));
    expect(shared.single.$1.single.readAsStringSync(), contains('"c": 7'));
  });

  testWidgets('settings: explanations + allowed range, reset to defaults, pause, validation', (tester) async {
    late String id;
    await tester.runAsync(() async {
      await c.load();
      id = (await c.addAccount(name: 'sim', broker: BrokerKind.simulator, credentials: const {})).id;
      final p = c.account(id)!.profile;
      await c.updateProfile(p.copyWith(settings: p.settings.copyWith(riskPerTradePercent: 4)));
    });
    await tester.pumpWidget(MaterialApp(home: Directionality(textDirection: TextDirection.rtl, child: SettingsScreen(controller: c, accountId: id))));
    expect(find.textContaining('المسموح: 0.1–10 • المقترح: 0.5–2'), findsOneWidget);
    expect(find.text('4.0'), findsOneWidget);
    await tester.tap(find.byKey(const Key('reset-defaults')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('استعادة'));
    await tester.pumpAndSettle();
    expect(find.text('1.0'), findsOneWidget);
    await tester.tap(find.text('إيقاف مؤقت للدخول الجديد'));
    await tester.pump();
    await tester.scrollUntilVisible(find.byKey(const Key('setting-maxOrdersPerDay')), 200,
        scrollable: find.byType(Scrollable).first);
    expect(find.text('حدود الأمان'), findsOneWidget);
    await tester.enterText(find.byKey(const Key('setting-maxOrdersPerDay')), '0');
    await tester.tap(find.text('حفظ'));
    await tester.pumpAndSettle();
    expect(find.text('إعدادات غير صالحة'), findsOneWidget);
    await tester.tap(find.text('حسنًا'));
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const Key('setting-maxOrdersPerDay')), '5');
    await tester.runAsync(() async {
      await tester.tap(find.text('حفظ'));
      await Future<void>.delayed(const Duration(milliseconds: 50));
    });
    await tester.pumpAndSettle();
    final s = c.account(id)!.profile.settings;
    expect(s.riskPerTradePercent, 1.0);
    expect(s.pauseNewEntries, isTrue);
    expect(s.maxOrdersPerDay, 5);
  });

  testWidgets('live mode screen: this build cannot enable live (button disabled, reason shown)', (tester) async {
    late String id;
    await tester.runAsync(() async {
      await c.load();
      id = (await c.addAccount(name: 'alp', broker: BrokerKind.alpaca, credentials: const {})).id;
    });
    await tester.pumpWidget(MaterialApp(home: Directionality(textDirection: TextDirection.rtl, child: LiveModeScreen(controller: c, accountId: id))));
    expect(LiveTradingGuard.buildAllowsLive, isFalse);
    expect(find.text('هذه النسخة من التطبيق لا تسمح بالتداول الحقيقي إطلاقًا'), findsOneWidget);
    final button = tester.widget<FilledButton>(find.widgetWithText(FilledButton, 'تفعيل التداول الحقيقي لهذا الحساب'));
    expect(button.onPressed, isNull);
    expect(c.account(id)!.profile.mode, TradingMode.paper);
  });

  test('unrealized P/L in the report uses the latest quotes', () {
    final contract = OptionContract(underlying: 'AAPL', right: OptionRight.put, expiry: DateTime.utc(2026, 11, 20), strikeCents: 20000);
    final rt = AccountRuntime(
        AccountProfile(id: 'a', name: 'x', broker: BrokerKind.alpaca, mode: TradingMode.paper, createdAt: DateTime.utc(2026)),
        AccountState())
      ..positions = [Position(contract: contract, quantity: 3, averageCostCents: 200, openedAt: DateTime.utc(2026, 10, 19))]
      ..quotes = {contract.occSymbol: OptionQuote(contract: contract, bidCents: 140, askCents: 160, time: DateTime.utc(2026, 10, 19))};
    expect(c.unrealizedPnlCents(rt), (150 - 200) * 3 * 100);
    expect(c.report(rt).unrealizedPnlCents, -15000);
    rt.quotes = const {};
    expect(c.unrealizedPnlCents(rt), isNull);
  });
}
