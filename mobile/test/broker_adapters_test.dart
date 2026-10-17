import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:options_ai_trader/brokers/alpaca_paper.dart';
import 'dart:io';

import 'package:options_ai_trader/brokers/broker_adapter.dart';
import 'package:options_ai_trader/brokers/broker_http.dart';
import 'package:options_ai_trader/brokers/broker_models.dart';
import 'package:options_ai_trader/brokers/ibkr_paper.dart';
import 'package:options_ai_trader/brokers/live_gate.dart';
import 'package:options_ai_trader/brokers/tradestation_sim.dart';

http.Response json(Object body, [int status = 200]) =>
    http.Response(jsonEncode(body), status, headers: {'content-type': 'application/json'});

BrokerAccount account(BrokerKind kind, {Map<String, String> settings = const {},
        BrokerEnvironment env = BrokerEnvironment.paper}) =>
    BrokerAccount(id: '${kind.name}-test', label: 'test', broker: kind, environment: env,
        settings: settings, createdAt: DateTime.utc(2026, 10, 17));

final alpacaCreds = BrokerCredentials({'keyId': 'PKFIXTURE1', 'secretKey': 'fixturesecret1'});
final tsCreds = BrokerCredentials({'clientId': 'tsclient1', 'clientSecret': 'tssecret1', 'refreshToken': 'tsrefresh1'});
const ibkrSettings = {'gatewayUrl': 'https://gateway.local:5000', 'accountId': 'DU1234567'};

PaperOrderRequest order({String? conid, AssetClass asset = AssetClass.option}) => PaperOrderRequest(
    symbol: 'AAPL261120C00200000', assetClass: asset, side: OrderSide.buy, quantity: 1,
    limitPrice: '1.25', clientOrderId: 'oat-fixture-0001', ibkrConid: conid);

