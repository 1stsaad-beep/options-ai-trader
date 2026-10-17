import 'dart:convert';
import 'dart:math';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:options_ai_trader/direct_alpaca.dart';
import 'package:options_ai_trader/brokers/broker_models.dart';
import 'package:options_ai_trader/brokers/broker_options.dart';
import 'package:options_ai_trader/brokers/broker_order_admission.dart';
import 'package:options_ai_trader/brokers/broker_order_journal.dart';
import 'package:options_ai_trader/brokers/broker_order_service.dart';
import 'package:options_ai_trader/brokers/broker_portfolio.dart';
import 'package:options_ai_trader/brokers/broker_portfolio_screen.dart';
import 'package:options_ai_trader/brokers/broker_store.dart';

const call = 'AAPL261120C00200000', put = 'AAPL261120P00180000';
// Monday 2026-10-19 11:00 New York (EDT) — inside the entry window.
final open = DateTime.utc(2026, 10, 19, 15, 0, 0);

http.Response json(Object body, [int status = 200]) =>
    http.Response(jsonEncode(body), status, headers: {'content-type': 'application/json'});

BrokerAccount acct(BrokerKind kind, {BrokerEnvironment env = BrokerEnvironment.paper}) => BrokerAccount(
    id: '${kind.name}-t', label: 't', broker: kind, environment: env, createdAt: open,
    settings: kind == BrokerKind.ibkr ? const {'gatewayUrl': 'https://gw.local:5000', 'accountId': 'DU1234567'} : const {});

BrokerPortfolio portfolio({String cash = '10000.00', String equity = '10000.00', String? bp = '20000.00',
        List<BrokerPosition> positions = const [], DateTime? at, BrokerKind kind = BrokerKind.alpaca,
        BrokerEnvironment env = BrokerEnvironment.paper}) =>
    BrokerPortfolio(acct(kind, env: env), BrokerAccountSnapshot(broker: kind, brokerAccountId: 'X', cash: cash, equity: equity,
        buyingPower: bp, paperVerified: true), positions, at ?? open);

BrokerQuote quote({String contract = call, int bid = 120, int ask = 125, int size = 50, DateTime? at}) => BrokerQuote(
    contract: contract, bid: bid, ask: ask, bidSize: size, askSize: size, time: at ?? open.subtract(const Duration(seconds: 2)),
    source: 'test', timeSource: 'QUOTE');

BrokerOrderTicket buy({String contract = call, int qty = 1, int limit = 125, String? conid}) =>
    BrokerOrderTicket(contract: contract, side: TicketSide.buyToOpen, quantity: qty, limitCents: limit, ibkrConid: conid);
BrokerOrderTicket sell({String contract = call, int qty = 1, int limit = 120}) =>
    BrokerOrderTicket(contract: contract, side: TicketSide.sellToClose, quantity: qty, limitCents: limit);

BrokerOrderRecord record(String contract, String side, String state, {int qty = 1, int cost = 12570}) =>
    BrokerOrderJournal.fold([
      {'seq': 1, 'clientOrderId': 'oat-x', 'type': 'INTENT', 'state': OrderState.intent, 'contract': contract,
        'side': side, 'quantity': qty, 'costCents': cost},
      if (state != OrderState.intent) {'seq': 2, 'clientOrderId': 'oat-x', 'type': 'ACK', 'state': state},
    ]).single;

String? reason(BrokerOrderTicket t, {BrokerPortfolio? p, BrokerQuote? q, bool noQuote = false,
        List<BrokerOrderRecord> orders = const [], DateTime? now}) =>
    admitBrokerOrder(t, p ?? portfolio(), noQuote ? null : (q ?? quote(contract: t.contract)), orders, now ?? open).reason;

BrokerPosition pos(String symbol, String qty, {String mv = '250', String pl = '0', String? conid}) =>
    BrokerPosition(symbol: symbol, quantity: qty, marketValue: mv, unrealizedPl: pl, contractId: conid);

