import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:options_ai_trader/brokers/broker_accounts_screen.dart';
import 'package:options_ai_trader/brokers/broker_adapter.dart';
import 'package:options_ai_trader/brokers/broker_models.dart';
import 'package:options_ai_trader/brokers/broker_options.dart';
import 'package:options_ai_trader/brokers/broker_portfolio.dart';
import 'package:options_ai_trader/brokers/broker_portfolio_screen.dart';
import 'package:options_ai_trader/brokers/broker_store.dart';

http.Response json(Object body, [int status = 200]) =>
    http.Response(jsonEncode(body), status, headers: {'content-type': 'application/json'});

class FakeAdapter implements BrokerAdapter {
  final bool paper;
  int positionCalls = 0;
  FakeAdapter({this.paper = true});
  @override
  BrokerKind get kind => BrokerKind.alpaca;
  @override
  Future<BrokerAccountSnapshot> connect() async =>
      BrokerAccountSnapshot(broker: kind, brokerAccountId: 'PA1', paperVerified: paper);
  @override
  Future<List<BrokerPosition>> positions() async { positionCalls++; return const []; }
  @override
  Future<BrokerOrderAck> submitPaperOrder(PaperOrderRequest order) => throw UnimplementedError();
  @override
  Future<BrokerQuote?> optionQuote(OccContract contract, {String? conid}) async => null;
  @override
  Future<BrokerOrderLookup> orderStatus({required String clientOrderId, String? brokerOrderId,
      Map<String, dynamic>? match}) async => const BrokerOrderLookup(null);
}

// HTTP/storage futures need real async turns interleaved with frames; the
// indeterminate progress bar never settles while a load is in flight.
Future<void> settle(WidgetTester tester) async {
  for (var i = 0; i < 20 && find.byType(LinearProgressIndicator).evaluate().isNotEmpty || i < 3; i++) {
    await tester.runAsync(() => Future<void>.delayed(const Duration(milliseconds: 10)));
    await tester.pump(const Duration(milliseconds: 50));
  }
  await tester.pumpAndSettle();
}

Widget host(Widget child) => MaterialApp(home: Directionality(textDirection: TextDirection.rtl, child: child));

