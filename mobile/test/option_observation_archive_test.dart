import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:options_ai_trader/direct_alpaca.dart';
import 'package:options_ai_trader/direct_decision_view.dart';
import 'package:options_ai_trader/market_paper.dart';
import 'package:options_ai_trader/observed_option_replay.dart';
import 'package:options_ai_trader/option_observation_archive.dart';
import 'market_paper_safety_test.dart' show FaultPaperStore;

void main() {
  const contract='NVDA261016C00200000';
  late DateTime now;late FaultPaperStore store;late MarketPaper paper;late String id;
  OptionQuote quote({int bid=200,int ask=210,String feed='opra'})=>OptionQuote(contract,feed,now,bid,ask,10,10);
  Future<void> evaluate({bool close=false,int bid=200,int ask=210})=>paper.evaluate(id:id,symbol:'NVDA',signal:'CALL',
    confirmedReverse:false,dataValid:()=>true,observation:now.toIso8601String(),quotes:(_)async=>quote(bid:bid,ask:ask),forceClose:close);
  Map<String,dynamic> observation(int milliseconds)=>{'account':'a','source':'fixture',
    'capturedAt':DateTime.utc(2026,10,13,15).add(Duration(milliseconds:milliseconds)).toIso8601String(),
    'quote':{'contract':contract,'feed':'opra','at':DateTime.utc(2026,10,13,15).add(Duration(milliseconds:milliseconds)).toIso8601String(),
      'bid':200,'ask':210,'bidSize':10,'askSize':10}};
  setUp(()async {
    now=DateTime.utc(2026,10,13,15,1);store=FaultPaperStore();paper=MarketPaper(store,clock:()=>now);
    await paper.load();await paper.add('independent');id=paper.accounts.single['id'] as String;
    await paper.configure(id,{'enabled':true,'contracts':{'NVDA:CALL':contract}});
  });
  test('opening and hold observations commit with balances and survive stopped restart',()async {
    await evaluate();now=now.add(const Duration(seconds:30));await evaluate(bid:208);
    expect(paper.journal.length,1);expect(paper.optionObservations(id).length,2);
    final recovered=MarketPaper(store,clock:()=>now);await recovered.load();expect(recovered.account(id)['enabled'],false);
    expect(recovered.optionObservations(id),paper.optionObservations(id));
    final restored=MarketPaper(FaultPaperStore(),clock:()=>now);await restored.load();await restored.restoreBackup(paper.exportBackup());
    expect(restored.optionObservations(id),paper.optionObservations(id));expect(restored.account(id)['enabled'],false);
  });
  test('closed accounts retain observed horizon without rearming or rewriting receipts',()async {
    await evaluate();final entry=paper.journal.first;
    now=now.add(const Duration(seconds:1));await evaluate(close:true);await paper.configure(id,{'enabled':false});
    final before=paper.account(id),original=jsonEncode(paper.journal);
    now=DateTime.utc(2026,10,13,15,1,59);
    await paper.observeRecentOptions(source:'fixture',quotes:(_)async=>quote(bid:250,ask:260),active:()=>true);
    final result=replayObservedOption({'entry':entry,'observations':paper.optionObservations(id),
      'asOf':'2026-10-13T15:02:00.000Z','horizonSeconds':60});
    expect(result['pnlCents'],3870);expect(paper.account(id),before);expect(jsonEncode(paper.journal),original);
  });
  test('inactive source mismatch or elapsed window makes no quote request',()async {
    await evaluate();var calls=0;
    Future<OptionQuote?> reader(String _)async{calls++;return quote();}
    await paper.observeRecentOptions(source:'fixture',quotes:reader,active:()=>false);
    await paper.observeRecentOptions(source:'alpaca',quotes:reader,active:()=>true);
    now=now.add(const Duration(minutes:6));await paper.observeRecentOptions(source:'fixture',quotes:reader,active:()=>true);
    expect(calls,0);
  });
  test('indicator or missing quotes never enter observed archive',()async {
    await evaluate();now=now.add(const Duration(seconds:30));
    await paper.observeRecentOptions(source:'fixture',quotes:(_)async=>quote(feed:'indicative'),active:()=>true);
    await paper.observeRecentOptions(source:'fixture',quotes:(_)async=>null,active:()=>true);
    expect(paper.optionObservations(id).length,1);
  });
  test('dropped observation write preserves original and retry confirms exactly once',()async {
    await evaluate();now=now.add(const Duration(seconds:30));final original=jsonEncode(store.value);
    store.dropWrite=true;await paper.observeRecentOptions(source:'fixture',quotes:(_)async=>quote(),active:()=>true);
    expect(jsonEncode(store.value),original);expect(paper.optionArchiveError,isNotNull);
    store.dropWrite=false;await paper.observeRecentOptions(source:'fixture',quotes:(_)async=>quote(),active:()=>true);
    expect(paper.optionObservations(id).length,2);expect(paper.optionArchiveError,isNull);
    await paper.observeRecentOptions(source:'fixture',quotes:(_)async=>quote(),active:()=>true);expect(paper.optionObservations(id).length,2);
  });
  test('corrupt optional quotes cannot veto qualified owned manual protection',()async {
    await evaluate();store.value!['optionArchive']={'invalid':true};
    final recovered=MarketPaper(store,clock:()=>now);await recovered.load();expect(recovered.ready,true);
    await recovered.evaluate(id:id,symbol:'NVDA',signal:'WAIT',confirmedReverse:false,dataValid:()=>false,
      observation:'manual',quotes:(_)async=>quote(),forceClose:true);
    expect(recovered.account(id)['positions'],isEmpty);expect(recovered.copy()['optionArchive'],{'invalid':true});
    expect(recovered.optionArchiveError,isNotNull);
  });
  test('segments preserve duplicates first capture and immutable returned records',() {
    final archive=OptionObservationArchive.read(OptionObservationArchive.read(null).append([for(var i=0;i<1001;i++)observation(i)]));
    expect((archive.toJson()['segments'] as List).map((s)=>(s as List).length),[1000,1]);
    final repeated=observation(0);repeated['capturedAt']=observation(2000)['capturedAt'];
    expect(archive.append([repeated]),isNull);
    archive.observations.first['quote']['bid']=1;expect(archive.observations.first['quote']['bid'],200);
  });
  test('reordered or malformed imported observations fail without replacing original',() {
    final archive=OptionObservationArchive.read(OptionObservationArchive.read(null).append([observation(20)]));
    final before=jsonEncode(archive.toJson());
    expect(()=>archive.append([observation(10)]),throwsFormatException);
    final bad=observation(30);bad['quote']['feed']='indicative';expect(()=>archive.append([bad]),throwsFormatException);
    expect(jsonEncode(archive.toJson()),before);
  });
  test('capacity is explicit without eviction',() {
    expect(()=>OptionObservationArchive.read(null).append([for(var i=0;i<=OptionObservationArchive.maxObservations;i++)observation(i)]),throwsFormatException);
  });
  testWidgets('read-only UI separates later counterfactual from original receipt',(tester)async {
    await evaluate();now=DateTime.utc(2026,10,13,15,5,59);
    await paper.observeRecentOptions(source:'fixture',quotes:(_)async=>quote(bid:250,ask:260),active:()=>true);
    final original=jsonEncode(paper.journal),before=paper.account(id);
    await tester.pumpWidget(MaterialApp(home:DirectDecisionView(event:paper.journal.first,
      observations:paper.optionObservations(id),asOf:DateTime.utc(2026,10,13,15,6))));
    expect(find.byKey(const Key('option-replay-result')),findsNothing);
    await tester.ensureVisible(find.byKey(const Key('option-replay-toggle')));await tester.tap(find.byKey(const Key('option-replay-toggle')));await tester.pumpAndSettle();
    await tester.scrollUntilVisible(find.byKey(const Key('option-replay-result')),200,scrollable:find.byType(Scrollable).first);
    expect(find.textContaining('38.70 USD'),findsOneWidget);
    expect(paper.account(id),before);expect(jsonEncode(paper.journal),original);expect(tester.takeException(),isNull);
  });
}
