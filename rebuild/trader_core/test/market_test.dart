import 'dart:convert';

import 'package:test/test.dart';
import 'package:trader_core/trader_core.dart';

import 'adapters_test.dart' show FakeHttp;

/// Real-broker-like wrapper around the simulator: reports `alpaca` and appends
/// a still-forming bar, like a live data feed does.
class RealLikeBroker implements BrokerAdapter {
  final SimulatorBroker inner;
  final DateTime Function() clock;
  final List<int> placed = [];
  RealLikeBroker(this.inner, this.clock);

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
  Future<BrokerOrder> placeOrder(OrderRequest r) {
    placed.add(r.quantity);
    return inner.placeOrder(r);
  }

  @override
  Future<void> cancelOrder(String id) => inner.cancelOrder(id);
  @override
  Future<BrokerOrder?> order(String id) => inner.order(id);
  @override
  Future<List<Candle>> bars(String symbol, BarTimeframe tf, {int limit = 300}) async {
    final b = await inner.bars(symbol, tf, limit: limit);
    final last = b.last;
    // Forming bar: started 5 minutes ago (a 15m bar completes 10 minutes from now).
    return [
      ...b,
      Candle(time: clock().subtract(const Duration(minutes: 5)), open: last.close, high: last.close * 1.01,
          low: last.close * 0.99, close: last.close * 1.005)
    ];
  }

  @override
  Future<double> lastPrice(String s) => inner.lastPrice(s);
  @override
  Future<List<OptionQuote>> optionChain(String u, {required DateTime minExpiry, required DateTime maxExpiry, OptionRight? right}) =>
      inner.optionChain(u, minExpiry: minExpiry, maxExpiry: maxExpiry, right: right);
  @override
  Future<OptionQuote?> optionQuote(OptionContract c) => inner.optionQuote(c);
}

class FakeClock implements MarketClockSource {
  BrokerMarketClock? value;
  Object? error;
  @override
  Future<BrokerMarketClock> marketClock() async {
    if (error != null) throw error!;
    return value!;
  }
}