void main() {
  group('contract identity and money', () {
    test('OCC and TradeStation symbols round-trip', () {
      final c = OccContract.parse(call)!;
      expect(c.tradeStationSymbol, 'AAPL 261120C200');
      expect(OccContract.parse('SPY261120P00502500')!.tradeStationSymbol, 'SPY 261120P502.5');
      expect(OccContract.fromTradeStation('SPY 261120P502.5')!.occ, 'SPY261120P00502500');
      expect(OccContract.parse('AAPL261320C00200000'), isNotNull); // calendar validity is checked by paperExpiry
      expect(OccContract.parse('bad'), isNull);
    });
    test('decimal cents are exact and conservative', () {
      expect(decimalCents('1.25'), 125);
      expect(decimalCents('1.251'), 125);
      expect(decimalCents('1.251', up: true), 126);
      expect(decimalCents('-30.505'), -3051);
      expect(decimalCents('-30.505', up: true), -3050);
      expect(decimalCents('1e3'), isNull);
      expect(centsText(-305), '-3.05');
    });
  });

  group('admission', () {
    test('qualified buy is admitted with conservative fee', () {
      final a = admitBrokerOrder(buy(qty: 2), portfolio(), quote(), const [], open);
      expect(a.reason, isNull);
      expect(a.costCents, 2 * 125 * 100 + 2 * 70);
      expect(a.passed, containsAll(['PAPER_ONLY', 'SESSION', 'QUALIFIED_QUOTE', 'OPPOSITE_DIRECTION_LOCK', 'TRADE_RISK']));
    });
    test('Live accounts and archived accounts are refused', () {
      expect(reason(buy(), p: portfolio(env: BrokerEnvironment.live)), 'LIVE_NOT_APPROVED');
    });
    test('session, expiry, freshness and quote gates', () {
      expect(reason(buy(), now: DateTime.utc(2026, 10, 17, 15)), 'SESSION_NO_SESSION');
      expect(reason(buy(), now: DateTime.utc(2026, 10, 19, 12)), 'SESSION_PREOPEN');
      expect(reason(buy(contract: 'AAPL261019C00200000'), q: quote(contract: 'AAPL261019C00200000')), 'EXPIRY_CLOSE_ONLY');
      expect(reason(buy(), p: portfolio(at: open.subtract(const Duration(seconds: 61)))), 'PORTFOLIO_STALE');
      expect(reason(buy(), noQuote: true), 'QUOTE_UNAVAILABLE');
      expect(reason(buy(), q: quote(contract: put)), 'QUOTE_MISMATCH');
      expect(reason(buy(), q: quote(at: open.subtract(const Duration(seconds: 31)))), 'QUOTE_STALE');
      expect(reason(buy(limit: 100), q: quote(bid: 80, ask: 125)), 'QUOTE_SPREAD_TOO_WIDE');
      expect(reason(buy(qty: 3), q: quote(size: 2)), 'QUOTE_SIZE_INSUFFICIENT');
      expect(reason(buy(limit: 130)), 'LIMIT_OUTSIDE_QUOTE');
      expect(reason(buy(limit: 119)), 'LIMIT_OUTSIDE_QUOTE');
    });
    test('unresolved orders block everything', () {
      expect(reason(buy(), orders: [record(put, 'BUY_TO_OPEN', OrderState.unknown)]), 'UNRESOLVED_ORDER_RECONCILE_REQUIRED');
      expect(reason(buy(), orders: [record(put, 'BUY_TO_OPEN', OrderState.intent)]), 'UNRESOLVED_ORDER_RECONCILE_REQUIRED');
    });
    test('opposite-direction lock covers holdings and open orders', () {
      expect(reason(buy(), p: portfolio(positions: [pos(put, '1')])), 'OPPOSITE_DIRECTION_LOCK');
      expect(reason(buy(), orders: [record(put, 'BUY_TO_OPEN', OrderState.open)]), 'OPPOSITE_DIRECTION_LOCK');
      expect(reason(buy(), orders: [record(put, 'BUY_TO_OPEN', OrderState.canceled)]), isNull);
      expect(reason(buy(), p: portfolio(positions: [pos('MSFT261120P00300000', '1')])), isNull);
    });
    test('risk caps reuse paper defaults', () {
      expect(reason(buy(qty: 1), p: portfolio(cash: '100.00')), 'RISK_LIMIT');
      expect(reason(buy(qty: 4)), 'RISK_LIMIT'); // 4*125*100+280 > 5% of 10000.00
      expect(reason(buy(qty: 1), p: portfolio(positions: [pos('MSFT261120C00300000', '1', mv: '2900')])),
          'ALLOCATION_RISK_LIMIT');
      expect(reason(buy(qty: 1, limit: 125), p: portfolio(equity: '1000000.00', cash: '1000000.00', bp: null,
          positions: [pos('MSFT261120C00300000', '10', mv: '100')])), 'CONTRACT_COUNT_RISK_LIMIT');
      expect(reason(buy(), p: portfolio(positions: [for (final s in ['MSFT', 'NVDA', 'TSLA', 'AMD']) pos('${s}261120C00100000', '1', mv: '10')])),
          'POSITION_COUNT_RISK_LIMIT');
      expect(reason(buy(), p: portfolio(positions: [pos('MSFT261120C00300000', '1', mv: '10', pl: '-300')])),
          'DAILY_LOSS_RISK_LIMIT');
      expect(reason(buy(), p: portfolio(positions: [const BrokerPosition(symbol: 'MSFT261120C00300000', quantity: '1')])),
          'RISK_UNAVAILABLE_POSITION_MARK');
      expect(reason(buy(), p: portfolio(cash: 'n/a')), 'BALANCE_UNAVAILABLE');
    });
    test('closing needs an owned long position but is not vetoed by entry caps', () {
      expect(reason(sell()), 'CLOSE_EXCEEDS_POSITION');
      final losing = portfolio(cash: '0.00', positions: [pos(call, '2', mv: '10', pl: '-5000')]);
      final a = admitBrokerOrder(sell(qty: 2), losing, quote(), const [], open);
      expect(a.reason, isNull);
      expect(a.costCents, -(2 * 120 * 100) + 140);
      expect(reason(sell(qty: 2), p: losing, orders: [record(call, 'SELL_TO_CLOSE', OrderState.open)]), 'CLOSE_EXCEEDS_POSITION');
      expect(reason(sell(), p: portfolio(positions: [pos(call, '-1')])), 'SHORT_OPTION_REVIEW_REQUIRED');
      // Closing is allowed in the exit window after the entry cutoff.
      expect(reason(sell(), p: portfolio(positions: [pos(call, '1')], at: DateTime.utc(2026, 10, 19, 19, 50)),
          now: DateTime.utc(2026, 10, 19, 19, 50), q: quote(at: DateTime.utc(2026, 10, 19, 19, 49, 50))), isNull);
      expect(reason(buy(), p: portfolio(at: DateTime.utc(2026, 10, 19, 19, 50)), now: DateTime.utc(2026, 10, 19, 19, 50),
          q: quote(at: DateTime.utc(2026, 10, 19, 19, 49, 50))), 'SESSION_EXIT_WINDOW');
    });
    test('IBKR requires conid', () {
      expect(reason(buy(), p: portfolio(kind: BrokerKind.ibkr)), 'IBKR_CONID_REQUIRED');
      expect(reason(buy(conid: '265598'), p: portfolio(kind: BrokerKind.ibkr)), isNull);
    });
  });

  group('service', () {
    late MemorySecureKeyValue mem;
    late BrokerAccountRegistry reg;
    late DateTime now;
    setUp(() {
      mem = MemorySecureKeyValue();
      reg = BrokerAccountRegistry(mem, random: Random(3));
      now = open;
    });
    OptionQuote direct({int bid = 120, int ask = 125, DateTime? at}) =>
        OptionQuote(call, 'opra', at ?? now.subtract(const Duration(seconds: 1)), bid, ask, 50, 50);

    MockClient alpaca({required Future<http.Response> Function(http.Request) order, List<String>? log}) => MockClient((r) async {
          log?.add('${r.method} ${r.url.host}${r.url.path}');
          expect(r.url.host, 'paper-api.alpaca.markets');
          if (r.url.path == '/v2/account') return json({'account_number': 'PA1', 'cash': '10000', 'equity': '10000', 'buying_power': '20000'});
          if (r.url.path == '/v2/positions') return json([]);
          if (r.url.path == '/v2/orders') return order(r);
          return json({}, 404);
        });

    Future<BrokerAccount> addAlpaca() =>
        reg.add(broker: BrokerKind.alpaca, label: 'A', values: {'keyId': 'PKFIXTURE1', 'secretKey': 'fixturesecret1'});

    test('Alpaca: intent persisted before send, OCC limit order to paper-api, ACK journaled', () async {
      final a = await addAlpaca();
      late Map body;
      late BrokerOrderService svc;
      final client = alpaca(order: (r) async {
        final events = await svc.journal(a).events();
        expect(events.single['type'], 'INTENT');
        expect(events.single['confirmedByUser'], true);
        body = jsonDecode(r.body) as Map;
        return json({'id': 'alp-1', 'status': 'accepted'});
      });
      svc = BrokerOrderService(reg, client: client, clock: () => now, directQuote: (_) async => direct());
      final review = await svc.review(a, buy());
      expect(review.admission.admitted, isTrue);
      now = now.add(const Duration(seconds: 5));
      final out = await svc.submit(review);
      expect(out.state, OrderState.open);
      expect(body['symbol'], call);
      expect(body['type'], 'limit');
      expect(body['limit_price'], '1.25');
      expect(body['client_order_id'], out.clientOrderId);
      final orders = await svc.journal(a).orders();
      expect(orders.single.state, OrderState.open);
      expect(orders.single.brokerOrderId, 'alp-1');
      expect(orders.single.events.map((e) => e['seq']), [1, 2]);
      expect(jsonEncode(mem.data[BrokerOrderJournal.key(a.id)]), isNot(contains('fixturesecret1')));
    });

    test('timeouts become UNKNOWN and block the account; definitive rejects do not', () async {
      final a = await addAlpaca();
      var mode = 'timeout';
      final svc = BrokerOrderService(reg, clock: () => now, directQuote: (_) async => direct(),
          client: alpaca(order: (r) async {
            if (mode == 'timeout') throw http.ClientException('reset');
            return json({'message': 'invalid'}, 422);
          }));
      final first = await svc.submit(await svc.review(a, buy()));
      expect(first.state, OrderState.unknown);
      expect((await svc.review(a, buy())).admission.reason, 'UNRESOLVED_ORDER_RECONCILE_REQUIRED');

      final b = await reg.add(broker: BrokerKind.alpaca, label: 'B', values: {'keyId': 'PKFIXTURE2', 'secretKey': 'fixturesecret2'});
      mode = 'reject';
      final second = await svc.submit(await svc.review(b, buy()));
      expect(second.state, OrderState.rejected);
      expect(second.code, 'HTTP_422');
      expect((await svc.review(b, buy())).admission.admitted, isTrue);
    });

    test('expired review and failed re-validation never send or journal', () async {
      final a = await addAlpaca();
      var posts = 0;
      var q = direct();
      final svc = BrokerOrderService(reg, clock: () => now, directQuote: (_) async => q,
          client: alpaca(order: (r) async { posts++; return json({'id': 'x', 'status': 'new'}); }));
      final review = await svc.review(a, buy());
      now = now.add(const Duration(seconds: 61));
      await expectLater(svc.submit(review), throwsA(isA<BrokerException>().having((e) => e.code, 'code', 'REVIEW_EXPIRED')));
      now = open;
      final again = await svc.review(a, buy());
      q = direct(bid: 130, ask: 135); // market moved: limit 1.25 no longer within quote
      await expectLater(svc.submit(again), throwsA(isA<BrokerException>().having((e) => e.code, 'code', 'LIMIT_OUTSIDE_QUOTE')));
      expect(posts, 0);
      expect(await svc.journal(a).events(), isEmpty);
    });

    test('Alpaca without the Direct OPRA quote fails closed', () async {
      final a = await addAlpaca();
      final svc = BrokerOrderService(reg, clock: () => now, directQuote: (_) async => null,
          client: alpaca(order: (r) async => fail('must not send')));
      expect((await svc.review(a, buy())).admission.reason, 'QUOTE_UNAVAILABLE');
    });

    test('TradeStation: SIM quote and order with TradeStation option symbol', () async {
      final a = await reg.add(broker: BrokerKind.tradestation, label: 'TS',
          values: {'clientId': 'tsclient1', 'clientSecret': 'tssecret1', 'refreshToken': 'tsrefresh1'});
      late Map body;
      final svc = BrokerOrderService(reg, clock: () => now, client: MockClient((r) async {
        expect(['sim-api.tradestation.com', 'signin.tradestation.com'], contains(r.url.host));
        switch (r.url.path) {
          case '/oauth/token': return json({'access_token': 'acc1', 'expires_in': 1200});
          case '/v3/brokerage/accounts': return json({'Accounts': [{'AccountID': 'SIM1'}]});
          case '/v3/brokerage/accounts/SIM1/balances':
            return json({'Balances': [{'AccountID': 'SIM1', 'CashBalance': '10000', 'Equity': '10000', 'BuyingPower': '20000'}]});
          case '/v3/brokerage/accounts/SIM1/positions': return json({'Positions': []});
          case '/v3/marketdata/quotes/AAPL%20261120C200': // single percent-encoding
            return json({'Quotes': [{'Symbol': 'AAPL 261120C200', 'Bid': '1.20', 'Ask': '1.25', 'BidSize': 40, 'AskSize': 40}]});
          case '/v3/orderexecution/orders':
            body = jsonDecode(r.body) as Map;
            return json({'Orders': [{'OrderID': '777', 'Message': 'Sent'}]});
        }
        return json({}, 404);
      }));
      final review = await svc.review(a, buy());
      expect(review.quote!.timeSource, 'RECEIVED');
      final out = await svc.submit(review);
      expect(out.brokerOrderId, '777');
      expect(body['Symbol'], 'AAPL 261120C200');
      expect(body['TradeAction'], 'BUYTOOPEN');
      expect(body['LimitPrice'], '1.25');
    });

    test('IBKR: snapshot quote by conid; confirmation prompts are terminal NOT placed', () async {
      final a = await reg.add(broker: BrokerKind.ibkr, label: 'IB', values: {'gatewayUrl': 'https://gw.local:5000', 'accountId': 'DU1234567'});
      final svc = BrokerOrderService(reg, clock: () => now, client: MockClient((r) async {
        switch (r.url.path) {
          case '/v1/api/iserver/auth/status': return json({'authenticated': true, 'connected': true});
          case '/v1/api/portfolio/accounts': return json([{'accountId': 'DU1234567'}]);
          case '/v1/api/portfolio/DU1234567/summary':
            return json({'totalcashvalue': {'amount': 10000}, 'netliquidation': {'amount': 10000}, 'buyingpower': {'amount': 20000}});
          case '/v1/api/portfolio/DU1234567/positions/0': return json([]);
          case '/v1/api/iserver/marketdata/snapshot':
            expect(r.url.queryParameters['conids'], '265598');
            return json([{'conid': 265598, '84': '1.20', '86': '1.25', '88': '30', '85': '30',
              '_updated': now.subtract(const Duration(seconds: 1)).millisecondsSinceEpoch}]);
          case '/v1/api/iserver/account/DU1234567/orders':
            return json([{'id': 'reply-9', 'message': ['Confirm price']}]);
        }
        return json({}, 404);
      }));
      final out = await svc.submit(await svc.review(a, buy(conid: '265598')));
      expect(out.state, OrderState.confirmationRequired);
      final o = (await svc.journal(a).orders()).single;
      expect(o.terminal, isTrue);
      expect((await svc.review(a, buy(conid: '265598'))).admission.admitted, isTrue);
    });

    test('corrupt journal is never overwritten and blocks sending', () async {
      final a = await addAlpaca();
      mem.data[BrokerOrderJournal.key(a.id)] = '{"version":1,"account":"other","events":[]}';
      final svc = BrokerOrderService(reg, clock: () => now, directQuote: (_) async => direct(),
          client: alpaca(order: (r) async => fail('must not send')));
      await expectLater(svc.review(a, buy()), throwsA(isA<BrokerJournalException>()));
      expect(mem.data[BrokerOrderJournal.key(a.id)], contains('"other"'));
    });
  });

  group('ticket UI', () {
    Future<void> settle(WidgetTester tester) async {
      for (var i = 0; i < 20 && find.byType(LinearProgressIndicator).evaluate().isNotEmpty || i < 3; i++) {
        await tester.runAsync(() => Future<void>.delayed(const Duration(milliseconds: 10)));
        await tester.pump(const Duration(milliseconds: 50));
      }
      await tester.pumpAndSettle();
    }

    testWidgets('review then explicit confirm sends; cancel sends nothing', (tester) async {
      final mem = MemorySecureKeyValue();
      final reg = BrokerAccountRegistry(mem);
      late BrokerAccount a;
      await tester.runAsync(() async {
        a = await reg.add(broker: BrokerKind.alpaca, label: 'Alpaca 1', values: {'keyId': 'PKFIXTURE1', 'secretKey': 'fixturesecret1'});
      });
      var posts = 0;
      final client = MockClient((r) async {
        if (r.url.path == '/v2/account') return json({'account_number': 'PA1', 'cash': '10000', 'equity': '10000', 'buying_power': '20000'});
        if (r.url.path == '/v2/positions') return json([]);
        posts++;
        return json({'id': 'alp-$posts', 'status': 'accepted'});
      });
      final svc = BrokerOrderService(reg, client: client, clock: () => open,
          directQuote: (_) async => OptionQuote(call, 'opra', open.subtract(const Duration(seconds: 1)), 120, 125, 50, 50));
      await tester.pumpWidget(MaterialApp(home: Directionality(textDirection: TextDirection.rtl,
          child: BrokerPortfolioScreen(account: a, registry: reg, client: client, clock: () => open, orderService: svc))));
      await settle(tester);
      Future<void> fillAndReview() async {
        await tester.tap(find.byKey(const ValueKey('new-paper-order')));
        await tester.pumpAndSettle();
        await tester.enterText(find.byKey(const ValueKey('ticket-contract')), call);
        await tester.enterText(find.byKey(const ValueKey('ticket-limit')), '1.25');
        await tester.tap(find.text('مراجعة'));
        await settle(tester);
        expect(find.text('مقبول بعد الفحوص. يلزم تأكيدك للإرسال.'), findsOneWidget);
        await tester.tap(find.text('إرسال…'));
        await tester.pumpAndSettle();
        expect(find.text('تأكيد إرسال أمر Paper'), findsOneWidget);
      }
      await fillAndReview();
      await tester.tap(find.text('إلغاء'));
      await tester.pumpAndSettle();
      expect(posts, 0);
      await tester.tap(find.text('إغلاق'));
      await tester.pumpAndSettle();
      await fillAndReview();
      await tester.tap(find.byKey(const ValueKey('confirm-send')));
      await settle(tester);
      expect(posts, 1);
      expect(find.textContaining('مفتوح لدى الوسيط'), findsWidgets);
      expect(find.text('أوامر Paper (1)'), findsOneWidget);
    });
  });
}
