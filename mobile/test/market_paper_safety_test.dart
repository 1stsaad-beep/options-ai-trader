import 'dart:convert';
import 'package:flutter_test/flutter_test.dart';
import 'package:options_ai_trader/direct_alpaca.dart';
import 'package:options_ai_trader/market_paper.dart';

class FaultPaperStore implements PaperStore {
  PaperRow? value;
  bool dropWrite = false, throwAfterWrite = false, unreadable = false;
  bool failReadAfterWrite = false;
  int writes = 0;
  @override
  Future<PaperRow?> read() async {
    if (unreadable) throw StateError('read unavailable');
    return value == null ? null : jsonDecode(jsonEncode(value)) as PaperRow;
  }
  @override
  Future<void> write(PaperRow next) async {
    writes++;
    if (!dropWrite) value = jsonDecode(jsonEncode(next)) as PaperRow;
    if (failReadAfterWrite) unreadable = true;
    if (throwAfterWrite) throw StateError('response lost after write');
  }
}

void main() {
  final clock = DateTime.utc(2026, 10, 13, 15, 1, 15);
  const call = 'NVDA261016C00200000', put = 'NVDA261016P00200000';
  late FaultPaperStore store;
  late MarketPaper paper;
  late String id;
  OptionQuote quote(String contract, {int bid = 200, int ask = 210}) =>
      OptionQuote(contract, 'opra', clock, bid, ask, 10, 10);
  Future<void> cycle({bool valid = true, bool analysisThrows = false,
    int bid = 200, int ask = 210, bool close = false, bool missingQuote = false,
    String signal = 'CALL', bool reverse = false, String observation = 'bar1'}) =>
      paper.evaluate(id: id, symbol: 'NVDA', signal: signal,
        confirmedReverse: reverse, observation: observation,
        dataValid: () { if (analysisThrows) throw StateError('optional analysis'); return valid; },
        quotes: (contract) async => missingQuote ? null : quote(contract, bid: bid, ask: ask),
        forceClose: close);
  setUp(() async {
    store = FaultPaperStore();
    paper = MarketPaper(store, clock: () => clock);
    await paper.load();
    await paper.add('Independent');
    id = paper.accounts.single['id'] as String;
    await paper.configure(id, {'enabled': true, 'contracts': {'NVDA:CALL': call, 'NVDA:PUT': put}});
  });

  test('fresh option stop survives stale optional stock analysis', () async {
    await cycle();
    await cycle(valid: false, bid: 160, ask: 170);
    expect(paper.account(id)['positions'], isEmpty);
    expect(paper.journal.last['decision'], 'CLOSED_STOP_LOSS');
    expect(paper.account(id)['cash'], 994870);
  });
  test('throwing optional analysis cannot suppress a justified stop', () async {
    await cycle();
    await cycle(analysisThrows: true, bid: 160, ask: 170);
    expect(paper.account(id)['positions'], isEmpty);
    expect(paper.journal.last['decision'], 'CLOSED_STOP_LOSS');
  });
  test('fresh option take profit survives stale optional analysis', () async {
    await cycle();
    await cycle(valid: false, bid: 300, ask: 310);
    expect(paper.account(id)['positions'], isEmpty);
    expect(paper.journal.last['decision'], 'CLOSED_TAKE_PROFIT');
  });
  test('owned manual close does not require a new stock entry signal', () async {
    await cycle();
    await cycle(valid: false, close: true);
    expect(paper.account(id)['positions'], isEmpty);
    expect(paper.journal.last['decision'], 'CLOSED_MANUAL');
  });
  test('invalid stock signal never opens opposite after protective close', () async {
    await cycle();
    await cycle(valid: false, bid: 160, ask: 170, signal: 'PUT', reverse: true, observation: 'bar2');
    expect(paper.account(id)['positions'], isEmpty);
    expect(paper.journal.where((row) => row['decision'] == 'OPENED_PUT'), isEmpty);
  });
  test('missing option price cannot create a protective fill', () async {
    await cycle();
    final cash = paper.account(id)['cash'];
    await cycle(valid: false, close: true, missingQuote: true);
    expect((paper.account(id)['positions'] as Map).length, 1);
    expect(paper.account(id)['cash'], cash);
  });
  test('manual close with no owned position never becomes an entry', () async {
    await cycle(close: true);
    expect(paper.account(id)['positions'], isEmpty);
    expect(paper.account(id)['cash'], 1000000);
    expect(paper.journal.last['decision'], 'NO_OWNED_POSITION');
  });
  test('invalid stock data cannot authorize profitable addition', () async {
    await paper.configure(id, {'addEnabled': true});
    await cycle();
    await cycle(valid: false, bid: 235, ask: 240);
    expect((paper.account(id)['positions'] as Map)['NVDA']['quantity'], 1);
  });
  test('persisted malformed account is refused without replacing original', () async {
    store.value!['accounts'][0]['cash'] = -1;
    final original = jsonEncode(store.value), writes = store.writes;
    final recovered = MarketPaper(store, clock: () => clock);
    await recovered.load();
    expect(recovered.ready, isFalse);
    expect(recovered.error, isNotNull);
    expect(jsonEncode(store.value), original);
    expect(store.writes, writes);
  });
  test('duplicate persisted account identity is rejected', () async {
    (store.value!['accounts'] as List).add(jsonDecode(jsonEncode(store.value!['accounts'][0])));
    final recovered = MarketPaper(store, clock: () => clock);
    await recovered.load();
    expect(recovered.ready, isFalse);
  });
  test('returned nested account data cannot mutate authoritative ledger', () async {
    await cycle();
    (paper.account(id)['positions'] as Map).clear();
    (paper.accounts.single['contracts'] as Map).clear();
    (paper.journal.last['quote'] as Map)['bid'] = 999999;
    expect((paper.account(id)['positions'] as Map).length, 1);
    expect((paper.account(id)['contracts'] as Map).length, 2);
    expect(paper.journal.last['quote']['bid'], 200);
  });
  test('configuration rejects wrong enablement type', () async {
    await expectLater(paper.configure(id, {'enabled': 'yes'}), throwsArgumentError);
    expect(paper.account(id)['enabled'], isTrue);
  });
  test('configuration rejects a contract bound to the wrong direction', () async {
    await expectLater(paper.configure(id, {'contracts': {'NVDA:CALL': put}}), throwsArgumentError);
    expect(paper.account(id)['contracts']['NVDA:CALL'], call);
  });
  test('lost write acknowledgement is resolved by exact durable readback', () async {
    store.throwAfterWrite = true;
    await cycle();
    expect((paper.account(id)['positions'] as Map).length, 1);
    expect(paper.account(id)['cash'], store.value!['accounts'][0]['cash']);
    expect(paper.journal.length, 1);
    await cycle();
    expect(paper.journal.length, 1);
  });
  test('successful write response without stored bytes cannot create a fill', () async {
    store.dropWrite = true;
    await cycle();
    expect(paper.account(id)['positions'], isEmpty);
    expect(paper.error, isNotNull);
  });
  test('unreadable write outcome latches mutation until recovery', () async {
    store.failReadAfterWrite = true;
    await cycle();
    final writes = store.writes;
    store.unreadable = false;
    store.failReadAfterWrite = false;
    await cycle(observation: 'bar2', signal: 'PUT', reverse: true);
    await paper.add('Must not overwrite uncertain ledger');
    expect(paper.ready, isFalse);
    expect(store.writes, writes);
    expect(store.value!['accounts'].length, 1);
  });
  test('changed durable state is never overwritten from stale memory', () async {
    store.value!['accounts'][0]['cash'] = 123456;
    final original = jsonEncode(store.value), writes = store.writes;
    await cycle();
    expect(paper.ready, isFalse);
    expect(store.writes, writes);
    expect(jsonEncode(store.value), original);
  });
}