void main() {
  const cal = MarketCalendar();

  group('New York time', () {
    test('DST transitions 2026 (Mar 8 07:00Z, Nov 1 06:00Z)', () {
      expect(NewYorkTime.offsetAt(DateTime.utc(2026, 3, 8, 6, 59)), const Duration(hours: -5));
      expect(NewYorkTime.offsetAt(DateTime.utc(2026, 3, 8, 7)), const Duration(hours: -4));
      expect(NewYorkTime.offsetAt(DateTime.utc(2026, 11, 1, 5, 59)), const Duration(hours: -4));
      expect(NewYorkTime.offsetAt(DateTime.utc(2026, 11, 1, 6)), const Duration(hours: -5));
      expect(NewYorkTime.dstStartUtc(2027), DateTime.utc(2027, 3, 14, 7));
      expect(NewYorkTime.dstEndUtc(2027), DateTime.utc(2027, 11, 7, 6));
    });

    test('wall <-> UTC for the session open in summer and winter', () {
      expect(NewYorkTime.toUtc(2026, 7, 1, 9, 30), DateTime.utc(2026, 7, 1, 13, 30));
      expect(NewYorkTime.toUtc(2026, 12, 1, 9, 30), DateTime.utc(2026, 12, 1, 14, 30));
      expect(NewYorkTime.toUtc(2026, 3, 9, 9, 30), DateTime.utc(2026, 3, 9, 13, 30)); // first EDT Monday
      expect(NewYorkTime.toUtc(2026, 11, 2, 9, 30), DateTime.utc(2026, 11, 2, 14, 30)); // first EST Monday
      expect(NewYorkTime.hm(DateTime.utc(2026, 7, 1, 20)), '16:00');
    });

    test('date key is the New York date', () {
      expect(NewYorkTime.dateKey(DateTime.utc(2026, 10, 19, 2)), '2026-10-18'); // 22:00 EDT
      expect(NewYorkTime.dateKey(DateTime.utc(2026, 10, 19, 4)), '2026-10-19'); // 00:00 EDT
      expect(NewYorkTime.dateKey(DateTime.utc(2026, 12, 1, 4, 59)), '2026-11-30'); // 23:59 EST
    });
  });

  group('NYSE calendar', () {
    test('rules reproduce the official NYSE table 2026-2028', () {
      for (final y in [2026, 2027, 2028]) {
        final official = {
          for (final e in MarketCalendar.officialHolidays.entries)
            if (e.key.year == y) e.key
        };
        expect(MarketCalendar.ruleHolidays(y).keys.toSet(), official, reason: 'holidays $y');
        expect(MarketCalendar.ruleEarlyCloses(y), {
          for (final d in MarketCalendar.officialEarlyCloses)
            if (d.year == y) d
        }, reason: 'early closes $y');
      }
    });

    test('2026-2027 holidays are closed with their names; weekends closed', () {
      expect(cal.isTradingDay(DateTime.utc(2026, 4, 3)), isFalse); // Good Friday
      expect(cal.holidayName(DateTime.utc(2026, 7, 3)), contains('الاستقلال'));
      expect(cal.isTradingDay(DateTime.utc(2027, 7, 5)), isFalse);
      expect(cal.isTradingDay(DateTime.utc(2027, 12, 24)), isFalse);
      expect(cal.isTradingDay(DateTime.utc(2026, 10, 17)), isFalse); // Saturday
      expect(cal.isTradingDay(DateTime.utc(2026, 10, 19)), isTrue);
      expect(cal.isTradingDay(DateTime.utc(2027, 12, 31)), isTrue); // Saturday New Year 2028 not observed
    });

    test('phases on a regular EDT day', () {
      MarketPhase at(int h, int m) => cal.statusAt(DateTime.utc(2026, 10, 19, h, m)).phase;
      expect(at(7, 59), MarketPhase.closed);
      expect(at(8, 0), MarketPhase.preMarket); // 04:00 ET
      expect(at(13, 29), MarketPhase.preMarket);
      expect(at(13, 30), MarketPhase.open);
      expect(at(19, 59), MarketPhase.open);
      expect(at(20, 0), MarketPhase.postMarket);
      expect(at(23, 59), MarketPhase.postMarket);
      expect(cal.statusAt(DateTime.utc(2026, 10, 20, 0, 0)).phase, MarketPhase.closed); // 20:00 ET
    });

    test('early close: Nov 27 2026 closes 13:00 EST (18:00Z)', () {
      expect(cal.statusAt(DateTime.utc(2026, 11, 27, 17, 59)).isOpen, isTrue);
      final after = cal.statusAt(DateTime.utc(2026, 11, 27, 18));
      expect(after.phase, MarketPhase.postMarket);
      expect(after.today!.earlyClose, isTrue);
      expect(cal.statusAt(DateTime.utc(2026, 11, 27, 22)).phase, MarketPhase.closed); // after 17:00 ET
    });

    test('next open skips weekends and holidays', () {
      // Thursday Jul 2 2026 after close -> Fri Jul 3 holiday -> Mon Jul 6 09:30 EDT.
      final s = cal.statusAt(DateTime.utc(2026, 7, 2, 21));
      expect(s.nextOpen, DateTime.utc(2026, 7, 6, 13, 30));
      final hol = cal.statusAt(DateTime.utc(2026, 11, 26, 15));
      expect(hol.phase, MarketPhase.closed);
      expect(hol.closedReasonAr, 'عيد الشكر');
      expect(hol.nextOpen, DateTime.utc(2026, 11, 27, 14, 30));
      expect(hol.nextClose, DateTime.utc(2026, 11, 27, 18));
      final open = cal.statusAt(DateTime.utc(2026, 10, 19, 15));
      expect(open.nextClose, DateTime.utc(2026, 10, 19, 20));
      expect(open.nextOpen, DateTime.utc(2026, 10, 20, 13, 30));
      expect(cal.statusAt(DateTime.utc(2026, 10, 17, 12)).closedReasonAr, 'عطلة نهاية الأسبوع');
    });
  });

  group('completed bars', () {
    List<Candle> intraday(DateTime first, int n, Duration step) => [
          for (var i = 0; i < n; i++)
            Candle(time: first.add(step * i), open: 10, high: 11, low: 9, close: 10.5)
        ];

    test('the forming intraday bar is dropped until its period ends', () {
      final b = intraday(DateTime.utc(2026, 10, 19, 13, 30), 3, const Duration(minutes: 15)); // last starts 14:00Z
      expect(cal.completedBars(b, BarTimeframe.m15, DateTime.utc(2026, 10, 19, 14, 10)), hasLength(2));
      expect(cal.completedBars(b, BarTimeframe.m15, DateTime.utc(2026, 10, 19, 14, 15)), hasLength(3));
    });

    test('an hourly bar spanning an early close completes at the close', () {
      final b = intraday(DateTime.utc(2026, 11, 27, 17), 1, const Duration(hours: 1));
      expect(cal.barCompletesAt(b.single.time, BarTimeframe.h1), DateTime.utc(2026, 11, 27, 18));
    });

    test('a daily bar completes at that session close (16:00 ET / 13:00 on early close)', () {
      final fri = Candle(time: DateTime.utc(2026, 10, 16, 4), open: 10, high: 11, low: 9, close: 10);
      expect(cal.completedBars([fri], BarTimeframe.d1, DateTime.utc(2026, 10, 16, 19, 59)), isEmpty);
      expect(cal.completedBars([fri], BarTimeframe.d1, DateTime.utc(2026, 10, 16, 20)), hasLength(1));
      final early = Candle(time: DateTime.utc(2026, 11, 27, 5), open: 10, high: 11, low: 9, close: 10);
      expect(cal.barCompletesAt(early.time, BarTimeframe.d1), DateTime.utc(2026, 11, 27, 18));
    });

    test('simulator bars are kept as-is (complete by construction)', () {
      final b = intraday(DateTime.utc(2026, 10, 19, 13, 30), 3, const Duration(minutes: 15));
      final now = DateTime.utc(2026, 10, 19, 14, 10);
      expect(TradingEngine.completedBarsFor(BrokerKind.simulator, b, BarTimeframe.m15, now), hasLength(3));
      expect(TradingEngine.completedBarsFor(BrokerKind.alpaca, b, BarTimeframe.m15, now), hasLength(2));
    });
  });

  group('market hours gate', () {
    final openNow = DateTime.utc(2026, 10, 19, 15);
    test('calendar only when no broker clock', () async {
      expect((await MarketHoursGate().status(openNow)).isOpen, isTrue);
    });

    test('broker clock must agree; disagreement is treated as closed; failure falls back', () async {
      final fc = FakeClock();
      final g = MarketHoursGate(clockSource: fc);
      fc.value = BrokerMarketClock(
          timestamp: openNow, isOpen: true, nextOpen: openNow, nextClose: DateTime.utc(2026, 10, 19, 20));
      final agree = await g.status(openNow);
      expect(agree.isOpen, isTrue);
      expect(agree.source, StatusSource.broker);
      fc.value = BrokerMarketClock(
          timestamp: openNow, isOpen: false, nextOpen: DateTime.utc(2026, 10, 20, 13, 30), nextClose: openNow);
      final closedByBroker = await g.status(openNow);
      expect(closedByBroker.isOpen, isFalse);
      expect(closedByBroker.noteAr, isNotNull);
      fc.value = BrokerMarketClock(timestamp: openNow, isOpen: true, nextOpen: openNow, nextClose: openNow);
      expect((await g.status(DateTime.utc(2026, 10, 18, 15))).isOpen, isFalse); // Sunday: calendar wins
      fc.error = const BrokerException(BrokerErrorCode.network, 'down');
      final fallback = await g.status(openNow);
      expect(fallback.isOpen, isTrue);
      expect(fallback.source, StatusSource.calendar);
      expect(g.lastBrokerError, contains('down'));
    });

    test('Alpaca /v2/clock is parsed with its offsets', () async {
      final http = FakeHttp((m, u, b) {
        expect(u.path, '/v2/clock');
        expect(u.host, 'paper-api.alpaca.markets');
        return HttpResult(200, jsonEncode({
          'timestamp': '2026-10-19T11:00:00.5-04:00',
          'is_open': true,
          'next_open': '2026-10-20T09:30:00-04:00',
          'next_close': '2026-10-19T16:00:00-04:00',
        }));
      });
      final a = AlpacaAdapter(
          accountId: 'a', credentials: const BrokerCredentials({'keyId': 'k', 'secretKey': 's'}), http: http);
      final c = await a.marketClock();
      expect(c.isOpen, isTrue);
      expect(c.nextClose, DateTime.utc(2026, 10, 19, 20));
      expect(c.nextOpen, DateTime.utc(2026, 10, 20, 13, 30));
      expect(TradingEngine.defaultMarketHours(a)!.clockSource, same(a));
    });
  });

  group('trading engine with market hours', () {
    late DateTime now;
    late RealLikeBroker broker;
    late AccountState state;
    final seen = <List<Candle>>[];
    EngineSignal sig(EngineId id) =>
        EngineSignal(engine: id, bias: Bias.bullish, strength: 1, pattern: 'TEST', reasonAr: 'اختبار', knownAtIndex: 0);
    final analyzer = Analyzer(engines: {
      EngineId.trend: (c) {
        seen.add(c);
        return [sig(EngineId.trend)];
      },
      EngineId.momentum: (_) => [sig(EngineId.momentum)],
    });
    AccountProfile profile() => AccountProfile(
          id: 'acc',
          name: 'x',
          broker: BrokerKind.alpaca,
          mode: TradingMode.paper,
          createdAt: DateTime.utc(2026, 1, 1),
          watchlist: const ['AAPL'],
          enabled: true,
          settings: const AccountSettings(riskPerTradePercent: 5, maxPositionPercent: 20, entryAggressiveness: 1),
        );

    void setUpAt(DateTime t) {
      now = t;
      final market = SyntheticMarket(clock: () => now);
      broker = RealLikeBroker(SimulatorBroker(market: market, startingCashCents: 10000000, clock: () => now), () => now);
      state = AccountState();
      seen.clear();
    }

    TradingEngine engine() => TradingEngine(profile: profile(), broker: broker, state: state, analyzer: analyzer, clock: () => now);

    test('outside regular hours: no analysis, no orders, one info note per closed period', () async {
      setUpAt(DateTime.utc(2026, 10, 19, 21)); // 17:00 EDT, post-market
      final e = engine();
      expect(e.marketHours, isNotNull);
      final r = await e.runCycle();
      await e.runCycle();
      expect(r.ran, isTrue);
      expect(r.noteAr, contains('بعد الإغلاق'));
      expect(broker.placed, isEmpty);
      expect(seen, isEmpty);
      expect(state.journal.where((j) => j.action == JournalAction.info && j.reasonAr.contains('لا تحليل ولا أوامر')),
          hasLength(1));
      expect(e.lastMarketStatus!.phase, MarketPhase.postMarket);
    });

    test('holiday: closed with its name', () async {
      setUpAt(DateTime.utc(2026, 11, 26, 16));
      final r = await engine().runCycle();
      expect(r.noteAr, contains('عيد الشكر'));
      expect(broker.placed, isEmpty);
    });

    test('during regular hours: trades, and engines get completed bars only', () async {
      setUpAt(DateTime.utc(2026, 10, 19, 15)); // 11:00 EDT
      final raw = await broker.bars('AAPL', BarTimeframe.m15);
      await engine().runCycle();
      expect(broker.placed, isNotEmpty);
      expect(seen, isNotEmpty);
      expect(seen.first.length, raw.length - 1);
      expect(seen.first.last.time, raw[raw.length - 2].time);
    });

    test('daily-loss day key is the New York date', () async {
      setUpAt(DateTime.utc(2026, 10, 20, 1)); // 21:00 EDT Oct 19
      await engine().runCycle();
      expect(state.dayKey, '2026-10-19');
    });
  });
}
