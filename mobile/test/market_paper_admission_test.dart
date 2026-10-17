import 'dart:convert';
import 'package:flutter_test/flutter_test.dart';
import 'package:options_ai_trader/direct_alpaca.dart';
import 'package:options_ai_trader/market_paper.dart';
import 'package:options_ai_trader/market_paper_validation.dart';
import 'package:options_ai_trader/paper_execution.dart';
import 'package:options_ai_trader/paper_return.dart';
import 'market_paper_safety_test.dart' show FaultPaperStore;

void main() {
  const call = 'NVDA261023C00200000', put = 'NVDA261023P00200000';
  late DateTime clock;
  late MarketPaper paper;
  late FaultPaperStore store;
  late String id;
  var quoteReads = 0;
  Future<void> cycle({String source = 'fixture', String signal = 'CALL', bool reverse = false,
      bool valid = true, bool close = false, bool missing = false, int bid = 200, int ask = 210, int size = 40}) =>
    paper.evaluate(id: id, symbol: 'NVDA', signal: signal, confirmedReverse: reverse,
      dataValid: () => valid, observation: clock.toIso8601String(), forceClose: close,
      evidence: {'source': source}, quotes: (c) async {
        quoteReads++;
        return missing ? null : OptionQuote(c, 'opra', clock, bid, ask, size, size);
      });
  setUp(() async {
    clock = DateTime.utc(2026, 10, 13, 15, 1); quoteReads = 0;
    store = FaultPaperStore(); paper = MarketPaper(store, clock: () => clock);
    await paper.load(); await paper.add('Qualification', initialCash: 10000000, executionPolicy: conservativeExecution);
    id = paper.accounts.single['id'] as String;
    await paper.configure(id, {'enabled': true, 'quantity': 1, 'holdingMode': 'swing', 'partialPercent': 0,
      'contracts': {'NVDA:CALL': call, 'NVDA:PUT': put}});
  });
  test('Alpaca OPRA quote alone cannot admit a new contract or debit cash', () async {
    await cycle(source: 'alpaca');
    expect(quoteReads, 0);
    expect(paper.account(id)['positions'], isEmpty); expect(paper.account(id)['cash'], 10000000);
    expect(paper.journal.last['decision'], 'CONTRACT_ELIGIBILITY_UNVERIFIED');
    expect(paper.journal.last['evidence']['admissionContract'], 'observed-contract-admission-v1');
    expect(paper.journal.last['fill'], isNull); validatePaper(paper.copy());
    final writes = store.writes; await cycle(source: 'alpaca'); expect(store.writes, writes);
  });
  test('missing qualification blocks add but never strands owned stop protection', () async {
    await paper.configure(id, {'addEnabled': true}); await cycle();
    final original = jsonEncode(paper.journal.first), cash = paper.account(id)['cash'];
    clock = clock.add(const Duration(seconds: 1)); await cycle(source: 'alpaca', bid: 240, ask: 250);
    expect(paper.account(id)['positions']['NVDA']['quantity'], 1); expect(paper.account(id)['cash'], cash);
    expect(paper.journal.last['decision'], 'CONTRACT_ELIGIBILITY_UNVERIFIED');
    clock = clock.add(const Duration(seconds: 1)); await cycle(source: 'alpaca', valid: false, bid: 171, ask: 176);
    expect(paper.account(id)['positions'], isEmpty); expect(paper.journal.last['decision'], 'CLOSED_STOP_LOSS');
    expect(jsonEncode(paper.journal.first), original); validatePaper(paper.copy());
  });
  test('market reversal closes owned contract and remains flat without qualification', () async {
    await cycle(); clock = clock.add(const Duration(seconds: 1));
    await cycle(source: 'alpaca', signal: 'PUT', reverse: true);
    expect(paper.account(id)['positions'], isEmpty);
    expect(paper.journal.where((e) => e['decision'] == 'CLOSED_CONFIRMED_DIVERGENCE').length, 1);
    expect(paper.journal.last['decision'], 'CONTRACT_ELIGIBILITY_UNVERIFIED');
    expect(paper.journal.where((e) => e['decision'] == 'OPENED_PUT'), isEmpty);
  });
  test('qualification outage preserves manual close intent across restart and partial fills', () async {
    await paper.configure(id, {'quantity': 2}); await cycle();
    await cycle(source: 'alpaca', close: true, missing: true);
    expect(paper.account(id)['positions']['NVDA']['closeIntent']['remaining'], 2);
    paper = MarketPaper(store, clock: () => clock); await paper.load();
    clock = clock.add(const Duration(seconds: 1)); await cycle(source: 'alpaca', close: true, size: 4);
    expect(paper.account(id)['positions']['NVDA']['quantity'], 1);
    clock = clock.add(const Duration(seconds: 1)); await cycle(source: 'alpaca', close: true, size: 4);
    expect(paper.account(id)['positions'], isEmpty); validatePaper(paper.copy());
  });
  test('conservative stop uses entry and exit costs at the exact boundary', () async {
    await cycle(); clock = clock.add(const Duration(seconds: 1));
    await cycle(bid: 171, ask: 176, valid: false);
    expect(paper.account(id)['positions'], isEmpty);
    expect(paper.journal.last['fill']['realizedPnl'], -4240);
    expect(paper.journal.last['evidence']['protectionContract'], 'net-liquidation-protection-v1');
  });
  test('take profit waits for net 40 percent instead of the gross bid threshold', () async {
    await cycle(); clock = clock.add(const Duration(seconds: 1)); await cycle(bid: 297, ask: 307);
    expect(paper.account(id)['positions']['NVDA']['quantity'], 1);
    clock = clock.add(const Duration(seconds: 1)); await cycle(bid: 299, ask: 309);
    expect(paper.account(id)['positions'], isEmpty); expect(paper.journal.last['decision'], 'CLOSED_TAKE_PROFIT');
  });
  test('addition requires ten percent after both fee sides and slippage', () async {
    await paper.configure(id, {'addEnabled': true}); await cycle();
    clock = clock.add(const Duration(seconds: 1)); await cycle(bid: 233, ask: 243);
    expect(paper.account(id)['positions']['NVDA']['quantity'], 1);
    clock = clock.add(const Duration(seconds: 1)); await cycle(bid: 235, ask: 245);
    expect(paper.account(id)['positions']['NVDA']['quantity'], 2);
  });
  test('return comparisons remain exact beyond JSON safe intermediate products', () {
    final policy = {'executionPolicy': conservativeExecution};
    final position = {'quantity': 900000, 'cost': 8999999847000000, 'entryFees': 63000000, 'highBid': 100000000};
    final result = PaperReturn(policy, position, 100000000);
    expect(result.liquidation, BigInt.parse('8999999847000000'));
    expect(result.gainAtLeast(0), false); expect(result.lossAtLeast(0), true);
    expect(result.trailingAtLeast(15), false);
  });
}
