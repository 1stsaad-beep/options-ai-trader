import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:options_ai_trader/demo/chart_analysis.dart';
import 'package:options_ai_trader/demo/chart_lab.dart';
import 'package:options_ai_trader/demo/engine.dart';
import 'package:options_ai_trader/demo/wave_analysis.dart';

List<ChartPivot> points(List<double> prices, {bool firstHigh = false,
    List<int>? ticks, int lag = 2}) => List.generate(prices.length, (i) {
  final tick = ticks == null ? i * 10 : ticks[i];
  return ChartPivot(tick, tick + lag, prices[i], i.isEven ? firstHigh : !firstHigh);
});

List<DemoCandle> observations() {
  final anchors = <int, double>{0:110, 4:100, 14:110, 24:105,
    34:125, 44:115, 54:130, 64:90, 74:110};
  final keys = anchors.keys.toList();
  return List.generate(75, (tick) {
    final right = keys.firstWhere((key) => key >= tick);
    final left = keys.lastWhere((key) => key <= tick);
    final value = left == right ? anchors[left]! : anchors[left]! +
      (anchors[right]! - anchors[left]!) * (tick - left) / (right - left);
    return DemoCandle(tick, value, value + .1, value - .1, value, 100);
  });
}

void main() {
  test('ABC and third wave remain competing bullish and bearish candidates', () {
    for (final bearish in [false, true]) {
      final prices = [100.0, 110.0, 105.0, 125.0];
      final scenarios = ChartWaveAnalysis.candidates(points(
        bearish ? prices.map((p) => 300 - p).toList() : prices,
        firstHigh: bearish));
      expect(scenarios.map((s) => s.kind), containsAll(['third', 'abc']));
      final abc = scenarios.singleWhere((s) => s.kind == 'abc');
      expect(abc.bullish, !bearish);
      expect(abc.labels, ['0', 'A', 'B', 'C']);
      expect(abc.observedAt, 32);
      expect(abc.toJson()['executable'], isFalse);
    }
  });

  test('fifth and complete impulse enforce non-overlap and non-shortest third', () {
    final valid = points([100, 110, 105, 125, 115, 130]);
    expect(ChartWaveAnalysis.candidates(valid.take(5).toList())
      .where((s) => s.kind == 'fifth'), hasLength(1));
    expect(ChartWaveAnalysis.candidates(valid)
      .where((s) => s.kind == 'impulse'), hasLength(1));
    expect(ChartWaveAnalysis.candidates(points([100,110,105,125,109,130]))
      .where((s) => s.kind == 'impulse'), isEmpty);
    expect(ChartWaveAnalysis.candidates(points([100,120,110,125,121,145]))
      .where((s) => s.kind == 'impulse'), isEmpty);
  });

  test('wave 2 cannot erase wave 1 and nonalternating geometry is rejected', () {
    expect(ChartWaveAnalysis.candidates(points([100,110,99,125])), isEmpty);
    expect(ChartWaveAnalysis.candidates([
      const ChartPivot(0,2,100,false), const ChartPivot(10,12,110,false),
      const ChartPivot(20,22,105,false), const ChartPivot(30,32,125,true),
    ]), isEmpty);
  });

  test('candidate validation rejects historical ordering and nonfinite prices', () {
    expect(() => ChartWaveAnalysis.candidates([
      const ChartPivot(5,7,100,false), const ChartPivot(4,6,110,true),
    ]), throwsFormatException);
    expect(() => ChartWaveAnalysis.candidates([
      const ChartPivot(0,2,double.nan,false),
    ]), throwsFormatException);
    expect(() => ChartWaveAnalysis.candidates([], degree:'invented'), throwsArgumentError);
  });

  test('nested 3 of 3 cannot be known before parent confirmation', () {
    final main = ChartWaveAnalysis.candidates(points([100,120,110,170],
      ticks:[0,10,20,50], lag:4));
    final inner = ChartWaveAnalysis.candidates(points([110,130,120,160],
      ticks:[20,30,40,50]), degree:'internal');
    final nested = ChartWaveAnalysis.nestedThirds(main, inner).single;
    expect(nested.kind, 'third_of_third');
    expect(nested.observedAt, 54);
    expect(nested.parentId, main.singleWhere((s) => s.kind=='third').id);
    expect(nested.labels.last, '(3)?');
    final outside = ChartWaveAnalysis.candidates(points([110,130,120,160],
      ticks:[19,30,40,50]), degree:'internal');
    expect(ChartWaveAnalysis.nestedThirds(main, outside), isEmpty);
    final opposite = ChartWaveAnalysis.candidates(points([190,170,180,140],
      firstHigh:true, ticks:[20,30,40,50]), degree:'internal');
    expect(ChartWaveAnalysis.nestedThirds(main, opposite), isEmpty);
  });

  test('wave event is only visible after the confirming candle', () {
    final bars = observations();
    final journal = ChartWaveJournal()..append(bars.take(36).toList());
    expect(journal.events, isEmpty);
    journal.append(bars.take(37).toList());
    expect(journal.events, isNotEmpty);
    expect(journal.events.every((e) => e.observedAt == 36), isTrue);
    expect(journal.view(35).primary, isNull);
    expect(journal.view(36).primary!.degree, 'internal');
    expect(journal.view(36).alternate!.kind, 'abc');
  });

  test('appended future candles never change old primary alternate or journal', () {
    final bars = observations();
    final journal = ChartWaveJournal()..append(bars.take(40).toList());
    final eventPrefix = jsonEncode(journal.events.map((e) => e.toJson()).toList());
    final before = journal.view(36);
    final count = journal.events.length;
    journal.append(bars);
    final after = journal.view(36);
    expect(after.primary!.id, before.primary!.id);
    expect(after.alternate!.id, before.alternate!.id);
    expect(jsonEncode(after.events.map((e) => e.toJson()).toList()),
      jsonEncode(before.events.map((e) => e.toJson()).toList()));
    expect(jsonEncode(journal.events.take(count).map((e) => e.toJson()).toList()), eventPrefix);
    expect(() => journal.view(75), throwsFormatException);
  });

  test('invalidation is append-only and cannot revive on price recovery', () {
    final bars = observations();
    final journal = ChartWaveJournal()..append(bars);
    final initial = journal.view(36).primary!;
    final invalidation = journal.events.singleWhere((e) =>
      e.scenarioId == initial.id && e.event == 'INVALIDATED');
    expect(invalidation.observedAt, greaterThan(36));
    expect(journal.view(invalidation.observedAt - 1).active.map((s) => s.id),
      contains(initial.id));
    expect(journal.view(74).active.map((s) => s.id), isNot(contains(initial.id)));
    final size = journal.events.length;
    journal.append(bars);
    expect(journal.events.length, size);
  });

  test('source revisions shrinking and invalid candles fail without journal changes', () {
    final bars = observations();
    final journal = ChartWaveJournal()..append(bars.take(40).toList());
    final before = jsonEncode(journal.toJson());
    final changed = bars.take(40).toList();
    changed[3] = const DemoCandle(3,109,110,108,109,100);
    expect(() => journal.append(changed), throwsFormatException);
    expect(() => journal.append(bars.take(39).toList()), throwsFormatException);
    final bad = bars.toList();
    bad[74] = const DemoCandle(74,100,95,110,100,100);
    expect(() => journal.append(bad), throwsFormatException);
    expect(jsonEncode(journal.toJson()), before);
  });

  test('serializable journal restores with exact causal event evidence', () {
    final journal = ChartWaveJournal()..append(observations());
    final state = jsonDecode(jsonEncode(journal.toJson())) as Map<String,dynamic>;
    final restored = ChartWaveJournal.restore(state);
    expect(jsonEncode(restored.toJson()), jsonEncode(journal.toJson()));
    expect(restored.view(36).primary!.id, journal.view(36).primary!.id);
    (state['events'] as List).removeLast();
    expect(() => ChartWaveJournal.restore(state), throwsFormatException);
  });

  test('MTF excludes incomplete candles and preserves the completed prefix', () {
    final bars = observations();
    final early = ChartWaveAnalysis.aggregate(bars.take(14).toList(), 5);
    expect(early.length, 2);
    expect(early.map((b) => b.tick), [4,9]);
    expect(early.first.open, bars.first.open);
    expect(early.first.close, bars[4].close);
    expect(early.first.volume, 500);
    final later = ChartWaveAnalysis.aggregate(bars, 5);
    expect(later.take(2).map((b) => b.close), early.map((b) => b.close));
    final frames = ChartWaveAnalysis.timeframes(bars.take(14).toList());
    expect(frames.last.bars, isEmpty);
    expect(frames[1].ready, isFalse);
    expect(frames[1].bias, 'إحماء غير كافٍ');
  });

  test('MTF pivot confirmation uses actual source ticks not compacted indices', () {
    final values = [10.0,20.0,30.0,20.0,10.0];
    final bars = List.generate(values.length, (i) => DemoCandle(
      i*5+4, values[i], values[i]+.1, values[i]-.1, values[i], 100));
    final peak = DemoChartAnalysis.pivots(bars).single;
    expect(peak.index, 14);
    expect(peak.confirmedAt, 24);
    expect(() => DemoChartAnalysis.pivots(bars,radius:0), throwsArgumentError);
  });

  testWidgets('offline wave journal MTF and alternate controls render in RTL', (tester) async {
    final engine = DemoEngine()..tick = 75;
    tester.view.physicalSize = const Size(360, 800);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    await tester.pumpWidget(MaterialApp(home:Directionality(
      textDirection:TextDirection.rtl, child:Scaffold(body:SingleChildScrollView(
        child:DemoChartLab(engine:engine,symbol:'NVDA'))))));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('wave-journal-summary')), findsOneWidget);
    expect(find.byKey(const Key('wave-mtf-heading')), findsOneWidget);
    await tester.ensureVisible(find.byKey(const Key('wave-alternate-toggle')));
    await tester.tap(find.byKey(const Key('wave-alternate-toggle')));
    await tester.pump();
    expect(tester.widget<FilterChip>(find.byKey(
      const Key('wave-alternate-toggle'))).selected, isFalse);
    await tester.ensureVisible(find.text('ملاحظة سابقة'));
    await tester.tap(find.text('ملاحظة سابقة'));
    await tester.pump();
    expect(find.textContaining('الملاحظة 74 من 75'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
}
