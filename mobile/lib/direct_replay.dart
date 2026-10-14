import 'dart:math' as math;
import 'dart:convert';
import 'direct_alpaca.dart';
import 'market_indicators.dart';
import 'market_geometry.dart';
import 'observed_bar_archive.dart';
import 'demo/wave_analysis.dart';

/// The entire bounded source used by the decision, including indicator warmup.
/// Never truncate independently of the analysis window.
Map<String,dynamic> directBarEvidence(List<MarketBar> rows)=>{
  'sourceWindow':{'version':1,'count':rows.length,
    'firstAt':rows.isEmpty?null:rows.first.time.toUtc().toIso8601String(),
    'lastAt':rows.isEmpty?null:rows.last.time.toUtc().toIso8601String()},
  'bars':[for(final b in rows){'at':b.time.toUtc().toIso8601String(),
    'o':b.open,'h':b.high,'l':b.low,'c':b.close,'v':b.volume}],
};

/// Read-only replay of saved observations. No network, generated prices or
/// recalculated decision reason; older truncated evidence remains explicit.
class DirectDecisionRecord {
  final String originalJson;
  final List<MarketBar> bars;
  final bool completeSource;
  const DirectDecisionRecord._(this.originalJson,this.bars,this.completeSource);
  Map<String,dynamic> get original=>jsonDecode(originalJson) as Map<String,dynamic>;
  factory DirectDecisionRecord.read(Map<String,dynamic> event,{ObservedBarArchive? archive}) {
    try {
      final frozen=jsonEncode(event),copy=jsonDecode(frozen) as Map<String,dynamic>;
      final evidence=copy['evidence'] as Map? ?? {};
      final at=DateTime.parse(copy['at'] as String);
      final raw=evidence.containsKey('barReference')?
        (archive??(throw const FormatException('Referenced source is unavailable'))).resolve(copy['symbol'] as String,Map<String,dynamic>.from(evidence),at):
        evidence['bars'] as List? ?? [];
      if(raw.length>1000)throw const FormatException('Source window exceeds limit');
      final recorded=evidence['recordedAt']==null?at:DateTime.parse(evidence['recordedAt'] as String);
      if(recorded.isAfter(at))throw const FormatException('Evidence after decision');
      final bars=<MarketBar>[];
      for(final value in raw) {
        final row=Map<String,dynamic>.from(value as Map);
        final time=DateTime.parse(row['at'] as String).toUtc();
        final b=MarketBar.parse({...row,'t':time.millisecondsSinceEpoch});
        if(b.time.add(const Duration(minutes:1)).isAfter(recorded)||
          (bars.isNotEmpty&&!b.time.isAfter(bars.last.time))) {
          throw const FormatException('Incomplete, future or unordered observation');
        }
        bars.add(b);
      }
      final window=evidence['sourceWindow'] as Map?;
      final complete=window?['version']==1&&window?['count']==bars.length&&bars.isNotEmpty&&
        window?['firstAt']==bars.first.time.toIso8601String()&&window?['lastAt']==bars.last.time.toIso8601String();
      if(window!=null&&!complete&&!(bars.isEmpty&&window['version']==1&&window['count']==0&&window['firstAt']==null&&window['lastAt']==null)) {
        throw const FormatException('Source window mismatch');
      }
      return DirectDecisionRecord._(frozen,List.unmodifiable(bars),complete);
    } catch(_) {
      throw const FormatException('Saved decision observations are unavailable or invalid');
    }
  }
}

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
ChartWaveView directWaveView(List<MarketBar> rows) {
  if(rows.isEmpty)return ChartWaveView(-1,const [],const []);
  final bars=[for(var i=0;i<rows.length;i++)rows[i].candle(i)];
  final journal=ChartWaveJournal()..append(bars);
  return journal.view(bars.last.tick);
}

Map<String,dynamic> directResearchSnapshot(List<MarketBar> rows,{ChartWaveView? archivedWaves,Map<String,dynamic>? archiveOrigin}) {
  final bars=[for(var i=0;i<rows.length;i++)rows[i].candle(i)];
  if(bars.length<35)return {'version':'direct-research-v4','indicatorContract':marketIndicatorContract,'geometryContract':marketGeometryContract,'status':'INSUFFICIENT_OBSERVED_BARS','executable':false};
  final waves=archivedWaves??directWaveView(rows);
  final geometry=MarketGeometry.confirmedPivots(rows);
  return {'version':'direct-research-v4','indicatorContract':marketIndicatorContract,'geometryContract':marketGeometryContract,'status':'OBSERVED_SHADOW','executable':false,
    'firstObservedAt':rows.first.time.toUtc().toIso8601String(),'lastObservedAt':rows.last.time.toUtc().toIso8601String(),
    if(archiveOrigin!=null)'waveArchiveOrigin':archiveOrigin,
    'waveCandidates':[for(final s in waves.active)s.toJson()],
    'waveEvents':[for(final e in waves.events)e.toJson()],
    'primaryWaveId':waves.primary?.id,'alternateWaveId':waves.alternate?.id,
    'indicators':MarketIndicators.summary(rows),
    'harmonics':MarketGeometry.harmonics(geometry),
    'classicalPatterns':MarketGeometry.classicPatterns(geometry,rows.last.close),
    'divergences':[for(final minutes in [1,5,15]) ...(() {
      final frame=directTimeframe(rows,minutes);
      return [for(final d in MarketIndicators.divergences(frame))
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
