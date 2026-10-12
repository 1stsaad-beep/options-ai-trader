import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:options_ai_trader/api.dart';
import 'package:options_ai_trader/market_data.dart';

Map<String, dynamic> fixture() => Map<String, dynamic>.from(
  jsonDecode(File('test/fixtures/market_data_v1.json').readAsStringSync()) as Map);

void main() {
  for (final kind in ['snapshot', 'bars', 'chain']) {
    test('Python provider contract parses $kind without inventing fields', () {
      final raw = fixture()[kind];
      final value = MarketObservation.parse(raw, 'account-one', 'AAPL', kind);
      expect(value.value['virtual_fills_enabled'], false);
      if (kind == 'chain') {
        expect((value.data['contracts'] as List).single['greeks'], null);
        expect(value.data['quote_delay_seconds'], null);
      }
    });
  }
  test('status from Python keeps Basic analysis-only', () {
    final status = MarketStatus.parse(fixture()['status'], 'account-one');
    expect(status.symbols, ['AAPL', 'MSFT']);
    expect(status.enabled, true);
  });
  for (final override in [
    {'account_id':'account-two'}, {'mode':'demo_synthetic'}, {'provider':'mock'},
    {'feed':'opra'}, {'virtual_fills_enabled':true}, {'external_orders_enabled':true},
    {'schema_version':2}, {'point_in_time_backtest_verified':true},
  ]) {
    test('rejects mismatched identity/source/authority $override', () {
      final raw = Map<String, dynamic>.from(fixture()['snapshot'] as Map)..addAll(override);
      expect(() => MarketObservation.parse(raw, 'account-one', 'AAPL', 'snapshot'), throwsFormatException);
    });
  }
  test('rejects malformed OHLCV and nullable price remains unknown', () {
    final raw = fixture()['bars'];
    raw['data']['bars'][0]['l'] = 200;
    expect(() => MarketObservation.parse(raw, 'account-one', 'AAPL', 'bars'), throwsFormatException);
    final snapshot = fixture()['snapshot'];
    snapshot['data']['price'] = null; snapshot['data']['trade'] = null;
    expect(MarketObservation.parse(snapshot, 'account-one', 'AAPL', 'snapshot').data['price'], null);
  });
  test('non-finite prices and missing timezone rejected', () {
    final raw = fixture()['snapshot'];
    raw['data']['price'] = double.nan;
    expect(() => MarketObservation.parse(raw, 'account-one', 'AAPL', 'snapshot'), throwsFormatException);
    raw['data']['price'] = 200;
    raw['captured_at'] = '2026-10-12T15:00:00';
    expect(() => MarketObservation.parse(raw, 'account-one', 'AAPL', 'snapshot'), throwsFormatException);
  });
  test('modified options cannot masquerade as actual OPRA', () {
    final raw = fixture()['chain'];
    raw['data']['quote_quality'] = 'OPRA';
    expect(() => MarketObservation.parse(raw, 'account-one', 'AAPL', 'chain'), throwsFormatException);
  });

  Future<void> mount(WidgetTester tester, TraderApi api) async {
    await tester.pumpWidget(MaterialApp(home: Directionality(textDirection: TextDirection.rtl,
      child: MarketDataScreen(api: api, initialAccount: 'account-one', accounts: const [
        {'id':'account-one', 'name':'الحساب الأول'}, {'id':'account-two','name':'الحساب الثاني'},
      ]))));
    await tester.pumpAndSettle();
  }
  testWidgets('disabled connection only reads own backend status; no prices or orders', (tester) async {
    final paths = <String>[];
    final api = TraderApi(client: MockClient((request) async {
      paths.add(request.url.path);
      expect(request.method, 'GET');
      final status = fixture()['status'];
      status['connection_enabled'] = false;
      return http.Response(jsonEncode(status),200);
    }));
    addTearDown(api.close);
    await mount(tester, api);
    expect(paths, ['/api/accounts/account-one/market-data/status']);
    expect(find.textContaining('الاتصال غير مفعّل'), findsOneWidget);
    final button = tester.widget<OutlinedButton>(find.widgetWithText(OutlinedButton, 'جلب السعر'));
    expect(button.onPressed, null);
    expect(find.byType(TextField), findsNothing); // No Alpaca key fields.
    expect(tester.takeException(), null);
  });
  testWidgets('explicit GET displays real-data provenance and indicative Greeks absence', (tester) async {
    final methods = <String>[];
    final api = TraderApi(client: MockClient((request) async {
      methods.add(request.method);
      final key = request.url.path.split('/').last;
      return http.Response(jsonEncode(fixture()[key]),200);
    }));
    addTearDown(api.close);
    await mount(tester, api);
    await tester.ensureVisible(find.text('جلب السعر'));
    await tester.tap(find.text('جلب السعر')); await tester.pumpAndSettle();
    await tester.scrollUntilVisible(find.textContaining('آخر صفقة IEX: 200.00'),180);
    expect(find.textContaining('آخر صفقة IEX: 200.00'),findsOneWidget);
    await tester.ensureVisible(find.text('خيارات إرشادية'));
    await tester.tap(find.text('خيارات إرشادية')); await tester.pumpAndSettle();
    await tester.scrollUntilVisible(find.textContaining('غير متاحة؛ لم تُقدّر محليًا'),180);
    expect(find.textContaining('غير متاحة؛ لم تُقدّر محليًا'),findsOneWidget);
    expect(methods.every((m) => m == 'GET'),true);
    expect(find.textContaining('آخر صفقة IEX: 200.00'),findsNothing);
    expect(tester.takeException(),null);
  });
  testWidgets('history request includes explicit UTC cutoff and renders real-data candle layer at 360px', (tester) async {
    tester.view.physicalSize = const Size(360, 800); tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize); addTearDown(tester.view.resetDevicePixelRatio);
    final api = TraderApi(client: MockClient((request) async {
      if (request.url.path.endsWith('/bars')) {
        expect(request.url.queryParameters['timeframe'],'1Day');
        expect(request.url.queryParameters['end']!.endsWith('Z'),true);
        expect(DateTime.parse(request.url.queryParameters['start']!).isBefore(DateTime.parse(request.url.queryParameters['end']!)),true);
      }
      return http.Response(jsonEncode(fixture()[request.url.path.split('/').last]),200);
    }));
    addTearDown(api.close);
    await mount(tester,api);
    await tester.ensureVisible(find.text('جلب OHLCV'));
    await tester.tap(find.text('جلب OHLCV')); await tester.pumpAndSettle();
    await tester.scrollUntilVisible(find.byType(MarketCandleChart),250);
    expect(find.byType(MarketCandleChart),findsOneWidget);
    expect(find.byType(InteractiveViewer),findsOneWidget);
    expect(tester.takeException(),null);
  });
  testWidgets('late response cannot cross account change', (tester) async {
    final pending = Completer<http.Response>();
    final api = TraderApi(client: MockClient((request) async {
      if (request.url.path.endsWith('/snapshot')) return pending.future;
      final status = fixture()['status'];
      status['account_id'] = request.url.path.split('/')[3];
      return http.Response(jsonEncode(status),200);
    }));
    addTearDown(api.close);
    await mount(tester,api);
    await tester.ensureVisible(find.text('جلب السعر'));
    await tester.tap(find.text('جلب السعر')); await tester.pump();
    await tester.ensureVisible(find.byKey(const ValueKey('market-account-account-one')));
    await tester.tap(find.byKey(const ValueKey('market-account-account-one')));
    await tester.pump(); await tester.pump(const Duration(milliseconds:400));
    await tester.tap(find.text('الحساب الثاني').last);
    await tester.pump(); await tester.pump(const Duration(milliseconds:400));
    pending.complete(http.Response(jsonEncode(fixture()['snapshot']),200));
    await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('market-account-account-two')),findsOneWidget);
    expect(find.textContaining('آخر صفقة IEX'),findsNothing);
    expect(tester.takeException(),null);
  });
  testWidgets('fetch error clears stale result and never falls back to Demo', (tester) async {
    var snapshots = 0;
    final api = TraderApi(client: MockClient((request) async {
      final key = request.url.path.split('/').last;
      if (key == 'snapshot' && ++snapshots > 1) return http.Response('{"detail":"DATA_RATE_LIMITED"}',429);
      return http.Response(jsonEncode(fixture()[key]),200);
    }));
    addTearDown(api.close);
    await mount(tester,api);
    for (var i=0;i<2;i++) {
      await tester.ensureVisible(find.text('جلب السعر'));
      await tester.tap(find.text('جلب السعر')); await tester.pumpAndSettle();
    }
    expect(find.textContaining('حد الاستخدام'),findsOneWidget);
    expect(find.textContaining('آخر صفقة IEX'),findsNothing);
  });
}
