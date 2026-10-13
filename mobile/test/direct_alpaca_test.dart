import 'dart:convert';
import 'package:flutter_test/flutter_test.dart';
import 'package:options_ai_trader/direct_alpaca.dart';

final time=DateTime.utc(2026,10,13,15,1,15);
Map<String,dynamic> sample()=>{'connected':true,'enabled':true,'feed':'iex','session':'regular','source':'alpaca','reason':'CONNECTED','asOf':time.millisecondsSinceEpoch,
  'bars':{'NVDA':[{'t':DateTime.utc(2026,10,13,15).millisecondsSinceEpoch,'o':100,'h':102,'l':99,'c':101,'v':10}]},'events':[]};
void main(){
  test('LIVE requires source auth enabled receipt and closed fresh bar',(){
    expect(DirectSnapshot.parse(jsonEncode(sample())).live('NVDA',time),isTrue);
    for(final field in ['connected','enabled']){final j=sample()..[field]=false;expect(DirectSnapshot.parse(jsonEncode(j)).live('NVDA',time),isFalse);}
    expect(DirectSnapshot.parse(jsonEncode(sample()..['source']='mock')).label('NVDA',time),contains('اصطناعية'));
    expect(DirectSnapshot.parse(jsonEncode(sample())).live('NVDA',time.add(const Duration(seconds:9))),isFalse);
    expect(DirectSnapshot.parse(jsonEncode(sample())).live('NVDA',time.subtract(const Duration(minutes:1))),isFalse);
    expect(DirectSnapshot.parse(jsonEncode(sample())).live('AAPL',time),isFalse);
  });
  test('out of order bars merge and duplicate correction wins',(){final j=sample();final list=(j['bars'] as Map)['NVDA'] as List;
    list.add({...Map<String,int>.from(list.first as Map),'c':102});list.add({...Map<String,int>.from(list.first as Map),'t':DateTime.utc(2026,10,13,14,59).millisecondsSinceEpoch});
    final rows=DirectSnapshot.parse(jsonEncode(j)).series['NVDA']!;expect(rows.length,2);expect(rows.last.close,102);expect(rows.first.time,DateTime.utc(2026,10,13,14,59));});
  test('invalid OHLCV and unknown feed rejected',(){final j=sample();((j['bars'] as Map)['NVDA'] as List).first['h']=90;expect(()=>DirectSnapshot.parse(jsonEncode(j)),throwsFormatException);
    expect(()=>DirectSnapshot.parse(jsonEncode(sample()..['feed']='invented')),throwsFormatException);});
  test('stock bars never qualify as options; indicative stale crossed and invalid contracts rejected',(){
    OptionQuote q(String contract,String feed,DateTime t,int bid,int ask)=>OptionQuote(contract,feed,t,bid,ask,10,10);
    expect(q('NVDA261016C00200000','opra',time,200,210).valid(time),isTrue);
    expect(q('NVDA','opra',time,200,210).valid(time),isFalse);
    expect(q('NVDA261016C00200000','indicative',time,200,210).valid(time),isFalse);
    expect(q('NVDA261016C00200000','opra',time.subtract(const Duration(seconds:31)),200,210).valid(time),isFalse);
    expect(q('NVDA261016C00200000','opra',time.add(const Duration(seconds:1)),200,210).valid(time),isFalse);
    expect(q('NVDA261016C00200000','opra',time,220,210).valid(time),isFalse);
    expect(q('NVDA261016C00200000','opra',time,100,210).valid(time),isFalse);
    expect(q('NVDA270231C00200000','opra',time,200,210).valid(time),isFalse);
    expect(q('NVDA261012C00200000','opra',time,200,210).valid(time),isFalse);
  });
}
