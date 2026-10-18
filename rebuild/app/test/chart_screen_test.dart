import 'dart:ui' as ui;

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:options_ai_trader_app/chart/chart_layers.dart';
import 'package:options_ai_trader_app/chart/chart_painter.dart';
import 'package:options_ai_trader_app/chart/chart_viewport.dart';
import 'package:options_ai_trader_app/chart/interactive_chart.dart';
import 'package:options_ai_trader_app/screens/chart_screen.dart';
import 'package:trader_core/trader_core.dart';

final t0 = DateTime.utc(2026, 3, 2, 14, 30);

List<double> path(double start, List<(int, double)> legs) {
  final out = <double>[start];
  var cur = start;
  for (final (n, target) in legs) {
    final step = (target - cur) / n;
    for (var i = 1; i <= n; i++) {
      out.add(cur + step * i);
    }
    cur = target;
  }
  return out;
}

/// Same fixture shape as trader_core's tests: open = close, high/low = close ± 0.05.
List<Candle> bars(List<double> closes, {Duration step = const Duration(minutes: 15)}) => [
      for (var i = 0; i < closes.length; i++)
        Candle(time: t0.add(step * i), open: closes[i], high: closes[i] + 0.05, low: closes[i] - 0.05, close: closes[i], volume: 1000.0 + i)
    ];

// A Gartley at the end (harmonic geometry + PRZ) after a long lead-in.
final gartley = bars(path(120, [
  (40, 110),
  (10, 100),
  (10, 120),
  (10, 107.64),
  (10, 115.28),
  (10, 104.28),
  (1, 104.6),
  (1, 104.9),
  (1, 105.1)
]));

Future<ChartAnalysis> syncAnalyze(String s, List<Candle> b, Map<EngineId, double> w) async =>
    ChartAnalysis.compute(s, b, weights: w, scoreBars: b.length);

Widget host(Widget child) => MaterialApp(
      locale: const Locale('ar'),
      builder: (c, w) => Directionality(textDirection: TextDirection.rtl, child: w!),
      home: child,
    );

