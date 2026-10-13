import 'dart:convert';
import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:options_ai_trader/market_paper.dart';
import 'market_paper_safety_test.dart' show FaultPaperStore;

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  late FaultPaperStore legacy;
  String? bytes;
  late int writes;
  setUp((){
    debugDefaultTargetPlatformOverride=TargetPlatform.android;legacy=FaultPaperStore();bytes=null;writes=0;
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger.setMockMethodCallHandler(DevicePaperStore.channel,(call)async{
      if(call.method=='read')return bytes;
      if(call.method=='write') {
        if(call.arguments['expected']!=bytes)throw PlatformException(code:'PAPER_STORAGE_UNCERTAIN');
        bytes=call.arguments['next'] as String;writes++;return true;
      }
      throw MissingPluginException();
    });
  });
  tearDown((){debugDefaultTargetPlatformOverride=null;TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger.setMockMethodCallHandler(DevicePaperStore.channel,null);});
  test('validated preferences migrate once without deleting original',()async{
    final old=MarketPaper(legacy);await old.load();await old.add('Legacy retained');final original=jsonEncode(legacy.value);
    final first=DevicePaperStore(legacyStore:legacy);expect((await first.read())!['accounts'].length,1);expect(writes,1);
    expect(jsonEncode(legacy.value),original);await DevicePaperStore(legacyStore:legacy).read();expect(writes,1);
  });
  test('invalid legacy ledger is retained without disk migration',()async{
    legacy.value={'version':1,'accounts':'bad','journal':[]};final store=DevicePaperStore(legacyStore:legacy);
    await expectLater(store.read(),throwsFormatException);expect(bytes,isNull);expect(writes,0);
  });
  test('native CAS rejects an intervening writer',()async{
    final store=DevicePaperStore(legacyStore:legacy);await store.read();
    bytes='{"version":1,"accounts":[],"journal":[]}';
    await expectLater(store.write({'version':1,'accounts':[],'journal':[]}),throwsA(isA<PlatformException>()));expect(writes,0);
  });
  test('missing native storage never silently falls back on Android',()async{
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger.setMockMethodCallHandler(DevicePaperStore.channel,null);
    final paper=MarketPaper(DevicePaperStore(legacyStore:legacy));await paper.load();expect(paper.ready,false);expect(legacy.writes,0);
  });
}
