import 'package:test/test.dart';
import 'package:trader_core/trader_core.dart';

/// Elliott waves are descriptive only: they may be drawn on the chart but never feed the composite score,
/// an entry, an exit or any order — whatever weight is saved (research: no proven forecasting edge).
void main() {
  final now = DateTime.utc(2026, 6, 1, 15);
  late SyntheticMarket market;
  late SimulatorBroker broker;
  late AccountState state;

  EngineSignal sig(EngineId id) => EngineSignal(
      engine: id, bias: Bias.bullish, strength: 1, pattern: 'TEST', reasonAr: 'إشارة اختبار', knownAtIndex: 0);

  /// Every engine is present; only the listed ones see something.
  Analyzer analyzerWith(Set<EngineId> firing) => Analyzer(engines: {
        for (final id in EngineId.values) id: (_) => firing.contains(id) ? [sig(id)] : const <EngineSignal>[],
      });

  // Permissive settings, every engine ON with weight 3 (Elliott too, as an old save would have it).
  AccountSettings permissive() => AccountSettings.fromJson({
        'riskPerTradePercent': 5,
        'maxPositionPercent': 20,
        'entryAggressiveness': 1.0,
        'stopLossPercent': 50,
        'symbolCooldownMinutes': 0,
        'minScore': 5,
        'minAgreeingEngines': 1,
        'requireTrendAlignment': false,
        'engineWeights': {for (final id in EngineId.values) id.name: 3},
      });

  AccountProfile profile(AccountSettings s) => AccountProfile(
        id: 'acc-elliott',
        name: 'تجريبي',
        broker: BrokerKind.simulator,
        mode: TradingMode.paper,
        createdAt: now,
        watchlist: const ['AAPL'],
        enabled: true,
        startingCashCents: 10000000,
        settings: s,
      );

  Future<void> cycles(AccountSettings s, Analyzer a, {int n = 3}) async {
    final e = TradingEngine(profile: profile(s), broker: broker, state: state, analyzer: a, clock: () => now);
    for (var i = 0; i < n; i++) {
      await e.runCycle();
    }
  }

  setUp(() {
    market = SyntheticMarket(clock: () => now);
    broker = SimulatorBroker(market: market, startingCashCents: 10000000, clock: () => now);
    state = AccountState();
  });

  test('control: the same permissive setup DOES trade on a non-Elliott signal', () async {
    await cycles(permissive(), analyzerWith({EngineId.momentum}));
    expect(await broker.positions(), isNotEmpty);
  });

  test('an Elliott-only setup never produces an order (all engines on, migrated weights)', () async {
    await cycles(permissive(), analyzerWith({EngineId.elliott}));
    expect(await broker.positions(), isEmpty);
    expect(await broker.openOrders(), isEmpty);
    expect(state.journal.where((j) => j.action == JournalAction.entry || j.action == JournalAction.scaleIn), isEmpty);
  });

  test('…even when an Elliott weight > 0 is forced in directly (no migration path)', () async {
    const raw = AccountSettings(
      riskPerTradePercent: 5,
      maxPositionPercent: 20,
      entryAggressiveness: 1.0,
      stopLossPercent: 50,
      symbolCooldownMinutes: 0,
      minScore: 5,
      minAgreeingEngines: 1,
      requireTrendAlignment: false,
      engineWeights: {
        EngineId.trend: 3,
        EngineId.momentum: 3,
        EngineId.divergence: 3,
        EngineId.harmonic: 3,
        EngineId.elliott: 3,
        EngineId.classical: 3,
      },
    );
    await cycles(raw, analyzerWith({EngineId.elliott}));
    expect(await broker.positions(), isEmpty);
    expect(await broker.openOrders(), isEmpty);
  });

  test('Elliott never enters the score, but stays available to the chart overlay', () {
    final candles = [
      for (var i = 0; i < 80; i++)
        Candle(time: now.subtract(Duration(minutes: 15 * (80 - i))), open: 100, high: 101, low: 99, close: 100, volume: 1)
    ];
    final a = analyzerWith({EngineId.elliott});
    final w = {for (final id in EngineId.values) id: 3.0};
    final r = a.analyze('AAPL', candles, weights: w);
    expect(r.score, 0);
    expect(r.signals, isEmpty);
    final full = a.analyzeWithFindings('AAPL', candles, weights: w);
    expect(full.report.score, 0);
    expect(full.findings[EngineId.elliott], hasLength(1)); // drawn on the chart
    final chart = ChartAnalysis.compute('AAPL', candles, weights: w, analyzer: a);
    expect(chart.report.signals, isEmpty);
    expect(chart.findings[EngineId.elliott], isNotEmpty);
    expect(chart.scoreHistory.whereType<double>().every((x) => x == 0), isTrue);
  });

  test('defaults and migration: Elliott weight is always 0', () {
    expect(const AccountSettings().engineWeights[EngineId.elliott], 0);
    final old = AccountSettings.fromJson({
      'engineWeights': {'trend': 1.5, 'elliott': 0.8}
    });
    expect(old.engineWeights[EngineId.elliott], 0);
    expect(old.engineWeights[EngineId.trend], 1.5);
    expect(old.toJson()['engineWeights'], containsPair('elliott', 0.0));
    final edited = const AccountSettings().copyWith(engineWeights: {EngineId.elliott: 2, EngineId.trend: 1});
    expect(edited.engineWeights[EngineId.elliott], 0);
    expect(EngineId.elliott.descriptiveOnly, isTrue);
    expect([for (final id in EngineId.values) if (id.descriptiveOnly) id], [EngineId.elliott]);
    expect(kElliottNoticeAr, 'تحليل وصفي — لم يُثبت قدرة تنبؤية، لا يُستخدم كإشارة تداول');
  });
}
