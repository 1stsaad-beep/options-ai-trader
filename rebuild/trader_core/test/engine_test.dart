import 'package:test/test.dart';
import 'package:trader_core/trader_core.dart';

/// Engine wiring with the simulator broker and a scripted analyzer, so tests
/// control the signal and check what the account does with it.
void main() {
  final now = DateTime.utc(2026, 6, 1, 15);
  late SyntheticMarket market;
  late SimulatorBroker broker;
  late AccountState state;
  var bias = Bias.bullish;

  EngineSignal sig(EngineId id) => EngineSignal(
      engine: id, bias: bias, strength: 1, pattern: 'TEST', reasonAr: 'إشارة اختبار', knownAtIndex: 0);

  final analyzer = Analyzer(engines: {
    EngineId.trend: (_) => bias == Bias.neutral ? const [] : [sig(EngineId.trend)],
    EngineId.momentum: (_) => bias == Bias.neutral ? const [] : [sig(EngineId.momentum)],
  });

  AccountProfile profile({double aggressiveness = 1.0}) => AccountProfile(
        id: 'acc1',
        name: 'تجريبي',
        broker: BrokerKind.simulator,
        mode: TradingMode.paper,
        createdAt: now,
        watchlist: const ['AAPL'],
        enabled: true,
        startingCashCents: 10000000,
        settings: AccountSettings(
          riskPerTradePercent: 5,
          maxPositionPercent: 20,
          entryAggressiveness: aggressiveness,
          stopLossPercent: 50,
          symbolCooldownMinutes: 0, // cooldown has its own tests (safety_test.dart)
        ),
      );

  TradingEngine engine(AccountProfile p) =>
      TradingEngine(profile: p, broker: broker, state: state, analyzer: analyzer, clock: () => now);

  setUp(() {
    market = SyntheticMarket(clock: () => now);
    broker = SimulatorBroker(market: market, startingCashCents: 10000000, clock: () => now);
    state = AccountState();
    bias = Bias.bullish;
  });

  test('bullish signal buys a Call and journals the reason', () async {
    final r = await engine(profile()).runCycle();
    expect(r.ran, isTrue);
    final pos = await broker.positions();
    expect(pos, hasLength(1));
    expect(pos.single.contract.right, OptionRight.call);
    expect(pos.single.contract.underlying, 'AAPL');
    final entry = state.journal.firstWhere((e) => e.action == JournalAction.entry);
    expect(entry.reasonAr, contains('Call'));
    expect(entry.details['analysis'], isNotNull);
    expect(state.metas, hasLength(1));
  });

  test('flip: opposite signal closes the Call first; the Put opens only on a later cycle', () async {
    final e = engine(profile());
    await e.runCycle();
    bias = Bias.bearish;
    await e.runCycle();
    var pos = await broker.positions();
    expect(pos, isEmpty, reason: 'call closed by opposite signal');
    expect(state.trades, hasLength(1));
    expect(state.trades.single.exitKind, ExitKind.oppositeSignal.name);
    // Same cycle must not have opened a Put.
    expect((await broker.openOrders()).where((o) => o.contract.right == OptionRight.put), isEmpty);
    await e.runCycle();
    pos = await broker.positions();
    expect(pos.single.contract.right, OptionRight.put);
  });

  test('a working Call order locks out a Put until it is resolved', () async {
    // Passive pricing (bid) never fills in the simulator, so the order stays working.
    final e = engine(profile(aggressiveness: 0));
    await e.runCycle();
    final working = await broker.openOrders();
    expect(working.single.contract.right, OptionRight.call);
    bias = Bias.bearish;
    await e.runCycle(); // cycle 2: order still within timeout
    expect((await broker.openOrders()).where((o) => o.contract.right == OptionRight.put), isEmpty);
    expect(await broker.positions(), isEmpty);
  });

  test('disabled accounts never trade', () async {
    final r = await engine(profile().copyWith(enabled: false)).runCycle();
    expect(r.ran, isFalse);
    expect(await broker.openOrders(), isEmpty);
  });

  test('state survives a JSON round trip', () async {
    await engine(profile()).runCycle();
    final restored = AccountState.fromJson(Map<String, dynamic>.from(state.toJson()));
    expect(restored.metas.keys, state.metas.keys);
    expect(restored.journal.length, state.journal.length);
    final sim2 = SimulatorBroker(market: market, startingCashCents: 0, clock: () => now)..restore(broker.toJson());
    expect((await sim2.positions()).length, (await broker.positions()).length);
    expect(sim2.cashCents, broker.cashCents);
  });

  group('simulator broker', () {
    test('rejects buying beyond cash and selling more than held', () async {
      final c = (await market.optionChain('AAPL',
              minExpiry: now.add(const Duration(days: 7)), maxExpiry: now.add(const Duration(days: 30)), right: OptionRight.call))
          .first
          .contract;
      final small = SimulatorBroker(market: market, startingCashCents: 100, clock: () => now);
      final buy = await small.placeOrder(
          OrderRequest(clientOrderId: 'b1', contract: c, side: OrderSide.buyToOpen, quantity: 1, limitPriceCents: 99999));
      expect(buy.status, OrderStatus.rejected);
      final sell = await small.placeOrder(
          OrderRequest(clientOrderId: 's1', contract: c, side: OrderSide.sellToClose, quantity: 1, limitPriceCents: 1));
      expect(sell.status, OrderStatus.rejected);
    });

    test('same client order id is idempotent', () async {
      final c = (await market.optionChain('AAPL',
              minExpiry: now.add(const Duration(days: 7)), maxExpiry: now.add(const Duration(days: 30)), right: OptionRight.put))
          .first
          .contract;
      final r = OrderRequest(clientOrderId: 'same', contract: c, side: OrderSide.buyToOpen, quantity: 1, limitPriceCents: 1);
      final a = await broker.placeOrder(r);
      final b = await broker.placeOrder(r);
      expect(a.id, b.id);
      expect((await broker.openOrders()).length, 1);
    });

    test('synthetic market is deterministic', () async {
      final m2 = SyntheticMarket(clock: () => now);
      expect(await market.lastPrice('MSFT'), await m2.lastPrice('MSFT'));
      final bars = await market.bars('MSFT', BarTimeframe.h1, limit: 50);
      expect(bars, hasLength(50));
      expect(bars.last.time.isBefore(now), isTrue);
    });
  });
}
