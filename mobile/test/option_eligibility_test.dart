import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:options_ai_trader/direct_alpaca.dart';
import 'package:options_ai_trader/brokers/broker_models.dart';
import 'package:options_ai_trader/brokers/broker_options.dart';
import 'package:options_ai_trader/brokers/broker_order_admission.dart';
import 'package:options_ai_trader/brokers/broker_order_service.dart';
import 'package:options_ai_trader/brokers/broker_order_ticket.dart';
import 'package:options_ai_trader/brokers/broker_store.dart';
import 'package:options_ai_trader/brokers/option_eligibility.dart';

const call = 'AAPL261120C00200000';
final now = DateTime.utc(2026, 10, 19, 15, 0, 0); // Monday, regular session

Map<String, dynamic> terms({Map<String, dynamic> over = const {}, Map<String, dynamic> deliverable = const {}}) => {
      'id': 'c1', 'symbol': call, 'status': 'active', 'tradable': true, 'expiration_date': '2026-11-20',
      'root_symbol': 'AAPL', 'underlying_symbol': 'AAPL', 'underlying_asset_id': 'u1', 'type': 'call',
      'style': 'american', 'strike_price': '200', 'multiplier': '100', 'size': '100',
      'open_interest': '1520', 'open_interest_date': '2026-10-16', 'close_price': '7.05',
      'deliverables': [{'type': 'equity', 'symbol': 'AAPL', 'asset_id': 'u1', 'amount': '100',
        'allocation_percentage': '100', 'settlement_type': 'T+1', 'settlement_method': 'CCC',
        'delayed_settlement': false, ...deliverable}],
      ...over,
    };

BrokerQuote quote({int bid = 700, int ask = 720, String contract = call}) => BrokerQuote(contract: contract, bid: bid,
    ask: ask, bidSize: 50, askSize: 50, time: now.subtract(const Duration(seconds: 2)), source: 'test', timeSource: 'QUOTE');
UnderlyingQuote spot({int bid = 19995, int ask = 20005, Duration age = const Duration(seconds: 3), String symbol = 'AAPL'}) =>
    UnderlyingQuote(symbol, bid, ask, now.subtract(age));

OptionEligibility eval({Map<String, dynamic>? t, BrokerQuote? q, UnderlyingQuote? u, String contract = call,
        EligibilityPolicy policy = const EligibilityPolicy()}) =>
    evaluateEligibility(contract: OccContract.parse(contract)!, terms: t, quote: q, underlying: u, now: now, policy: policy);

http.Response json(Object body, [int status = 200]) =>
    http.Response(jsonEncode(body), status, headers: {'content-type': 'application/json'});

