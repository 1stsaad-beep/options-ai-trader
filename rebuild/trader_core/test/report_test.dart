import 'dart:convert';

import 'package:test/test.dart';
import 'package:trader_core/trader_core.dart';

TradeRecord trade(DateTime exit, int entry, int exitP, {List<String> engines = const ['trend'], int fees = 0}) => TradeRecord(
      occSymbol: 'AAPL261120C00200000',
      underlying: 'AAPL',
      right: OptionRight.call,
      entryTime: exit.subtract(const Duration(hours: 2)),
      exitTime: exit,
      quantity: 1,
      entryPremiumCents: entry,
      exitPremiumCents: exitP,
      feesCents: fees,
      exitKind: 'takeProfit',
      entryReasonAr: 'سبب، "مقتبس"',
      exitReasonAr: 'هدف\nالربح',
      engines: engines,
    );

void main() {
  test('wins, losses and breakevens are counted honestly (zero P/L is not a loss)', () {
    final r = PerformanceReport.compute([
      trade(DateTime.utc(2026, 10, 19, 15), 100, 150),
      trade(DateTime.utc(2026, 10, 19, 16), 100, 80),
      trade(DateTime.utc(2026, 10, 19, 17), 100, 100),
    ], const []);
    expect((r.wins, r.losses, r.breakevens, r.trades), (1, 1, 1, 3));
    expect(r.winRatePercent, closeTo(33.33, 0.01));
  });

  test('daily/weekly by New York date, per-engine stats, unrealized', () {
    final trades = [
      trade(DateTime.utc(2026, 10, 20, 2), 100, 150, engines: ['trend', 'momentum']), // NY 2026-10-19 (Mon)
      trade(DateTime.utc(2026, 10, 20, 15), 100, 50, engines: ['trend']), // NY 2026-10-20
      trade(DateTime.utc(2026, 10, 26, 15), 100, 120, engines: const []), // next week
    ];
    final curve = [
      EquityPoint(DateTime.utc(2026, 10, 19), 100000),
      EquityPoint(DateTime.utc(2026, 10, 20), 110000),
      EquityPoint(DateTime.utc(2026, 10, 21), 99000),
    ];
    final r = AccountReport.build(trades, curve, unrealizedPnlCents: 1234);
    expect(r.daily.map((d) => d.key), ['2026-10-26', '2026-10-20', '2026-10-19']);
    expect(r.daily.last.pnlCents, 5000);
    expect(r.weekly.map((w) => (w.key, w.trades, w.pnlCents)), [('2026-10-26', 1, 2000), ('2026-10-19', 2, 0)]);
    expect(AccountReport.weekKey(DateTime.utc(2026, 10, 25, 3)), '2026-10-19'); // Sat night NY
    final trend = r.engines.firstWhere((e) => e.engine == 'trend');
    expect((trend.trades, trend.wins, trend.losses, trend.pnlCents), (2, 1, 1, 0));
    expect(r.engines.firstWhere((e) => e.engine == 'momentum').trades, 1);
    expect(r.untaggedTrades, 1);
    expect(r.performance.maxDrawdownPercent, closeTo(10, 0.001));
    final j = jsonDecode(jsonEncode(r.toJson())) as Map<String, dynamic>;
    expect(j['summary']['unrealizedPnlCents'], 1234);
    expect((j['trades'] as List).first['result'], 'win');
  });

  test('CSV exports escape quotes, commas and new lines', () {
    final r = AccountReport.build([trade(DateTime.utc(2026, 10, 19, 15), 100, 150)], const []);
    final csv = r.tradesCsv();
    final lines = csv.split('\r\n');
    expect(lines.first, startsWith('contract,underlying,right'));
    expect(csv, contains('"سبب، ""مقتبس"""'));
    expect(csv, contains('"هدف\nالربح"'));
    expect(r.periodsCsv(), contains('2026-10-19,day,1,1,0,0,50.0'));
    expect(toCsv(['a'], [['x,y']]), 'a\r\n"x,y"\r\n');
  });

  test('activity log CSV has one row per symbol per cycle', () {
    final c1 = CycleRecord(cycle: 1, start: DateTime.utc(2026, 10, 19, 14, 30))
      ..marketPhase = 'open'
      ..symbols['AAPL'] = CycleSymbolNote('AAPL', score: 70, bias: 'bullish', action: 'entry', reasonAr: 'دخول')
      ..symbols['SPY'] = CycleSymbolNote('SPY', score: 10, action: 'skip', reasonAr: 'ضعيف')
      ..orders.add('entry 1× X');
    final c2 = CycleRecord(cycle: 2, start: DateTime.utc(2026, 10, 19, 21))..marketPhase = 'closed';
    final lines = cyclesCsv([c1, c2]).trim().split('\r\n');
    expect(lines, hasLength(4));
    expect(lines[1], startsWith('1,2026-10-19T14:30:00.000Z,2026-10-19,10:30,open,,AAPL,70.0,bullish,entry,دخول,entry 1× X,0,,'));
    expect(lines[3], startsWith('2,'));
  });

  test('engine attribution survives JSON for tracked orders, metas and trades', () {
    final t = trade(DateTime.utc(2026, 10, 19), 1, 2, engines: ['harmonic']);
    expect(TradeRecord.fromJson(t.toJson()).engines, ['harmonic']);
    final m = PositionMeta(occSymbol: 'X', entryTime: DateTime.utc(2026), entryPremiumCents: 1, initialQuantity: 1, entryScore: 1, entryReasonAr: 'r', engines: ['trend']);
    expect(PositionMeta.fromJson(m.toJson()).engines, ['trend']);
    final o = TrackedOrder(orderId: 'o', clientOrderId: 'c', occSymbol: 'X', side: OrderSide.buyToOpen, purpose: 'entry', reasonAr: 'r', submittedCycle: 1, engines: ['elliott']);
    expect(TrackedOrder.fromJson(o.toJson()).engines, ['elliott']);
    // Old saves without the field still load.
    final old = t.toJson()..remove('eng');
    expect(TradeRecord.fromJson(old).engines, isEmpty);
  });
}
