/// Engines and the trading engine on REAL historical bars (AAPL and SPY,
/// public Yahoo Finance chart data fetched without any key, see
/// test/fixtures/*.csv). Options are priced with Black-Scholes on the real
/// underlying (no public options history without keys), so these tests check
/// behaviour and safety invariants, not profitability.
library;

import 'dart:io';
import 'dart:math' as math;

import 'package:test/test.dart';
import 'package:trader_core/trader_core.dart';

List<Candle> loadFixture(String name) {
  final lines = File('test/fixtures/$name.csv').readAsLinesSync();
  return [
    for (final l in lines)
      if (!l.startsWith('#') && !l.startsWith('time') && l.trim().isNotEmpty)
        () {
          final p = l.split(',');
          return Candle(
              time: DateTime.parse(p[0]),
              open: double.parse(p[1]),
              high: double.parse(p[2]),
              low: double.parse(p[3]),
              close: double.parse(p[4]),
              volume: double.parse(p[5]));
        }()
  ];
}

/// Synthetic option pricing on top of a replayed real underlying.
class ReplayMarket extends SyntheticMarket {
  final Map<String, List<Candle>> series;
  final Duration barLength;
  ReplayMarket(this.series, this.barLength, DateTime Function() clock) : super(clock: clock, annualVol: 0.30);

  /// Bars started at or before now (the last one may still be forming,
  /// exactly like a real broker).
  List<Candle> _upTo(String s) => [for (final c in series[s]!) if (!c.time.isAfter(clock())) c];

  @override
  Future<List<Candle>> bars(String symbol, BarTimeframe timeframe, {int limit = 300}) async {
    final b = _upTo(symbol);
    return b.sublist(math.max(0, b.length - limit));
  }

  @override
  Future<double> lastPrice(String symbol) async => _upTo(symbol).last.close;
}

/// Alpaca-like adapter (so the real NYSE-hours gate and completed-bar rule
/// apply) over the simulator's order book.
class ReplayBroker implements BrokerAdapter {
  final SimulatorBroker inner;
  ReplayBroker(this.inner);
  @override
  BrokerKind get kind => BrokerKind.alpaca;
  @override
  TradingMode get mode => TradingMode.paper;
  @override
  Future<void> connect() => inner.connect();
  @override
  Future<AccountSnapshot> account() => inner.account();
  @override
  Future<List<Position>> positions() => inner.positions();
  @override
  Future<List<BrokerOrder>> openOrders() => inner.openOrders();
  @override
  Future<BrokerOrder> placeOrder(OrderRequest r) => inner.placeOrder(r);
  @override
  Future<void> cancelOrder(String id) => inner.cancelOrder(id);
  @override
  Future<BrokerOrder?> order(String id) => inner.order(id);
  @override
  Future<List<Candle>> bars(String s, BarTimeframe tf, {int limit = 300}) => inner.bars(s, tf, limit: limit);
  @override
  Future<double> lastPrice(String s) => inner.lastPrice(s);
  @override
  Future<List<OptionQuote>> optionChain(String u, {required DateTime minExpiry, required DateTime maxExpiry, OptionRight? right}) =>
      inner.optionChain(u, minExpiry: minExpiry, maxExpiry: maxExpiry, right: right);
  @override
  Future<OptionQuote?> optionQuote(OptionContract c) => inner.optionQuote(c);
}

