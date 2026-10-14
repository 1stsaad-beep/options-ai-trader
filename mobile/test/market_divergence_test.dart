import 'dart:convert';
import 'dart:io';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:options_ai_trader/direct_alpaca.dart';
import 'package:options_ai_trader/direct_labs.dart';
import 'package:options_ai_trader/direct_replay.dart';
import 'package:options_ai_trader/market_indicators.dart';
import 'package:options_ai_trader/demo/chart_analysis.dart';
import 'package:options_ai_trader/demo/chart_painter.dart';
import 'market_indicators_test.dart' show closeTree;

List<dynamic> portableDivergences(List<ChartDivergence> values)=>[for(final d in values){
  'kind':marketDivergenceLabels.entries.singleWhere((e)=>e.value==d.kind).key,'oscillator':d.indicator,
  'from':[d.first.index,d.first.confirmedAt,d.first.price,d.first.high],
  'to':[d.second.index,d.second.confirmedAt,d.second.price,d.second.high],
  'momentum_from':d.firstValue,'momentum_to':d.secondValue,
}];
void main() {
  final fixture=jsonDecode(File('test/fixtures/divergence_contract_v1.json').readAsStringSync()) as Map;
  for(final c in fixture['cases'] as List) {
    test('server/Direct confirmed divergence: ${c['name']}',(){
      expect(fixture['contract'],marketDivergenceContract);
      final points=[for(final p in c['points'] as List)ChartPivot(p[0] as int,p[1] as int,(p[2] as num).toDouble(),p[3] as bool)];
      final oscillator=[for(final v in c['oscillator'] as List)v==null?null:(v as num).toDouble()];
      closeTree(portableDivergences(MarketIndicators.confirmedDivergences(points,oscillator,name:c['indicator'] as String)),c['expected']);
    });
  }
  for(final c in fixture['bars'] as List) {
    final rows=[for(final b in c['bars'] as List)MarketBar.parse({...Map<String,dynamic>.from(b as Map),
      't':DateTime.parse(b['at'] as String).millisecondsSinceEpoch})];
    test('observed source, confirmation and every causal prefix: ${c['name']}',(){
      final expected=c['expected'] as List;
      closeTree(portableDivergences(MarketIndicators.divergences(rows)),expected);
      for(var end=1;end<=rows.length;end++) {
        closeTree(portableDivergences(MarketIndicators.divergences(rows.take(end).toList())),expected.where((d)=>d['to'][1]<end).toList());
      }
      final snapshot=directResearchSnapshot(rows);
      expect(snapshot['version'],'direct-research-v5');expect(snapshot['divergenceContract'],marketDivergenceContract);
      final minute=(snapshot['divergences'] as List).where((d)=>d['timeframeMinutes']==1).toList();
      expect(minute.length,expected.length);
      for(var i=0;i<minute.length;i++) {
        expect(minute[i]['knownAt'],rows[expected[i]['to'][1] as int].time.toIso8601String());
        expect(minute[i]['label'],'${expected[i]['oscillator']}: ${marketDivergenceLabels[expected[i]['kind']]}');
      }
    });
    if(c['name']=='rising') {
      testWidgets('Direct indicator painter uses the canonical confirmed segments',(tester)async {
        await tester.pumpWidget(MaterialApp(home:Scaffold(body:SingleChildScrollView(child:DirectLabs(rows:rows,symbol:'NVDA',source:'fixture')))));
        await tester.ensureVisible(find.text('Indicator Lab'));await tester.tap(find.text('Indicator Lab'));await tester.pumpAndSettle();
        final painter=tester.widget<CustomPaint>(find.byKey(const Key('direct-chart'))).painter! as DemoCandlePainter;
        expect(painter.divergences,isNotEmpty);closeTree(portableDivergences(painter.divergences),c['expected']);
        expect(tester.takeException(),isNull);
      });
    }
  }
  test('invalid confirmations, unbounded oscillators and unsupported configuration reject',(){
    const a=ChartPivot(3,6,100,false),b=ChartPivot(13,16,90,false);
    final oscillator=List<double?>.filled(17,50);
    expect(()=>MarketIndicators.confirmedDivergences([a,b],oscillator.sublist(0,16)),throwsFormatException);
    expect(()=>MarketIndicators.confirmedDivergences([b,a],oscillator),throwsFormatException);
    expect(()=>MarketIndicators.confirmedDivergences([const ChartPivot(3,3,100,false)],oscillator),throwsFormatException);
    expect(()=>MarketIndicators.confirmedDivergences([a,b],[...oscillator]..[3]=double.nan),throwsFormatException);
    expect(()=>MarketIndicators.confirmedDivergences([a,b],oscillator,name:'UNKNOWN'),throwsFormatException);
    expect(()=>MarketIndicators.confirmedDivergences([a,b],oscillator,minDistance:0),throwsFormatException);
    expect(()=>MarketIndicators.confirmedDivergences([a,b],oscillator,maxDistance:2),throwsFormatException);
    expect(()=>MarketIndicators.confirmedDivergences([a,b],oscillator,minimumMomentumChange:-1),throwsFormatException);
    expect(MarketIndicators.divergences([]),isEmpty);
  });
}