void main() {
  test('standard liquid contract with a fresh quote is eligible with model Greeks', () {
    final e = eval(t: terms(), q: quote(), u: spot());
    expect(e.reasons, isEmpty);
    expect(e.eligible, isTrue);
    expect(e.passed, containsAll(['CONTRACT_TERMS', 'SPREAD', 'UNDERLYING_QUOTE', 'GREEKS']));
    expect(e.facts['greeksSource'], 'MODEL_FROM_QUOTE_MID');
    final iv = e.facts['impliedVol'] as double, delta = (e.facts['greeks'] as Map)['delta'] as double;
    expect(iv, inInclusiveRange(0.25, 0.40));
    expect(delta, inInclusiveRange(0.45, 0.65));
    expect(e.facts['spreadBps'], 281);
  });

  test('adjusted or non-standard contracts are refused', () {
    expect(eval(t: terms(deliverable: {'amount': '150'}), q: quote(), u: spot()).reasons, ['ADJUSTED_OR_UNSUPPORTED_CONTRACT']);
    expect(eval(t: terms(over: {'multiplier': '10'}), q: quote(), u: spot()).reasons, contains('ADJUSTED_OR_UNSUPPORTED_CONTRACT'));
    expect(eval(t: terms(over: {'style': 'european'}), q: quote(), u: spot()).reasons, contains('ADJUSTED_OR_UNSUPPORTED_CONTRACT'));
    expect(eval(t: terms(deliverable: {'delayed_settlement': true}), q: quote(), u: spot()).reasons,
        contains('ADJUSTED_OR_UNSUPPORTED_CONTRACT'));
    expect(eval(t: terms(over: {'deliverables': []}), q: quote(), u: spot()).reasons, contains('ADJUSTED_OR_UNSUPPORTED_CONTRACT'));
  });

  test('identity, tradability and open interest', () {
    expect(eval(t: terms(over: {'strike_price': '205'}), q: quote(), u: spot()).reasons, contains('CONTRACT_TERMS_IDENTITY_MISMATCH'));
    expect(eval(t: terms(over: {'type': 'put'}), q: quote(), u: spot()).reasons, contains('CONTRACT_TERMS_IDENTITY_MISMATCH'));
    expect(eval(t: terms(over: {'tradable': false}), q: quote(), u: spot()).reasons, ['CONTRACT_NOT_TRADABLE']);
    expect(eval(t: terms(over: {'open_interest': '40'}), q: quote(), u: spot()).reasons, ['OPEN_INTEREST_TOO_LOW']);
    expect(eval(t: terms(over: {'open_interest_date': '2026-10-01'}), q: quote(), u: spot()).reasons, ['OPEN_INTEREST_STALE']);
    expect(eval(t: terms(over: {'open_interest': null}), q: quote(), u: spot()).reasons, ['OPEN_INTEREST_UNAVAILABLE']);
    expect(eval(t: null, q: quote(), u: spot()).reasons, ['CONTRACT_TERMS_UNAVAILABLE']);
  });

  test('spread, underlying and implied-vol/delta gates', () {
    expect(eval(t: terms(), q: quote(bid: 600, ask: 720), u: spot()).reasons, ['SPREAD_TOO_WIDE']);
    expect(eval(t: terms(), q: null, u: spot()).reasons, ['OPTION_QUOTE_UNUSABLE']);
    expect(eval(t: terms(), q: quote(), u: null).reasons, ['UNDERLYING_QUOTE_UNAVAILABLE']);
    expect(eval(t: terms(), q: quote(), u: spot(symbol: 'MSFT')).reasons, ['UNDERLYING_QUOTE_UNAVAILABLE']);
    expect(eval(t: terms(), q: quote(), u: spot(age: const Duration(seconds: 45))).reasons, ['UNDERLYING_QUOTE_STALE']);
    // Premium below intrinsic (spot 230): cannot imply a volatility.
    expect(eval(t: terms(), q: quote(), u: spot(bid: 22995, ask: 23005)).reasons, ['IMPLIED_VOL_PRICE_BELOW_INTRINSIC']);
    // Far out of the money: delta below 0.15.
    expect(eval(t: terms(), q: quote(bid: 20, ask: 22), u: spot(bid: 17995, ask: 18005)).reasons, ['DELTA_TOO_SMALL']);
    expect(eval(t: terms(), q: quote(), u: spot(), policy: const EligibilityPolicy(maxImpliedVol: 0.2)).reasons,
        ['IMPLIED_VOL_TOO_HIGH']);
    expect(eval(t: terms(), q: quote(), u: spot(), policy: const EligibilityPolicy(maxAbsDelta: 0.5)).reasons,
        ['DELTA_TOO_LARGE']);
  });

  test('expired or unsupported-calendar contracts fail closed', () {
    final late = evaluateEligibility(contract: OccContract.parse(call)!, terms: terms(), quote: quote(), underlying: spot(),
        now: DateTime.utc(2026, 11, 20, 21, 5));
    expect(late.reasons, contains('EXPIRY_TIME_UNAVAILABLE'));
  });

  test('eligibility text labels model Greeks and lists reasons', () {
    final text = eligibilityText(eval(t: terms(over: {'open_interest': '40'}), q: quote(), u: spot()));
    expect(text, contains('Eligibility: FAIL'));
    expect(text, contains('model IV'));
    expect(text, contains('OPEN_INTEREST_TOO_LOW'));
  });

  group('service integration', () {
    late MemorySecureKeyValue mem;
    late BrokerAccountRegistry reg;
    late List<String> calls;
    late Map<String, dynamic> served;
    setUp(() {
      mem = MemorySecureKeyValue();
      reg = BrokerAccountRegistry(mem);
      calls = [];
      served = terms();
    });
    MockClient client() => MockClient((r) async {
          calls.add('${r.url.host}${r.url.path}');
          switch (r.url.path) {
            case '/v2/account': return json({'account_number': 'PA1', 'cash': '100000', 'equity': '100000', 'buying_power': '200000'});
            case '/v2/positions': return json([]);
            case '/v2/options/contracts/$call': return json(served);
            case '/v2/orders': return json({'id': 'alp-9', 'client_order_id': (jsonDecode(r.body) as Map)['client_order_id'], 'status': 'accepted'});
          }
          return json({}, 404);
        });
    BrokerOrderService svc() => BrokerOrderService(reg, client: client(), clock: () => now,
        directQuote: (_) async => OptionQuote(call, 'opra', now.subtract(const Duration(seconds: 1)), 700, 720, 50, 50),
        underlyingQuote: (_) async => spot());
    const buy = BrokerOrderTicket(contract: call, side: TicketSide.buyToOpen, quantity: 1, limitCents: 720);

    test('eligible entry is admitted and the INTENT records the eligibility evidence', () async {
      final a = await reg.add(broker: BrokerKind.alpaca, label: 'A', values: {'keyId': 'PKFIXTURE1', 'secretKey': 'fixturesecret1'});
      final s = svc();
      final r = await s.review(a, buy);
      expect(r.admission.reason, isNull);
      expect(r.admission.passed.last, 'OPTION_ELIGIBILITY');
      await s.submit(r);
      final intent = (await s.journal(a).events()).first;
      expect((intent['eligibility'] as Map)['eligible'], isTrue);
      expect(calls.where((c) => c == 'paper-api.alpaca.markets/v2/options/contracts/$call').length, 2); // review + re-admission
      expect(calls.every((c) => c.startsWith('paper-api.alpaca.markets/')), isTrue); // allowlist unchanged
    });

    test('ineligible entry is refused; closing orders are never vetoed by eligibility', () async {
      final a = await reg.add(broker: BrokerKind.alpaca, label: 'A', values: {'keyId': 'PKFIXTURE1', 'secretKey': 'fixturesecret1'});
      served = terms(deliverable: {'amount': '150'});
      final r = await svc().review(a, buy);
      expect(r.admission.reason, 'OPTION_NOT_ELIGIBLE');
      expect(r.eligibility!.reasons, ['ADJUSTED_OR_UNSUPPORTED_CONTRACT']);
      expect(orderMessage('OPTION_NOT_ELIGIBLE'), isNot('OPTION_NOT_ELIGIBLE'));
      final close = await svc().review(a, const BrokerOrderTicket(contract: call, side: TicketSide.sellToClose, quantity: 1, limitCents: 700));
      expect(close.eligibility, isNull);
      expect(close.admission.reason, isNot('OPTION_NOT_ELIGIBLE'));
    });

    test('non-Alpaca accounts use a registered Alpaca account for terms, else fail closed', () async {
      final ts = await reg.add(broker: BrokerKind.tradestation, label: 'TS',
          values: {'clientId': 'tsclient1', 'clientSecret': 'tssecret1', 'refreshToken': 'tsrefresh1'});
      final s = BrokerOrderService(reg, clock: () => now, client: client(), underlyingQuote: (_) async => spot());
      var e = await s.eligibilityFor(ts, buy, quote());
      expect(e.reasons, ['CONTRACT_TERMS_UNAVAILABLE']);
      await reg.add(broker: BrokerKind.alpaca, label: 'A', values: {'keyId': 'PKFIXTURE1', 'secretKey': 'fixturesecret1'});
      e = await s.eligibilityFor(ts, buy, quote());
      expect(e.eligible, isTrue);
    });
  });
}
