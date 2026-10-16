import 'dart:convert';
import 'dart:io';
import 'package:flutter_test/flutter_test.dart';
import 'package:options_ai_trader/direct_alpaca.dart';
import 'package:options_ai_trader/market_strategy.dart';
import 'package:options_ai_trader/strategy_replay.dart';

void main() {
  final fixture=jsonDecode(File('test/fixtures/market_strategy_v1.json').readAsStringSync()) as Map;
  for(final c in fixture['cases'] as List) {
    test('shared observed strategy every causal prefix: ${c['name']}',(){
      expect(fixture['contract'],marketStrategyContract);
      final rows=[for(final b in c['bars'] as List)MarketBar.parse({...Map<String,dynamic>.from(b as Map),'t':DateTime.parse(b['at'] as String).millisecondsSinceEpoch})];
      for(var end=1;end<=rows.length;end++) {
        final prefix=rows.take(end).toList();
        expect({for(final strategy in marketStrategies)strategy:MarketSignal.analyze(prefix,strategy:strategy).toJson()},c['prefixes'][end-1]);
      }
      expect(MarketSignal.analyze(rows,strategy:'missing').reason,'UNSUPPORTED_STRATEGY');
    });
  }
  Map<String,dynamic> query()=>{'account':'mp-fixture','symbol':'NVDA','source':'fixture','capturedAt':'2026-10-13T15:30:00.000Z',
    'bars':jsonDecode(jsonEncode(fixture['cases'][0]['bars'])),'cursor':40};
  test('comparison consumes only the cursor prefix and retains original input',(){
    final q=query(),original=jsonEncode(query()),result=compareStrategies(q);
    expect(result['status'],'COMPARED');expect(result['signals'],fixture['cases'][0]['prefixes'][40]);
    expect(result['prefixCount'],41);expect(result['executionAllowed'],false);expect(result['pnlCents'],isNull);
    expect(result['historicalAvailabilityVerified'],false);expect(jsonEncode(q),original);
    (q['bars'] as List).last.addAll({'o':1000,'h':1001,'l':999,'c':1000});
    expect(compareStrategies(q),result);
    expect(MarketSignal.greater(100+1e-8,100),false);expect(MarketSignal.greater(100+1e-6,100),true);
  });
  test('invalid source never produces signals',(){
    final changes=<void Function(Map<String,dynamic>)>[
      (q)=>q['cursor']=true,(q)=>q['cursor']=-1,(q)=>q['cursor']=1000,(q)=>q['bars']=[],
      (q)=>q['source']='indicative',(q)=>q['account']=' ',(q)=>q['symbol']='../NVDA',(q)=>q['executionAllowed']=true,
      (q)=>q['capturedAt']='2026-10-13T14:00:00Z',(q)=>q['capturedAt']='2026-02-30T15:30:00Z',
      (q)=>q['bars'][0]['c']=true,(q)=>q['bars'][0]['c']=1e300,(q)=>q['bars'][0]['c']=500,(q)=>q['bars'][0]['v']=-1,
      (q)=>q['bars'][0]['at']=q['bars'][1]['at'],(q)=>q['bars'][0]['at']='2026-10-13T14:00:00',
      (q)=>q['bars'][0]['at']='2026-10-13T14:00:00.000001Z',(q)=>q['bars'][0]['assumed']=true,
    ];
    for(final change in changes) {
      final q=query();change(q);final result=compareStrategies(q);
      expect(result['status'],'INVALID_OBSERVED_SOURCE');expect(result.containsKey('signals'),false);expect(result['executionAllowed'],false);
    }
  });
}