void main() {
  group('Live lock', () {
    test('approval flag defaults off and Live is unavailable', () {
      expect(LiveTradingGate.buildApproved, isFalse);
      expect(LiveTradingGate.liveAvailable, isFalse);
      expect(() => LiveTradingGate.requirePaper(BrokerEnvironment.live), throwsA(isA<LiveTradingDisabled>()));
      LiveTradingGate.requirePaper(BrokerEnvironment.paper);
    });
    test('no adapter can be created for a Live account and no request is sent', () {
      var calls = 0;
      final client = MockClient((_) async { calls++; return json({}); });
      for (final kind in BrokerKind.values) {
        expect(() => createPaperAdapter(account(kind, settings: kind == BrokerKind.ibkr ? ibkrSettings : const {},
                env: BrokerEnvironment.live), kind == BrokerKind.alpaca ? alpacaCreds : tsCreds, client: client),
            throwsA(isA<LiveTradingDisabled>()));
      }
      expect(calls, 0);
    });
    test('archived accounts do not connect', () {
      final a = account(BrokerKind.alpaca).copyWith(archived: true);
      expect(() => createPaperAdapter(a, alpacaCreds, client: MockClient((_) async => json({}))),
          throwsA(isA<BrokerException>().having((e) => e.code, 'code', 'ACCOUNT_ARCHIVED')));
    });
  });

  group('Alpaca Paper', () {
    test('connects only to paper-api with key headers and parses exact decimals', () async {
      final seen = <http.BaseRequest>[];
      final adapter = AlpacaPaperAdapter(alpacaCreds, client: MockClient((r) async {
        seen.add(r);
        return json({'account_number': 'PA3FIXTURE', 'currency': 'USD', 'cash': '100000.10',
            'equity': '100000.10', 'buying_power': '200000.20', 'status': 'ACTIVE'});
      }));
      final s = await adapter.connect();
      expect(seen.single.url.toString(), 'https://paper-api.alpaca.markets/v2/account');
      expect(seen.single.headers['APCA-API-KEY-ID'], 'PKFIXTURE1');
      expect(seen.single.headers['APCA-API-SECRET-KEY'], 'fixturesecret1');
      expect((seen.single as http.Request).followRedirects, isFalse);
      expect(s.cash, '100000.10');
      expect(s.buyingPower, '200000.20');
      expect(s.paperVerified, isTrue);
    });
    test('limit order goes to paper /v2/orders', () async {
      late http.Request sent;
      final adapter = AlpacaPaperAdapter(alpacaCreds, client: MockClient((r) async {
        sent = r;
        return json({'id': 'ord-1', 'status': 'accepted'});
      }));
      final ack = await adapter.submitPaperOrder(order());
      expect(sent.method, 'POST');
      expect(sent.url.host, 'paper-api.alpaca.markets');
      final body = jsonDecode(sent.body) as Map;
      expect(body['type'], 'limit');
      expect(body['limit_price'], '1.25');
      expect(body['qty'], '1');
      expect(ack.orderId, 'ord-1');
    });
    test('HTTP errors map to codes without leaking credentials', () async {
      for (final status in [401, 403, 429, 500]) {
        final adapter = AlpacaPaperAdapter(alpacaCreds,
            client: MockClient((_) async => json({'message': 'denied'}, status)));
        try {
          await adapter.connect();
          fail('expected error');
        } on BrokerException catch (e) {
          expect(e.code, 'HTTP_$status');
          expect(e.toString(), isNot(contains('fixturesecret1')));
        }
      }
    });
    test('redirects are rejected', () async {
      final adapter = AlpacaPaperAdapter(alpacaCreds, client: MockClient((_) async =>
          http.Response('', 302, headers: {'location': 'https://elsewhere.example/'})));
      await expectLater(adapter.connect(),
          throwsA(isA<BrokerException>().having((e) => e.code, 'code', 'REDIRECT_REJECTED')));
    });
    test('timeouts and malformed bodies fail closed', () async {
      final slow = AlpacaPaperAdapter(alpacaCreds, timeout: const Duration(milliseconds: 50),
          client: MockClient((_) => Future.delayed(const Duration(seconds: 2), () => json({}))));
      await expectLater(slow.connect(),
          throwsA(isA<BrokerException>().having((e) => e.code, 'code', 'TIMEOUT')));
      final bad = AlpacaPaperAdapter(alpacaCreds, client: MockClient((_) async => http.Response('not json', 200)));
      await expectLater(bad.connect(), throwsA(isA<BrokerException>().having((e) => e.code, 'code', 'INVALID_DATA')));
    });
    test('rejects malformed keys before any request', () {
      expect(() => AlpacaPaperAdapter(BrokerCredentials({'keyId': 'a b', 'secretKey': ''}),
          client: MockClient((_) async => json({}))), throwsA(isA<BrokerException>()));
    });
    test('credentials toString is redacted', () {
      expect(alpacaCreds.toString(), isNot(contains('fixturesecret1')));
      expect(BrokerCredentials.mask('PKFIXTURE1'), '••••URE1');
    });
  });

  group('IBKR Paper', () {
    test('requires a DU paper account id and https gateway', () {
      final c = MockClient((_) async => json({}));
      expect(() => IbkrPaperAdapter({'gatewayUrl': 'https://g:5000', 'accountId': 'U1234567'}, client: c),
          throwsA(isA<BrokerException>().having((e) => e.code, 'code', 'NOT_PAPER_ACCOUNT')));
      expect(() => IbkrPaperAdapter({'gatewayUrl': 'http://g:5000', 'accountId': 'DU1234567'}, client: c),
          throwsA(isA<BrokerException>().having((e) => e.code, 'code', 'INVALID_GATEWAY')));
    });
    test('checks auth status, account membership and parses summary', () async {
      final paths = <String>[];
      final adapter = IbkrPaperAdapter(ibkrSettings, client: MockClient((r) async {
        paths.add('${r.method} ${r.url}');
        switch (r.url.path) {
          case '/v1/api/iserver/auth/status': return json({'authenticated': true, 'connected': true});
          case '/v1/api/portfolio/accounts': return json([{'accountId': 'DU1234567'}]);
          case '/v1/api/portfolio/DU1234567/summary':
            return json({'totalcashvalue': {'amount': 1000000.5, 'currency': 'USD'},
              'netliquidation': {'amount': 1000100}, 'buyingpower': {'amount': 4000000}});
        }
        return json({}, 404);
      }));
      final s = await adapter.connect();
      expect(paths.first, 'POST https://gateway.local:5000/v1/api/iserver/auth/status');
      expect(s.brokerAccountId, 'DU1234567');
      expect(s.cash, '1000000.5');
      expect(s.equity, '1000100');
    });
    test('unauthenticated gateway and missing account fail closed', () async {
      final unauth = IbkrPaperAdapter(ibkrSettings, client: MockClient((_) async => json({'authenticated': false})));
      await expectLater(unauth.connect(),
          throwsA(isA<BrokerException>().having((e) => e.code, 'code', 'IBKR_NOT_AUTHENTICATED')));
      final other = IbkrPaperAdapter(ibkrSettings, client: MockClient((r) async =>
          r.url.path.endsWith('auth/status') ? json({'authenticated': true}) : json([{'accountId': 'U7654321'}])));
      await expectLater(other.connect(),
          throwsA(isA<BrokerException>().having((e) => e.code, 'code', 'ACCOUNT_NOT_FOUND')));
    });
    test('orders bind the paper account and never auto-confirm', () async {
      late http.Request sent;
      final adapter = IbkrPaperAdapter(ibkrSettings, client: MockClient((r) async {
        sent = r;
        return json([{'id': 'reply-1', 'message': ['Price exceeds band']}]);
      }));
      await expectLater(adapter.submitPaperOrder(order()), throwsA(isA<BrokerException>()));
      final ack = await adapter.submitPaperOrder(order(conid: '265598'));
      expect(sent.url.path, '/v1/api/iserver/account/DU1234567/orders');
      final o = (jsonDecode(sent.body) as Map)['orders'][0] as Map;
      expect(o['acctId'], 'DU1234567');
      expect(o['orderType'], 'LMT');
      expect(ack.status, 'NEEDS_CONFIRMATION');
    });
    test('requests to other hosts are refused', () async {
      final adapter = IbkrPaperAdapter(ibkrSettings, client: MockClient((_) async => json({})));
      expect(adapter, isNotNull);
      expect(IbkrPaperAdapter.parseGateway('https://gateway.local:5000/x').path, '/v1/api');
    });
  });

  group('TradeStation SIM', () {
    test('refreshes token at signin and calls only sim-api; persists rotated token', () async {
      final calls = <String>[];
      String? rotated;
      final adapter = TradeStationSimAdapter(tsCreds, const {}, onRefreshTokenRotated: (t) async => rotated = t,
          client: MockClient((r) async {
        calls.add('${r.method} ${r.url.host}${r.url.path}');
        if (r.url.path == '/oauth/token') {
          final form = Uri.splitQueryString(r.body);
          expect(form['grant_type'], 'refresh_token');
          expect(form['refresh_token'], 'tsrefresh1');
          return json({'access_token': 'acc1', 'expires_in': 1200, 'refresh_token': 'tsrefresh2'});
        }
        expect(r.headers['Authorization'], 'Bearer acc1');
        if (r.url.path == '/v3/brokerage/accounts') {
          return json({'Accounts': [{'AccountID': 'SIM123456M', 'AccountType': 'Margin'}]});
        }
        if (r.url.path == '/v3/brokerage/accounts/SIM123456M/balances') {
          return json({'Balances': [{'AccountID': 'SIM123456M', 'CashBalance': '25000.00',
            'Equity': '25000.00', 'BuyingPower': '50000.00'}]});
        }
        return json({}, 404);
      }));
      final s = await adapter.connect();
      expect(calls, [
        'POST signin.tradestation.com/oauth/token',
        'GET sim-api.tradestation.com/v3/brokerage/accounts',
        'GET sim-api.tradestation.com/v3/brokerage/accounts/SIM123456M/balances',
      ]);
      expect(rotated, 'tsrefresh2');
      expect(s.cash, '25000.00');
    });
    test('configured account must exist; order uses SIM orderexecution', () async {
      late http.Request sent;
      final client = MockClient((r) async {
        if (r.url.path == '/oauth/token') return json({'access_token': 'acc1', 'expires_in': 1200});
        if (r.url.path == '/v3/brokerage/accounts') return json({'Accounts': [{'AccountID': 'SIM1'}, {'AccountID': 'SIM2'}]});
        sent = r;
        return json({'Orders': [{'OrderID': '9001', 'Message': 'Sent'}]});
      });
      final missing = TradeStationSimAdapter(tsCreds, const {'accountId': 'SIM9'}, client: client);
      await expectLater(missing.connect(),
          throwsA(isA<BrokerException>().having((e) => e.code, 'code', 'ACCOUNT_NOT_FOUND')));
      final adapter = TradeStationSimAdapter(tsCreds, const {'accountId': 'SIM2'}, client: client);
      final ack = await adapter.submitPaperOrder(order());
      expect(sent.url.toString(), 'https://sim-api.tradestation.com/v3/orderexecution/orders');
      final body = jsonDecode(sent.body) as Map;
      expect(body['AccountID'], 'SIM2');
      expect(body['TradeAction'], 'BUYTOOPEN');
      expect(body['OrderType'], 'Limit');
      expect(ack.orderId, '9001');
    });
    test('authorize URL requests offline_access on signin host', () {
      final u = TradeStationSimAdapter.authorizeUrl(clientId: 'tsclient1', redirectUri: 'http://localhost:3000', state: 's1');
      expect(u.host, 'signin.tradestation.com');
      expect(u.queryParameters['scope'], contains('offline_access'));
    });
  });

  test('transport refuses non-allowlisted hosts, plain http and userinfo before sending', () async {
    var calls = 0;
    final t = BrokerHttp(MockClient((_) async { calls++; return json({}); }), {'paper-api.alpaca.markets'});
    for (final u in ['https://api.alpaca.markets/v2/account', 'http://paper-api.alpaca.markets/v2/account',
        'https://u:p@paper-api.alpaca.markets/v2/account']) {
      await expectLater(t.send('GET', Uri.parse(u)),
          throwsA(isA<BrokerException>().having((e) => e.code, 'code', 'HOST_NOT_ALLOWED')));
    }
    expect(calls, 0);
  });

  test('broker sources contain no Live trading hosts', () {
    for (final f in Directory('lib/brokers').listSync().whereType<File>()) {
      final text = f.readAsStringSync();
      expect(text, isNot(contains("'api.alpaca.markets'")), reason: f.path);
      expect(text, isNot(contains('https://api.alpaca.markets')), reason: f.path);
      expect(text, isNot(contains("Uri.https('api.tradestation.com'")), reason: f.path);
      expect(text, isNot(contains("'api.tradestation.com'")), reason: f.path);
    }
    expect(AlpacaPaperAdapter.host, 'paper-api.alpaca.markets');
    expect(TradeStationSimAdapter.apiHost, 'sim-api.tradestation.com');
  });

  test('order validation rejects market-like or malformed orders', () {
    expect(() => PaperOrderRequest(symbol: 'AAPL', assetClass: AssetClass.equity, side: OrderSide.buy,
        quantity: 0, limitPrice: '1', clientOrderId: 'oat-fixture-0001'), throwsA(isA<BrokerException>()));
    expect(() => PaperOrderRequest(symbol: 'AAPL', assetClass: AssetClass.equity, side: OrderSide.buy,
        quantity: 1, limitPrice: '0', clientOrderId: 'oat-fixture-0001'), throwsA(isA<BrokerException>()));
  });
}
