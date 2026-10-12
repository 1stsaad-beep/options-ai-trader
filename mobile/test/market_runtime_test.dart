import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:options_ai_trader/api.dart';
import 'package:options_ai_trader/market_runtime.dart';
import 'package:shared_preferences/shared_preferences.dart';

Map<String, dynamic> fixture() => Map<String, dynamic>.from(
  jsonDecode(File('test/fixtures/market_runtime_v1.json').readAsStringSync()) as Map);

class RuntimeServer {
  final data = fixture();
  final calls = <http.Request>[];
  int? failure;
  Future<http.Response> handle(http.Request request) async {
    calls.add(request);
    expect(request.url.host, 'runtime.invalid');
    expect(request.headers['authorization'], 'Bearer phone-test-token');
    expect(request.url.path, startsWith('/api/accounts/'));
    expect(request.url.path, contains('/market-runtime/'));
    final account = request.url.path.split('/')[3];
    final prefix = account == 'account-one' ? '' : 'second_';
    if (failure != null) return http.Response('{"detail":"PRIVATE_INTERNAL_DETAIL"}', failure!);
    final path = request.url.path.split('/').last;
    if (request.method == 'GET') {
      expect(['status', 'events'], contains(path));
      return http.Response(jsonEncode(data['$prefix$path']), 200);
    }
    if (request.method == 'PUT') {
      expect(path, 'config');
      final body = jsonDecode(request.body) as Map;
      expect(body.keys.toSet(), {'expected_version', 'enabled', 'strategies'});
      final config = data['${prefix}status']['config'] as Map;
      expect(body['expected_version'], config['version']);
      config['version'] = (config['version'] as int) + 1;
      config['enabled'] = body['enabled'];
      config['strategies'] = body['strategies'];
      return http.Response(jsonEncode({...data['${prefix}status'] as Map, ...config}), 200);
    }
    expect(request.method, 'POST');
    expect(path, 'ack');
    final eventId = request.url.path.split('/')[6];
    final item = (data['${prefix}events']['items'] as List).firstWhere((e) => e['id'] == eventId);
    item['acknowledged_at'] = data['${prefix}status']['server_time'];
    return http.Response(jsonEncode({...data['${prefix}status'] as Map, 'acknowledged': true}), 200);
  }
  TraderApi api() => TraderApi(baseUrl: 'https://runtime.invalid', token: 'phone-test-token', client: MockClient(handle));
}

Future<void> mount(WidgetTester tester, TraderApi api, {Brightness brightness = Brightness.light,
    Duration interval = Duration.zero}) async {
  await tester.pumpWidget(MaterialApp(theme: ThemeData(brightness: brightness),
    home: Directionality(textDirection: TextDirection.rtl, child: MarketRuntimeScreen(
      api: api, initialAccount: 'account-one', refreshInterval: interval, accounts: const [
        {'id': 'account-one', 'name': 'الحساب الأول'}, {'id': 'account-two', 'name': 'الحساب الثاني'},
      ]))));
  await tester.pumpAndSettle();
}

Future<void> scrollTo(WidgetTester tester, Finder target) async {
  await tester.scrollUntilVisible(target, 180);
  await tester.pumpAndSettle();
}