void main() {
  final loaded = <BarTimeframe>[];
  final journal = [
    JournalEntry(
        time: gartley[60].time.add(const Duration(minutes: 2)),
        action: JournalAction.entry,
        symbol: 'TEST',
        reasonAr: 'دخول',
        details: {'analysis': {'close': gartley[60].close}, 'contract': 'TEST261120C00105000'}),
    JournalEntry(
        time: gartley[70].time.add(const Duration(minutes: 1)),
        action: JournalAction.orderFilled,
        symbol: 'TEST',
        reasonAr: 'تنفيذ بيع 1 عقد',
        details: {'side': 'sellToClose'}),
  ];

  ChartScreen screen() => ChartScreen(
        symbol: 'TEST',
        title: 'حساب',
        initialTimeframe: BarTimeframe.m15,
        accountTimeframe: BarTimeframe.m15,
        weights: const {},
        loadBars: (tf) async {
          loaded.add(tf);
          return gartley;
        },
        journal: () => journal,
        analyze: syncAnalyze,
      );

  testWidgets('loads the same bars, shows the score and engine findings', (tester) async {
    loaded.clear();
    tester.view.physicalSize = const Size(1080, 2200);
    tester.view.devicePixelRatio = 2.5;
    addTearDown(tester.view.reset);
    await tester.pumpWidget(host(screen()));
    await tester.pumpAndSettle();
    expect(loaded, [BarTimeframe.m15]);
    expect(find.byKey(const Key('interactive-chart')), findsOneWidget);
    final report = Analyzer().analyze('TEST', gartley);
    final sign = report.score >= 0 ? '+' : '';
    expect(find.textContaining('النتيجة $sign${report.score.toStringAsFixed(0)}'), findsOneWidget);
    // The harmonic engine sees the Gartley; the chart data carries its geometry.
    final chart = tester.widget<InteractiveChart>(find.byType(InteractiveChart));
    final g = chart.data.analysis.findings[EngineId.harmonic]!.firstWhere((s) => s.pattern == 'GARTLEY');
    expect(g.geometry.points.map((p) => p.label), ['X', 'A', 'B', 'C', 'D']);
    expect(identical(chart.data.candles, gartley), isTrue);
    // Trade markers resolved onto bars 60 and 70.
    expect(chart.data.markers.map((m) => m.index), [60, 70]);
  });

  testWidgets('long-press shows the exact OHLC of the bar under the finger; tap hides it', (tester) async {
    tester.view.physicalSize = const Size(1080, 2200);
    tester.view.devicePixelRatio = 2.5;
    addTearDown(tester.view.reset);
    await tester.pumpWidget(host(screen()));
    await tester.pumpAndSettle();
    final state = tester.state<InteractiveChartState>(find.byType(InteractiveChart));
    final box = tester.getRect(find.byKey(const Key('interactive-chart')));
    // Choose the bar at 40% of the plot width.
    final plotW = box.width - 4 - ChartLayout.axisWidth;
    final i = state.viewport.barAt(plotW * 0.4, plotW);
    final at = Offset(box.left + 4 + state.viewport.x(i, plotW), box.top + 100);
    await tester.longPressAt(at);
    await tester.pumpAndSettle();
    final k = gartley[state.crossIndex!];
    expect((state.crossIndex! - i).abs(), lessThanOrEqualTo(1));
    expect(find.text('O ${CandleChartPainter.fmt(k.open)}  H ${CandleChartPainter.fmt(k.high)}'), findsOneWidget);
    expect(find.byKey(const Key('readout-time')), findsOneWidget);
    await tester.tapAt(at);
    await tester.pump(const Duration(milliseconds: 400));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('readout-time')), findsNothing);
  });

  testWidgets('drag pans into history; layer toggles change the painted layers', (tester) async {
    tester.view.physicalSize = const Size(1080, 2200);
    tester.view.devicePixelRatio = 2.5;
    addTearDown(tester.view.reset);
    await tester.pumpWidget(host(screen()));
    await tester.pumpAndSettle();
    final state = tester.state<InteractiveChartState>(find.byType(InteractiveChart));
    final before = state.viewport.rightIndex;
    await tester.drag(find.byKey(const Key('interactive-chart')), const Offset(200, 0));
    await tester.pumpAndSettle();
    expect(state.viewport.rightIndex, lessThan(before));

    expect(tester.widget<InteractiveChart>(find.byType(InteractiveChart)).layers, contains(ChartLayer.harmonic));
    await tester.tap(find.byKey(const Key('chart-layers')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('layer-harmonic')));
    await tester.tap(find.byKey(const Key('layer-ema')));
    await tester.pumpAndSettle();
    final layers = tester.widget<InteractiveChart>(find.byType(InteractiveChart)).layers;
    expect(layers, isNot(contains(ChartLayer.harmonic)));
    expect(layers, contains(ChartLayer.ema));
  });

  testWidgets('switching timeframe reloads bars for that timeframe', (tester) async {
    loaded.clear();
    await tester.pumpWidget(host(screen()));
    await tester.pumpAndSettle();
    await tester.tap(find.text('1س'));
    await tester.pumpAndSettle();
    expect(loaded, [BarTimeframe.m15, BarTimeframe.h1]);
  });

  testWidgets('load errors are shown, not thrown', (tester) async {
    await tester.pumpWidget(host(ChartScreen(
      symbol: 'BAD',
      title: 'x',
      initialTimeframe: BarTimeframe.d1,
      accountTimeframe: BarTimeframe.m15,
      weights: const {},
      loadBars: (_) async => throw const BrokerException(BrokerErrorCode.auth, 'HTTP 403'),
      journal: () => const [],
      analyze: syncAnalyze,
    )));
    await tester.pumpAndSettle();
    expect(find.textContaining('تعذر تحميل الشارت'), findsOneWidget);
    expect(find.textContaining('HTTP 403'), findsOneWidget);
  });

  test('candle paths are cached across crosshair-only repaints', () {
    final data = ChartData(ChartAnalysis.compute('TEST', gartley, scoreBars: 1), BarTimeframe.m15, const []);
    final cache = CandleCache();
    const colors = ChartColors(up: Colors.green, down: Colors.red, grid: Colors.grey, axisText: Colors.black, background: Colors.white);
    final viewport = ChartViewport(barCount: gartley.length);
    Canvas canvas() => Canvas(ui.PictureRecorder());
    for (var k = 0; k < 3; k++) {
      CandleChartPainter(data: data, viewport: viewport, layers: ChartLayer.values.toSet(), colors: colors, cache: cache)
          .paint(canvas(), const Size(400, 600));
    }
    expect(cache.builds, 1);
    viewport.pan(50, 400 - ChartLayout.axisWidth);
    CandleChartPainter(data: data, viewport: viewport, layers: ChartLayer.values.toSet(), colors: colors, cache: cache)
        .paint(canvas(), const Size(400, 600));
    expect(cache.builds, 2);
  });
}
