import 'dart:convert';
import 'dart:io';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:options_ai_trader/api.dart';
import 'package:options_ai_trader/direct_labs.dart';
import 'package:options_ai_trader/observed_server.dart';
import 'package:options_ai_trader/observed_server_controls.dart';

Map<String,dynamic> fixture()=>jsonDecode(File('test/fixtures/observed_server_v1.json').readAsStringSync()) as Map<String,dynamic>;

class Server {
  final data=fixture(),calls=<http.Request>[];
  int? failure;
  bool malformedEvents=false;
  Future<http.Response> handle(http.Request r) async {
    calls.add(r);
    expect(r.url.host,'server.invalid');expect(r.headers['authorization'],'Bearer fixture-owner');
    expect(r.url.path,startsWith('/api/observed-paper/'));
    if(failure!=null)return http.Response('{"detail":"PRIVATE_FAILURE"}',failure!);
    final end=r.url.path.split('/').last;
    if(r.method=='POST') {
      expect(end,'control');final body=jsonDecode(r.body) as Map;
      expect(body.keys.toSet(),{'request_key','expected_version','command'});
      expect(body['expected_version'],data['snapshot']['version']);
      expect(body['command']['kind'],'ENABLE');
      data['snapshot']['state']['enabled']=body['command']['enabled'];
      data['snapshot']['version']=(data['snapshot']['version'] as int)+1;
      return http.Response('{}',200);
    }
    expect(r.method,'GET');
    if(end=='events') {
      final after=int.parse(r.url.queryParameters['after']!);
      final list=(data['events']['events'] as List).where((e)=>e['version']>after).take(2).toList();
      return http.Response(jsonEncode({...data['events'] as Map,'account':malformedEvents?'other':'server-one',
        'events':list,'nextAfter':list.isEmpty?after:list.last['version']}),200);
    }
    return http.Response(jsonEncode(data[end=='state'?'snapshot':end]),200);
  }
  TraderApi api()=>TraderApi(baseUrl:'https://server.invalid',token:'fixture-owner',client:MockClient(handle));
}
Future<void> mount(WidgetTester tester,TraderApi api,{Brightness brightness=Brightness.light}) async {
  await tester.pumpWidget(MaterialApp(theme:ThemeData(brightness:brightness),home:Directionality(textDirection:TextDirection.rtl,child:ObservedServerScreen(api:api))));
  await tester.pumpAndSettle();
}
Future<void> show(WidgetTester tester,Finder finder) async {
  await tester.scrollUntilVisible(finder,180);await tester.pumpAndSettle();
}
Future<void> dialog(WidgetTester tester,Widget child) async {
  await tester.pumpWidget(MaterialApp(home:Scaffold(body:Builder(builder:(context)=>TextButton(onPressed:()=>showDialog<void>(context:context,builder:(_)=>child),child:const Text('Open'))))));
  await tester.tap(find.text('Open'));await tester.pumpAndSettle();
}