void main() {
  final fixtures = {for (final n in ['aapl_d1', 'aapl_h1', 'spy_d1', 'spy_h1']) n: loadFixture(n)};

  test('fixtures are sane real OHLC data', () {
    for (final e in fixtures.entries) {
      final b = e.value;
      expect(b.length, greaterThan(400), reason: e.key);
      for (var i = 0; i < b.length; i++) {
        final c = b[i];
        expect(c.high, greaterThanOrEqualTo(math.max(c.open, c.close) - 1e-6), reason: '${e.key} $i');
        expect(c.low, lessThanOrEqualTo(math.min(c.open, c.close) + 1e-6), reason: '${e.key} $i');
        if (i > 0) expect(c.time.isAfter(b[i - 1].time), isTrue);
      }
    }
  });

  test('all six engines run on real bars without look-ahead (signals known within the prefix)', () {
    final analyzer = Analyzer();
    for (final e in fixtures.entries) {
      final b = e.value;
      var reports = 0, signals = 0;
      for (var k = 150; k <= b.length; k += 37) {
        final prefix = b.sublist(math.max(0, k - 300), k);
        final r = analyzer.analyze(e.key, prefix);
        reports++;
        expect(r.score.isFinite, isTrue);
        expect(r.score.abs(), lessThanOrEqualTo(100));
        for (final s in r.signals) {
          signals++;
          expect(s.strength, inInclusiveRange(0, 1), reason: '${e.key} ${s.engine}');
          expect(s.knownAtIndex, lessThan(prefix.length), reason: '${e.key} ${s.engine} ${s.pattern}');
          expect(s.reasonAr, isNotEmpty);
        }
        // Same input → same output (deterministic).
        expect(analyzer.analyze(e.key, prefix).score, r.score);
      }
      expect(reports, greaterThan(5));
      expect(signals, greaterThan(0), reason: '${e.key}: engines should find something on 2 years of real data');
    }
  });

  for (final (sym, tf) in [('AAPL', BarTimeframe.h1), ('SPY', BarTimeframe.h1), ('AAPL', BarTimeframe.d1), ('SPY', BarTimeframe.d1)]) {
    test('$sym ${tf.name} replay: engine keeps every safety rule on real bars', () async {
      final bars = fixtures['${sym.toLowerCase()}_${tf.name}']!;
      var now = bars[300].time;
      final market = ReplayMarket({sym: bars}, tf.duration, () => now);
      final broker = ReplayBroker(SimulatorBroker(market: market, startingCashCents: 10000000, clock: () => now));
      final state = AccountState();
      final seenLast = <DateTime>[];
      final analyzer = Analyzer(engines: {
        for (final e in Analyzer.defaultEngines.entries)
          e.key: (List<Candle> c) {
            if (e.key == EngineId.trend) seenLast.add(c.last.time);
            return e.value(c);
          }
      });
      final settings = AccountSettings(
        timeframe: tf,
        maxOpenPositions: 2,
        maxOrdersPerDay: 3,
        symbolCooldownMinutes: 60,
        riskPerTradePercent: 2,
      );
      final profile = AccountProfile(
          id: 'r', name: 'replay', broker: BrokerKind.alpaca, mode: TradingMode.paper, createdAt: now,
          watchlist: [sym], enabled: true, settings: settings);
      final engine = TradingEngine(profile: profile, broker: broker, state: state, analyzer: analyzer, clock: () => now);
      final ordersPerDay = <String, int>{};
      var cycles = 0;
      for (var i = 300; i < bars.length; i++) {
        // Inside bar i (30 min into an hourly bar, 3 h into a daily session):
        // bar i is forming, bars < i are complete.
        now = bars[i].time.add(tf == BarTimeframe.d1 ? const Duration(hours: 3) : const Duration(minutes: 30));
        final before = state.ordersToday;
        final beforeKey = state.ordersDayKey;
        await engine.runCycle();
        cycles++;
        // Engines never see the forming bar.
        if (seenLast.isNotEmpty) {
          expect(seenLast.last.isBefore(bars[i].time), isTrue, reason: 'forming bar leaked at $i');
        }
        final opened = state.ordersDayKey == beforeKey ? state.ordersToday - before : state.ordersToday;
        ordersPerDay.update(NewYorkTime.dateKey(now), (v) => v + opened, ifAbsent: () => opened);
        final pos = await broker.positions();
        expect(pos.length, lessThanOrEqualTo(settings.maxOpenPositions));
        final rights = pos.where((p) => p.contract.underlying == sym).map((p) => p.contract.right).toSet();
        expect(rights.length, lessThanOrEqualTo(1), reason: 'Call/Put lock violated at $i');
      }
      expect(state.cycles.length, cycles);
      for (final v in ordersPerDay.values) {
        expect(v, lessThanOrEqualTo(settings.maxOrdersPerDay));
      }
      expect(state.journal.where((j) => j.action == JournalAction.error), isEmpty,
          reason: state.journal.where((j) => j.action == JournalAction.error).map((j) => j.reasonAr).join('\n'));
      for (final t in state.trades) {
        expect(t.entryReasonAr, isNotEmpty);
        expect(t.exitReasonAr, isNotEmpty);
        expect(t.engines, isNotEmpty);
      }
      final report = AccountReport.build(state.trades, state.equityCurve, startingEquityCents: 10000000);
      expect(report.daily.fold<int>(0, (a, d) => a + d.pnlCents), report.performance.realizedPnlCents);
      expect(report.performance.wins + report.performance.losses + report.performance.breakevens, state.trades.length);
      // Informational (no profitability claim): printed in the test log.
      final entries = state.journal.where((j) => j.action == JournalAction.entry).length;
      // ignore: avoid_print
      print('$sym ${tf.name} replay: $cycles cycles, $entries entries, ${state.trades.length} closed trades, '
          'realized ${formatUsd(report.performance.realizedPnlCents)}, maxDD ${report.performance.maxDrawdownPercent.toStringAsFixed(2)}%');
    });
  }
}
