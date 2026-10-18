import 'dart:convert';

import 'package:test/test.dart';
import 'package:trader_core/trader_core.dart';

class FakeHttp implements HttpTransport {
  final List<(String, Uri, Map<String, String>, String?)> calls = [];
  final HttpResult Function(String method, Uri url, String? body) responder;
  FakeHttp(this.responder);

  @override
  Future<HttpResult> send(String method, Uri url, {Map<String, String> headers = const {}, String? body}) async {
    calls.add((method, url, headers, body));
    return responder(method, url, body);
  }
}

void main() {
  const creds = BrokerCredentials({'keyId': 'PKTEST', 'secretKey': 'secret'});
  final now = DateTime.utc(2026, 6, 1, 15);
  final contract = OptionContract(underlying: 'AAPL', right: OptionRight.call, expiry: DateTime.utc(2026, 6, 19), strikeCents: 20000);

  group('Alpaca', () {
    test('paper endpoints, auth headers and balance parsing', () async {
      final http = FakeHttp((m, u, b) => HttpResult(
          200, jsonEncode({'status': 'ACTIVE', 'cash': '1000.50', 'equity': '1200.00', 'options_buying_power': '900'})));
      final a = AlpacaAdapter(accountId: 'acc', credentials: creds, http: http, clock: () => now);
      await a.connect();
      final snap = await a.account();
      expect(snap.cashCents, 100050);
      expect(snap.equityCents, 120000);
      expect(snap.buyingPowerCents, 90000);
      expect(http.calls.first.$2.host, 'paper-api.alpaca.markets');
      expect(http.calls.first.$3['APCA-API-KEY-ID'], 'PKTEST');
    });

    test('order payload is a buy-to-open limit order with OCC symbol', () async {
      final http = FakeHttp((m, u, b) => HttpResult(
          200,
          jsonEncode({
            'id': 'ord-1',
            'client_order_id': 'cid',
            'symbol': contract.occSymbol,
            'asset_class': 'us_option',
            'side': 'buy',
            'qty': '2',
            'filled_qty': '0',
            'limit_price': '3.10',
            'status': 'accepted',
            'created_at': now.toIso8601String(),
          })));
      final a = AlpacaAdapter(accountId: 'acc', credentials: creds, http: http, clock: () => now);
      final o = await a.placeOrder(OrderRequest(
          clientOrderId: 'cid', contract: contract, side: OrderSide.buyToOpen, quantity: 2, limitPriceCents: 310));
      final body = jsonDecode(http.calls.single.$4!) as Map<String, dynamic>;
      expect(body['symbol'], 'AAPL260619C00200000');
      expect(body['type'], 'limit');
      expect(body['limit_price'], '3.10');
      expect(body['position_intent'], 'buy_to_open');
      expect(o.status, OrderStatus.pending);
      expect(o.quantity, 2);
    });

    test('live mode is refused before any HTTP request', () async {
      final http = FakeHttp((m, u, b) => const HttpResult(200, '{}'));
      final a = AlpacaAdapter(accountId: 'acc', credentials: creds, http: http, mode: TradingMode.live, clock: () => now);
      await expectLater(
        a.placeOrder(OrderRequest(clientOrderId: 'x', contract: contract, side: OrderSide.buyToOpen, quantity: 1, limitPriceCents: 1)),
        throwsA(isA<BrokerException>().having((e) => e.code, 'code', BrokerErrorCode.liveLocked)),
      );
      expect(http.calls, isEmpty);
    });

    test('HTTP errors are categorised', () async {
      final http = FakeHttp((m, u, b) => const HttpResult(401, '{"message":"forbidden"}'));
      final a = AlpacaAdapter(accountId: 'acc', credentials: creds, http: http, clock: () => now);
      await expectLater(a.account(), throwsA(isA<BrokerException>().having((e) => e.code, 'code', BrokerErrorCode.auth)));
    });

    test('positions ignore stocks and short options', () async {
      final http = FakeHttp((m, u, b) => HttpResult(
          200,
          jsonEncode([
            {'symbol': 'AAPL', 'asset_class': 'us_equity', 'qty': '10', 'avg_entry_price': '190'},
            {'symbol': contract.occSymbol, 'asset_class': 'us_option', 'qty': '3', 'avg_entry_price': '2.50'},
            {'symbol': 'AAPL260619P00180000', 'asset_class': 'us_option', 'qty': '-1', 'avg_entry_price': '1.00'},
          ])));
      final a = AlpacaAdapter(accountId: 'acc', credentials: creds, http: http, clock: () => now);
      final p = await a.positions();
      expect(p, hasLength(1));
      expect(p.single.contract, contract);
      expect(p.single.averageCostCents, 250);
    });
  });

  group('IBKR', () {
    test('paper mode refuses a non-paper (non-DU) account', () async {
      final http = FakeHttp((m, u, b) => HttpResult(200, jsonEncode({'authenticated': true})));
      final a = IbkrAdapter(
          accountId: 'acc',
          credentials: const BrokerCredentials({'gatewayUrl': 'https://10.0.0.2:5000', 'accountId': 'U123'}),
          http: http,
          clock: () => now);
      await expectLater(a.connect(), throwsA(isA<BrokerException>()));
    });
  });

  group('credentials', () {
    test('completeness per broker', () {
      expect(const BrokerCredentials({}).isCompleteFor(BrokerKind.simulator), isTrue);
      expect(creds.isCompleteFor(BrokerKind.alpaca), isTrue);
      expect(creds.isCompleteFor(BrokerKind.tradestation), isFalse);
    });
  });
}
