import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:options_ai_trader/direct_alpaca.dart';
import 'package:options_ai_trader/direct_decision_view.dart';
import 'package:options_ai_trader/direct_replay.dart';
import 'package:options_ai_trader/demo/chart_painter.dart';
import 'package:options_ai_trader/market_paper.dart';
import 'package:options_ai_trader/market_paper_backup.dart';
import 'market_paper_safety_test.dart' show FaultPaperStore;
import 'observed_bar_archive_test.dart' show archivedTestEvidence;

void main() {
  const contract='NVDA261016C00200000';
  late DateTime now;late FaultPaperStore store;late MarketPaper paper;late String id;
  OptionQuote quote()=>OptionQuote(contract,'opra',now,200,210,10,10);
  Future<void> evaluate({String? account,bool close=false,Map<String,dynamic>? evidence})=>paper.evaluate(
    id:account??id,symbol:'NVDA',signal:'CALL',confirmedReverse:false,dataValid:()=>true,
    observation:'2026-10-14T06:39:00.000Z',quotes:(_)async=>quote(),forceClose:close,
    evidence:evidence??archivedTestEvidence(0,1000,now));
  Future<String> add()async {
    await paper.add('independent');final id=paper.accounts.last['id'] as String;
    await paper.configure(id,{'enabled':true,'contracts':{'NVDA:CALL':contract}});return id;
  }
  setUp(()async {
    now=DateTime.utc(2026,10,14,15,1);store=FaultPaperStore();paper=MarketPaper(store,clock:()=>now);
    await paper.load();id=await add();
  });
  test('four independent accounts save one source and recover original references stopped',()async {
    final ids=[id,await add(),await add(),await add()];
    for(final account in ids){await evaluate(account:account);}
    expect(paper.journal.length,4);expect(paper.accounts.every((a)=>(a['positions'] as Map).length==1),true);
    final epochs=paper.copy()['barArchive']['epochs'] as List;
    expect(epochs.length,1);expect((epochs.single['rows'] as List).length,1000);
    expect(paper.journal.every((e)=>e['evidence']['bars']==null&&e['evidence']['barReference']['epoch']==1),true);
    final original=jsonEncode(paper.journal),snapshot=paper.barArchive!;
    for(final e in paper.journal){expect(DirectDecisionRecord.read(e,archive:snapshot).bars.length,1000);}
    final recovered=MarketPaper(store,clock:()=>now);await recovered.load();expect(recovered.ready,true);
    expect(recovered.accounts.every((a)=>a['enabled']==false),true);expect(jsonEncode(recovered.journal),original);
    final restored=MarketPaper(FaultPaperStore(),clock:()=>now);await restored.load();await restored.restoreBackup(paper.exportBackup());
    expect(jsonEncode(restored.journal),original);expect(restored.barArchive!.toJson(),snapshot.toJson());
    expect(restored.accounts.every((a)=>a['enabled']==false),true);
  });
  test('new references never rewrite legacy inline receipts or change original JSON',()async {
    final legacy=archivedTestEvidence(0,1000,now)..remove('session');await evaluate(evidence:legacy);
    final original=jsonEncode(paper.journal.first);expect(paper.journal.first['evidence']['bars'],isNotNull);
    await evaluate(close:true);expect(paper.journal.last['evidence']['barReference'],isNotNull);
    expect(jsonEncode(paper.journal.first),original);expect(DirectDecisionRecord.read(paper.journal.first).bars.length,1000);
    final saved=DirectDecisionRecord.read(paper.journal.last,archive:paper.barArchive);
    expect(saved.original['evidence'].containsKey('bars'),false);expect(saved.originalJson,jsonEncode(paper.journal.last));
    saved.original['evidence']['barReference']['epoch']=99;
    expect(saved.original['evidence']['barReference']['epoch'],1);
  });
  test('dropped write creates no dangling source or financial receipt and retry confirms once',()async {
    final original=jsonEncode(store.value);store.dropWrite=true;await evaluate();
    expect(jsonEncode(store.value),original);expect(paper.journal,isEmpty);expect(paper.copy()['barArchive'],isNull);
    expect(paper.barArchiveError,isNotNull);expect(paper.account(id)['positions'],isEmpty);
    store.dropWrite=false;await evaluate();expect(paper.journal.length,1);expect(paper.barArchiveError,isNull);
    expect(DirectDecisionRecord.read(paper.journal.single,archive:paper.barArchive).bars.length,1000);
  });
  test('lost write acknowledgement reconciles complete source and receipt atomically',()async {
    store.throwAfterWrite=true;await evaluate();expect(paper.ready,true);expect(paper.journal.length,1);
    expect(DirectDecisionRecord.read(paper.journal.single,archive:paper.barArchive).completeSource,true);
  });
  test('concurrent durable owner cannot be overwritten by source capture',()async {
    final second=MarketPaper(store,clock:()=>now);await second.load();await second.add('second owner');
    final original=jsonEncode(store.value);await evaluate();
    expect(paper.ready,false);expect(jsonEncode(store.value),original);expect(store.value!['barArchive'],isNull);
  });
  test('corrupt optional source cannot veto qualified owned protection or erase originals',()async {
    await evaluate();final entry=jsonEncode(paper.journal.first);store.value!['barArchive']={'invalid':true};
    paper=MarketPaper(store,clock:()=>now);await paper.load();expect(paper.ready,true);
    expect(paper.barArchive,isNull);await evaluate(close:true);
    expect(paper.account(id)['positions'],isEmpty);expect(paper.copy()['barArchive'],{'invalid':true});
    expect(jsonEncode(paper.journal.first),entry);expect(paper.barArchiveError,isNotNull);
    expect(paper.journal.last['evidence']['bars'],isNotNull);
    expect(DirectDecisionRecord.read(paper.journal.last).completeSource,true);
    expect(()=>DirectDecisionRecord.read(paper.journal.first),throwsFormatException);
  });
  test('backup refuses missing sources altered joins and future first-capture evidence',()async {
    await evaluate();final original=paper.exportBackup();
    for(final corrupt in <void Function(Map<String,dynamic>)>[
      (book)=>book.remove('barArchive'),
      (book)=>book['journal'][0]['evidence']['barReference']['symbol']='AAPL',
      (book)=>book['journal'][0]['evidence']['barReference']['count']=999,
      (book)=>book['barArchive']['epochs'][0]['captures'][0]['at']=now.add(const Duration(seconds:1)).toIso8601String(),
    ]) {
      final envelope=jsonDecode(original) as Map<String,dynamic>;corrupt(envelope['ledger'] as Map<String,dynamic>);
      expect(()=>PaperBackup.inspect(jsonEncode(envelope)),throwsFormatException);
    }
    expect(paper.exportBackup(),original);
  });
  test('archive-only destination is not overwritten by a backup',()async {
    await evaluate();final target=FaultPaperStore()..value={'version':1,'accounts':<dynamic>[],'journal':<dynamic>[],
      'barArchive':paper.barArchive!.toJson()};
    final other=MarketPaper(target,clock:()=>now);await other.load();final original=jsonEncode(target.value);
    await expectLater(other.restoreBackup(paper.exportBackup()),throwsStateError);expect(jsonEncode(target.value),original);
  });
  testWidgets('saved source reference paints a causal cursor without materializing original JSON',(tester)async {
    await evaluate();final event=paper.journal.single,original=jsonEncode(event);
    await tester.pumpWidget(MaterialApp(home:DirectDecisionView(event:event,barArchive:paper.barArchive)));
    await tester.pumpAndSettle();
    DemoCandlePainter painter()=>tester.widget<CustomPaint>(find.byKey(const Key('decision-replay-chart'))).painter! as DemoCandlePainter;
    expect(painter().bars.length,1000);expect(painter().markers.length,1);
    tester.widget<Slider>(find.byKey(const Key('replay-slider'))).onChanged!(10);await tester.pumpAndSettle();
    expect(painter().bars.length,11);expect(painter().markers,isEmpty);
    expect(find.byKey(const Key('replay-original-reason')),findsNothing);expect(find.byKey(const Key('replay-original-json')),findsNothing);
    expect(jsonEncode(event),original);expect(jsonEncode(paper.journal.single),original);expect(tester.takeException(),isNull);
  });
  testWidgets('standalone referenced receipt explicitly lacks source without inventing a chart',(tester)async {
    await evaluate();await tester.pumpWidget(MaterialApp(home:DirectDecisionView(event:paper.journal.single)));
    expect(find.byKey(const Key('replay-invalid')),findsOneWidget);expect(find.byKey(const Key('decision-replay-chart')),findsNothing);
  });
}
