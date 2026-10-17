import 'dart:convert';
import 'dart:io';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:options_ai_trader/api.dart';
import 'package:options_ai_trader/observed_server.dart';
import 'package:options_ai_trader/observed_server_comparison.dart';

Map<String, dynamic> data() => jsonDecode(File('test/fixtures/observed_experiment_v1.json').readAsStringSync()) as Map<String, dynamic>;

class ExperimentServer {
  final fixture = data(), calls = <http.Request>[];
  bool exists = false, lostAck = false, malformed = false;
  Future<http.Response> handle(http.Request request) async {
    calls.add(request);
    expect(request.url.host, 'server.invalid');
    expect(request.headers['authorization'], 'Bearer fixture-owner');
    final end = request.url.path.split('/').last;
    dynamic response;
    if (request.method == 'POST') {
      expect(end, 'experiment');
      expect(jsonDecode(request.body), {'source': 'alpaca'});
      final created = !exists;
      exists = true;
      if (lostAck) return http.Response('{"detail":"PRIVATE_PROVIDER_BODY"}', 503);
      response = {...fixture['experiment'] as Map, 'created': created};
    } else {
      expect(request.method, 'GET');
      if (end == 'accounts') {
        response = {'mode': 'observed_market_virtual', 'externalOrder': false, 'accounts': exists ? observedExperimentIds('alpaca') : []};
      } else if (end == 'status') {
        response = {'mode': 'observed_market_virtual', 'externalOrder': false, 'newMarketEntryAllowed': false,
          'heartbeatFresh': false, 'serverTime': '2026-10-17T05:00:00Z', 'state': 'WORKER_UNAVAILABLE'};
      } else if (end == 'state') {
        final id = request.url.path.split('/')[4];
        response = (fixture['experiment']['accounts'] as List).singleWhere((r) => r['state']['id'] == id);
      } else {
        expect(end, 'comparison');
        expect(request.url.queryParameters['accounts'], observedExperimentIds('alpaca').join(','));
        response = fixture['comparison'];
        if (malformed) response['accounts'][0]['performance']['source'] = 'fixture';
      }
    }
    return http.Response(jsonEncode(response), 200);
  }
  TraderApi api() => TraderApi(baseUrl: 'https://server.invalid', token: 'fixture-owner', client: MockClient(handle));
}

Future<void> mount(WidgetTester tester, TraderApi api, {Brightness brightness = Brightness.light}) async {
  await tester.pumpWidget(MaterialApp(theme: ThemeData(brightness: brightness),
    home: Directionality(textDirection: TextDirection.rtl, child: ObservedServerScreen(api: api))));
  await tester.pumpAndSettle();
}

Future<void> tap(WidgetTester tester, String key) async {
  final finder = find.byKey(Key(key));
  await tester.scrollUntilVisible(finder, 160);
  await tester.tap(finder);
  await tester.pumpAndSettle();
}

void main() {
  test('actual SQL fixture preserves four genesis identities and report balances', () {
    final fixture = data(), ids = observedExperimentIds('alpaca');
    final accounts = parseObservedExperiment(fixture['experiment'], 'alpaca');
    expect(accounts.map((a) => a.state['cash']), everyElement(100000));
    final report = parseObservedComparison(fixture['comparison'], ids, 'alpaca');
    expect(report['accounts'].length, 4);
    expect(report['threeSessionAcceptance'], 'NOT_RUN');
    fixture['comparison']['accounts'][0]['performance']['cashCents'] = 0;
    expect(report['accounts'][0]['performance']['cashCents'], 100000);
  });
  for (final field in ['source', 'cashCents', 'eventHash', 'version', 'liquidationEquityCents', 'winningQuoteRoundTrips']) {
    test('rejects mismatched or invented comparison $field', () {
      final fixture = data(), p = fixture['comparison']['accounts'][0]['performance'];
      p[field] = switch (field) {'source' => 'fixture', 'eventHash' => 'invalid', _ => 99};
      expect(() => parseObservedComparison(fixture['comparison'], observedExperimentIds('alpaca'), 'alpaca'), throwsFormatException);
    });
  }
  test('retry accepts current controls but a created response cannot arm accounts', () {
    final fixture = data()['experiment'];
    fixture['accounts'][0]['state']['enabled'] = true;
    expect(() => parseObservedExperiment(fixture, 'alpaca'), throwsFormatException);
    fixture['created'] = false;
    expect(parseObservedExperiment(fixture, 'alpaca').first.state['enabled'], true);
    fixture['accounts'][0]['state']['initialCash'] = 100001;
    expect(() => parseObservedExperiment(fixture, 'alpaca'), throwsFormatException);
  });
  testWidgets('creation requires explicit gesture and only one bounded setup write', (tester) async {
    final server = ExperimentServer(), api = server.api(); addTearDown(api.close);
    await mount(tester, api);
    expect(server.calls.every((r) => r.method == 'GET'), true);
    await tap(tester, 'observed-experiment');
    expect(server.calls.where((r) => r.method == 'POST'), isEmpty);
    await tester.tap(find.byKey(const Key('observed-experiment-confirm'))); await tester.pumpAndSettle();
    expect(server.calls.where((r) => r.method == 'POST').length, 1);
    expect(server.exists, true);
    expect(find.byKey(const Key('observed-comparison')), findsOneWidget);
    expect(tester.takeException(), null);
  });
  testWidgets('lost setup acknowledgement never retries or overwrites balances', (tester) async {
    final server = ExperimentServer()..lostAck = true, api = server.api(); addTearDown(api.close);
    await mount(tester, api); await tap(tester, 'observed-experiment');
    await tester.tap(find.byKey(const Key('observed-experiment-confirm'))); await tester.pumpAndSettle();
    expect(find.textContaining('PRIVATE_PROVIDER_BODY'), findsNothing);
    expect(find.byKey(const Key('observed-error')), findsOneWidget);
    expect(server.calls.where((r) => r.method == 'POST').length, 1);
    await tester.tap(find.byKey(const Key('observed-refresh'))); await tester.pumpAndSettle();
    expect(server.calls.where((r) => r.method == 'POST').length, 1);
    expect(find.byKey(const Key('observed-comparison')), findsOneWidget);
    expect(tester.takeException(), null);
  });
  for (final brightness in Brightness.values) {
    testWidgets('360px RTL $brightness comparison displays four independently scrollable accounts', (tester) async {
      tester.view.physicalSize = const Size(360, 800); tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize); addTearDown(tester.view.resetDevicePixelRatio);
      final server = ExperimentServer()..exists = true, api = server.api(); addTearDown(api.close);
      await mount(tester, api, brightness: brightness); await tap(tester, 'observed-comparison');
      expect(find.byType(ObservedComparisonScreen), findsOneWidget);
      expect(find.textContaining('لم تُقبل بعد'), findsOneWidget);
      for (final id in observedExperimentIds('alpaca')) {
        await tester.scrollUntilVisible(find.byKey(Key('comparison-$id')), 200);
        expect(find.byKey(Key('comparison-$id')), findsOneWidget);
        expect(tester.takeException(), null);
      }
      expect(server.calls.every((r) => r.method == 'GET'), true);
    });
  }
  testWidgets('mixed source response never opens a comparison', (tester) async {
    final server = ExperimentServer()..exists = true..malformed = true, api = server.api(); addTearDown(api.close);
    await mount(tester, api); await tap(tester, 'observed-comparison');
    expect(find.byType(ObservedComparisonScreen), findsNothing);
    expect(find.byKey(const Key('observed-error')), findsOneWidget);
    expect(server.calls.every((r) => r.method == 'GET'), true);
  });
}
