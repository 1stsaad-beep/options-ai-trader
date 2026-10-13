import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:options_ai_trader/direct_alpaca.dart';
import 'package:options_ai_trader/direct_screen.dart';
import 'package:options_ai_trader/direct_labs.dart';
import 'market_paper_test.dart' show MemoryPaperStore;

class MockDirect extends DirectAlpaca {
  bool saved=false;int starts=0,stops=0;bool secure=false;DirectSettings config=const DirectSettings();
  @override Future<bool> hasKeys()async=>saved;
  @override Future<String> keyState()async=>saved?'readable':'missing';
  @override Future<DirectSettings> settings()async=>config;
  @override Future<void> saveSettings(DirectSettings value)async{config=value;}
  @override Future<void> secureScreen(bool enabled)async{secure=enabled;}
  @override Future<void> saveKeys(String id,String secret)async{saved=true;}
  @override Future<void> start(String feed,String session,List<String> symbols)async{starts++;}
  @override Future<void> stop()async{stops++;}
  @override Future<DirectSnapshot> snapshot()async=>DirectSnapshot(source:'mock');
  @override Future<bool> background()async=>false;
}
void main(){
  testWidgets('no automatic network connection, secret is obscured then cleared after save',(tester)async{
    tester.view.physicalSize=const Size(1100,2400);tester.view.devicePixelRatio=1;addTearDown(tester.view.resetPhysicalSize);addTearDown(tester.view.resetDevicePixelRatio);
    final api=MockDirect();await tester.pumpWidget(MaterialApp(home:DirectAlpacaScreen(api:api,paperStore:MemoryPaperStore())));await tester.pumpAndSettle();
    expect(api.starts,0);expect(api.secure,isTrue);
    await tester.enterText(find.byKey(const Key('alpaca-key')),'mock-public');
    await tester.enterText(find.byKey(const Key('alpaca-secret')),'mock-private');
    expect(tester.widget<TextField>(find.byKey(const Key('alpaca-secret'))).obscureText,isTrue);
    final secretController=tester.widget<TextField>(find.byKey(const Key('alpaca-secret'))).controller!;
    final keyController=tester.widget<TextField>(find.byKey(const Key('alpaca-key'))).controller!;
    await tester.ensureVisible(find.text('حفظ المفاتيح المشفرة'));await tester.tap(find.text('حفظ المفاتيح المشفرة'));await tester.pumpAndSettle();
    expect(secretController.text,isEmpty);
    expect(keyController.text,isEmpty);
    expect(api.saved,isTrue);expect(api.starts,0);
    await tester.pumpWidget(const SizedBox());await tester.pumpAndSettle();expect(api.secure,isFalse);
  });
  testWidgets('five labs consume provided OHLCV and retain source label',(tester)async{
    final start=DateTime.utc(2026,10,13,14),rows=List.generate(45,(i)=>MarketBar(start.add(Duration(minutes:i)),100+i.toDouble(),102+i.toDouble(),99+i.toDouble(),101+i.toDouble(),1000));
    await tester.pumpWidget(MaterialApp(home:Scaffold(body:SingleChildScrollView(child:DirectLabs(rows:rows,symbol:'NVDA',source:'Alpaca IEX • تاريخية')))));
    for(final label in ['Wave Lab','Classic Chart Lab','Harmonic Lab','Indicator Lab','AI Confluence Lab']){
      await tester.ensureVisible(find.text(label));await tester.tap(find.text(label));await tester.pump();expect(tester.takeException(),isNull);
      expect(find.byKey(const Key('direct-series-source')),findsOneWidget);
    }
    expect(find.textContaining('اصطناعية • Shadow'),findsNothing);
  });
}