void main() {
  final t0 = DateTime(2026, 10, 17, 20, 40, 0);

  test('unverified paper snapshot never loads positions', () async {
    final a = BrokerAccount(id: 'alpaca-x', label: 'A', broker: BrokerKind.alpaca, createdAt: t0);
    final fake = FakeAdapter(paper: false);
    await expectLater(loadPortfolio(a, fake), throwsA(isA<BrokerException>()));
    expect(fake.positionCalls, 0);
  });

  test('stale after 60 seconds', () async {
    final a = BrokerAccount(id: 'alpaca-x', label: 'A', broker: BrokerKind.alpaca, createdAt: t0);
    final p = await loadPortfolio(a, FakeAdapter(), clock: () => t0);
    expect(p.isStale(t0.add(const Duration(seconds: 60))), isFalse);
    expect(p.isStale(t0.add(const Duration(seconds: 61))), isTrue);
  });

  testWidgets('Alpaca paper balances and positions render exactly as reported', (tester) async {
    final reg = BrokerAccountRegistry(MemorySecureKeyValue());
    final a = await reg.add(broker: BrokerKind.alpaca, label: 'Alpaca 1', values: {'keyId': 'PKFIXTURE1', 'secretKey': 'fixturesecret1'});
    var now = t0;
    var calls = 0;
    final client = MockClient((r) async {
      calls++;
      expect(r.url.host, 'paper-api.alpaca.markets');
      if (r.url.path == '/v2/account') {
        return json({'account_number': 'PA3FIXTURE', 'currency': 'USD', 'cash': '9876.54', 'equity': '10012.34',
          'buying_power': '19753.08', 'status': 'ACTIVE'});
      }
      return json([
        {'symbol': 'AAPL261120C00200000', 'qty': '2', 'avg_entry_price': '1.25', 'market_value': '300', 'unrealized_pl': '50'},
        {'symbol': 'NVDA261120P00150000', 'qty': '1', 'avg_entry_price': '2.10', 'market_value': '180', 'unrealized_pl': '-30.5'},
      ]);
    });
    await tester.pumpWidget(host(BrokerPortfolioScreen(account: a, registry: reg, client: client, clock: () => now)));
    await settle(tester);
    expect(find.text('9876.54'), findsOneWidget);
    expect(find.text('10012.34'), findsOneWidget);
    expect(find.text('19753.08'), findsOneWidget);
    expect(find.text('PA3FIXTURE'), findsOneWidget);
    expect(find.text('المراكز (2)'), findsOneWidget);
    expect(find.text('AAPL261120C00200000'), findsOneWidget);
    expect(find.text('-30.5'), findsOneWidget);
    expect(find.text('وقت الاستلام: 2026-10-17 20:40:00'), findsOneWidget);
    expect(find.byKey(const ValueKey('portfolio-stale')), findsNothing);
    expect(find.textContaining('fixturesecret1'), findsNothing);
    expect(calls, 2);
    now = t0.add(const Duration(minutes: 2));
    await tester.tap(find.byTooltip('تحديث'));
    await settle(tester);
    expect(calls, 4);
    expect(find.text('وقت الاستلام: 2026-10-17 20:42:00'), findsOneWidget);
  });

  testWidgets('failed refresh keeps previous values marked stale with the error', (tester) async {
    final reg = BrokerAccountRegistry(MemorySecureKeyValue());
    final a = await reg.add(broker: BrokerKind.alpaca, label: 'A', values: {'keyId': 'PKFIXTURE1', 'secretKey': 'fixturesecret1'});
    var fail = false;
    final client = MockClient((r) async {
      if (fail) return json({'message': 'no'}, 401);
      return r.url.path == '/v2/account' ? json({'account_number': 'PA1', 'cash': '1'}) : json([]);
    });
    await tester.pumpWidget(host(BrokerPortfolioScreen(account: a, registry: reg, client: client, clock: () => DateTime(2026, 10, 17))));
    await settle(tester);
    expect(find.text('لا توجد مراكز مفتوحة.'), findsOneWidget);
    fail = true;
    await tester.tap(find.byTooltip('تحديث'));
    await settle(tester);
    expect(find.text(brokerMessage('HTTP_401')), findsOneWidget);
    expect(find.byKey(const ValueKey('portfolio-stale')), findsOneWidget);
    expect(find.text('PA1'), findsOneWidget);
  });

  testWidgets('IBKR and TradeStation accounts load their own Paper portfolios', (tester) async {
    final reg = BrokerAccountRegistry(MemorySecureKeyValue());
    final ib = await reg.add(broker: BrokerKind.ibkr, label: 'IB',
        values: {'gatewayUrl': 'https://gateway.local:5000', 'accountId': 'DU1234567'});
    final ts = await reg.add(broker: BrokerKind.tradestation, label: 'TS',
        values: {'clientId': 'tsclient1', 'clientSecret': 'tssecret1', 'refreshToken': 'tsrefresh1'});
    final client = MockClient((r) async {
      switch (r.url.path) {
        case '/v1/api/iserver/auth/status': return json({'authenticated': true, 'connected': true});
        case '/v1/api/portfolio/accounts': return json([{'accountId': 'DU1234567'}]);
        case '/v1/api/portfolio/DU1234567/summary': return json({'totalcashvalue': {'amount': 1000, 'currency': 'USD'}});
        case '/v1/api/portfolio/DU1234567/positions/0':
          return json([{'contractDesc': 'SPY NOV2026 500 C', 'position': 3, 'avgPrice': 4.5, 'mktValue': 1500, 'unrealizedPnl': 150}]);
        case '/oauth/token': return json({'access_token': 'acc1', 'expires_in': 1200, 'refresh_token': 'tsrefresh2'});
        case '/v3/brokerage/accounts': return json({'Accounts': [{'AccountID': 'SIM1'}]});
        case '/v3/brokerage/accounts/SIM1/balances': return json({'Balances': [{'AccountID': 'SIM1', 'CashBalance': '25000.00'}]});
        case '/v3/brokerage/accounts/SIM1/positions': return json({'Positions': []});
      }
      return json({}, 404);
    });
    await tester.pumpWidget(host(BrokerPortfolioScreen(account: ib, registry: reg, client: client)));
    await settle(tester);
    expect(find.text('DU1234567'), findsOneWidget);
    expect(find.text('SPY NOV2026 500 C'), findsOneWidget);
    expect(find.text('150'), findsOneWidget);
    await tester.pumpWidget(host(BrokerPortfolioScreen(key: UniqueKey(), account: ts, registry: reg, client: client)));
    await settle(tester);
    expect(find.text('SIM1'), findsOneWidget);
    expect(find.text('25000.00'), findsOneWidget);
    expect(find.text('لا توجد مراكز مفتوحة.'), findsOneWidget);
    expect((await reg.credentials(ts.id))['refreshToken'], 'tsrefresh2');
  });

  testWidgets('tapping an account in settings opens its portfolio', (tester) async {
    final reg = BrokerAccountRegistry(MemorySecureKeyValue());
    await reg.add(broker: BrokerKind.alpaca, label: 'Alpaca 1', values: {'keyId': 'PKFIXTURE1', 'secretKey': 'fixturesecret1'});
    final client = MockClient((r) async =>
        r.url.path == '/v2/account' ? json({'account_number': 'PA9', 'cash': '5'}) : json([]));
    await tester.pumpWidget(host(BrokerAccountsScreen(registry: reg, client: client)));
    await settle(tester);
    await tester.tap(find.text('Alpaca 1'));
    await settle(tester);
    expect(find.byType(BrokerPortfolioScreen), findsOneWidget);
    expect(find.text('PA9'), findsOneWidget);
  });
}
