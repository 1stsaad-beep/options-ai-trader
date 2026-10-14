import 'dart:convert';
import 'package:flutter_test/flutter_test.dart';
import 'package:options_ai_trader/direct_alpaca.dart';
import 'package:options_ai_trader/direct_replay.dart';

void main() {
  List<MarketBar> rows(int count)=>List.generate(count,(i)=>MarketBar(DateTime.utc(2026,10,13,14,i),100+i%7.0,110,90,100+i%9.0,100));
  test('higher timeframes contain only complete UTC-aligned contiguous groups',(){
    final bars=rows(14);expect(directTimeframe(bars,5).length,2);
    expect(directTimeframe(bars.sublist(1),5).length,1);
    final gap=[...bars]..removeAt(7);expect(directTimeframe(gap,5).length,1);
    expect(directTimeframe(bars,15),isEmpty);
  });
  test('research snapshot retains original prefix and confirmed times',(){
    final prefix=rows(40),original=jsonEncode(directResearchSnapshot(prefix));
    directResearchSnapshot(rows(70));
    expect(jsonEncode(directResearchSnapshot(prefix)),original);
    final research=directResearchSnapshot(prefix);
    expect(research['executable'],false);
    for(final wave in research['waveCandidates'] as List){expect(wave['observed_at']<40,true);}
  });
  test('trade markers use original observation and never option price as stock y coordinate',(){
    final event={'symbol':'NVDA','decision':'OPENED_CALL','fill':{'side':'BUY','quantity':1,'price':210},
      'evidence':{'observation':'2026-10-13T14:07:00.000Z'}};
    final markers=directTradeMarkers(directTimeframe(rows(15),5),5,'NVDA',[event]);
    expect(markers.single['tick'],1);expect(markers.single['optionPriceCents'],210);
    expect(directTradeMarkers(rows(15),1,'AAPL',[event]),isEmpty);
    expect(directTradeMarkers(rows(5),1,'NVDA',[event]),isEmpty);
  });
  Map<String,dynamic> decision(List<MarketBar> bars)=>{'account':'a','symbol':'NVDA','at':'2026-10-14T12:00:00.000Z',
    'decision':'OPENED_CALL','evidence':{'recordedAt':'2026-10-14T11:59:00.000Z','rule':'ORIGINAL',...directBarEvidence(bars)}};
  test('new decision evidence preserves all 1000 analysis bars and immutable original',(){
    final bars=rows(1000),event=decision(bars),saved=DirectDecisionRecord.read(event);
    expect(saved.bars.length,1000);expect(saved.completeSource,true);
    (event['evidence'] as Map)['rule']='changed later';
    saved.original['evidence']['rule']='another alias';
    expect(saved.original['evidence']['rule'],'ORIGINAL');
    expect(()=>saved.bars.clear(),throwsUnsupportedError);
  });
  test('legacy truncated source stays partial and is not silently reconstructed',(){
    final event=decision(rows(200));final evidence=event['evidence'] as Map;
    evidence.remove('sourceWindow');evidence['bars']=(evidence['bars'] as List).sublist(80);
    final saved=DirectDecisionRecord.read(event);expect(saved.completeSource,false);expect(saved.bars.length,120);
  });
  test('replay rejects forged source counts and future or incomplete bars',(){
    final event=decision(rows(200));event['evidence']['sourceWindow']['count']=120;
    expect(()=>DirectDecisionRecord.read(event),throwsFormatException);
    final future=decision(rows(10));future['at']='2026-10-13T14:09:30Z';future['evidence']['recordedAt']=future['at'];
    expect(()=>DirectDecisionRecord.read(future),throwsFormatException);
  });
  test('replay rejects out of order and malformed OHLCV without fabricated fallback',(){
    final event=decision(rows(5));(event['evidence']['bars'] as List).insert(1,event['evidence']['bars'][0]);
    expect(()=>DirectDecisionRecord.read(event),throwsFormatException);
    final bad=decision(rows(5));bad['evidence']['bars'][0]['h']=1;
    expect(()=>DirectDecisionRecord.read(bad),throwsFormatException);
  });
}
