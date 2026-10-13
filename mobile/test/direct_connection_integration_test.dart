import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:options_ai_trader/direct_alpaca.dart';
import 'package:options_ai_trader/direct_screen.dart';
import 'market_paper_test.dart' show MemoryPaperStore;

// Widget -> real Dart adapter -> mocked native channel/storage/transport contract.
// No provider credentials or real network. Native/Keystore integration is tested separately on Android.
class NativeMock {
  String state='readable';
  DirectSettings config=const DirectSettings(real:true);
  String outcome='CONNECTED_DATA',phase='idle';
  bool saveFails=false,settingsFail=false,active=false;
  int starts=0,stops=0;
  final calls=<String>[];
  Future<dynamic> handle(MethodCall call) async {
    calls.add(call.method);
    switch(call.method){
      case 'secureScreen':return true;
      case 'keyState':return state;
      case 'getSettings':return config.encode();
      case 'saveKeys':
        if(saveFails)throw PlatformException(code:'KEY_SAVE_FAILED',message:'mock-private-value');
        state='readable';return true;
      case 'saveSettings':
        if(settingsFail)throw PlatformException(code:'SETTINGS_SAVE_FAILED');
        final candidate=DirectSettings.parse((call.arguments as Map)['settings'] as String);
        if(candidate.real&&state!='readable')throw PlatformException(code:state=='missing'?'KEYS_MISSING':'KEYSTORE_UNAVAILABLE');
        config=candidate;return true;
      case 'start':
        expect((call.arguments as Map)['confirmed'],isTrue);
        expect(config.real,isTrue);expect(state,'readable');starts++;active=true;phase=outcome=='WAIT'?'running':outcome.startsWith('CONNECTED_')?'succeeded':'failed';return true;
      case 'stop':stops++;active=false;return true;
      case 'backgroundStatus':return false;
      case 'snapshot':return jsonEncode({'enabled':active,'connected':active&&phase=='succeeded','feed':config.feed,'session':config.session,
        'source':'alpaca','reason':active?(phase=='succeeded'?'CONNECTED':outcome=='WAIT'?'CONNECTING':outcome):'DISABLED',
        'asOf':DateTime.now().millisecondsSinceEpoch,'bars':<String,dynamic>{},'events':[],'symbols':config.symbols,
        'testStatus':phase,'testCode':phase=='idle'?'NOT_TESTED':outcome=='WAIT'?'CONNECTING':outcome,'testAt':phase=='idle'?0:1});
      default:throw MissingPluginException();
    }
  }
}
Future<void> open(WidgetTester tester,NativeMock mock)async{
  TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger.setMockMethodCallHandler(DirectAlpaca.channel,mock.handle);
  await tester.pumpWidget(MaterialApp(home:DirectAlpacaScreen(paperStore:MemoryPaperStore())));await tester.pumpAndSettle();
}
Future<void> tap(WidgetTester tester,String key)async{
  final target=find.byKey(Key(key));
  await tester.scrollUntilVisible(target,180,scrollable:find.byType(Scrollable).first);
  await tester.pumpAndSettle();
  // Settle lazy layout before centering; an edge-visible button can be under navigation.
  await Scrollable.ensureVisible(tester.element(target),alignment:0.5);
  await tester.pumpAndSettle();expect(target.hitTestable(),findsOneWidget);
  await tester.tap(target);await tester.pumpAndSettle();
}
Future<void> close(WidgetTester tester)async{await tester.pumpWidget(const SizedBox());await tester.pumpAndSettle();}
void main(){
  tearDown(()=>TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger.setMockMethodCallHandler(DirectAlpaca.channel,null));
  testWidgets('saved real preference feed and session survive route recreation without automatic start',(tester)async{
    final mock=NativeMock()..config=const DirectSettings(real:false,feed:'sip',session:'extended',symbols:['TSLA']);
    await open(tester,mock);await tap(tester,'alpaca-real');expect(mock.config.real,isTrue);expect(mock.starts,0);
    await close(tester);await open(tester,mock);
    await tester.scrollUntilVisible(find.byKey(const Key('alpaca-real')),180,scrollable:find.byType(Scrollable).first);
    expect(tester.widget<SwitchListTile>(find.byKey(const Key('alpaca-real'))).value,isTrue);
    expect(mock.config.feed,'sip');expect(mock.config.session,'extended');expect(mock.config.symbols,['TSLA']);expect(mock.starts,0);
    await close(tester);
  });
  testWidgets('missing keys explain why testing and enabling are refused',(tester)async{
    final mock=NativeMock()..state='missing'..config=const DirectSettings();await open(tester,mock);
    await tap(tester,'alpaca-test');expect(find.textContaining('لا توجد مفاتيح محفوظة'),findsWidgets);expect(mock.starts,0);
    await tap(tester,'alpaca-real');expect(mock.config.real,isFalse);expect(mock.starts,0);await close(tester);
  });
  testWidgets('OFF explains prerequisite rather than a silent disabled test button',(tester)async{
    final mock=NativeMock()..config=const DirectSettings();await open(tester,mock);await tap(tester,'alpaca-test');
    expect(find.textContaining('فعّل Real Market Data'),findsWidgets);expect(mock.starts,0);await close(tester);
  });
  testWidgets('unreadable secure storage never claims usable keys or starts network',(tester)async{
    final mock=NativeMock()..state='unreadable';await open(tester,mock);await tap(tester,'alpaca-test');
    expect(find.textContaining('تعذرت قراءته أو فك تشفيره'),findsWidgets);expect(mock.starts,0);await close(tester);
  });
  testWidgets('failed secure save keeps obscured input and never reports success or leaks exception',(tester)async{
    final mock=NativeMock()..state='missing'..saveFails=true;await open(tester,mock);
    await tester.scrollUntilVisible(find.byKey(const Key('alpaca-key')),150,scrollable:find.byType(Scrollable).first);
    await tester.enterText(find.byKey(const Key('alpaca-key')),'mock-public-id');
    await tester.scrollUntilVisible(find.byKey(const Key('alpaca-secret')),150,scrollable:find.byType(Scrollable).first);
    await tester.enterText(find.byKey(const Key('alpaca-secret')),'mock-private-value');
    final field=tester.widget<TextField>(find.byKey(const Key('alpaca-secret')));await tap(tester,'alpaca-save');
    expect(field.controller!.text,'mock-private-value');expect(field.obscureText,isTrue);expect(find.textContaining('لم يتأكد الحفظ'),findsWidgets);
    expect(find.textContaining('تم الحفظ والتحقق'),findsNothing);expect(find.byWidgetPredicate((w)=>w is Text&&(w.data?.contains('mock-private-value')??false)),findsNothing);expect(mock.starts,0);await close(tester);
  });
  testWidgets('settings persistence failure does not flip the displayed switch',(tester)async{
    final mock=NativeMock()..config=const DirectSettings()..settingsFail=true;await open(tester,mock);await tap(tester,'alpaca-real');
    expect(tester.widget<SwitchListTile>(find.byKey(const Key('alpaca-real'))).value,isFalse);expect(mock.starts,0);await close(tester);
  });
  for(final code in ['HTTP_401','HTTP_403','HTTP_429','NETWORK_ERROR','TIMEOUT','AUTH_TIMEOUT']){
    testWidgets('explicit Test Connection shows $code result beside the button',(tester)async{
      final mock=NativeMock()..outcome=code;await open(tester,mock);expect(mock.starts,0);await tap(tester,'alpaca-test');
      expect(mock.starts,1);expect(find.text(directMessage(code)),findsWidgets);
      await tester.scrollUntilVisible(find.byKey(const Key('alpaca-test-feedback')),100,scrollable:find.byType(Scrollable).first);
      expect(tester.getRect(find.byKey(const Key('alpaca-test-feedback'))).overlaps(Offset.zero & tester.view.physicalSize/tester.view.devicePixelRatio),isTrue);
      expect(find.textContaining('mock-private'),findsNothing);await close(tester);
    });
  }
  testWidgets('success is explicit while no candles never earns LIVE',(tester)async{
    final mock=NativeMock()..outcome='CONNECTED_NO_BARS';await open(tester,mock);await tap(tester,'alpaca-test');
    expect(mock.starts,1);expect(find.text(directMessage('CONNECTED_NO_BARS')),findsWidgets);await close(tester);
  });
  testWidgets('unresolved connection has a bounded visible timeout and stops transport',(tester)async{
    final mock=NativeMock()..outcome='WAIT';await open(tester,mock);await tap(tester,'alpaca-test');
    await tester.pump(const Duration(seconds:36));await tester.pumpAndSettle();
    expect(find.text(directMessage('TIMEOUT')),findsWidgets);expect(mock.active,isFalse);expect(mock.stops,greaterThan(0));await close(tester);
  });
}
