import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:options_ai_trader/direct_alpaca.dart';
import 'package:options_ai_trader/direct_screen.dart';
import 'package:options_ai_trader/direct_labs.dart';
import 'package:options_ai_trader/demo/chart_painter.dart';
import 'package:options_ai_trader/demo/screen.dart';
import 'package:options_ai_trader/demo/store.dart';
import 'direct_connection_integration_test.dart' show NativeMock,open,tap,close;
import 'market_paper_test.dart' show MemoryPaperStore;
import 'demo_widget_test.dart' show destination;

void main(){
  tearDown(()=>TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger.setMockMethodCallHandler(DirectAlpaca.channel,null));
  testWidgets('route removal and recreation retain the single native connection and restore Connected',(t)async{
    final mock=NativeMock();await open(t,mock);await tap(t,'alpaca-test');expect(mock.starts,1);
    final stops=mock.stops;await close(t);expect(mock.active,isTrue);expect(mock.stops,stops);
    await open(t,mock);expect(find.textContaining('Connected •'),findsWidgets);expect(mock.starts,1);
    await tap(t,'alpaca-test');expect(mock.starts,1);await close(t);
  });
  testWidgets('two route consumers observe one native session without starting another',(t)async{
    final mock=NativeMock()..active=true..phase='succeeded';await open(t,mock);
    final navigator=t.state<NavigatorState>(find.byType(Navigator));
    navigator.push(MaterialPageRoute<void>(builder:(_)=>DirectAlpacaScreen(paperStore:MemoryPaperStore())));await t.pumpAndSettle();
    await tap(t,'alpaca-test');expect(mock.starts,0);navigator.pop();await t.pumpAndSettle();
    expect(mock.active,isTrue);expect(mock.stops,0);await close(t);
  });
  testWidgets('missing native snapshot is unknown rather than a claimed network disconnect',(t)async{
    final mock=NativeMock()..snapshotFails=true;await open(t,mock);
    expect(t.widget<Text>(find.byKey(const Key('direct-status'))).data,contains('الحالة غير مؤكدة'));
    expect(t.widget<Text>(find.byKey(const Key('direct-status'))).data, isNot(contains('Disconnected')));await close(t);
  });
  testWidgets('UI lifecycle does not own socket start stop and reads recovered native state',(t)async{
    final mock=NativeMock()..active=true..phase='succeeded';await open(t,mock);
    t.binding.handleAppLifecycleStateChanged(AppLifecycleState.inactive);
    t.binding.handleAppLifecycleStateChanged(AppLifecycleState.paused);await t.pump();
    expect(mock.stops,0);expect(mock.starts,0);
    // Native Activity/Session handles screen-off separately; this verifies bridge/UI recovery.
    mock.active=false;t.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);await t.pumpAndSettle();
    expect(find.textContaining('Disconnected •'),findsWidgets);
    mock.active=true;await t.pump(const Duration(seconds:1));await t.pumpAndSettle();
    expect(find.textContaining('Connected •'),findsWidgets);expect(mock.starts,0);await close(t);
  });
  testWidgets('IEX channel OHLCV reaches the actual chart painter with no Demo fallback',(t)async{
    final time=(DateTime.now().toUtc().millisecondsSinceEpoch~/60000-1)*60000;
    final mock=NativeMock()..active=true..phase='succeeded'..bars={'NVDA':[{'t':time,'o':811.0,'h':815.0,'l':810.0,'c':814.25,'v':19.0}]};
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger.setMockMethodCallHandler(DirectAlpaca.channel,mock.handle);
    await t.pumpWidget(MaterialApp(home:DirectAlpacaScreen(initialPage:1,paperStore:MemoryPaperStore())));await t.pumpAndSettle();
    await t.scrollUntilVisible(find.byKey(const Key('direct-chart')),120,scrollable:find.byType(Scrollable).first);await t.pumpAndSettle();
    final painter=t.widget<CustomPaint>(find.byKey(const Key('direct-chart'))).painter! as DemoCandlePainter;
    expect(painter.bars.length,1);expect(painter.bars.single.close,814.25);expect(painter.priceLabel,contains('Alpaca IEX'));expect(painter.priceLabel,isNot(contains('synthetic')));
    mock.bars['NVDA'][0]['c']=813.75;await t.pump(const Duration(seconds:1));await t.pumpAndSettle();
    expect((t.widget<CustomPaint>(find.byKey(const Key('direct-chart'))).painter! as DemoCandlePainter).bars.single.close,813.75);
    expect(mock.starts,0);await close(t);
  });
  testWidgets('empty actual data shows no synthetic candles',(t)async{
    await t.pumpWidget(const MaterialApp(home:Scaffold(body:DirectLabs(rows:[],symbol:'NVDA',source:'Alpaca IEX • قديمة'))));
    expect(find.byKey(const Key('direct-empty-chart')),findsOneWidget);expect(find.byKey(const Key('direct-chart')),findsNothing);
  });
  test('stale and disconnected actual bars never earn LIVE and timestamps retain provenance',(){
    final now=DateTime.utc(2026,10,13,17,0);final j={'enabled':true,'connected':true,'feed':'iex','session':'regular','source':'alpaca','reason':'CONNECTED','asOf':now.millisecondsSinceEpoch,
      'bars':{'NVDA':[{'t':now.subtract(const Duration(minutes:1)).millisecondsSinceEpoch,'o':11,'h':12,'l':10,'c':11,'v':1}]},'events':[],
      'state':'CONNECTED','lastMessageAt':now.millisecondsSinceEpoch,'lastBarAt':now.millisecondsSinceEpoch,'lastError':'CONNECTION_LIMIT','lastErrorAt':1};
    final s=DirectSnapshot.parse(jsonEncode(j));expect(s.live('NVDA',now),isTrue);expect(s.live('NVDA',now.add(const Duration(minutes:3))),isFalse);
    j['connected']=false;expect(DirectSnapshot.parse(jsonEncode(j)).live('NVDA',now),isFalse);expect(s.lastMessageAt,now.millisecondsSinceEpoch);expect(s.lastError,'CONNECTION_LIMIT');
  });
  testWidgets('Demo chart offers actual source route without rewriting stored accounts or risks',(t)async{
    final store=MemoryDemoStore();var opened=0;
    await t.pumpWidget(MaterialApp(home:DemoScreen(store:store,onTheme:(_){},onBackend:(){},onDirectChart:(){opened++;})));await t.pumpAndSettle();
    await destination(t,'مختبر الرسوم المتقدم');
    final before=await store.load();
    await t.scrollUntilVisible(find.byKey(const Key('select-alpaca-chart')),120,scrollable:find.byType(Scrollable).first);await t.pumpAndSettle();
    await Scrollable.ensureVisible(t.element(find.byKey(const Key('select-alpaca-chart'))),alignment:0.5);await t.pumpAndSettle();
    await t.tap(find.byKey(const Key('select-alpaca-chart')));await t.pumpAndSettle();
    expect(opened,1);expect(await store.load(),before);await close(t);
  });
}
