import 'dart:convert';
import 'dart:io';
import 'package:flutter_test/flutter_test.dart';
import 'package:options_ai_trader/demo/wave_analysis.dart';
import 'package:options_ai_trader/direct_alpaca.dart';
import 'package:options_ai_trader/direct_replay.dart';
import 'package:options_ai_trader/direct_wave_archive.dart';

void near(dynamic actual,dynamic expected,String path) {
  if(expected is num){expect(actual,closeTo(expected.toDouble(),1e-9),reason:path);}
  else if(expected is List){expect(actual,isA<List>(),reason:path);expect((actual as List).length,expected.length,reason:path);for(var i=0;i<expected.length;i++){near(actual[i],expected[i],'$path/$i');}}
  else if(expected is Map){expect(actual,isA<Map>(),reason:path);expect((actual as Map).keys.toSet(),expected.keys.toSet(),reason:path);for(final k in expected.keys){near(actual[k],expected[k],'$path/$k');}}
  else{expect(actual,expected,reason:path);}
}
Map<String,dynamic> portable(Map s,Map<String,Map> known)=>{
  for(final k in ['kind','degree','bullish','points','labels','invalidation','activation','targets','evidence','observed_at'])k:s[k],
  'parentPoints':s['parent_id']==null?null:known[s['parent_id']]!['points'],
};
String eventKey(Map e) {
  final s=e['scenario'] as Map;
  return [e['event'],e['tick'],s['kind'],s['degree'],(s['points'] as List).map((p)=>p[0]).join(','),
    ((s['parentPoints']??[]) as List).map((p)=>p[0]).join(',')].join('|');
}
void main() {
  final fixture=jsonDecode(File('test/fixtures/wave_contract_v1.json').readAsStringSync()) as Map;
  final origin=DateTime.utc(2026,10,13,14),captured=DateTime.utc(2026,10,14);
  List<MarketBar> rows(Map c)=>[for(var i=0;i<(c['bars'] as List).length;i++)(() {
    final v=c['bars'][i] as List;return MarketBar(origin.add(Duration(minutes:i)),
      (v[0] as num).toDouble(),(v[1] as num).toDouble(),(v[2] as num).toDouble(),(v[3] as num).toDouble(),(v[4] as num).toDouble());
  })()];
  for(final raw in fixture['cases'] as List) {
    final c=raw as Map;
    test('server/Direct wave geometry and causal events every prefix: ${c['name']}',() {
      expect(fixture['contract'],marketWaveContract);
      final source=rows(c),journal=ChartWaveJournal(strictMarket:true);
      final known=<String,Map>{};var cursor=0;
      for(final step in c['steps'] as List) {
        final end=step['through'] as int;
        journal.append([for(var i=0;i<=end;i++)source[i].candle(i)]);
        final newEvents=journal.events.skip(cursor).toList();cursor=journal.events.length;
        for(final e in newEvents){known[e.scenarioId]=jsonDecode(e.snapshotJson) as Map;}
        final actual=[for(final e in newEvents){'event':e.event,'tick':e.observedAt,'close':e.close,
          'scenario':portable(jsonDecode(e.snapshotJson) as Map,known)}]..sort((a,b)=>eventKey(a).compareTo(eventKey(b)));
        near(actual,step['events'],'${c['name']}/$end');
        expect(journal.view(end).contract,marketWaveContract);
        expect(journal.view(end).active.every((s)=>s.observedAt<=end),true);
      }
      expect(ChartWaveJournal.restore(journal.toJson()).toJson(),journal.toJson());
      expect(directWaveView(source).contract,marketWaveContract);
      final snapshot=directResearchSnapshot(source);
      expect(snapshot['version'],'direct-research-v6');expect(snapshot['waveContract'],marketWaveContract);
    });
  }
  test('old checkpoint remains exact and engine change seals rather than rewrites its epoch',() {
    final source=rows((fixture['cases'] as List).first as Map),legacy=ChartWaveJournal()..append([for(var i=0;i<source.length;i++)source[i].candle(i)]);
    const identity='fixture|iex|extended';
    final old={'sequence':1,'source':identity,'boundary':'INITIAL','times':source.map((b)=>b.time.millisecondsSinceEpoch).toList(),
      'capturedAt':captured.toIso8601String(),'captures':[{'through':source.length-1,'at':captured.toIso8601String()}],
      'journal':legacy.toJson()};
    final archive=DirectWaveArchive.read({'version':1,'symbols':{'NVDA':[old]}});
    final original=jsonEncode(archive.toJson());
    expect(ChartWaveJournal.restore(legacy.toJson()).toJson(),legacy.toJson());
    expect(archive.view('NVDA',identity)!.contract,legacyWaveContract);
    expect(directResearchSnapshot(source,archivedWaves:archive.view('NVDA',identity))['waveContract'],legacyWaveContract);
    final next=DirectWaveArchive.read(archive.append('NVDA',identity,source,captured));
    expect(jsonEncode(archive.toJson()),original);expect(next.epochs('NVDA').first,old);
    expect(next.epochs('NVDA').last['boundary'],'ENGINE_CHANGED');
    expect(next.view('NVDA',identity)!.contract,marketWaveContract);
    expect(next.append('NVDA',identity,source,captured),isNull);
    expect(DirectWaveArchive.read(next.toJson()).toJson(),next.toJson());
  });
  test('archive refuses a backdated engine/source capture without changing originals',() {
    final source=rows((fixture['cases'] as List).first as Map),a=DirectWaveArchive.read(
      DirectWaveArchive.read(null).append('NVDA','fixture|iex|extended',source,captured));
    final before=jsonEncode(a.toJson());
    expect(()=>a.append('NVDA','fixture|sip|extended',source,captured.subtract(const Duration(seconds:1))),throwsFormatException);
    expect(jsonEncode(a.toJson()),before);
  });
  test('unknown wave engine checkpoint never silently falls back to legacy rules',() {
    final state=ChartWaveJournal(strictMarket:true).toJson();state['contract']='future-engine';
    expect(()=>ChartWaveJournal.restore(state),throwsFormatException);
    final downgrade=ChartWaveJournal(strictMarket:true).toJson();downgrade['version']=1;
    expect(()=>ChartWaveJournal.restore(downgrade),throwsFormatException);
  });
}
