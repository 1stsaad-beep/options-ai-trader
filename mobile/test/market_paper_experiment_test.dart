import 'dart:convert';
import 'package:flutter_test/flutter_test.dart';
import 'package:options_ai_trader/direct_alpaca.dart';
import 'package:options_ai_trader/direct_labs.dart';
import 'package:options_ai_trader/market_paper.dart';
import 'package:options_ai_trader/market_paper_reports.dart';
import 'market_paper_safety_test.dart' show FaultPaperStore;

void main() {
  final now = DateTime.utc(2026, 10, 13, 15, 1, 15);
  const call = 'NVDA261016C00200000', put = 'NVDA261016P00200000';
  late FaultPaperStore store;
  late MarketPaper paper;
  late String id;
  OptionQuote quote(String contract, {int bid = 40, int ask = 42}) =>
      OptionQuote(contract, 'opra', now, bid, ask, 10, 10);
  Future<void> evaluate({bool close = false, int bid = 40, int ask = 42, String source = 'fixture'}) =>
      paper.evaluate(id: id, symbol: 'NVDA', signal: 'CALL', confirmedReverse: false,
        dataValid: () => true, observation: DateTime.utc(2026, 10, 13, 15).toIso8601String(),
        quotes: (c) async => quote(c, bid: bid, ask: ask), forceClose: close,
        evidence: {'source': source});
  setUp(() async {
    store = FaultPaperStore(); paper = MarketPaper(store, clock: () => now);
    await paper.load(); await paper.createComparisonExperiment();
    id = paper.accounts.first['id'] as String;
    await paper.configure(id, {'enabled': true, 'contracts': {'NVDA:CALL': call, 'NVDA:PUT': put}});
  });

  test('experiment is explicit idempotent and has four independent USD1000 accounts', () async {
    expect(paper.accounts.length, 4);
    expect(paper.accounts.map((a) => a['initialCash']), everyElement(100000));
    expect(paper.accounts.map((a) => a['strategy']).toSet(), paperStrategies.toSet());
    final before = jsonEncode(paper.copy());
    await paper.createComparisonExperiment();
    expect(jsonEncode(paper.copy()), before);
    expect(paper.accounts.skip(1).every((a) => a['enabled'] == false), isTrue);
    await paper.configure(id, {'watchlist': ['AAPL'], 'riskPercent': 1});
    expect(paper.accounts[1]['watchlist'], ['NVDA', 'AAPL', 'TSLA']);
    expect(paper.accounts[1]['riskPercent'], 5);
  });
  test('experiment never resets previously created account balances or settings', () async {
    final separate = MarketPaper(FaultPaperStore(), clock: () => now);
    await separate.load(); await separate.add('Preserve legacy workflow');
    final original = jsonEncode(separate.accounts.single);
    await separate.createComparisonExperiment();
    expect(separate.accounts.length, 5);
    expect(jsonEncode(separate.accounts.first), original);
  });
  test('a removed watch symbol cannot accept a new entry', () async {
    await paper.configure(id, {'watchlist': ['AAPL']});
    await evaluate();
    expect(paper.account(id)['positions'], isEmpty);
    expect(paper.journal.last['decision'], 'ACCOUNT_WATCHLIST_BLOCKED');
  });
  test('report accounts for bid ask entry exit fees and original trade reason', () async {
    await evaluate();
    final open = paper.performance(id);
    expect(open['realizedPnlCents'], 0);
    expect(open['unrealizedPnlCents'], -330);
    expect(open['totalFeesCents'], 65);
    expect(open['equityCents'], 99670);
    await evaluate(close: true, bid: 50, ask: 52);
    final closed = paper.performance(id);
    expect(closed['realizedPnlCents'], 670);
    expect(closed['unrealizedPnlCents'], 0);
    expect(closed['totalFeesCents'], 130);
    expect(closed['closedTrades'], 1);
    expect(closed['winRatePercent'], 100);
    expect(closed['sampledMaxDrawdownCents'], 330);
    expect(paper.journal.last['fill']['realizedPnl'], 670);
    expect(paper.journal.last['evidence']['strategy'], 'trend');
    final original = jsonEncode(paper.journal);
    await paper.configure(id, {'strategy': 'breakout'});
    expect(jsonEncode(paper.journal), original);
  });
  test('stale marks leave unrealized value and return unavailable', () async {
    await evaluate();
    final later = MarketPaper(store, clock: () => now.add(const Duration(seconds:31)));
    await later.load();
    expect(later.performance(id)['valuationComplete'], isFalse);
    expect(later.performance(id)['unrealizedPnlCents'], isNull);
    expect(later.performance(id)['returnPercent'], isNull);
  });
  test('fixture decisions never become three real market sessions', () async {
    await evaluate(); await evaluate(close: true);
    final report = paper.comparison();
    expect(report['status'], 'NOT_RUN');
    expect((report['sessions'] as List).length, 3);
    for (final session in report['sessions'] as List) {
      expect(session['status'], 'NOT_RUN');
      expect(session['date'], isNull);
      expect(session['accounts'][0]['realizedPnlCents'], isNull);
    }
  });
  test('one actual observation is labeled partial and never full-session acceptance', () async {
    await evaluate(source: 'alpaca');
    final report = paper.comparison();
    expect(report['status'], 'PARTIAL_OBSERVATIONS_NOT_FULL_SESSION_ACCEPTANCE');
    expect(report['sessions'][0]['date'], '2026-10-13');
    expect(report['sessions'][0]['status'], 'PARTIALLY_OBSERVED');
    expect(report['sessions'][1]['status'], 'NOT_RUN');
  });
  test('positive cash tampering fails receipt reconciliation on reload', () async {
    await evaluate();
    store.value!['accounts'][0]['cash'] += 1;
    final original = jsonEncode(store.value);
    final restored = MarketPaper(store, clock: () => now);
    await restored.load();
    expect(restored.ready, isFalse);
    expect(jsonEncode(store.value), original);
  });
  test('journal rolls over without removing original evidence or stopping a fill', () async {
    final book = paper.copy();
    book['journal'] = List.generate(1000, (i) => {'account': id, 'symbol': 'NVDA',
      'at': now.toIso8601String(), 'decision': 'DATA_GAP_$i'});
    store.value = book;
    paper = MarketPaper(store, clock: () => now);
    await paper.load(); await paper.configure(id, {'enabled': true});
    await evaluate();
    expect(paper.copy()['journalArchive'][0].length, 1000);
    expect(paper.journal.length, 1001);
    expect(paper.journal.first['decision'], 'DATA_GAP_0');
    expect(paper.journal.last['decision'], 'OPENED_CALL');
    final recovered = MarketPaper(store, clock: () => now); await recovered.load();
    expect(recovered.ready, isTrue);
    expect(recovered.journal.length, 1001);
  });
  test('configured quantitative strategies apply distinct deterministic rules', () {
    final bars = List.generate(40, (i) => MarketBar(
      DateTime.utc(2026,10,13,14,i), 100, 101, 99, 100, 100));
    bars.add(MarketBar(DateTime.utc(2026,10,13,14,40),100,104,99.5,103,200));
    expect(MarketSignal.analyze(bars, strategy:'breakout').direction, 'CALL');
    expect(MarketSignal.analyze(bars, strategy:'trend').direction, 'WAIT');
    expect(MarketSignal.analyze(bars, strategy:'pullback').direction, 'WAIT');
    expect(MarketSignal.analyze(bars, strategy:'divergence').direction, 'WAIT');
    expect(MarketSignal.analyze(bars, strategy:'unknown').direction, 'WAIT');
    final prefix = MarketSignal.analyze(bars, strategy:'breakout').reason;
    final future = [...bars, MarketBar(DateTime.utc(2026,10,13,14,41),103,103,90,90,500)];
    expect(MarketSignal.analyze(future.take(bars.length).toList(), strategy:'breakout').reason, prefix);
  });
  test('entry decision requires contiguous completed warmup bars', () {
    final bars = List.generate(35, (i) => MarketBar(
      DateTime.utc(2026,10,13,14,26+i),100,101,99,100,100));
    DirectSnapshot snapshot(List<MarketBar> rows) => DirectSnapshot(connected:true,enabled:true,
      source:'alpaca',received:now,series:{'NVDA':rows});
    expect(snapshot(bars).validForDecision('NVDA',now), isTrue);
    bars[10] = MarketBar(bars[10].time.subtract(const Duration(minutes:1)),100,101,99,100,100);
    expect(snapshot(bars).validForDecision('NVDA',now), isFalse);
  });
  test('a rejected admission is a risk block rather than a claimed violation',()async{
    await paper.configure(id,{'allocationPercent':0});await evaluate();
    final account=(paper.comparison()['accounts'] as List).first;
    expect(account['riskBlocks'],1);expect(account['riskViolations'],isNull);
    expect(paper.account(id)['positions'],isEmpty);
  });

}
