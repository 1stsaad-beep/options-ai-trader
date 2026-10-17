import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:options_ai_trader/demo/chart_analysis.dart';
import 'package:options_ai_trader/demo/chart_fixtures.dart';
import 'package:options_ai_trader/demo/chart_lab.dart';
import 'package:options_ai_trader/demo/engine.dart';
import 'package:options_ai_trader/demo/wave_analysis.dart';

List<Object> geometry(ChartPivot p)=>[p.index,p.confirmedAt,p.price,p.high];

void main() {
  test('aggregated journal preserves original ticks and rejects missing groups',() {
    final bars=ChartWaveAnalysis.aggregate(ChartFixtures.bars('impulse'),5);
    final journal=ChartWaveJournal(factor:5)..append(bars);
    expect(journal.latestTick,69);
    expect(ChartWaveJournal.restore(journal.toJson()).toJson(),journal.toJson());
    expect(()=>ChartWaveJournal(factor:5).append(bars.where((b)=>b.tick!=14).toList()),throwsFormatException);
    expect(()=>ChartWaveJournal().append(bars),throwsFormatException);
  });
  test('continuous OHLC plateau confirms only rightmost turn after full delay',() {
    final bars=ChartFixtures.bars('abc');
    final turns=DemoChartAnalysis.pivots(bars);
    expect(turns.map((p)=>p.index),[7,19,31,43]);
    expect(turns.map((p)=>p.confirmedAt),[9,21,33,45]);
    expect(DemoChartAnalysis.pivots(bars.take(9).toList()),isEmpty);
    for(var length=1;length<=bars.length;length++) {
      expect(DemoChartAnalysis.pivots(bars.take(length).toList()).map(geometry).toList(),
        turns.where((p)=>p.confirmedAt<length).map(geometry).toList());
    }
    expect(DemoChartAnalysis.pivots(List.generate(20,(i)=>DemoCandle(i,100,101,99,100,10))),isEmpty);
  });

  test('baseline pictured monotonic prefix legitimately has no wave or harmonic',() {
    final e=DemoEngine()..tick=75;
    final bars=DemoChartAnalysis.bars(e,'NVDA',75);
    final pivots=DemoChartAnalysis.pivots(bars);
    expect(pivots,isEmpty);expect(DemoChartAnalysis.harmonics(pivots),isEmpty);
    expect((ChartWaveJournal()..append(bars)).view(75).primary,isNull);
  });

  test('controlled candles produce primary and alternate without fabricated labels',() {
    final bars=ChartFixtures.bars('abc'),journal=ChartWaveJournal();
    journal.append(bars.take(45).toList());expect(journal.events,isEmpty);
    journal.append(bars);
    final view=journal.view(bars.last.tick);
    expect(view.primary!.labels,['0','1','2','3?']);
    expect(view.alternate!.labels,['0','A','B','C']);
    expect(view.primary!.observedAt,lessThanOrEqualTo(bars.last.tick));
    expect(journal.view(44).primary,isNull);
    final impulse=ChartFixtures.bars('impulse');
    expect((ChartWaveJournal()..append(impulse)).view(impulse.last.tick).active
      .map((s)=>s.kind),contains('impulse'));
  });

  test('Bat geometry has actual ratio PRZ containing D distinct from invalidation',() {
    final p=DemoChartAnalysis.harmonics(DemoChartAnalysis.pivots(ChartFixtures.bars('bat'))).single;
    expect(p.name,'Bat');expect(p.points,hasLength(5));
    expect(p.przLow!,lessThanOrEqualTo(p.points.last.price));
    expect(p.przHigh!,greaterThanOrEqualTo(p.points.last.price));
    expect(p.przLow,isNot(p.invalidation));
  });

  test('divergence has confirmed price and calculated RSI MACD endpoints',() {
    final bars=ChartFixtures.bars('divergence');
    final d=DemoChartAnalysis.divergenceSegments(bars);
    expect(d.where((d)=>d.kind=='صاعد عادي').map((d)=>d.indicator),containsAll(['RSI','MACD']));
    for(final segment in d) {
      expect(segment.confirmedAt,lessThanOrEqualTo(bars.last.tick));
      expect(segment.secondValue,greaterThan(segment.firstValue));
    }
    // Nonzero/gapped source ticks must map by identity, never by list index.
    final shifted=[for(final b in bars)DemoCandle(b.tick+100,b.open,b.high,b.low,b.close,b.volume)];
    expect(DemoChartAnalysis.divergences(shifted),DemoChartAnalysis.divergences(bars));
  });

  test('MACD warmup and histogram arithmetic preserve every historical prefix',() {
    final closes=ChartFixtures.bars('divergence').map((b)=>b.close).toList();
    final all=DemoChartAnalysis.macdSeries(closes);
    expect(all.line.take(25).every((v)=>v==null),isTrue);
    expect(all.signal.take(33).every((v)=>v==null),isTrue);
    expect(all.signal[33],isNotNull);
    for(var n=1;n<=closes.length;n++) {
      final p=DemoChartAnalysis.macdSeries(closes.take(n).toList());
      expect(p.line,all.line.take(n));expect(p.signal,all.signal.take(n));
      expect(p.histogram,all.histogram.take(n));
      if(n>33)expect(p.histogram.last,p.line.last!-p.signal.last!);
    }
  });

  Future<void> mount(WidgetTester t,DemoEngine e,{int? initialEnd}) async {
    t.view.physicalSize=const Size(360,900);t.view.devicePixelRatio=1;
    addTearDown(t.view.resetPhysicalSize);addTearDown(t.view.resetDevicePixelRatio);
    await t.pumpWidget(MaterialApp(home:Directionality(textDirection:TextDirection.rtl,
      child:Scaffold(body:SingleChildScrollView(child:DemoChartLab(engine:e,symbol:'NVDA',initialEnd:initialEnd))))));
    await t.pumpAndSettle();
  }
  DemoCandlePainter painter(WidgetTester t)=>t.widgetList<CustomPaint>(find.byType(CustomPaint))
      .map((w)=>w.painter).whereType<DemoCandlePainter>().single;
  Future<void> select(WidgetTester t,String name) async {
    await t.ensureVisible(find.byKey(const Key('chart-fixture-selector')));
    await t.tap(find.byKey(const Key('chart-fixture-selector')));await t.pumpAndSettle();
    await t.tap(find.text(ChartFixtures.labels[name]!).last);await t.pumpAndSettle();
  }
  Future<void> lab(WidgetTester t,int i) async {
    await t.ensureVisible(find.byKey(Key('chart-lab-$i')));
    await t.tap(find.byKey(Key('chart-lab-$i')));await t.pumpAndSettle();
  }

  testWidgets('same mutable engine follows new ticks but pinned replay never follows', (t) async {
    final e=DemoEngine()..tick=60;await mount(t,e);
    e.step(enter:false);await mount(t,e);
    expect(find.textContaining('الملاحظة 61 من 61'),findsOneWidget);
    await t.ensureVisible(find.text('ملاحظة سابقة'));await t.tap(find.text('ملاحظة سابقة'));await t.pump();
    e.step(enter:false);await mount(t,e);
    expect(find.textContaining('الملاحظة 60 من 62'),findsOneWidget);
    await t.pumpWidget(const SizedBox());await mount(t,e,initialEnd:40);
    e.step(enter:false);await mount(t,e,initialEnd:40);
    expect(painter(t).bars.last.tick,40);
    expect(find.byKey(const Key('chart-fixture-selector')),findsNothing);
  });

  testWidgets('fixture through detector journal toggles and painter preserves account bytes',(t) async {
    final e=DemoEngine()..createAccount('unchanged',2000000);final before=e.encode();
    await mount(t,e);expect(find.text('لا سيناريو موجي صالح عند هذا المؤشر؛ لا يُختلق ترقيم.'),findsOneWidget);
    // These drawing fixtures were tuned to the original Demo 4/2 convention (B11 default is market 3/1).
    await t.ensureVisible(find.byKey(const Key('chart-market-rules')));
    await t.tap(find.byKey(const Key('chart-market-rules')));await t.pumpAndSettle();
    await select(t,'abc');expect(painter(t).patterns,hasLength(2));
    expect(painter(t).layerLabels,contains('C'));
    expect(find.byKey(const Key('chart-fixture-warning')),findsOneWidget);
    await t.ensureVisible(find.byKey(const Key('wave-alternate-toggle')));
    await t.tap(find.byKey(const Key('wave-alternate-toggle')));await t.pump();
    expect(painter(t).patterns,hasLength(1));
    await select(t,'bat');await lab(t,2);
    expect(painter(t).layerLabels,containsAll(['X','A','B','C','D','PRZ']));
    await select(t,'divergence');await lab(t,3);
    expect(painter(t).divergences,isNotEmpty);
    expect(painter(t).macdValues!.histogram.whereType<double>(),isNotEmpty);
    expect(painter(t).layerLabels,containsAll(['RSI 14 (rolling)','MACD 12/26','Signal 9','Histogram']));
    await t.ensureVisible(find.widgetWithText(FilterChip,'الرسومات'));
    await t.tap(find.widgetWithText(FilterChip,'الرسومات'));await t.pump();
    expect(painter(t).overlays,isFalse);
    expect(painter(t).layerLabels.where((s)=>s.contains('صاعد عادي')),isEmpty);
    await t.tap(find.widgetWithText(FilterChip,'المؤشرات'));await t.pump();
    expect(painter(t).indicators,isFalse);
    expect(painter(t).layerLabels, isNot(contains('MACD 12/26')));
    expect(e.encode(),before);expect(t.takeException(),isNull);
  });

  testWidgets('fit viewport time aggregation and zoom remain usable at 360 pixels',(t) async {
    await mount(t,DemoEngine()..tick=180);
    final canvas=find.byKey(const Key('chart-canvas'));
    expect(t.getSize(canvas).width,lessThanOrEqualTo(360));
    await t.ensureVisible(find.byKey(const Key('chart-zoom-in')));
    await t.tap(find.byKey(const Key('chart-zoom-in')));await t.pump();
    var viewer=t.widget<InteractiveViewer>(find.byKey(const Key('chart-pan-zoom')));
    expect(viewer.transformationController!.value.getMaxScaleOnAxis(),greaterThan(1));
    await t.tap(find.byKey(const Key('chart-fit')));await t.pump();
    expect(viewer.transformationController!.value.getMaxScaleOnAxis(),1);
    await t.tap(find.byKey(const Key('chart-factor-5')));await t.pump();
    expect(painter(t).bars.last.tick,179);expect(painter(t).bars.length,36);
    expect(t.takeException(),isNull);
  });
}
