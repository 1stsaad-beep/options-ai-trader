@Tags(['golden'])
library;
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:options_ai_trader/demo/chart_analysis.dart';
import 'package:options_ai_trader/demo/chart_fixtures.dart';
import 'package:options_ai_trader/demo/chart_painter.dart';
import 'package:options_ai_trader/demo/wave_analysis.dart';

void main() {
  for(final brightness in [Brightness.dark,Brightness.light]) {
    for(final name in ['abc','bat','divergence']) {
      testWidgets('$name ${brightness.name} canvas golden',(t) async {
        final bars=ChartFixtures.bars(name),closes=bars.map((b)=>b.close).toList();
        final wave=(ChartWaveJournal()..append(bars)).view(bars.last.tick);
        final patterns=name=='abc'?[wave.primary!.drawing(),wave.alternate!.drawing(alternate:true)]:
          name=='bat'?DemoChartAnalysis.harmonics(DemoChartAnalysis.pivots(bars)):<ChartPattern>[];
        final painter=DemoCandlePainter(bars,DemoChartAnalysis.summary(bars),patterns,[],
          ColorScheme.fromSeed(seedColor:Colors.teal,brightness:brightness),name=='bat'?2:name=='abc'?0:3,
          true,true,DemoChartAnalysis.rsi(closes),macdValues:DemoChartAnalysis.macdSeries(closes),
          divergences:DemoChartAnalysis.divergenceSegments(bars));
        await t.pumpWidget(Directionality(textDirection:TextDirection.rtl,child:Center(child:
          RepaintBoundary(key:const Key('golden'),child:CustomPaint(size:const Size(360,440),painter:painter)))));
        await expectLater(find.byKey(const Key('golden')),matchesGoldenFile('goldens/$name-${brightness.name}.png'));
      });
    }
  }
}
