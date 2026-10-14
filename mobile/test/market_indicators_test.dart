import 'dart:convert';
import 'dart:io';
import 'package:flutter_test/flutter_test.dart';
import 'package:options_ai_trader/direct_alpaca.dart';
import 'package:options_ai_trader/direct_replay.dart';
import 'package:options_ai_trader/market_indicators.dart';

void closeTree(Object? actual,Object? expected) {
  if(expected is Map) {
    expect(actual,isA<Map>());expect((actual as Map).keys.toSet(),expected.keys.toSet());
    for(final key in expected.keys){closeTree(actual[key],expected[key]);}
  }else if(expected is List) {
    expect(actual,isA<List>());expect((actual as List).length,expected.length);
    for(var i=0;i<expected.length;i++){closeTree(actual[i],expected[i]);}
  }else if(expected is num) {expect(actual,closeTo(expected,1e-9));}
  else {expect(actual,expected);}
}
void main() {
  final fixture=jsonDecode(File('test/fixtures/indicator_contract_v1.json').readAsStringSync()) as Map;
  for(final raw in fixture['cases'] as List) {
    final c=raw as Map;
    final bars=[for(final b in c['bars'] as List)MarketBar.parse({...Map<String,dynamic>.from(b as Map),
      't':DateTime.parse(b['at'] as String).millisecondsSinceEpoch})];
    test('Python/Dart indicator contract: ${c['name']}',() {
      expect(fixture['contract'],marketIndicatorContract);closeTree(MarketIndicators.series(bars),c['expected']);
    });
    test('all observed prefixes preserve indicator warmup and original values: ${c['name']}',() {
      final full=MarketIndicators.series(bars);
      for(var end=1;end<=bars.length;end++) {
        final short=MarketIndicators.series(bars.take(end).toList());
        for(final key in full.keys) {
          if(full[key] is Map) {
            for(final sub in (full[key] as Map).keys){closeTree(short[key][sub],(full[key][sub] as List).take(end).toList());}
          }else {closeTree(short[key],(full[key] as List).take(end).toList());}
        }
      }
    });
    if(bars.length>=35) {
      test('saved Direct snapshot uses canonical indicator values: ${c['name']}',() {
      final snapshot=directResearchSnapshot(bars),expected=c['expected'] as Map;
      expect(snapshot['version'],'direct-research-v4');expect(snapshot['indicatorContract'],marketIndicatorContract);
      closeTree(snapshot['indicators']['rsi14'],expected['rsi14'].last);
      closeTree(snapshot['indicators']['atr14'],expected['atr14'].last);
      closeTree(snapshot['indicators']['ema20'],expected['ema20'].last);
      closeTree(snapshot['indicators']['vwap'],expected['vwap_utc_day'].last);
      });
    }
  }
  test('known seed, flat RSI and zero-volume availability',() {
    expect(MarketIndicators.ema([1,2,3,4],3),[null,null,2,3]);
    expect(MarketIndicators.rsi(List.filled(20,10.0)).last,50);
    expect(()=>MarketIndicators.ema([double.nan],1),throwsFormatException);
    expect(()=>MarketIndicators.macd([1,2],fast:26,slow:12),throwsFormatException);
    expect(()=>MarketIndicators.series([]),throwsFormatException);
  });
  test('reversed/repeated or malformed bars fail closed',() {
    final now=DateTime.utc(2026,10,13,15),b=MarketBar(DateTime.utc(2026,10,13,15),100,101,99,100,10);
    expect(()=>MarketIndicators.series([b,b]),throwsFormatException);
    expect(()=>MarketIndicators.series([MarketBar(now,100,99,98,100,10)]),throwsFormatException);
    expect(()=>MarketIndicators.series([MarketBar(now,100,101,99,100,-1)]),throwsFormatException);
  });
}
