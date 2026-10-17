import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:options_ai_trader/demo/chart_analysis.dart';
import 'package:options_ai_trader/demo/chart_lab.dart';
import 'package:options_ai_trader/demo/engine.dart';
import 'package:options_ai_trader/demo/wave_analysis.dart';
import 'package:options_ai_trader/direct_alpaca.dart';
import 'package:options_ai_trader/extended_patterns.dart';
import 'package:options_ai_trader/market_geometry.dart';

/// Alternating pivots from prices; first is a high when [startHigh].
List<ChartPivot> piv(List<double> prices, {required bool startHigh}) => [
      for (var i = 0; i < prices.length; i++) ChartPivot(10 + i * 6, 13 + i * 6, prices[i], startHigh ? i.isEven : i.isOdd)
    ];

/// Piecewise-linear candles through anchors (index == tick), like the display fixtures.
List<DemoCandle> candles(Map<int, double> anchors) {
  final ticks = anchors.keys.toList();
  double value(int t) {
    final l = ticks.lastWhere((k) => k <= t), r = ticks.firstWhere((k) => k >= t);
    return l == r ? anchors[l]! : anchors[l]! + (anchors[r]! - anchors[l]!) * (t - l) / (r - l);
  }
  return [
    for (var t = 0; t <= ticks.last; t++)
      () {
        final c = value(t);
        return DemoCandle(t, c, c + .1, c - .1, c, 1000);
      }()
  ];
}

String kinds(List<ChartPivot> p, double close) => extendedPatterns(p, close).map((m) => m['kind']).join(',');

