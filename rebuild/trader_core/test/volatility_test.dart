import 'dart:math' as math;

import 'package:test/test.dart';
import 'package:trader_core/trader_core.dart';

void main() {
  final now = DateTime.utc(2026, 6, 1, 15); // Monday 11:00 ET
  final contract = OptionContract(underlying: 'AAPL', right: OptionRight.call, expiry: DateTime.utc(2026, 6, 5), strikeCents: 10000);

  List<Candle> dailyFromReturns(double start, List<double> logReturns) {
    var p = start;
    final out = <Candle>[];
    var t = DateTime.utc(2026, 4, 1, 13, 30);
    out.add(Candle(time: t, open: p, high: p, low: p, close: p, volume: 1));
    for (final r in logReturns) {
      p *= math.exp(r);
      t = t.add(const Duration(days: 1));
      out.add(Candle(time: t, open: p, high: p, low: p, close: p, volume: 1));
    }
    return out;
  }

  test('realized vol: annualised sample stdev of log returns', () {
    final rets = [for (var i = 0; i < 20; i++) i.isEven ? 0.01 : -0.01];
    final closes = [for (final c in dailyFromReturns(100, rets)) c.close];
    // mean 0, sample stdev = 0.01*sqrt(20/19)
    expect(realizedVol(closes, lookback: 20), closeTo(0.01 * math.sqrt(20 / 19) * math.sqrt(252), 1e-9));
    expect(realizedVol(closes.sublist(0, 10), lookback: 20), isNull);
  });

  test('implied vol solver inverts Black-Scholes', () {
    for (final v in [0.12, 0.3, 0.85]) {
      final px = blackScholes(isCall: false, spot: 100, strike: 97, years: 10 / 365, vol: v).price;
      expect(impliedVolFromPrice(isCall: false, spot: 100, strike: 97, years: 10 / 365, price: px), closeTo(v, 1e-5));
    }
    expect(impliedVolFromPrice(isCall: true, spot: 100, strike: 100, years: 0.1, price: 150), isNull);
  });

  test('years to expiry runs to the 16:00 ET close of expiry day', () {
    // Mon 15:00Z -> Fri 20:00Z (EDT) = 4 days 5 hours
    expect(yearsToExpiry(contract, now) * 365 * 24, closeTo(4 * 24 + 5, 1e-6));
  });

  OptionQuote quote({double? iv, int bid = 190, int ask = 210}) =>
      OptionQuote(contract: contract, bidCents: bid, askCents: ask, time: now, impliedVolatility: iv);
  final daily = dailyFromReturns(100, [for (var i = 0; i < 30; i++) i.isEven ? 0.01 : -0.01]); // RV ~16%

  test('disabled filter measures but never blocks', () {
    final v = evaluateVolFilter(f: const VolFilterSettings(), q: quote(iv: 0.9), spot: 100, now: now, daily: daily);
    expect(v.ivRv, greaterThan(5));
    expect(v.blocked, isFalse);
    expect(v.ivSource, 'broker');
    expect(v.summaryAr, contains('IV/RV'));
  });

  test('enabled: IV/RV above the cap blocks; below passes', () {
    const f = VolFilterSettings(enabled: true, maxIvRvRatio: 1.5, maxBreakevenToExpectedMove: 0);
    final rv = evaluateVolFilter(f: f, q: quote(iv: 0.2), spot: 100, now: now, daily: daily).rv!;
    expect(evaluateVolFilter(f: f, q: quote(iv: rv * 1.6), spot: 100, now: now, daily: daily).blockReasonAr, contains('IV/RV'));
    expect(evaluateVolFilter(f: f, q: quote(iv: rv * 1.4), spot: 100, now: now, daily: daily).blocked, isFalse);
  });

  test('enabled: break-even move far above the expected move blocks', () {
    const f = VolFilterSettings(enabled: true, maxIvRvRatio: 99, maxBreakevenToExpectedMove: 1.0);
    // premium $2 on a 100 call with spot 100: break-even 2%; expected = 16% * sqrt(4.2/365) ~ 1.7%
    final v = evaluateVolFilter(f: f, q: quote(iv: 0.3), spot: 100, now: now, daily: daily);
    expect(v.breakevenMovePct, closeTo(2.0, 1e-9));
    expect(v.breakevenToExpected, greaterThan(1));
    expect(v.blockReasonAr, contains('حركة التعادل'));
  });

  test('IV falls back to the value solved from the mid; missing data blocks only when enabled', () {
    final v = evaluateVolFilter(f: const VolFilterSettings(), q: quote(), spot: 100, now: now, daily: daily);
    expect(v.ivSource, 'solved');
    final px = blackScholes(isCall: true, spot: 100, strike: 100, years: v.years, vol: v.iv!).price;
    expect(px, closeTo(2.0, 1e-4));
    final none = evaluateVolFilter(
        f: const VolFilterSettings(enabled: true), q: quote(iv: 0.3), spot: 100, now: now, daily: daily.sublist(0, 5));
    expect(none.rv, isNull);
    expect(none.blockReasonAr, contains('تعذر'));
  });

  test('intraday RV option uses the analysis bars', () {
    final intraday = [
      for (var i = 0; i < 26 * 25; i++)
        () {
          final c = i.isEven ? 100.0 : 100.5;
          return Candle(time: DateTime.utc(2026, 5, 1).add(Duration(minutes: 15 * i)), open: c, high: c, low: c, close: c, volume: 1);
        }()
    ];
    final v = evaluateVolFilter(
        f: const VolFilterSettings(useIntradayRv: true), q: quote(iv: 0.3), spot: 100, now: now, daily: daily, intraday: intraday);
    expect(v.rvIntraday, isNotNull);
    expect(v.rv, v.rvIntraday);
    expect(v.rvIntraday, greaterThan(v.rvDaily!));
  });

  group('engine', () {
    late DateTime t;
    late SimulatorBroker broker;
    late AccountState state;
    EngineSignal sig(EngineId id) =>
        EngineSignal(engine: id, bias: Bias.bullish, strength: 1, pattern: 'TEST', reasonAr: 'اختبار', knownAtIndex: 0);
    final analyzer = Analyzer(engines: {EngineId.trend: (_) => [sig(EngineId.trend)], EngineId.momentum: (_) => [sig(EngineId.momentum)]});
    TradingEngine engine(AccountSettings s) => TradingEngine(
        profile: AccountProfile(
            id: 'a', name: 'x', broker: BrokerKind.simulator, mode: TradingMode.paper, createdAt: t,
            watchlist: const ['AAPL'], enabled: true, startingCashCents: 10000000, settings: s),
        broker: broker, state: state, analyzer: analyzer, clock: () => t);
    const base = AccountSettings(riskPerTradePercent: 5, maxPositionPercent: 20, entryAggressiveness: 1, stopLossPercent: 50);

    setUp(() {
      t = DateTime.utc(2026, 6, 1, 15);
      broker = SimulatorBroker(market: SyntheticMarket(clock: () => t), startingCashCents: 10000000, clock: () => t);
      state = AccountState();
    });

    test('filter off (default): entry goes through and the journal carries IV, RV, IV/RV, bid/ask, spread', () async {
      expect(const AccountSettings().ivRvFilterEnabled, isFalse);
      await engine(base).runCycle();
      final e = state.journal.firstWhere((j) => j.action == JournalAction.entry);
      expect(e.reasonAr, contains('IV/RV'));
      expect(e.details['spreadPct'], isNotNull);
      expect(e.details['bid'], isNotNull);
      final vol = e.details['vol'] as Map;
      expect(vol['iv'], closeTo(0.35, 1e-9)); // simulator quotes carry IV
      expect(vol['ivRv'], isNotNull);
      expect(vol['blocked'], isFalse);
    });

    test('filter on with a tight cap: entry blocked, reason in journal and cycle log', () async {
      await engine(base.copyWith(ivRvFilterEnabled: true, maxIvRvRatio: 0.5, rvUseIntraday: true)).runCycle();
      expect(state.journal.where((j) => j.action == JournalAction.entry), isEmpty);
      final b = state.journal.firstWhere((j) => j.action == JournalAction.blocked);
      expect(b.reasonAr, contains('فلتر التقلب'));
      expect((b.details['vol'] as Map)['blocked'], isTrue);
      expect(state.cycles.single.symbols['AAPL']!.reasonAr, contains('IV/RV'));
      expect(await broker.positions(), isEmpty);
    });

    test('settings JSON round trip and validation of the new fields', () {
      final s = AccountSettings.fromJson(base
          .copyWith(ivRvFilterEnabled: true, maxIvRvRatio: 2.2, rvLookbackDays: 30, rvUseIntraday: true, maxBreakevenToExpectedMove: 0)
          .toJson());
      expect((s.ivRvFilterEnabled, s.maxIvRvRatio, s.rvLookbackDays, s.rvUseIntraday, s.maxBreakevenToExpectedMove), (true, 2.2, 30, true, 0.0));
      expect(base.copyWith(maxIvRvRatio: 0.2).validate(), isNotEmpty);
      expect(base.copyWith(rvLookbackDays: 2).validate(), isNotEmpty);
    });
  });
}
