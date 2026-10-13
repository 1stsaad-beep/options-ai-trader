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
}