void main() {
  test('triple top/bottom with neckline confirmation', () {
    final top = piv([120, 110, 121, 111, 120.5], startHigh: true);
    var r = extendedPatterns(top, 115).single;
    expect([r['kind'], r['neckline'], r['confirmed'], r['bias'], r['executable']], ['TRIPLE_TOP', 110, false, 'BEARISH', false]);
    expect(extendedPatterns(top, 109.9).single['confirmed'], isTrue);
    final bottom = piv([100, 110, 99.5, 111, 100.5], startHigh: false);
    r = extendedPatterns(bottom, 112).single;
    expect([r['kind'], r['neckline'], r['confirmed']], ['TRIPLE_BOTTOM', 111, true]);
    expect(kinds(piv([120, 110, 126, 111, 120], startHigh: true), 115), isEmpty); // peaks not equal
  });

  test('triangles, rectangle and wedges on six alternating pivots', () {
    expect(kinds(piv([120, 100, 120.5, 105, 120.2, 110], startHigh: true), 115), 'ASCENDING_TRIANGLE');
    expect(kinds(piv([100, 120, 100.4, 115, 100.2, 110], startHigh: false), 105), 'DESCENDING_TRIANGLE');
    // Overlapping interpretations are both reported (the last five also form a triple bottom).
    expect(kinds(piv([120, 100, 120.4, 100.5, 120.2, 100.2], startHigh: true), 110).split(','), contains('RECTANGLE'));
    expect(kinds(piv([110, 100, 114, 105, 117, 109], startHigh: true), 112), 'RISING_WEDGE');
    expect(kinds(piv([130, 110, 124, 107, 119, 105], startHigh: true), 110), 'FALLING_WEDGE');
    // Converging (falling highs, rising lows) belongs to the canonical server set, not duplicated here.
    expect(kinds(piv([130, 100, 125, 105, 120, 110], startHigh: true), 115), isEmpty);
    final asc = extendedPatterns(piv([120, 100, 120.5, 105, 120.2, 110], startHigh: true), 121).single;
    expect([asc['upper'], asc['lower'], asc['confirmed'], asc['breakout']], [120.5, 110, true, 'UP']);
  });

  test('inputs are validated and drawings carry labels', () {
    expect(() => extendedPatterns(piv([1, 2], startHigh: true), 0), throwsArgumentError);
    expect(() => extendedPatterns([const ChartPivot(5, 5, 10, true)], 10), throwsFormatException);
    final d = extendedDrawings(piv([120, 100, 120.5, 105, 120.2, 110], startHigh: true), 115).single;
    expect(d.triangle, isTrue);
    expect(d.labels, ['H1', 'L1', 'H2', 'L2', 'H3', 'L3']);
    final t = extendedDrawings(piv([120, 110, 121, 111, 120.5], startHigh: true), 115).single;
    expect([t.triangle, t.neckline, t.labels.first], [false, 110, 'P1']);
  });

  test('Demo candle pivots equal the Direct/server strict pivots on identical OHLC', () {
    final bars = candles({0: 110, 6: 100, 18: 110, 30: 105, 42: 125, 54: 115, 66: 130, 72: 127});
    final market = [for (final b in bars) MarketBar(DateTime.utc(2026, 10, 19, 14).add(Duration(minutes: b.tick)),
        b.open, b.high, b.low, b.close, b.volume)];
    final a = MarketGeometry.candlePivots(bars), b = MarketGeometry.confirmedPivots(market);
    expect(a.map((p) => [p.index, p.confirmedAt, p.price, p.high]).toList(),
        b.map((p) => [p.index, p.confirmedAt, p.price, p.high]).toList());
    expect(a, isNotEmpty);
    // The strict wave journal on Demo candles is built from exactly these pivots (no lookahead).
    final j = ChartWaveJournal(strictMarket: true)..append(bars);
    expect(j.toJson()['contract'], marketWaveContract);
    for (final p in a) {
      expect(p.confirmedAt, p.index + 3);
    }
  });

  test('end-to-end: triple top found from candles only after the last peak is confirmed', () {
    final bars = candles({0: 100, 8: 120, 16: 110, 24: 121, 32: 111, 40: 120.5, 48: 105});
    List<String> at(int end) {
      final upto = bars.where((b) => b.tick <= end).toList();
      final p = MarketGeometry.candlePivots(upto);
      return extendedPatterns(p, upto.last.close).map((m) => '${m['kind']}:${m['confirmed']}').toList();
    }
    expect(at(42), isEmpty); // peak at 40 not yet confirmed (needs 43)
    expect(at(43), ['TRIPLE_TOP:false']);
    expect(at(48), ['TRIPLE_TOP:true']); // close below the 110 neckline
  });

  testWidgets('Demo chart lab defaults to market rules and lists classic patterns', (t) async {
    t.view.physicalSize = const Size(360, 900);
    t.view.devicePixelRatio = 1;
    addTearDown(t.view.resetPhysicalSize);
    addTearDown(t.view.resetDevicePixelRatio);
    final e = DemoEngine()..tick = 80;
    await t.pumpWidget(MaterialApp(home: Directionality(textDirection: TextDirection.rtl,
        child: Scaffold(body: SingleChildScrollView(child: DemoChartLab(engine: e, symbol: 'NVDA'))))));
    await t.pumpAndSettle();
    expect(t.widget<FilterChip>(find.byKey(const Key('chart-market-rules'))).selected, isTrue);
    expect(find.text('قواعد السوق 3/1'), findsOneWidget);
    await t.ensureVisible(find.byKey(const Key('chart-lab-1')));
    await t.tap(find.byKey(const Key('chart-lab-1')));
    await t.pumpAndSettle();
    final status = t.widget<Text>(find.byKey(const Key('chart-analysis-status'))).data!;
    expect(status.contains('نموذج كلاسيكي') || status.contains('مرشح') || status.contains('كسر'), isTrue);
    await t.ensureVisible(find.byKey(const Key('chart-market-rules')));
    await t.tap(find.byKey(const Key('chart-market-rules')));
    await t.pumpAndSettle();
    expect(find.text('قواعد Demo القديمة 4/2'), findsOneWidget);
    expect(t.takeException(), isNull);
  });
}