void main() {
  test('Python snapshot and original event preserve integer accounting and source',() {
    final f=fixture(),saved=ObservedServerAccount.parse(f['snapshot'],'server-one');
    expect(saved.state['source'],'fixture');expect(saved.state['positions']['NVDA']['quantity'],3);
    expect(saved.version,4);
    for(final event in f['events']['events']){expect(ObservedServerEvent.parse(event).original,event['original']);}
    f['snapshot']['state']['cash']=0;expect(saved.state['cash'],isNot(0));
  });
  for(final change in [
    {'source':'demo'},{'id':'wrong'},{'cash':-1},{'cash':100.5},{'realized':1},{'enabled':'false'},
    {'executionContract':'unknown'},{'positions':<String,dynamic>{}},
  ]) {
    test('rejects unsafe or mismatched state $change',() {
      final raw=fixture()['snapshot'];(raw['state'] as Map).addAll(change);
      expect(()=>ObservedServerAccount.parse(raw,'server-one'),throwsFormatException);
    });
  }
  test('invalid event identity or changed original facts rejected',() {
    final raw=fixture()['events']['events'][3];raw['original']['facts']['externalOrder']=true;
    expect(()=>ObservedServerEvent.parse(raw),throwsFormatException);
  });
  test('explicit watchlist rejects duplicate directions, invalid calendar and fractional strikes',() {
    expect(observedContracts('NVDA261023C00150000\nNVDA261023P00150000')['NVDA'].length,2);
    for(final value in ['NVDA261023C00150000 NVDA261023C00155000','NVDA261332C00150000','NVDA261023C00150001','../orders']) {
      expect(()=>observedContracts(value),throwsFormatException);
    }
  });
  for(final brightness in Brightness.values) {
    testWidgets('360px RTL $brightness displays separate server account without provider request',(tester) async {
      tester.view.physicalSize=const Size(360,800);tester.view.devicePixelRatio=1;
      addTearDown(tester.view.resetPhysicalSize);addTearDown(tester.view.resetDevicePixelRatio);
      final server=Server(),api=server.api();addTearDown(api.close);await mount(tester,api,brightness:brightness);
      expect(find.textContaining('Server fixture'),findsOneWidget);
      expect(find.textContaining('الدخول السوقي الجديد مقفل'),findsOneWidget);
      expect(server.calls.map((r)=>r.method),['GET','GET','GET']);
      expect(tester.takeException(),null);
    });
  }
  testWidgets('explicit enable sends only versioned virtual command then rereads',(tester) async {
    final server=Server(),api=server.api();addTearDown(api.close);await mount(tester,api);
    await show(tester,find.byKey(const Key('observed-toggle')));await tester.tap(find.byKey(const Key('observed-toggle')));await tester.pumpAndSettle();
    expect(server.calls.where((r)=>r.method=='POST').length,1);
    expect(server.data['snapshot']['state']['enabled'],true);expect(server.calls.length,7);
    expect(tester.takeException(),null);
  });
  for(final failure in [409,503]) {
    testWidgets('uncertain write $failure invalidates control and never retries',(tester) async {
      final server=Server(),api=server.api();addTearDown(api.close);await mount(tester,api);server.failure=failure;
      await show(tester,find.byKey(const Key('observed-toggle')));await tester.tap(find.byKey(const Key('observed-toggle')));await tester.pumpAndSettle();
      expect(server.calls.where((r)=>r.method=='POST').length,1);expect(find.byKey(const Key('observed-toggle')),findsNothing);
      expect(find.textContaining('PRIVATE_FAILURE'),findsNothing);expect(find.byKey(const Key('observed-error')),findsOneWidget);
      server.failure=null;await tester.tap(find.byKey(const Key('observed-refresh')));await tester.pumpAndSettle();
      expect(server.calls.where((r)=>r.method=='POST').length,1);
    });
  }
  testWidgets('auth failure removes account and previous events',(tester) async {
    final server=Server(),api=server.api();addTearDown(api.close);await mount(tester,api);server.failure=401;
    await tester.tap(find.byKey(const Key('observed-refresh')));await tester.pumpAndSettle();
    expect(find.byKey(const Key('observed-account')),findsNothing);expect(find.byKey(const Key('observed-events')),findsNothing);
    expect(server.calls.every((r)=>r.method=='GET'),true);
  });
  testWidgets('event pages are bounded, sequential and reject cross-account envelopes',(tester) async {
    final server=Server(),api=server.api();addTearDown(api.close);await mount(tester,api);
    for(var page=0;page<2;page++) {
      await show(tester,find.byKey(const Key('observed-events')));await tester.tap(find.byKey(const Key('observed-events')));await tester.pumpAndSettle();
    }
    expect(find.textContaining('#0 •'),findsNothing);
    await show(tester,find.textContaining('#3 •'));expect(find.textContaining('#3 •'),findsOneWidget);
    server.malformedEvents=true;await show(tester,find.byKey(const Key('observed-events')));
    await tester.tap(find.byKey(const Key('observed-events')));await tester.pumpAndSettle();
    await tester.scrollUntilVisible(find.byKey(const Key('observed-error')),-180,scrollable:find.descendant(of:find.byType(ListView),matching:find.byType(Scrollable)).first);
    expect(find.byKey(const Key('observed-error')),findsOneWidget);
    expect(server.calls.where((r)=>r.method!='GET'),isEmpty);
  });
  testWidgets('saved server replay uses only prefix and hides final receipt at earlier cursor',(tester) async {
    final event=ObservedServerEvent.parse(fixture()['events']['events'][3]);
    final unchanged=jsonEncode(event.original);
    await tester.pumpWidget(MaterialApp(home:ObservedServerReplay(account:'server-one',event:event)));await tester.pumpAndSettle();
    final full=tester.widget<DirectLabs>(find.byType(DirectLabs)).rows.length;
    final slider=tester.widget<Slider>(find.byKey(const Key('observed-replay-slider')));
    slider.onChanged!(10);await tester.pumpAndSettle();
    expect(tester.widget<DirectLabs>(find.byType(DirectLabs)).rows.length,11);expect(full,greaterThan(11));
    expect(find.byKey(const Key('observed-original')),findsNothing);
    expect(jsonEncode(event.original),unchanged);expect(tester.takeException(),null);
  });
  testWidgets('invalid saved bars never manufacture a replacement chart',(tester) async {
    final event=ObservedServerEvent.parse(fixture()['events']['events'][3]);
    event.original['command']['observation']['bars']['NVDA'][0]['c']='missing';
    await tester.pumpWidget(MaterialApp(home:ObservedServerReplay(account:'server-one',event:event)));await tester.pumpAndSettle();
    expect(find.byType(DirectLabs),findsNothing);expect(find.byKey(const Key('observed-original')),findsOneWidget);
  });
  testWidgets('settlement preview includes shared fees and is invalidated by any edit',(tester) async {
    final f=fixture();
    await dialog(tester,ObservedServerSettlement(state:Map<String,dynamic>.from(f['snapshot']['state']),contract:'NVDA261023C00150000',serverTime:DateTime.parse(f['status']['serverTime'])));
    await tester.enterText(find.byKey(const Key('observed-settlement-price')),'155.00');
    await tester.enterText(find.byKey(const Key('observed-settlement-fee')),'1.00');
    await tester.enterText(find.byKey(const Key('observed-settlement-reference')),'fixture receipt');
    await tester.tap(find.byKey(const Key('observed-settlement-preview')));await tester.pumpAndSettle();
    expect(find.textContaining('-15001.00'),findsOneWidget);
    expect(tester.widget<FilledButton>(find.byKey(const Key('observed-settlement-save'))).onPressed,isNotNull);
    await tester.enterText(find.byKey(const Key('observed-settlement-quantity')),'10000');await tester.pump();
    expect(tester.widget<FilledButton>(find.byKey(const Key('observed-settlement-save'))).onPressed,isNull);
    await tester.tap(find.byKey(const Key('observed-settlement-preview')));await tester.pumpAndSettle();
    expect(find.byKey(const Key('observed-settlement-error')),findsOneWidget);expect(tester.takeException(),null);
  });
  testWidgets('configuration rejects out-of-policy quantity before closing',(tester) async {
    final config=Map<String,dynamic>.from(fixture()['snapshot']['state']['config']);
    await dialog(tester,ObservedServerConfig(config:config));
    await tester.enterText(find.byKey(const Key('observed-config-quantity')),'0');
    await tester.tap(find.byKey(const Key('observed-config-save')));await tester.pumpAndSettle();
    await tester.ensureVisible(find.byKey(const Key('observed-config-error')));await tester.pumpAndSettle();
    expect(find.byKey(const Key('observed-config-error')),findsOneWidget);expect(tester.takeException(),null);
  });
  testWidgets('version two policies and original performance are separate explicit reads',(tester) async {
    final server=Server();server.data.addAll(jsonDecode(File('test/fixtures/observed_server_v2.json').readAsStringSync()) as Map<String,dynamic>);
    final api=server.api();addTearDown(api.close);await mount(tester,api);
    expect(ObservedServerAccount.parse(server.data['snapshot'],'server-one').state['contract'],'observed-paper-ledger-v2');
    await show(tester,find.byKey(const Key('observed-performance')));await tester.tap(find.byKey(const Key('observed-performance')));await tester.pumpAndSettle();
    expect(find.textContaining('أقصى تراجع للمحقق'),findsOneWidget);
    expect(server.calls.every((r)=>r.method=='GET'),true);expect(tester.takeException(),null);
  });
  testWidgets('new lifecycle options default off and legacy config has no implicit upgrade',(tester) async {
    final data=jsonDecode(File('test/fixtures/observed_server_v2.json').readAsStringSync());
    await dialog(tester,ObservedServerConfig(config:Map<String,dynamic>.from(data['snapshot']['state']['config'])));
    expect(tester.widget<SwitchListTile>(find.byKey(const Key('observed-add'))).value,false);
    expect(tester.widget<SwitchListTile>(find.byKey(const Key('observed-scenario'))).value,false);
    await tester.tap(find.byKey(const Key('observed-add')));await tester.pumpAndSettle();
    expect(tester.widget<SwitchListTile>(find.byKey(const Key('observed-add'))).value,true);
    expect(data['snapshot']['state']['config']['addEnabled'],false);
  });
}
