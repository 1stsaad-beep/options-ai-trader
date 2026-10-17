import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:options_ai_trader/direct_alpaca.dart';
import 'package:options_ai_trader/brokers/broker_models.dart';
import 'package:options_ai_trader/brokers/broker_order_admission.dart';
import 'package:options_ai_trader/brokers/broker_order_journal.dart';
import 'package:options_ai_trader/brokers/broker_order_service.dart';
import 'package:options_ai_trader/brokers/broker_portfolio_screen.dart';
import 'package:options_ai_trader/brokers/broker_reconcile.dart';
import 'package:options_ai_trader/brokers/broker_store.dart';

const call = 'AAPL261120C00200000';
final open = DateTime.utc(2026, 10, 19, 15, 0, 0);

http.Response json(Object body, [int status = 200]) =>
    http.Response(jsonEncode(body), status, headers: {'content-type': 'application/json'});

const buy = BrokerOrderTicket(contract: call, side: TicketSide.buyToOpen, quantity: 2, limitCents: 125);

void main() {
  late MemorySecureKeyValue mem;
  late BrokerAccountRegistry reg;
  late DateTime now;
  setUp(() {
    mem = MemorySecureKeyValue();
    reg = BrokerAccountRegistry(mem);
    now = open;
  });

  OptionQuote direct() => OptionQuote(call, 'opra', now.subtract(const Duration(seconds: 1)), 120, 125, 50, 50);

  /// Alpaca paper mock whose order endpoints are driven by [orders] (keyed by id) and [byClient].
  MockClient alpaca({required Map<String, Map<String, dynamic>> orders, List<Map<String, dynamic>> Function()? positions,
      bool submitTimesOut = false, List<String>? log}) {
    return MockClient((r) async {
      log?.add('${r.method} ${r.url.path}');
      expect(r.url.host, 'paper-api.alpaca.markets');
      if (r.url.path == '/v2/account') return json({'account_number': 'PA1', 'cash': '10000', 'equity': '10000', 'buying_power': '20000'});
      if (r.url.path == '/v2/positions') return json(positions?.call() ?? const []);
      if (r.method == 'POST' && r.url.path == '/v2/orders') {
        final b = jsonDecode(r.body) as Map;
        orders['alp-1'] = {'id': 'alp-1', 'client_order_id': b['client_order_id'], 'status': 'accepted', 'filled_qty': '0'};
        if (submitTimesOut) throw http.ClientException('reset');
        return json(orders['alp-1']!);
      }
      if (r.url.path == '/v2/orders:by_client_order_id') {
        final hit = orders.values.where((o) => o['client_order_id'] == r.url.queryParameters['client_order_id']);
        return hit.isEmpty ? json({'message': 'not found'}, 404) : json(hit.first);
      }
      if (r.url.path.startsWith('/v2/orders/')) {
        final o = orders[r.url.pathSegments.last];
        return o == null ? json({}, 404) : json(o);
      }
      return json({}, 404);
    });
  }

  Future<BrokerAccount> addAlpaca() =>
      reg.add(broker: BrokerKind.alpaca, label: 'A', values: {'keyId': 'PKFIXTURE1', 'secretKey': 'fixturesecret1'});

  test('partial then full fill are appended as new events; earlier events untouched', () async {
    final a = await addAlpaca();
    final orders = <String, Map<String, dynamic>>{};
    final svc = BrokerOrderService(reg, requireEligibility: false, clock: () => now, directQuote: (_) async => direct(), client: alpaca(orders: orders));
    final out = await svc.submit(await svc.review(a, buy));
    final before = List<Map<String, dynamic>>.from(await svc.journal(a).events());

    orders['alp-1']!.addAll({'status': 'partially_filled', 'filled_qty': '1', 'filled_avg_price': '1.24'});
    var r = await svc.reconcile(a);
    expect([r.checked, r.updated, r.fills], [1, 1, 1]);
    var o = (await svc.journal(a).orders()).single;
    expect(o.state, OrderState.partiallyFilled);
    expect(o.filledQuantity, 1);

    orders['alp-1']!.addAll({'status': 'filled', 'filled_qty': '2', 'filled_avg_price': '1.245'});
    r = await svc.reconcile(a);
    o = (await svc.journal(a).orders()).single;
    expect(o.state, OrderState.filled);
    expect(o.terminal, isTrue);
    final events = await svc.journal(a).events();
    expect(events.sublist(0, before.length), before); // append-only
    expect(events.map((e) => e['type']), ['INTENT', 'ACK', 'FILL', 'FILL']);
    expect(events.last['fillQuantity'], 1);
    expect(events.last['averageFillPrice'], '1.245');
    expect(out.clientOrderId, o.clientOrderId);
    // Terminal orders are not queried again.
    r = await svc.reconcile(a);
    expect(r.checked, 0);
  });

  test('UNKNOWN send found by client order id becomes OPEN and unblocks admission', () async {
    final a = await addAlpaca();
    final orders = <String, Map<String, dynamic>>{};
    final svc = BrokerOrderService(reg, requireEligibility: false, clock: () => now, directQuote: (_) async => direct(),
        client: alpaca(orders: orders, submitTimesOut: true));
    expect((await svc.submit(await svc.review(a, buy))).state, OrderState.unknown);
    expect((await svc.review(a, buy)).admission.reason, 'UNRESOLVED_ORDER_RECONCILE_REQUIRED');
    final r = await svc.reconcile(a);
    expect(r.updated, 1);
    final o = (await svc.journal(a).orders()).single;
    expect(o.state, OrderState.open);
    expect(o.brokerOrderId, 'alp-1');
    // Pending order still reserves risk but no longer blocks as unresolved.
    expect((await svc.review(a, buy)).admission.reason, isNot('UNRESOLVED_ORDER_RECONCILE_REQUIRED'));
  });

  test('client id not found: NOT_PLACED only after 60 s; never earlier', () async {
    final a = await addAlpaca();
    final journal = BrokerOrderJournal(mem, a.id, clock: () => now);
    await journal.append('oat-crashed0000000001', 'INTENT', {'state': OrderState.intent, 'contract': call,
        'side': 'BUY_TO_OPEN', 'quantity': 1, 'limitCents': 125, 'costCents': 12570});
    final svc = BrokerOrderService(reg, requireEligibility: false, clock: () => now, client: alpaca(orders: {}));
    now = open.add(const Duration(seconds: 30));
    var r = await svc.reconcile(a);
    expect(r.stillUnresolved, ['oat-crashed0000000001']);
    now = open.add(const Duration(seconds: 61));
    r = await svc.reconcile(a);
    final o = (await journal.orders()).single;
    expect(o.state, OrderState.notPlaced);
    expect(o.events.last['basis'], 'BROKER_CLIENT_ID_NOT_FOUND');
  });

  test('inconsistent broker data is reported, not applied', () async {
    final a = await addAlpaca();
    final orders = <String, Map<String, dynamic>>{};
    final svc = BrokerOrderService(reg, requireEligibility: false, clock: () => now, directQuote: (_) async => direct(), client: alpaca(orders: orders));
    await svc.submit(await svc.review(a, buy));
    orders['alp-1']!.addAll({'status': 'filled', 'filled_qty': '5'}); // more than ordered
    final r = await svc.reconcile(a);
    expect(r.discrepancies.single, endsWith(':FILL_QUANTITY_INCONSISTENT'));
    expect((await svc.journal(a).orders()).single.state, OrderState.open);
    orders['alp-1']!['client_order_id'] = 'oat-someoneelse';
    final r2 = await svc.reconcile(a);
    expect(r2.discrepancies.single, endsWith(':LOOKUP_ORDER_IDENTITY_MISMATCH'));
  });

  test('positions below journal fills are flagged', () async {
    final a = await addAlpaca();
    final orders = <String, Map<String, dynamic>>{};
    var positions = <Map<String, dynamic>>[];
    final client = alpaca(orders: orders, positions: () => positions);
    final svc = BrokerOrderService(reg, requireEligibility: false, clock: () => now, directQuote: (_) async => direct(), client: client);
    await svc.submit(await svc.review(a, buy));
    orders['alp-1']!.addAll({'status': 'filled', 'filled_qty': '2', 'filled_avg_price': '1.25'});
    var r = await svc.reconcile(a);
    expect(r.discrepancies.single, '$call:POSITION_BELOW_JOURNAL(0<2)');
    positions = [{'symbol': call, 'qty': '2', 'market_value': '250', 'unrealized_pl': '0'}];
    r = await svc.reconcile(a);
    expect(r.discrepancies, isEmpty);
  });

  test('manual resolution is explicit, logged and only for unresolved orders', () async {
    final a = await addAlpaca();
    final journal = BrokerOrderJournal(mem, a.id, clock: () => now);
    await journal.append('oat-unknown000000001', 'INTENT', {'state': OrderState.intent, 'contract': call,
        'side': 'BUY_TO_OPEN', 'quantity': 1, 'limitCents': 125});
    await journal.append('oat-unknown000000001', 'SEND_RESULT', {'state': OrderState.unknown, 'code': 'TIMEOUT'});
    final rec = BrokerReconciler(journal, clock: () => now);
    await rec.resolveManually('oat-unknown000000001', note: 'checked broker app');
    final o = (await journal.orders()).single;
    expect(o.state, OrderState.userResolvedNotPlaced);
    expect(o.events.length, 3);
    await expectLater(rec.resolveManually('oat-unknown000000001', note: 'again'), throwsA(isA<BrokerJournalException>()));
  });

  test('TradeStation: unique same-day match links an UNKNOWN order; ambiguity stays unresolved', () async {
    final a = await reg.add(broker: BrokerKind.tradestation, label: 'TS',
        values: {'clientId': 'tsclient1', 'clientSecret': 'tssecret1', 'refreshToken': 'tsrefresh1'});
    final journal = BrokerOrderJournal(mem, a.id, clock: () => now);
    await journal.append('oat-tsunknown0000001', 'INTENT', {'state': OrderState.intent, 'contract': call,
        'side': 'BUY_TO_OPEN', 'quantity': 2, 'limitCents': 125});
    await journal.append('oat-tsunknown0000001', 'SEND_RESULT', {'state': OrderState.unknown, 'code': 'TIMEOUT'});
    Map<String, dynamic> tsOrder(String id) => {'OrderID': id, 'Status': 'FLL', 'LimitPrice': '1.25',
      'Legs': [{'Symbol': 'AAPL 261120C200', 'BuyOrSell': 'Buy', 'QuantityOrdered': '2', 'ExecQuantity': '2', 'ExecutionPrice': '1.25'}]};
    var list = [tsOrder('900'), tsOrder('901')];
    final svc = BrokerOrderService(reg, requireEligibility: false, clock: () => now, client: MockClient((r) async {
      switch (r.url.path) {
        case '/oauth/token': return json({'access_token': 'acc1', 'expires_in': 1200});
        case '/v3/brokerage/accounts': return json({'Accounts': [{'AccountID': 'SIM1'}]});
        case '/v3/brokerage/accounts/SIM1/balances': return json({'Balances': [{'AccountID': 'SIM1', 'CashBalance': '1', 'Equity': '1'}]});
        case '/v3/brokerage/accounts/SIM1/positions': return json({'Positions': [{'Symbol': 'AAPL 261120C200', 'Quantity': '2', 'MarketValue': '250', 'UnrealizedProfitLoss': '0'}]});
        case '/v3/brokerage/accounts/SIM1/orders': return json({'Orders': list});
      }
      return json({}, 404);
    }));
    var r = await svc.reconcile(a);
    expect(r.stillUnresolved, ['oat-tsunknown0000001']);
    list = [tsOrder('901')];
    r = await svc.reconcile(a);
    final o = (await journal.orders()).single;
    expect(o.state, OrderState.filled);
    expect(o.brokerOrderId, '901');
    expect(r.discrepancies, isEmpty);
  });

  test('IBKR: status by order_ref; absence never proves NOT_PLACED', () async {
    final a = await reg.add(broker: BrokerKind.ibkr, label: 'IB', values: {'gatewayUrl': 'https://gw.local:5000', 'accountId': 'DU1234567'});
    final journal = BrokerOrderJournal(mem, a.id, clock: () => now);
    await journal.append('oat-ibunknown0000001', 'INTENT', {'state': OrderState.intent, 'contract': call,
        'side': 'BUY_TO_OPEN', 'quantity': 1, 'limitCents': 125});
    var rows = <Map<String, dynamic>>[];
    final svc = BrokerOrderService(reg, requireEligibility: false, clock: () => now, client: MockClient((r) async {
      switch (r.url.path) {
        case '/v1/api/iserver/auth/status': return json({'authenticated': true});
        case '/v1/api/portfolio/accounts': return json([{'accountId': 'DU1234567'}]);
        case '/v1/api/portfolio/DU1234567/summary': return json({});
        case '/v1/api/portfolio/DU1234567/positions/0': return json([]);
        case '/v1/api/iserver/account/orders': return json({'orders': rows});
      }
      return json({}, 404);
    }));
    now = open.add(const Duration(minutes: 5));
    var r = await svc.reconcile(a);
    expect(r.stillUnresolved, ['oat-ibunknown0000001']);
    rows = [{'acct': 'DU1234567', 'orderId': 55, 'order_ref': 'oat-ibunknown0000001', 'status': 'Cancelled', 'filledQuantity': 0}];
    r = await svc.reconcile(a);
    expect((await journal.orders()).single.state, OrderState.canceled);
  });

  testWidgets('reconcile button shows summary and manual resolve needs confirmation', (tester) async {
    late BrokerAccount a;
    await tester.runAsync(() async {
      a = await addAlpaca();
      final j = BrokerOrderJournal(mem, a.id, clock: () => open);
      await j.append('oat-unknown000000002', 'INTENT', {'state': OrderState.intent, 'contract': call,
          'side': 'BUY_TO_OPEN', 'quantity': 1, 'limitCents': 125});
    });
    final client = alpaca(orders: {});
    final svc = BrokerOrderService(reg, requireEligibility: false, client: client, clock: () => open.add(const Duration(seconds: 10)));
    await tester.pumpWidget(MaterialApp(home: Directionality(textDirection: TextDirection.rtl,
        child: BrokerPortfolioScreen(account: a, registry: reg, client: client, clock: () => open.add(const Duration(seconds: 10)), orderService: svc))));
    Future<void> settle() async {
      for (var i = 0; i < 20 && find.byType(LinearProgressIndicator).evaluate().isNotEmpty || i < 3; i++) {
        await tester.runAsync(() => Future<void>.delayed(const Duration(milliseconds: 10)));
        await tester.pump(const Duration(milliseconds: 50));
      }
      await tester.pumpAndSettle();
    }
    await settle();
    await tester.ensureVisible(find.byKey(const ValueKey('reconcile-orders')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('reconcile-orders')));
    await settle();
    expect(find.textContaining('غير محسوم 1'), findsOneWidget);
    await tester.ensureVisible(find.byTooltip('حسم يدوي'));
    await tester.pumpAndSettle();
    await tester.tap(find.byTooltip('حسم يدوي'));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('confirm-resolve')));
    await settle();
    expect(find.textContaining('حُسم يدويًا'), findsOneWidget);
  });
}
