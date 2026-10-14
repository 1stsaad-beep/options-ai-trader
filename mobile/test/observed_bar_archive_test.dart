import 'dart:convert';
import 'package:flutter_test/flutter_test.dart';
import 'package:options_ai_trader/direct_alpaca.dart';
import 'package:options_ai_trader/direct_replay.dart';
import 'package:options_ai_trader/observed_bar_archive.dart';

List<MarketBar> archivedTestBars(int start,int count)=>[for(var i=start;i<start+count;i++)
  MarketBar(DateTime.utc(2026,10,13,14,i),100+i%7.0,110,90,100+i%9.0,100)];
Map<String,dynamic> archivedTestEvidence(int start,int count,DateTime at)=>{
  'source':'fixture','feed':'iex','session':'regular','recordedAt':at.toIso8601String(),
  ...directBarEvidence(archivedTestBars(start,count)),
};
void main() {
  final at=DateTime.utc(2026,10,14,12);
  test('identical decisions share one original window without modifying inputs',(){
    final evidence=archivedTestEvidence(0,1000,at),original=jsonEncode(evidence);
    final first=ObservedBarArchive.read(null).capture('NVDA',evidence,at);
    final second=first.archive.capture('NVDA',evidence,at);
    expect(second.reference,first.reference);expect(second.archive.toJson(),first.archive.toJson());
    expect(jsonEncode(evidence),original);expect((second.archive.toJson()['epochs'] as List).length,1);
    final stored={...evidence,'barReference':first.reference}..remove('bars');
    expect(first.archive.resolve('NVDA',stored,at),evidence['bars']);
    final separate=jsonEncode([for(var i=0;i<4;i++)evidence]).length;
    final shared=jsonEncode({'archive':first.archive.toJson(),'events':[for(var i=0;i<4;i++)stored]}).length;
    expect(shared,lessThan(separate~/4));
  });
  test('rolling windows append only new bars while original range is stable',(){
    final first=ObservedBarArchive.read(null).capture('NVDA',archivedTestEvidence(0,1000,at),at);
    final later=at.add(const Duration(minutes:1)),evidence=archivedTestEvidence(1,1000,later);
    final next=first.archive.capture('NVDA',evidence,later),epoch=(next.archive.toJson()['epochs'] as List).single;
    expect((epoch['rows'] as List).length,1001);expect((epoch['captures'] as List).length,2);
    expect(next.reference['start'],1);expect(next.reference['epoch'],1);
    expect(next.archive.resolve('NVDA',{...evidence,'barReference':next.reference}..remove('bars'),later),evidence['bars']);
    final original=archivedTestEvidence(0,1000,at);
    expect(next.archive.resolve('NVDA',{...original,'barReference':first.reference}..remove('bars'),at),original['bars']);
    expect((first.archive.toJson()['epochs'][0]['rows'] as List).length,1000);
  });
  test('source revisions preserve prior source instead of changing old replay',(){
    final evidence=archivedTestEvidence(0,5,at),first=ObservedBarArchive.read(null).capture('NVDA',evidence,at);
    final revised=archivedTestEvidence(0,5,at);revised['bars'][2]['c']=109.0;
    final next=first.archive.capture('NVDA',revised,at);
    expect(next.reference['epoch'],2);expect(next.archive.toJson()['epochs'][0],first.archive.toJson()['epochs'][0]);
    expect(next.archive.resolve('NVDA',{...evidence,'barReference':first.reference}..remove('bars'),at),evidence['bars']);
  });
  test('source symbol feed and session cannot silently share another origin',(){
    var archive=ObservedBarArchive.read(null);var sequence=0;
    for(final settings in [<String,dynamic>{},{'feed':'sip'},{'session':'extended'},{'source':'alpaca'},{}]) {
      final evidence={...archivedTestEvidence(0,5,at),...settings};
      final next=archive.capture('NVDA',evidence,at);archive=next.archive;
      expect(next.reference['epoch'],++sequence);
    }
    expect(archive.capture('AAPL',archivedTestEvidence(0,5,at),at).reference['epoch'],6);
  });
  test('missing overlap or removed minute starts an epoch without gap filling',(){
    final first=ObservedBarArchive.read(null).capture('NVDA',archivedTestEvidence(0,5,at),at);
    expect(first.archive.capture('NVDA',archivedTestEvidence(6,5,at),at).reference['epoch'],2);
    final missing=archivedTestEvidence(0,5,at);(missing['bars'] as List).removeAt(2);missing['sourceWindow']['count']=4;
    final next=first.archive.capture('NVDA',missing,at);expect(next.reference['epoch'],2);
    expect((next.archive.toJson()['epochs'][1]['rows'] as List).length,4);
    final contiguous=first.archive.capture('NVDA',archivedTestEvidence(5,5,at),at);
    expect(contiguous.reference['epoch'],1);expect(contiguous.reference['start'],5);
  });
  test('future first capture cannot be borrowed by an earlier decision',(){
    final first=ObservedBarArchive.read(null).capture('NVDA',archivedTestEvidence(0,5,at),at);
    final earlier=at.subtract(const Duration(seconds:1));
    expect(()=>first.archive.capture('NVDA',archivedTestEvidence(0,5,earlier),earlier),throwsFormatException);
    final evidence=archivedTestEvidence(0,5,earlier)..remove('bars');
    evidence['barReference']={...first.reference,'knownAt':earlier.toIso8601String()};
    expect(()=>first.archive.resolve('NVDA',evidence,earlier),throwsFormatException);
  });
  test('range identity and chronology must agree with original evidence',(){
    final evidence=archivedTestEvidence(0,5,at),first=ObservedBarArchive.read(null).capture('NVDA',evidence,at);
    final stored={...evidence,'barReference':first.reference}..remove('bars');
    for(final change in [{'symbol':'AAPL'},{'source':'alpaca|iex|regular'},{'epoch':2},{'start':1},
      {'count':4},{'knownAt':at.add(const Duration(seconds:1)).toIso8601String()},{'start':9223372036854775807}]) {
      expect(()=>first.archive.resolve('NVDA',{...stored,'barReference':{...first.reference,...change}},at),throwsFormatException);
    }
    expect(()=>first.archive.resolve('AAPL',stored,at),throwsFormatException);
    expect(()=>first.archive.resolve('NVDA',{...stored,'bars':evidence['bars']},at),throwsFormatException);
    expect(()=>first.archive.resolve('NVDA',stored,at.subtract(const Duration(seconds:1))),throwsFormatException);
  });
  test('incomplete unordered unqualified malformed and conflicting windows are rejected',(){
    for(final corrupt in <void Function(Map<String,dynamic>)>[
      (e)=>e['bars'][0]['h']=1,(e)=>e['bars'][1]['at']=e['bars'][0]['at'],
      (e)=>e['sourceWindow']['count']=4,(e)=>e['source']='estimated',
      (e)=>e.remove('session'),(e)=>e['recordedAt']='2026-10-13T14:04:59Z',
      (e)=>e['bars'][0]['at']='2026-10-13T14:00:00.000001Z',
    ]) {
      final evidence=archivedTestEvidence(0,5,at);corrupt(evidence);
      expect(()=>ObservedBarArchive.read(null).capture('NVDA',evidence,at),throwsFormatException);
    }
  });
  test('archive import validates captures ordering ranges and OHLCV without aliasing',(){
    final first=ObservedBarArchive.read(null).capture('NVDA',archivedTestEvidence(0,5,at),at),original=jsonEncode(first.archive.toJson());
    for(final corrupt in <void Function(Map<String,dynamic>)>[
      (s)=>s['epochs'][0]['sequence']=2,(s)=>s['epochs'][0]['captures'][0]['through']=4,
      (s)=>s['epochs'][0]['captures'][0]['at']='2026-10-13T14:04:59Z',
      (s)=>s['epochs'][0]['rows'][0][2]=1,(s)=>s['epochs'][0]['rows'][1][0]=s['epochs'][0]['rows'][0][0],
    ]){final bad=first.archive.toJson();corrupt(bad);expect(()=>ObservedBarArchive.read(bad),throwsFormatException);}
    first.archive.toJson()['epochs'].clear();expect(jsonEncode(first.archive.toJson()),original);
  });
  test('capacity never evicts original observations',(){
    final first=ObservedBarArchive.read(null).capture('NVDA',archivedTestEvidence(0,5,at),at),original=jsonEncode(first.archive.toJson());
    final tooMany=first.archive.toJson();tooMany['epochs'][0]['rows']=List.filled(ObservedBarArchive.maxBars+1,[0,100,110,90,100,100]);
    expect(()=>ObservedBarArchive.read(tooMany),throwsFormatException);
    final tooLarge=first.archive.toJson();tooLarge['unexpected']='x'*ObservedBarArchive.maxBytes;
    expect(()=>ObservedBarArchive.read(tooLarge),throwsFormatException);
    expect(jsonEncode(first.archive.toJson()),original);
  });
}