void main() {
  test('actual Python fixture preserves timestamps prices source and disabled fills', () {
    final raw = fixture();
    final status = RuntimeStatus.parse(raw['status'], 'account-one');
    final price = status.latest.singleWhere((r) => r['kind'] == 'stock_snapshot');
    expect(price['price'], 130);
    expect(price['market_time'], '2026-10-12T15:00:00+00:00');
    expect(status.value['virtual_fills_enabled'], false);
    expect(RuntimeEvents.parse(raw['events'], 'account-one').items, isNotEmpty);
    expect(RuntimeStatus.parse(raw['second_status'], 'account-two').latest, isEmpty);
  });
  for (final override in [
    {'account_id': 'account-two'}, {'schema_version': 2}, {'mode': 'demo_synthetic'},
    {'new_risk_allowed': true}, {'virtual_fills_enabled': true}, {'external_orders_enabled': true},
    {'stop_loss_execution_assumed': true}, {'server_time': '2026-10-12T15:00:00'},
  ]) {
    test('rejects unsafe or mismatched status $override', () {
      final raw = fixture()['status'] as Map<String, dynamic>;
      raw.addAll(override);
      expect(() => RuntimeStatus.parse(raw, 'account-one'), throwsFormatException);
    });
  }
  test('does not manufacture missing price; rejects future or nonfinite price and wrong feed', () {
    var raw = fixture()['status'];
    Map row() => (raw['latest'] as List).singleWhere((r) => r['kind'] == 'stock_snapshot') as Map;
    row()['price'] = null; row()['market_time'] = null;
    expect(RuntimeStatus.parse(raw, 'account-one').latest.last['price'], null);
    for (final change in [
      {'price': double.nan}, {'market_time': '2027-01-01T00:00:00Z'}, {'feed': 'opra'},
    ]) {
      raw = fixture()['status']; row().addAll(change);
      expect(() => RuntimeStatus.parse(raw, 'account-one'), throwsFormatException);
    }
  });
  test('old immutable events remain readable, cross-account event is refused', () {
    final raw = fixture()['events'];
    raw['items'][0].remove('schema_version');
    expect(RuntimeEvents.parse(raw, 'account-one').items, isNotEmpty);
    raw['items'][0]['account_id'] = 'account-two';
    expect(() => RuntimeEvents.parse(raw, 'account-one'), throwsFormatException);
  });
  test('rejects malformed config and duplicate events', () {
    expect(() => RuntimeConfig.parse({'version': 1, 'enabled': true, 'strategies': {'breakout': true}}), throwsFormatException);
    final raw = fixture()['events']; raw['items'].add(raw['items'][0]);
    expect(() => RuntimeEvents.parse(raw, 'account-one'), throwsFormatException);
  });
  for (final brightness in Brightness.values) {
    testWidgets('360px RTL $brightness shows cached IEX price and timestamps without provider requests', (tester) async {
      tester.view.physicalSize = const Size(360, 800); tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize); addTearDown(tester.view.resetDevicePixelRatio);
      SharedPreferences.setMockInitialValues({'existing-demo-backup': 'untouched'});
      final server = RuntimeServer(), api = server.api(); addTearDown(api.close);
      await mount(tester, api, brightness: brightness);
      expect(find.text('خادم السوق'), findsOneWidget);
      expect(find.text('اتصال API ناجح'), findsOneWidget);
      await scrollTo(tester, find.byKey(const Key('runtime-price-AAPL')));
      expect(find.text('آخر صفقة IEX: 130.00'), findsOneWidget);
      await scrollTo(tester, find.textContaining('وقت السعر:'));
      expect(find.textContaining('2026-10-12T15:00:00.000Z (UTC)'), findsWidgets);
      expect(server.calls.map((c) => c.method).toList(), ['GET', 'GET']);
      expect(find.byType(TextField), findsNothing);
      expect((await SharedPreferences.getInstance()).getString('existing-demo-backup'), 'untouched');
      expect(tester.takeException(), null);
    });
  }
  testWidgets('enable disable and strategy update are versioned account-only requests', (tester) async {
    final server = RuntimeServer(), api = server.api(); addTearDown(api.close);
    await mount(tester, api);
    for (final key in ['runtime-enabled', 'runtime-enabled', 'runtime-pullback']) {
      await scrollTo(tester, find.byKey(ValueKey(key)));
      await tester.tap(find.byKey(ValueKey(key))); await tester.pumpAndSettle();
    }
    final puts = server.calls.where((c) => c.method == 'PUT').toList();
    expect(puts.length, 3);
    expect(puts.map((c) => jsonDecode(c.body)['expected_version']).toList(), [2, 3, 4]);
    expect(server.data['status']['config']['enabled'], false);
    expect(server.data['status']['config']['strategies']['pullback'], true);
    expect(server.data['second_status']['config'], fixture()['second_status']['config']);
    expect(puts.every((c) => c.url.path.contains('/account-one/')), true);
    expect(tester.takeException(), null);
  });
  for (final failure in [409, 503]) {
    testWidgets('uncertain mutation $failure is not retried and requires reread', (tester) async {
      final server = RuntimeServer(), api = server.api(); addTearDown(api.close);
      await mount(tester, api);
      server.failure = failure;
      await scrollTo(tester, find.byKey(const Key('runtime-enabled')));
      await tester.tap(find.byKey(const Key('runtime-enabled'))); await tester.pumpAndSettle();
      expect(server.calls.where((c) => c.method == 'PUT').length, 1);
      expect(find.byKey(const Key('runtime-enabled')), findsNothing);
      expect(find.textContaining('لن يُعاد الطلب تلقائيًا'), findsOneWidget);
      expect(find.textContaining('PRIVATE_INTERNAL_DETAIL'), findsNothing);
      server.failure = null;
      await tester.tap(find.byTooltip('تحديث حالة الخادم')); await tester.pumpAndSettle();
      expect(server.calls.where((c) => c.method == 'PUT').length, 1);
      expect(server.data['status']['config']['enabled'], false);
    });
  }
  testWidgets('auth failure removes previous prices and never substitutes Demo', (tester) async {
    final server = RuntimeServer(), api = server.api(); addTearDown(api.close);
    await mount(tester, api);
    server.failure = 401;
    await tester.tap(find.byTooltip('تحديث حالة الخادم')); await tester.pumpAndSettle();
    expect(find.byKey(const Key('runtime-price-AAPL')), findsNothing);
    expect(find.textContaining('تعذر توثيق'), findsOneWidget);
    expect(server.calls.every((c) => c.method == 'GET'), true);
  });
  testWidgets('late first-account response cannot overwrite second account', (tester) async {
    final server = RuntimeServer(), pending = Completer<http.Response>();
    var held = false;
    final api = TraderApi(baseUrl: 'https://runtime.invalid', token: 'phone-test-token', client: MockClient((r) {
      if (held && r.url.path == '/api/accounts/account-one/market-runtime/status') return pending.future;
      return server.handle(r);
    })); addTearDown(api.close);
    await mount(tester, api);
    held = true;
    await tester.tap(find.byTooltip('تحديث حالة الخادم')); await tester.pump();
    await tester.tap(find.byKey(const ValueKey('runtime-account-account-one')));
    await tester.pump(); await tester.pump(const Duration(milliseconds: 400));
    await tester.tap(find.text('الحساب الثاني').last);
    await tester.pump(); await tester.pump(const Duration(milliseconds: 400));
    pending.complete(http.Response(jsonEncode(server.data['status']), 200));
    await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('runtime-account-account-two')), findsOneWidget);
    await scrollTo(tester, find.textContaining('لا مشاهدات محفوظة'));
    expect(find.byKey(const Key('runtime-price-AAPL')), findsNothing);
    expect(tester.takeException(), null);
  });
  testWidgets('durable event acknowledgement and pagination use own backend only', (tester) async {
    final server = RuntimeServer();
    final original = List<dynamic>.from(server.data['events']['items'] as List);
    server.data['events']['items'] = [original.first];
    server.data['events']['next_before'] = 'opaque+cursor/=';
    final api = server.api(); addTearDown(api.close);
    await mount(tester, api);
    await scrollTo(tester, find.text('تمت القراءة'));
    await tester.tap(find.text('تمت القراءة')); await tester.pumpAndSettle();
    expect(server.calls.where((c) => c.method == 'POST').single.url.path, endsWith('/${original.first['id']}/ack'));
    await scrollTo(tester, find.text('أحداث أقدم'));
    server.data['events']['items'] = [original.last]; server.data['events']['next_before'] = null;
    await tester.tap(find.text('أحداث أقدم')); await tester.pumpAndSettle();
    expect(server.calls.last.url.queryParameters['before'], 'opaque+cursor/=');
    expect(find.text('أحداث أقدم'), findsNothing);
    expect(tester.takeException(), null);
  });
  testWidgets('polls only while active and disposal cancels polling', (tester) async {
    final server = RuntimeServer(), api = server.api(); addTearDown(api.close);
    await mount(tester, api, interval: const Duration(seconds: 5));
    await tester.pump(const Duration(seconds: 5)); await tester.pumpAndSettle();
    expect(server.calls.length, 4);
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.paused);
    await tester.pump(const Duration(seconds: 10));
    expect(server.calls.length, 4);
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
    await tester.pumpAndSettle();
    expect(server.calls.length, 6);
    await tester.pumpWidget(const SizedBox());
    await tester.pump(const Duration(seconds: 10));
    expect(server.calls.length, 6);
    expect(tester.takeException(), null);
  });
}
