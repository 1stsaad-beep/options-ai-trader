import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:options_ai_trader/direct_alpaca.dart';
import 'package:options_ai_trader/direct_labs.dart';
import 'package:options_ai_trader/direct_wave_archive.dart';
import 'package:options_ai_trader/market_paper.dart';
import 'package:options_ai_trader/demo/chart_painter.dart';
import 'wave_analysis_test.dart' show observations;
import 'market_paper_safety_test.dart' show FaultPaperStore;

void main() {
  const source='fixture|iex|extended';
  final origin=DateTime.utc(2026,10,13,14),captured=DateTime.utc(2026,10,15);
  List<MarketBar> rows(int count) {
    final shape=observations();
    return List.generate(count,(i) {
      final b=shape[i<shape.length?i:shape.length-1];
      return MarketBar(origin.add(Duration(minutes:i)),b.open,b.high,b.low,b.close,b.volume);
    });
  }
  DirectWaveArchive first(List<MarketBar> bars)=>DirectWaveArchive.read(DirectWaveArchive.read(null).append('NVDA',source,bars,captured));
  test('rolling 1000-bar window preserves old origin events and invalidation across restart',()async {
    final store=FaultPaperStore(),paper=MarketPaper(FaultPaperStore(),clock:()=>captured);
    await paper.load();await paper.observeWaves('NVDA',source,rows(1000));
    final before=paper.waveArchive!.epochs('NVDA').single;
    expect((before['journal']['events'] as List).any((e)=>e['event']=='INVALIDATED'),true);
    await paper.observeWaves('NVDA',source,rows(1100).sublist(100));
    final after=paper.waveArchive!.epochs('NVDA').single;
    expect((after['times'] as List).length,1100);
    expect((after['journal']['events'] as List).take((before['journal']['events'] as List).length).toList(),before['journal']['events']);
    expect((after['captures'] as List).map((c)=>c['through']),[999,1099]);
    await store.write(paper.copy());final recovered=MarketPaper(store,clock:()=>captured);await recovered.load();
    expect(recovered.ready,true);expect(recovered.waveArchive!.epochs('NVDA'),[after]);
    final restored=MarketPaper(FaultPaperStore(),clock:()=>captured);await restored.load();
    await restored.restoreBackup(recovered.exportBackup());expect(restored.waveArchive!.toJson(),recovered.waveArchive!.toJson());
  });
  test('repeated and older windows are no-op and returned maps cannot mutate originals',() {
    final a=first(rows(100));final before=jsonEncode(a.toJson());
    expect(a.append('NVDA',source,rows(100),captured),isNull);
    expect(a.append('NVDA',source,rows(80),captured),isNull);
    (a.epochs('NVDA').single['times'] as List).clear();expect(jsonEncode(a.toJson()),before);
  });
  test('changed feed starts a new immutable epoch',() {
    final a=first(rows(100)),original=a.epochs('NVDA').single;
    final b=DirectWaveArchive.read(a.append('NVDA','fixture|sip|extended',rows(100),captured));
    expect(b.epochs('NVDA').first,original);expect(b.epochs('NVDA').last['boundary'],'SOURCE_CHANGED');
    expect(b.latest('NVDA',source),isNull);
  });
  test('revised overlap preserves original interpretation and labels replacement epoch',() {
    final a=first(rows(100)),revised=rows(100),b=revised[95];
    revised[95]=MarketBar(b.time,b.open,b.high+.5,b.low,b.close,b.volume);
    final updated=DirectWaveArchive.read(a.append('NVDA',source,revised,captured));
    expect(updated.epochs('NVDA').first,a.epochs('NVDA').single);
    expect(updated.epochs('NVDA').last['boundary'],'SOURCE_REVISED');
  });
  test('unexplained missing minute splits while complete regular session closure connects',() {
    final gap=[...rows(30)]..removeAt(15),a=first(gap);
    expect(a.epochs('NVDA').map((e)=>e['boundary']),['INITIAL','OBSERVATION_GAP']);
    expect(DirectWaveArchive.connected(DateTime.utc(2026,10,9,19,59),DateTime.utc(2026,10,12,13,30),'alpaca|iex|regular'),true);
    expect(DirectWaveArchive.connected(DateTime.utc(2026,10,9,19,58),DateTime.utc(2026,10,12,13,30),'alpaca|iex|regular'),false);
    expect(DirectWaveArchive.connected(DateTime.utc(2026,10,9,19,59),DateTime.utc(2026,10,13,13,30),'alpaca|iex|regular'),false);
  });
  test('incomplete/future candles cannot create archived knowledge',() {
    expect(()=>DirectWaveArchive.read(null).append('NVDA',source,rows(30),origin.add(const Duration(minutes:29,seconds:59))),throwsFormatException);
  });
  for(final target in ['event','time','capture']) {
    test('archive rejects corrupted $target instead of inventing a clean history',() {
      final state=first(rows(100)).toJson(),e=(state['symbols']['NVDA'] as List).single;
      if(target=='event'){e['journal']['events'][0]['close']=999;}
      if(target=='time'){e['times'][5]=e['times'][4];}
      if(target=='capture'){e['captures'][0]['through']=1;}
      expect(()=>DirectWaveArchive.read(state),throwsFormatException);
    });
  }
  test('failed archive write retains original history; exact retry may commit',()async {
    final store=FaultPaperStore(),paper=MarketPaper(FaultPaperStore(),clock:()=>captured);
    await paper.load();await paper.observeWaves('NVDA',source,rows(100));await store.write(paper.copy());
    final recovered=MarketPaper(store,clock:()=>captured);await recovered.load();final before=jsonEncode(store.value);
    store.dropWrite=true;await recovered.observeWaves('NVDA',source,rows(110));
    expect(jsonEncode(store.value),before);expect(recovered.waveArchiveError,isNotNull);
    store.dropWrite=false;await recovered.observeWaves('NVDA',source,rows(110));
    expect((recovered.waveArchive!.epochs('NVDA').single['times'] as List).length,110);
    expect(recovered.waveArchiveError,isNull);
  });
  test('optional corrupt archive does not make the financial account unreadable',()async {
    final store=FaultPaperStore(),paper=MarketPaper(FaultPaperStore());await paper.load();await paper.add('kept');
    await store.write({...paper.copy(),'waveArchive':{'invalid':true}});
    final original=jsonEncode(store.value),recovered=MarketPaper(store);await recovered.load();
    expect(recovered.ready,true);expect(recovered.waveArchive,isNull);expect(recovered.accounts.single['cash'],1000000);
    expect(jsonEncode(store.value),original);
  });
  test('optional archive corruption cannot veto a qualified owned manual close',()async {
    final clock=DateTime.utc(2026,10,13,15,5),store=FaultPaperStore();
    final paper=MarketPaper(store,clock:()=>clock);await paper.load();await paper.add('owned');
    final id=paper.accounts.single['id'] as String;
    await paper.configure(id,{'enabled':true,'contracts':{'NVDA:CALL':'NVDA261016C00200000'}});
    Future<OptionQuote?> quote(String c)async=>OptionQuote(c,'opra',clock,200,210,10,10);
    await paper.evaluate(id:id,symbol:'NVDA',signal:'CALL',confirmedReverse:false,dataValid:()=>true,observation:'entry',quotes:quote);
    store.value!['waveArchive']={'invalid':true};
    final recovered=MarketPaper(store,clock:()=>clock);await recovered.load();expect(recovered.waveArchive,isNull);
    await recovered.evaluate(id:id,symbol:'NVDA',signal:'WAIT',confirmedReverse:false,dataValid:()=>false,
      observation:'manual',quotes:quote,forceClose:true);
    expect(recovered.account(id)['positions'],isEmpty);expect(recovered.journal.last['decision'],'CLOSED_MANUAL');
    expect(recovered.copy()['waveArchive'],{'invalid':true});
  });
  test('capacity refusal preserves prior history without truncation',() {
    final a=first(rows(100)),before=jsonEncode(a.toJson());
    final far=origin.add(const Duration(days:8));
    expect(()=>a.append('NVDA',source,rows(DirectWaveArchive.maxBars+1),far),throwsFormatException);
    expect(jsonEncode(a.toJson()),before);
  });
  testWidgets('Direct wave lab uses archived events when provider window moves',(tester)async {
    final all=rows(1100),a=first(all);
    await tester.pumpWidget(MaterialApp(home:Scaffold(body:SingleChildScrollView(child:DirectLabs(
      rows:all.sublist(100),symbol:'NVDA',source:'fixture',waveEpoch:a.latest('NVDA',source))))));
    expect(find.textContaining('1100 شمعة'),findsOneWidget);
    final painter=tester.widget<CustomPaint>(find.byKey(const Key('direct-chart'))).painter! as DemoCandlePainter;
    expect(painter.bars.length,180);expect(tester.takeException(),isNull);
  });
}
