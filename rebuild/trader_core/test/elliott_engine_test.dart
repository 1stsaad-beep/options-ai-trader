import 'package:test/test.dart';
import 'package:trader_core/trader_core.dart';

import 'real_bars_test.dart' show loadFixture, ReplayBroker, ReplayMarket;

void main() {
  test('preset: experimental strategy off by default; preset sets the researched exits and is valid', () {
    const d = AccountSettings();
    expect(d.strategy, StrategyKind.composite);
    final p = d.withElliottDailyPreset();
    expect(p.strategy, StrategyKind.elliottDaily);
    expect(p.validate(), isEmpty);
    expect((p.minDaysToExpiry, p.maxDaysToExpiry, p.maxHoldingDays, p.exitDaysBeforeExpiry), (2, 9, 7, 1));
    expect(p.elliottAllowPuts, isFalse);
    final j = AccountSettings.fromJson(p.toJson());
    expect((j.strategy, j.elliottZigZagAtr, j.elliottFineAtr), (StrategyKind.elliottDaily, 1.5, 0.6));
    expect(d.copyWith(elliottFineAtr: 1.4, elliottZigZagAtr: 1.0).validate(), isNotEmpty);
  });

  test('engine: daily Elliott signal on the last completed daily bar opens a Call next session, tagged, once', () async {
    final s = const AccountSettings(
            riskPerTradePercent: 5, maxPositionPercent: 20, entryAggressiveness: 1, symbolCooldownMinutes: 0, timeframe: BarTimeframe.d1)
        .withElliottDailyPreset();
    final d = loadFixture('aapl_d1');
    final sigs = mtfElliottSignals(
        entry: TfSeries.of(BarTimeframe.d1, d),
        mid: weeklyFromDaily(d),
        p: ElliottParams(requireTop: false, requireMid: false, kEntry: s.elliottZigZagAtr, kFine: s.elliottFineAtr, puts: false));
    final sig = sigs.firstWhere((x) => x.index >= 120 && x.index + 1 < d.length);
    var t = d[sig.index + 1].time.add(const Duration(hours: 1)); // next session, bar i+1 still forming
    (AccountState, TradingEngine) make() {
      final broker = ReplayBroker(SimulatorBroker(
          market: ReplayMarket({'AAPL': d}, const Duration(days: 1), () => t), startingCashCents: 10000000, clock: () => t));
      final state = AccountState();
      return (
        state,
        TradingEngine(
          profile: AccountProfile(
              id: 'e', name: 'e', broker: BrokerKind.alpaca, mode: TradingMode.paper, createdAt: t,
              watchlist: const ['AAPL'], enabled: true, startingCashCents: 10000000, settings: s),
          broker: broker,
          state: state,
          analyzer: Analyzer(engines: const {}),
          clock: () => t,
        )
      );
    }

    final (state, engine) = make();
    await engine.runCycle();
    final entries = state.journal.where((j) => j.action == JournalAction.entry).toList();
    expect(entries, hasLength(1), reason: [for (final j in state.journal) j.reasonAr].join(' | '));
    expect(entries.single.reasonAr, contains('إليوت اليومية (تجريبية)'));
    final opened = [
      for (final o in state.tracked.values) (o.occSymbol, o.engines),
      for (final m in state.metas.entries) (m.key, m.value.engines),
    ];
    expect(opened, hasLength(1));
    expect(opened.single.$2, [elliottDailyTag]);
    expect(OptionContract.fromOcc(opened.single.$1).right, OptionRight.call);
    // the same signal later that session: used once only
    t = t.add(const Duration(hours: 2));
    await engine.runCycle();
    expect(state.journal.where((j) => j.action == JournalAction.entry), hasLength(1));

    // the session before the signal bar completed: no signal yet (no look-ahead)
    t = d[sig.index].time.add(const Duration(hours: 1));
    final (s2, e2) = make();
    await e2.runCycle();
    expect(s2.journal.where((j) => j.action == JournalAction.entry), isEmpty);
    expect(s2.journal.any((j) => j.reasonAr.contains('لا إشارة على آخر شمعة يومية مكتملة')), isTrue);
  });

  test('composite accounts are unaffected (no daily Elliott evaluation)', () async {
    final t = DateTime.utc(2026, 6, 1, 15);
    final broker = SimulatorBroker(market: SyntheticMarket(clock: () => t), startingCashCents: 10000000, clock: () => t);
    final state = AccountState();
    await TradingEngine(
      profile: AccountProfile(
          id: 'c', name: 'c', broker: BrokerKind.simulator, mode: TradingMode.paper, createdAt: t,
          watchlist: const ['AAPL'], enabled: true, startingCashCents: 10000000, settings: const AccountSettings()),
      broker: broker,
      state: state,
      analyzer: Analyzer(engines: const {}),
      clock: () => t,
    ).runCycle();
    expect(state.journal.where((j) => j.reasonAr.contains('إليوت اليومي')), isEmpty);
  });
}
