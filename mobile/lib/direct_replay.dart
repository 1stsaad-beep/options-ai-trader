import 'dart:math' as math;
import 'direct_alpaca.dart';
import 'demo/chart_analysis.dart';
import 'demo/wave_analysis.dart';

/// UTC-anchored complete intervals only. Missing minutes never become candles.
List<MarketBar> directTimeframe(List<MarketBar> rows,int minutes) {
  if(![1,5,15,60].contains(minutes))throw ArgumentError('timeframe');
  if(minutes==1)return List.unmodifiable(rows);
  final groups=<int,List<MarketBar>>{};
  for(final b in rows){final bucket=b.time.toUtc().millisecondsSinceEpoch~/(minutes*60000);(groups[bucket]??=[]).add(b);}
  final result=<MarketBar>[];
  for(final entry in groups.entries) {
    final bars=entry.value,start=entry.key*minutes*60000;
    if(bars.length!=minutes)continue;
    var complete=true;
    for(var i=0;i<bars.length;i++){if(bars[i].time.toUtc().millisecondsSinceEpoch!=start+i*60000)complete=false;}
    if(!complete)continue;
    result.add(MarketBar(DateTime.fromMillisecondsSinceEpoch(start,isUtc:true),bars.first.open,
      bars.map((b)=>b.high).reduce(math.max),bars.map((b)=>b.low).reduce(math.min),bars.last.close,
      bars.fold<double>(0,(s,b)=>s+b.volume)));
  }
  return List.unmodifiable(result);
}

/// A contemporaneous research snapshot, never an execution permission.
Map<String,dynamic> directResearchSnapshot(List<MarketBar> rows) {
  final bars=[for(var i=0;i<rows.length;i++)rows[i].candle(i)];
  if(bars.length<35)return {'version':'direct-research-v1','status':'INSUFFICIENT_OBSERVED_BARS','executable':false};
  final internal=ChartWaveAnalysis.candidates(DemoChartAnalysis.pivots(bars),degree:'internal');
  final main=ChartWaveAnalysis.candidates(DemoChartAnalysis.pivots(bars,radius:5));
  final waves=[...main,...internal,...ChartWaveAnalysis.nestedThirds(main,internal)];
  return {'version':'direct-research-v1','status':'OBSERVED_SHADOW','executable':false,
    'firstObservedAt':rows.first.time.toUtc().toIso8601String(),'lastObservedAt':rows.last.time.toUtc().toIso8601String(),
    'waveCandidates':[for(final s in waves)s.toJson()],
    'indicators':DemoChartAnalysis.summary(bars),
    'harmonics':[for(final h in DemoChartAnalysis.harmonics(DemoChartAnalysis.pivots(bars)))
      {'name':h.name,'points':[for(final p in h.points)[p.index,p.confirmedAt,p.price]],'przLow':h.przLow,'przHigh':h.przHigh,'invalidation':h.invalidation}],
    'divergences':[for(final minutes in [1,5,15]) ...(() {
      final frame=directTimeframe(rows,minutes);
      final candles=[for(var i=0;i<frame.length;i++)frame[i].candle(i)];
      return [for(final d in DemoChartAnalysis.divergenceSegments(candles))
        {'timeframeMinutes':minutes,'label':d.label,'knownAt':frame[d.confirmedAt].time.toUtc().toIso8601String(),
          'first':[frame[d.first.index].time.toUtc().toIso8601String(),d.first.price,d.firstValue],
          'second':[frame[d.second.index].time.toUtc().toIso8601String(),d.second.price,d.secondValue]}];
    })()],
  };
}

List<Map<String,dynamic>> directTradeMarkers(List<MarketBar> rows,int minutes,String symbol,List<Map<String,dynamic>> events) {
  final markers=<Map<String,dynamic>>[];
  for(final event in events) {
    if(event['symbol']!=symbol||event['fill'] is! Map)continue;
    final observed=DateTime.tryParse('${event['evidence']?['observation']}');
    if(observed==null)continue;
    final index=rows.indexWhere((b)=>!observed.isBefore(b.time)&&observed.isBefore(b.time.add(Duration(minutes:minutes))));
    if(index<0)continue;
    markers.add({'tick':index,'label':'${event['fill']['side']=='BUY'?'دخول/تعزيز':'خروج'} ×${event['fill']['quantity']}',
      'decision':event['decision'],'optionPriceCents':event['fill']['price'],'original':event});
  }
  return markers;
}
