import 'dart:io';
import 'dart:ui' as ui;
import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:options_ai_trader/direct_alpaca.dart';
import 'package:options_ai_trader/direct_labs.dart';
import 'package:options_ai_trader/market_geometry.dart';
import 'package:options_ai_trader/market_indicators.dart';
import 'package:options_ai_trader/demo/chart_painter.dart';

List<MarketBar> classicSource(List<double> prices,bool high,double close) {
  final last=3+(prices.length-1)*10;
  final vertices=<List<double>>[[0,prices.first+(high?-10:10)],
    for(var i=0;i<prices.length;i++)[3+i*10.0,prices[i]],[last+13.0,close],[last+19.0,close]];
  return [for(var i=0;i<=last+19;i++)(() {
    final n=vertices.indexWhere((p)=>p[0]>=i.toDouble(),1),a=vertices[n-1],b=vertices[n];
    final c=a[1]+(b[1]-a[1])*(i-a[0])/(b[0]-a[0]);
    return MarketBar(DateTime.utc(2026,10,13,14,i),c,c+.01,c-.01,c,1000);
  })()];
}
void main() {
  setUpAll(()async {
    final root=Platform.environment['FLUTTER_ROOT'];
    final font=File('$root/bin/cache/artifacts/material_fonts/Roboto-Regular.ttf');
    final loader=FontLoader('ClassicPreview')..addFont(Future.value(ByteData.sublistView(await font.readAsBytes())));
    await loader.load();
  });
  final cases=<({String kind,List<double> prices,bool high,double close,bool confirmed})>[
    (kind:'DOUBLE_TOP',prices:[200,180,201],high:true,close:179,confirmed:true),
    (kind:'DOUBLE_TOP',prices:[200,180,201],high:true,close:190,confirmed:false),
    (kind:'DOUBLE_BOTTOM',prices:[100,120,101],high:false,close:121,confirmed:true),
    (kind:'HEAD_AND_SHOULDERS',prices:[200,180,220,185,201],high:true,close:179,confirmed:true),
    (kind:'INVERSE_HEAD_AND_SHOULDERS',prices:[200,220,180,215,201],high:false,close:221,confirmed:true),
    (kind:'CONVERGING_TRIANGLE',prices:[200,100,190,110,180,120],high:true,close:150,confirmed:false),
    (kind:'CONVERGING_TRIANGLE',prices:[200,100,190,110,180,120],high:true,close:181,confirmed:true),
  ];
  for(final c in cases) {
    final rows=classicSource(c.prices,c.high,c.close);
    testWidgets('observed ${c.kind} confirmed=${c.confirmed} reaches actual Classic Lab painter',(tester)async {
      await tester.pumpWidget(MaterialApp(home:Scaffold(body:SingleChildScrollView(child:DirectLabs(rows:rows,symbol:'NVDA',source:'fixture')))));
      await tester.ensureVisible(find.text('Classic Chart Lab'));await tester.tap(find.text('Classic Chart Lab'));await tester.pumpAndSettle();
      DemoCandlePainter painter()=>tester.widget<CustomPaint>(find.byKey(const Key('direct-chart'))).painter! as DemoCandlePainter;
      final shape=painter().classicalPatterns.singleWhere((p)=>p.kind==c.kind);
      expect(shape.confirmed,c.confirmed);expect(shape.points.length,c.prices.length);
      expect(shape.labels.length,shape.points.length);
      expect(shape.points.every((p)=>p.confirmedAt<rows.length),true);
      if(shape.triangle) {
        expect(shape.neckline,isNull);expect(painter().layerLabels,containsAll(['Upper boundary','Lower boundary']));
      }else{expect(shape.neckline,isNotNull);expect(painter().layerLabels,contains('Neckline'));}
      expect(painter().layerLabels,contains('${c.kind}: ${c.confirmed?"BREAK_CONFIRMED":"CANDIDATE"}'));
      // Models, price levels and oscillator panels are independent controls.
      await tester.ensureVisible(find.byKey(const Key('direct-models')));await tester.tap(find.byKey(const Key('direct-models')));await tester.pumpAndSettle();
      expect(painter().classicalPatterns,isEmpty);expect(painter().patterns,isEmpty);expect(painter().divergences,isEmpty);
      expect(painter().indicators,true);expect(painter().layerLabels,contains('Support'));
      await tester.tap(find.byKey(const Key('direct-models')));await tester.tap(find.byKey(const Key('direct-levels')));await tester.pumpAndSettle();
      expect(painter().classicalPatterns,isNotEmpty);expect(painter().layerLabels,isNot(contains('Support')));expect(painter().indicators,true);
      await tester.tap(find.byKey(const Key('direct-indicators')));await tester.pumpAndSettle();
      expect(painter().indicators,false);expect(painter().classicalPatterns,isNotEmpty);expect(tester.takeException(),isNull);
    });
  }
  testWidgets('export deterministic classical research chart previews for visual inspection',(tester)async {
    for(final c in [cases[0],cases[3],cases[5]]) {
      final rows=classicSource(c.prices,c.high,c.close),pivots=MarketGeometry.confirmedPivots(rows);
      for(final dark in [false,true]) {
        final scheme=ColorScheme.fromSeed(seedColor:Colors.blue,brightness:dark?Brightness.dark:Brightness.light);
        await tester.pumpWidget(MaterialApp(home:Center(child:RepaintBoundary(key:const Key('classic-preview'),
          child:SizedBox(width:780,height:440,child:CustomPaint(painter:DemoCandlePainter(
            [for(var i=0;i<rows.length;i++)rows[i].candle(i)],MarketIndicators.summary(rows),[],[],scheme,1,true,false,[],
            classicalPatterns:MarketGeometry.classicDrawings(pivots,rows.last.close),fontFamily:'ClassicPreview',
            priceLabel:'FIXTURE STOCK • ${c.kind} • ${c.confirmed?"BREAK_CONFIRMED":"CANDIDATE"}',
            timeLabels:{for(var i=0;i<rows.length;i++)i:rows[i].time.toIso8601String().substring(11,16)})))))));
        await tester.pumpAndSettle();
        final boundary=tester.renderObject<RenderRepaintBoundary>(find.byKey(const Key('classic-preview')));
        await tester.runAsync(()async {
          final image=await boundary.toImage(),data=await image.toByteData(format:ui.ImageByteFormat.png);
          await File('classic-preview-${c.kind}-${dark?"dark":"light"}.png').writeAsBytes(data!.buffer.asUint8List());image.dispose();
        });
        expect(tester.takeException(),isNull);
      }
    }
  });
}
