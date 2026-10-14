import 'dart:convert';
import 'dart:io';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:options_ai_trader/direct_alpaca.dart';
import 'package:options_ai_trader/direct_replay.dart';
import 'package:options_ai_trader/direct_labs.dart';
import 'package:options_ai_trader/demo/chart_analysis.dart';
import 'package:options_ai_trader/demo/chart_painter.dart';
import 'package:options_ai_trader/market_geometry.dart';
import 'market_indicators_test.dart' show closeTree;

void main() {
  final fixture=jsonDecode(File('test/fixtures/geometry_contract_v1.json').readAsStringSync()) as Map;
  List<ChartPivot> points(List rows)=>[for(final p in rows)ChartPivot(p[0] as int,p[1] as int,(p[2] as num).toDouble(),p[3] as bool)];
  for(final c in fixture['harmonics'] as List) {
    test('canonical XABCD and PRZ: ${c['name']}',() {
      expect(fixture['contract'],marketGeometryContract);
      final p=points(c['points'] as List),actual=MarketGeometry.harmonics(p);
      closeTree(actual,c['expected']);expect(MarketGeometry.harmonics(p.take(4).toList()),isEmpty);
      for(final h in actual) {
        final drawing=MarketGeometry.drawing(h);expect(drawing.labels,['X','A','B','C','D']);
        expect(drawing.przLow!<=p.last.price&&p.last.price<=drawing.przHigh!,true);
      }
    });
  }
  for(final c in fixture['classical'] as List) {
    test('canonical classical confirmation: ${c['name']}',() {
      closeTree(MarketGeometry.classicPatterns(points(c['points'] as List),(c['close'] as num).toDouble()),c['expected']);
    });
  }
  for(final c in fixture['bars'] as List) {
    final rows=[for(final b in c['bars'] as List)MarketBar.parse({...Map<String,dynamic>.from(b as Map),
      't':DateTime.parse(b['at'] as String).millisecondsSinceEpoch})];
    test('strict completed-pivot prefixes and saved Direct geometry: ${c['name']}',() {
      final full=MarketGeometry.confirmedPivots(rows);
      List<List<Object>> plain(List<ChartPivot> points)=>[for(final p in points)[p.index,p.confirmedAt,p.price,p.high]];
      closeTree(plain(full),c['expected']);
      for(var length=1;length<=rows.length;length++) {
        closeTree(plain(MarketGeometry.confirmedPivots(rows.take(length).toList())),plain(full.where((p)=>p.confirmedAt<length).toList()));
      }
      final saved=directResearchSnapshot(rows);expect(saved['geometryContract'],marketGeometryContract);
      closeTree(saved['harmonics'],MarketGeometry.harmonics(full));
      if(c.containsKey('harmonics')){closeTree(saved['harmonics'],c['harmonics']);expect(saved['harmonics'],isNotEmpty);}
      closeTree(saved['classicalPatterns'],MarketGeometry.classicPatterns(full,rows.last.close));
    });
    if(c['name']=='gartley_source') {
      testWidgets('Direct painter receives actual detected XABCD and PRZ from completed source',(tester)async {
        await tester.pumpWidget(MaterialApp(home:Scaffold(body:SingleChildScrollView(child:DirectLabs(rows:rows,symbol:'NVDA',source:'fixture')))));
        await tester.ensureVisible(find.text('Harmonic Lab'));await tester.tap(find.text('Harmonic Lab'));await tester.pumpAndSettle();
        final painter=tester.widget<CustomPaint>(find.byKey(const Key('direct-chart'))).painter! as DemoCandlePainter;
        expect(painter.patterns.single.name,'Gartley');expect(painter.patterns.single.points.length,5);
        expect(painter.patterns.single.labels,['X','A','B','C','D']);
        expect(painter.patterns.single.przLow!,lessThanOrEqualTo(painter.patterns.single.points.last.price));
        expect(painter.patterns.single.przHigh!,greaterThanOrEqualTo(painter.patterns.single.points.last.price));
        expect(tester.takeException(),isNull);
      });
    }
  }
  test('invalid confirmations, ordering and tolerance cannot invent patterns',() {
    expect(()=>MarketGeometry.harmonics([const ChartPivot(1,1,100,false)]),throwsFormatException);
    expect(()=>MarketGeometry.harmonics([const ChartPivot(2,4,100,false),const ChartPivot(1,3,110,true)]),throwsFormatException);
    expect(()=>MarketGeometry.harmonics([],tolerance:.051),throwsArgumentError);
    expect(()=>MarketGeometry.classicPatterns([],double.nan),throwsArgumentError);
  });
}
