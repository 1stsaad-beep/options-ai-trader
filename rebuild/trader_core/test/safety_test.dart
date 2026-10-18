import 'dart:convert';

import 'package:test/test.dart';
import 'package:trader_core/trader_core.dart';

import 'adapters_test.dart' show FakeHttp;

void main() {
  var now = DateTime.utc(2026, 6, 1, 15);
  late SimulatorBroker broker;
  late AccountState state;
  var bias = Bias.bullish;

  EngineSignal sig(EngineId id) =>
      EngineSignal(engine: id, bias: bias, strength: 1, pattern: 'TEST', reasonAr: 'إشارة اختبار', knownAtIndex: 0);
  final analyzer = Analyzer(engines: {
    EngineId.trend: (_) => [sig(EngineId.trend)],
    EngineId.momentum: (_) => [sig(EngineId.momentum)],
  });

  AccountProfile profile({int cooldown = 60, int maxOrders = 10, List<String> watch = const ['AAPL']}) => AccountProfile(
        id: 'acc',
        name: 'x',
        broker: BrokerKind.simulator,
        mode: TradingMode.paper,
        createdAt: now,
        watchlist: watch,
        enabled: true,
        startingCashCents: 10000000,
        settings: AccountSettings(
          riskPerTradePercent: 5,
          maxPositionPercent: 20,
          entryAggressiveness: 1,
          stopLossPercent: 50,
          symbolCooldownMinutes: cooldown,
          maxOrdersPerDay: maxOrders,
          maxOpenPositions: 5,
        ),
      );

  TradingEngine engine(AccountProfile p) =>
      TradingEngine(profile: p, broker: broker, state: state, analyzer: analyzer, clock: () => now);

  setUp(() {
    now = DateTime.utc(2026, 6, 1, 15);
    final market = SyntheticMarket(clock: () => now);
    broker = SimulatorBroker(market: market, startingCashCents: 10000000, clock: () => now);
    state = AccountState();
    bias = Bias.bullish;
  });

  test('settings: new safety knobs validate and survive JSON (old saves get defaults)', () {
    const d = AccountSettings();
    expect(d.maxOrdersPerDay, 10);
    expect(d.symbolCooldownMinutes, 60);
    expect(const AccountSettings(maxOrdersPerDay: 0).validate(), isNotEmpty);
    expect(const AccountSettings(symbolCooldownMinutes: 2000).validate(), isNotEmpty);
    final s = AccountSettings.fromJson(const AccountSettings(maxOrdersPerDay: 3, symbolCooldownMinutes: 15).toJson());
    expect(s.maxOrdersPerDay, 3);
    expect(s.symbolCooldownMinutes, 15);
    final old = AccountSettings.fromJson(<String, dynamic>{'riskPerTradePercent': 2});
    expect(old.maxOrdersPerDay, 10);
  });

  test('cooldown: after an exit no re-entry on the symbol until it expires', () async {
    final e = engine(profile(cooldown: 60));
    await e.runCycle(); // buy Call
    bias = Bias.bearish;
    now = now.add(const Duration(minutes: 1));
    await e.runCycle(); // exit Call (opposite signal)
    expect(await broker.positions(), isEmpty);
    now = now.add(const Duration(minutes: 1));
    await e.runCycle(); // cooldown blocks the Put
    expect(await broker.positions(), isEmpty);
    expect(state.cycles.last.symbols['AAPL']!.reasonAr, contains('فترة تهدئة'));
    now = now.add(const Duration(minutes: 60));
    await e.runCycle();
    expect((await broker.positions()).single.contract.right, OptionRight.put);
  });

  test('max opening orders per day caps entries, exits are not capped, resets next NY day', () async {
    final e = engine(profile(maxOrders: 1, watch: const ['AAPL', 'MSFT'], cooldown: 0));
    await e.runCycle();
    expect(await broker.positions(), hasLength(1));
    expect(state.ordersToday, 1);
    now = now.add(const Duration(minutes: 1));
    final r = await e.runCycle();
    expect(r.noteAr, 'الحد اليومي للأوامر');
    expect(await broker.positions(), hasLength(1));
    expect(state.journal.where((j) => j.action == JournalAction.blocked && j.reasonAr.contains('أوامر الفتح')), hasLength(1));
    // Exit is still allowed although the cap is reached.
    bias = Bias.bearish;
    now = now.add(const Duration(minutes: 1));
    await e.runCycle();
    expect(state.trades, hasLength(1));
    // Next New York day: counter resets.
    bias = Bias.bullish;
    now = DateTime.utc(2026, 6, 2, 15);
    await e.runCycle();
    expect(state.ordersDayKey, '2026-06-02');
    expect(state.ordersToday, greaterThanOrEqualTo(1));
  });

  test('cycle records: scores, decision + reason per symbol, orders, fills; JSON round trip', () async {
    final e = engine(profile());
    await e.runCycle();
    final c = state.cycles.single;
    expect(c.cycle, 1);
    expect(c.ran, isTrue);
    expect(c.symbols['AAPL']!.score, greaterThan(0));
    expect(c.symbols['AAPL']!.action, 'entry');
    expect(c.orders.single, contains('شراء'));
    expect(c.fills, 1);
    expect(state.journal.where((j) => j.details['cycle'] == 1), isNotEmpty);
    // A rate-limited skip is still visible in the cycle record.
    bias = Bias.neutral;
    for (var k = 0; k < 2; k++) {
      now = now.add(const Duration(minutes: 1));
      await e.runCycle();
    }
    expect(state.cycles, hasLength(3));
    final back = AccountState.fromJson(jsonDecode(jsonEncode(state.toJson())) as Map<String, dynamic>);
    expect(back.cycles.map((x) => x.toJson()), state.cycles.map((x) => x.toJson()));
    expect(back.ordersToday, state.ordersToday);
    expect(back.lastTradeAt, state.lastTradeAt);
  });

  test('cycles are bounded', () {
    final s = AccountState();
    for (var i = 0; i < AccountState.maxCycles + 10; i++) {
      s.addCycle(CycleRecord(cycle: i, start: now));
    }
    expect(s.cycles, hasLength(AccountState.maxCycles));
    expect(s.cycles.first.cycle, 10);
  });

  test('Alpaca snapshot greeks (delta/gamma/theta/vega/IV) are parsed', () async {
    final occ = OptionContract(underlying: 'AAPL', right: OptionRight.call, expiry: DateTime.utc(2026, 6, 19), strikeCents: 20000);
    final http = FakeHttp((m, u, b) => HttpResult(
        200,
        jsonEncode({
          'snapshots': {
            occ.occSymbol: {
              'latestQuote': {'bp': 1.2, 'ap': 1.3, 't': '2026-06-01T15:00:00Z'},
              'greeks': {'delta': 0.45, 'gamma': 0.03, 'theta': -0.05, 'vega': 0.12},
              'impliedVolatility': 0.31,
            }
          }
        })));
    final a = AlpacaAdapter(accountId: 'a', credentials: const BrokerCredentials({'keyId': 'k', 'secretKey': 's'}), http: http);
    final q = (await a.optionQuote(occ))!;
    expect(q.delta, 0.45);
    expect(q.gamma, 0.03);
    expect(q.theta, -0.05);
    expect(q.vega, 0.12);
    expect(q.impliedVolatility, 0.31);
  });
}
