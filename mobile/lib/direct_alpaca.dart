import 'dart:convert';
import 'package:flutter/services.dart';
import 'demo/chart_analysis.dart';

class MarketBar {
  final DateTime time;
  final double open, high, low, close, volume;
  const MarketBar(this.time,this.open,this.high,this.low,this.close,this.volume);
  factory MarketBar.parse(Map<String,dynamic> j) {
    final v=[for(final k in ['o','h','l','c','v']) (j[k] as num).toDouble()];
    if(v.any((n)=>!n.isFinite)||v[2]<=0||v[1]<v[0]||v[1]<v[3]||v[2]>v[0]||v[2]>v[3]||v[4]<0) {
      throw const FormatException('Invalid OHLCV');
    }
    final t=DateTime.fromMillisecondsSinceEpoch(j['t'] as int,isUtc:true);
    if(t.millisecondsSinceEpoch%60000!=0) throw const FormatException('Invalid minute');
    return MarketBar(t,v[0],v[1],v[2],v[3],v[4]);
  }
  DemoCandle candle(int index)=>DemoCandle(index,open,high,low,close,volume);
}

class DirectSnapshot {
  final bool connected, enabled;
  final String feed, session, source, reason;
  final DateTime received;
  final Map<String,List<MarketBar>> series;
  final List<Map<String,dynamic>> events;
  DirectSnapshot({this.connected=false,this.enabled=false,this.feed='iex',this.session='regular',
    this.source='none',this.reason='DISABLED',DateTime? received,this.series=const {},this.events=const []})
      :received=received??DateTime.fromMillisecondsSinceEpoch(0,isUtc:true);
  factory DirectSnapshot.parse(String text) {
    final j=jsonDecode(text) as Map<String,dynamic>;
    if(!['iex','sip'].contains(j['feed'])||!['regular','extended'].contains(j['session']))throw const FormatException('Unknown feed');
    final series=<String,List<MarketBar>>{};
    for(final entry in (j['bars'] as Map<String,dynamic>).entries) {
      final byTime=<DateTime,MarketBar>{};
      for(final raw in entry.value as List) {final bar=MarketBar.parse(Map<String,dynamic>.from(raw as Map));byTime[bar.time]=bar;}
      series[entry.key]=byTime.values.toList()..sort((a,b)=>a.time.compareTo(b.time));
    }
    return DirectSnapshot(connected:j['connected']==true,enabled:j['enabled']==true,feed:j['feed'] as String,
      session:j['session'] as String,source:j['source'] as String,reason:j['reason'] as String,
      received:DateTime.fromMillisecondsSinceEpoch(j['asOf'] as int,isUtc:true),series:series,
      events:(j['events'] as List).map((e)=>Map<String,dynamic>.from(e as Map)).toList());
  }
  bool live(String symbol,DateTime now) {
    final rows=series[symbol];if(rows==null||rows.isEmpty)return false;
    final age=now.difference(rows.last.time).inMilliseconds,receipt=now.difference(received).inMilliseconds;
    return connected&&enabled&&source=='alpaca'&&age>=60000&&age<=150000&&receipt>=0&&receipt<=8000;
  }
  String label(String symbol,DateTime now)=>source=='mock'?'Mock • اصطناعية':
    live(symbol,now)?'LIVE • Alpaca ${feed.toUpperCase()}':source=='alpaca'?'Alpaca ${feed.toUpperCase()} • تاريخية/قديمة — ليست LIVE':'لا بيانات';
  bool validForDecision(String symbol,DateTime now) {
    final rows=series[symbol]??[];
    return live(symbol,now)&&rows.length>=35&&rows.last.time.difference(rows[rows.length-2].time).inSeconds==60;
  }
}

class OptionQuote {
  final String contract, feed;
  final DateTime time;
  final int bid,ask,bidSize,askSize;
  const OptionQuote(this.contract,this.feed,this.time,this.bid,this.ask,this.bidSize,this.askSize);
  factory OptionQuote.parse(String text){final j=jsonDecode(text) as Map<String,dynamic>;
    return OptionQuote(j['contract'] as String,j['feed'] as String,DateTime.fromMillisecondsSinceEpoch(j['t'] as int,isUtc:true),
      ((j['bid'] as num)*100).round(),((j['ask'] as num)*100).round(),j['bidSize'] as int,j['askSize'] as int);}
  static final pattern=RegExp(r'^([A-Z]{1,6})(\d{2})(\d{2})(\d{2})([CP])(\d{8})$');
  String get underlying=>pattern.firstMatch(contract)?.group(1)??'';
  String get direction=>pattern.firstMatch(contract)?.group(5)=='C'?'CALL':'PUT';
  bool valid(DateTime now,{int quantity=1}) {
    final match=pattern.firstMatch(contract);if(match==null)return false;
    final expiry=DateTime.utc(2000+int.parse(match[2]!),int.parse(match[3]!),int.parse(match[4]!));
    final today=DateTime.utc(now.year,now.month,now.day);
    final age=now.difference(time).inMilliseconds;
    return int.parse(match[3]!)==expiry.month&&int.parse(match[4]!)==expiry.day&&int.parse(match[6]!)>0&&
      feed=='opra'&&expiry.compareTo(today)>=0&&age>=0&&age<=30000&&bid>0&&ask>=bid&&
      ask-bid<=ask*.2&&quantity>0&&bidSize>=quantity&&askSize>=quantity;
  }
}

class DirectAlpaca {
  static const channel=MethodChannel('oat/alpaca_data');
  Future<bool> hasKeys() async=>await channel.invokeMethod<bool>('keyStatus')??false;
  Future<void> saveKeys(String id,String secret) async {await channel.invokeMethod<bool>('saveKeys',{'key':id,'secret':secret});}
  Future<void> secureScreen(bool enabled) async {await channel.invokeMethod<bool>('secureScreen',{'enabled':enabled});}
  Future<void> start(String feed,String session,List<String> symbols) async {await channel.invokeMethod<bool>('start',{'feed':feed,'session':session,'symbols':symbols});}
  Future<void> stop() async {await channel.invokeMethod<bool>('stop');}
  Future<DirectSnapshot> snapshot() async=>DirectSnapshot.parse((await channel.invokeMethod<String>('snapshot'))!);
  Future<bool> background() async=>await channel.invokeMethod<bool>('backgroundStatus')??false;
  Future<void> startBackground() async {await channel.invokeMethod<bool>('backgroundStart');}
  Future<OptionQuote?> quote(String contract) async {final text=await channel.invokeMethod<String>('quote',{'contract':contract});return text==null?null:OptionQuote.parse(text);}
}
