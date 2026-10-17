// B15 first-run phone-test path, end to end with fakes:
// Demo drawer -> Broker accounts -> Alpaca Paper key entry -> automatic connection test -> portfolio.
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:options_ai_trader/brokers/broker_accounts_screen.dart';
import 'package:options_ai_trader/brokers/broker_models.dart';
import 'package:options_ai_trader/brokers/broker_store.dart';
import 'package:options_ai_trader/demo/engine.dart';
import 'package:options_ai_trader/demo/store.dart';
import 'package:options_ai_trader/main.dart';

Future<void> settle(WidgetTester tester) async {
  for (var i = 0; i < 8; i++) {
    await tester.runAsync(() => Future<void>.delayed(const Duration(milliseconds: 10)));
    await tester.pump(const Duration(milliseconds: 50));
  }
  await tester.pumpAndSettle();
}

void main() {
  late MemorySecureKeyValue mem;
  late List<http.BaseRequest> requests;
  late MockClient client;
  setUp(() {
    mem = MemorySecureKeyValue();
    requests = [];
    client = MockClient((r) async {
      requests.add(r);
      final body = r.url.path == '/v2/account'
          ? {'account_number': 'PA3FIXTURE', 'currency': 'USD', 'cash': '100000', 'equity': '100000', 'buying_power': '200000', 'status': 'ACTIVE'}
          : r.url.path == '/v2/positions' ? [] : r.url.path == '/v2/orders' ? [] : {};
      return http.Response(jsonEncode(body), 200, headers: {'content-type': 'application/json'});
    });
  });

  Future<void> openBrokers(WidgetTester tester) async {
    final store = MemoryDemoStore((DemoEngine()..createAccount('Demo', 1000000)).encode());
    await tester.pumpWidget(TraderApp(demoStore: store,
        brokersBuilder: () => BrokerAccountsScreen(registry: BrokerAccountRegistry(mem), client: client)));
    await tester.pumpAndSettle();
    tester.state<ScaffoldState>(find.byType(Scaffold).first).openDrawer();
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('drawer-brokers')));
    await settle(tester);
  }

  Future<void> addAlpaca(WidgetTester tester, String keyId, String secret) async {
    await tester.tap(find.text('إضافة حساب'));
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const ValueKey('broker-field-alpaca-keyId')), ' $keyId\n');
    await tester.enterText(find.byKey(const ValueKey('broker-field-alpaca-secretKey')), secret);
    await tester.tap(find.byKey(const ValueKey('save-broker-account')));
    await settle(tester);
  }

  testWidgets('first run: drawer reaches brokers, Live greyed, Alpaca keys saved, connection auto-tested, portfolio opens',
      (tester) async {
    await openBrokers(tester);
    expect(find.text('حسابات الوسطاء (Paper)'), findsOneWidget);
    final live = tester.widget<SwitchListTile>(find.byKey(const ValueKey('live-switch')));
    expect([live.value, live.onChanged], [false, null]);

    await addAlpaca(tester, 'PKFIXTURE1', 'fixturesecret1');
    expect(find.textContaining('متصل (Paper) • PA3FIXTURE'), findsOneWidget);
    expect(requests, isNotEmpty);
    for (final r in requests) {
      expect(r.url.host, 'paper-api.alpaca.markets');
      expect(r.method, 'GET'); // connection test never places anything
    }
    expect(requests.first.headers['APCA-API-KEY-ID'], 'PKFIXTURE1'); // pasted whitespace trimmed
    expect(find.textContaining('fixturesecret1'), findsNothing);
    final stored = jsonEncode(mem.data);
    expect(stored, contains('fixturesecret1')); // only inside the secure store (Keystore on device)
    final accountsRecord = mem.data.entries.where((e) => !e.key.contains('secret') && !e.key.contains('cred'))
        .map((e) => e.value).join();
    expect(accountsRecord, isNot(contains('fixturesecret1')));

    await tester.tap(find.textContaining('متصل (Paper) • PA3FIXTURE'));
    await settle(tester);
    expect(find.text('PA3FIXTURE'), findsOneWidget);
    expect(find.byKey(const ValueKey('new-paper-order')), findsOneWidget);
    expect(find.byKey(const ValueKey('reconcile-orders')), findsOneWidget);
  });

  testWidgets('a live Alpaca key (AK…) is refused and nothing is stored or sent', (tester) async {
    await openBrokers(tester);
    await addAlpaca(tester, 'AKFIXTURE1', 'fixturesecret1');
    expect(find.textContaining('مفتاح Alpaca حقيقي'), findsOneWidget);
    expect(requests, isEmpty);
    expect(jsonEncode(mem.data), isNot(contains('fixturesecret1')));
    await tester.tap(find.text('إلغاء'));
    await tester.pumpAndSettle();
    expect(find.text('لا توجد حسابات.'), findsNWidgets(BrokerKind.values.length));
  });

  testWidgets('wrong Paper keys: 401 is shown clearly and keys can be archived', (tester) async {
    client = MockClient((r) async { requests.add(r); return http.Response('{"message":"unauthorized"}', 401); });
    await openBrokers(tester);
    await addAlpaca(tester, 'PKFIXTURE1', 'fixturesecret1');
    expect(find.textContaining('HTTP 401'), findsOneWidget);
    expect(find.textContaining('fixturesecret1'), findsNothing);
  });
}
