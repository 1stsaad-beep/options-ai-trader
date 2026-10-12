import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:options_ai_trader/api.dart';
import 'package:options_ai_trader/market_monitor.dart';

void main() {
  final binding = TestWidgetsFlutterBinding.ensureInitialized();
  final calls = <MethodCall>[];
  bool permission = true, failStart = false, failStatus = false;
  Map<String, dynamic> native = {'active': false, 'state': 'STOPPED'};
  setUp(() {
    debugDefaultTargetPlatformOverride = TargetPlatform.android;
    calls.clear(); permission = true; failStart = false; failStatus = false;
    native = {'active': false, 'state': 'STOPPED'};
    binding.defaultBinaryMessenger.setMockMethodCallHandler(MarketMonitor.channel, (call) async {
      calls.add(call);
      if (call.method == 'permission') return permission;
      if (call.method == 'status' && failStatus) throw PlatformException(code: 'fixture', message: 'PRIVATE_CREDENTIAL_FIXTURE');
      if (call.method == 'start') {
        if (failStart) throw PlatformException(code: 'fixture', message: 'PRIVATE_CREDENTIAL_FIXTURE');
        native = {'active': false, 'state': 'STARTING', 'account': 'account-one'};
      }
      if (call.method == 'stop') native = {'active': false, 'state': 'STOPPED'};
      return native;
    });
  });
  tearDown(() {
    binding.defaultBinaryMessenger.setMockMethodCallHandler(MarketMonitor.channel, null);
    debugDefaultTargetPlatformOverride = null;
  });
  Future<void> open(WidgetTester tester) async {
    await tester.pumpWidget(MaterialApp(home: Directionality(textDirection: TextDirection.rtl,
      child: MarketMonitorScreen(api: TraderApi(baseUrl: 'https://runtime.invalid', token: 'offline-fixture-token'), account: 'account-one'))));
    await tester.pumpAndSettle();
  }
  Future<void> requestStart(WidgetTester tester, {bool confirm = true}) async {
    await tester.ensureVisible(find.byKey(const Key('monitor-start')));
    await tester.tap(find.byKey(const Key('monitor-start')));
    await tester.pumpAndSettle();
    await tester.tap(find.text(confirm ? 'بدء الجلسة' : 'إلغاء'));
    await tester.pumpAndSettle();
  }
  Future<void> close(WidgetTester tester) async { await tester.pumpWidget(const SizedBox()); }

  testWidgets('no automatic start or permission request; cancellation is inert', (tester) async {
    await open(tester);
    expect(calls.map((c) => c.method), everyElement('status'));
    await requestStart(tester, confirm: false);
    expect(calls.where((c) => c.method == 'permission' || c.method == 'start'), isEmpty);
    await close(tester);
  });
  testWidgets('explicit consent passes only server token and selected account; waits for native confirmation', (tester) async {
    await open(tester); await requestStart(tester);
    final starts = calls.where((c) => c.method == 'start').toList();
    expect(starts.length, 1);
    expect(starts.single.arguments, {'baseUrl': 'https://runtime.invalid', 'token': 'offline-fixture-token', 'account': 'account-one'});
    expect(find.text(monitorLabel('STARTING')), findsOneWidget);
    expect(tester.widget<FilledButton>(find.byKey(const Key('monitor-start'))).onPressed, isNull);
    native = {'active': true, 'state': 'UNAVAILABLE', 'account': 'account-one'};
    await tester.pump(const Duration(seconds: 2)); await tester.pump();
    expect(find.text(monitorLabel('UNAVAILABLE')), findsOneWidget);
    await close(tester);
  });
  testWidgets('notification refusal never starts service', (tester) async {
    permission = false; await open(tester); await requestStart(tester);
    expect(calls.where((c) => c.method == 'start'), isEmpty);
    expect(find.byKey(const Key('monitor-error')), findsOneWidget);
    await close(tester);
  });
  testWidgets('uncertain start redacts native details and never retries', (tester) async {
    failStart = true; await open(tester); await requestStart(tester);
    await tester.pump(const Duration(seconds: 20)); await tester.pump();
    expect(calls.where((c) => c.method == 'start').length, 1);
    expect(find.textContaining('PRIVATE_CREDENTIAL_FIXTURE'), findsNothing);
    expect(find.byKey(const Key('monitor-error')), findsOneWidget);
    await close(tester);
  });
  testWidgets('explicit stop and native timeout return to stopped state', (tester) async {
    native = {'active': true, 'state': 'API_REACHABLE', 'account': 'account-one'};
    await open(tester);
    await tester.ensureVisible(find.byKey(const Key('monitor-stop')));
    await tester.tap(find.byKey(const Key('monitor-stop'))); await tester.pumpAndSettle();
    expect(calls.where((c) => c.method == 'stop').length, 1);
    expect(find.text(monitorLabel('STOPPED')), findsOneWidget);
    native = {'active': false, 'state': 'SYSTEM_TIMEOUT'};
    await tester.pump(const Duration(seconds: 2)); await tester.pump();
    expect(find.text(monitorLabel('SYSTEM_TIMEOUT')), findsOneWidget);
    await close(tester);
  });
  testWidgets('status failure clears assumed activity and keeps stop available', (tester) async {
    await open(tester); failStatus = true;
    await tester.pump(const Duration(seconds: 2)); await tester.pump();
    expect(find.text('حالة الخدمة غير متحققة'), findsOneWidget);
    expect(find.textContaining('PRIVATE_CREDENTIAL_FIXTURE'), findsNothing);
    expect(tester.widget<OutlinedButton>(find.byKey(const Key('monitor-stop'))).onPressed, isNotNull);
    await close(tester);
  });
  testWidgets('iOS never invokes Android plugin', (tester) async {
    debugDefaultTargetPlatformOverride = TargetPlatform.iOS;
    await open(tester);
    expect(calls, isEmpty);
    expect(find.text(monitorLabel('UNSUPPORTED')), findsOneWidget);
    await close(tester);
  });
  testWidgets('RTL narrow screen has no overflow and UI polling pauses in background', (tester) async {
    tester.view.physicalSize = const Size(360, 800);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize); addTearDown(tester.view.resetDevicePixelRatio);
    await open(tester);
    expect(tester.takeException(), isNull);
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.paused);
    final before = calls.length;
    await tester.pump(const Duration(seconds: 10));
    expect(calls.length, before);
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
    await tester.pump();
    expect(calls.length, greaterThan(before));
    await close(tester);
  });
}
