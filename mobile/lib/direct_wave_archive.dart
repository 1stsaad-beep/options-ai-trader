import 'dart:convert';
import 'direct_alpaca.dart';
import 'demo/wave_analysis.dart';
import 'market_paper_policy.dart';

/// Original observation epochs. Rolling provider windows append to the same
/// origin; revisions/source changes/unexplained gaps seal the old epoch.
/// This bounded archive fails explicitly at capacity and never deletes history.
class DirectWaveArchive {
  static const maxBars=10000,maxBytes=8*1024*1024;
  final Map<String,dynamic> _state;
  static String? _verified;
  DirectWaveArchive._(this._state);
  factory DirectWaveArchive.read(Object? value) {
    final state=value==null?{'version':1,'symbols':<String,dynamic>{}}:jsonDecode(jsonEncode(value));
    final encoded=jsonEncode(state);
    if(encoded.length>maxBytes||utf8.encode(encoded).length>maxBytes)throw const FormatException('Wave archive capacity exceeded');
    if(encoded!=_verified) {
      if(state is! Map<String,dynamic>||state['version']!=1||state['symbols'] is! Map||state.length!=2)throw const FormatException('Invalid wave archive');
      var count=0;
      for(final entry in (state['symbols'] as Map).entries) {
        if(entry.key is! String||!RegExp(r'^[A-Z][A-Z0-9.]{0,9}$').hasMatch(entry.key as String)||entry.value is! List)throw const FormatException('Invalid archive symbol');
        var sequence=0;
        for(final raw in entry.value as List) {
          final e=raw as Map<String,dynamic>,times=e['times'] as List;
          if(e['sequence']!=++sequence||!['INITIAL','SOURCE_CHANGED','SOURCE_REVISED','OBSERVATION_GAP','ENGINE_CHANGED'].contains(e['boundary'])||
              e['source'] is! String||!RegExp(r'^(alpaca|fixture)\|(iex|sip)\|(regular|extended)$').hasMatch(e['source'] as String)||
              times.isEmpty||times.any((t)=>t is! int||t%60000!=0)) {
            throw const FormatException('Invalid archive epoch');
          }
          final captured=DateTime.parse(e['capturedAt'] as String).toUtc().millisecondsSinceEpoch;
          if((times.last as int)+60000>captured)throw const FormatException('Incomplete archive candle');
          for(var i=1;i<times.length;i++) {
            if(times[i]<=times[i-1]||!connected(DateTime.fromMillisecondsSinceEpoch(times[i-1] as int,isUtc:true),
                DateTime.fromMillisecondsSinceEpoch(times[i] as int,isUtc:true),e['source'] as String)) {
              throw const FormatException('Unordered or discontinuous archive source');
            }
          }
          final journal=ChartWaveJournal.restore(e['journal'] as Map<String,dynamic>);
          if(journal.latestTick!=times.length-1)throw const FormatException('Archive source/time mismatch');
          var through=-1,received=-1;
          for(final rawCapture in e['captures'] as List) {
            final c=rawCapture as Map,at=DateTime.parse(c['at'] as String).toUtc().millisecondsSinceEpoch;
            if(c['through'] is! int||c['through']<=through||c['through']>=times.length||at<received||
                at<(times[c['through'] as int] as int)+60000) {
              throw const FormatException('Archive capture chronology mismatch');
            }
            through=c['through'] as int;received=at;
          }
          if(through!=times.length-1||received!=captured)throw const FormatException('Missing original capture boundary');
          count+=times.length;
          if(count>maxBars)throw const FormatException('Wave archive capacity exceeded');
        }
      }
      _verified=encoded;
    }
    return DirectWaveArchive._(state as Map<String,dynamic>);
  }
  Map<String,dynamic> toJson()=>jsonDecode(jsonEncode(_state)) as Map<String,dynamic>;
  List<Map<String,dynamic>> epochs(String symbol)=>
    (jsonDecode(jsonEncode((_state['symbols'] as Map)[symbol]??[])) as List).cast<Map<String,dynamic>>();

  /// A regular-session overnight/weekend closure is a known time boundary,
  /// not an invented candle. Incomplete sessions and unknown calendars split.
  static bool connected(DateTime before,DateTime after,String source) {
    if(after.difference(before)==const Duration(minutes:1))return true;
    if(!source.endsWith('|regular')||after.difference(before).inDays>7)return false;
    final prior=paperSession(before),next=paperSession(after),local=paperNewYork(after);
    final opening=DateTime.utc(local.year,local.month,local.day,9,30).add(after.toUtc().difference(local));
    if(prior.closes==null||next.closes==null||before.add(const Duration(minutes:1))!=prior.closes||after!=opening)return false;
    final previous=paperNewYork(before);
    for(var day=DateTime.utc(previous.year,previous.month,previous.day,12).add(const Duration(days:1));
        day.isBefore(DateTime.utc(local.year,local.month,local.day,12));day=day.add(const Duration(days:1))) {
      if(paperSession(day).status!='NO_SESSION')return false;
    }
    return true;
  }

  Map<String,dynamic>? append(String symbol,String source,List<MarketBar> incoming,DateTime captured) {
    if(incoming.isEmpty)return null;
    if(!RegExp(r'^[A-Z][A-Z0-9.]{0,9}$').hasMatch(symbol)||!RegExp(r'^(alpaca|fixture)\|(iex|sip)\|(regular|extended)$').hasMatch(source))throw const FormatException('Source identity required');
    for(var i=0;i<incoming.length;i++) {
      final b=incoming[i];
      MarketBar.parse({'t':b.time.millisecondsSinceEpoch,'o':b.open,'h':b.high,'l':b.low,'c':b.close,'v':b.volume});
      if(b.time.add(const Duration(minutes:1)).isAfter(captured)||(i>0&&!b.time.isAfter(incoming[i-1].time)))throw const FormatException('Completed ordered source required');
    }
    final next=toJson(),symbols=next['symbols'] as Map;
    final history=(symbols[symbol]??=<dynamic>[]) as List;
    Map<String,dynamic>? current=history.isEmpty?null:history.last as Map<String,dynamic>;
    String? boundary=current==null?'INITIAL':current['source']!=source?'SOURCE_CHANGED':null;
    if(current!=null&&captured.isBefore(DateTime.parse(current['capturedAt'] as String))) {
      throw const FormatException('Wave capture clock moved backwards');
    }
    if(boundary==null&&(current!['journal'] as Map)['version']!=2)boundary='ENGINE_CHANGED';
    if(boundary==null) {
      final epoch=current!,times=epoch['times'] as List,old=(epoch['journal']['source'] as List);
      final byTime={for(var i=0;i<times.length;i++)times[i]:old[i]};
      for(final b in incoming) {
        final prior=byTime[b.time.millisecondsSinceEpoch];
        if(prior!=null&&jsonEncode((prior as List).skip(1).toList())!=jsonEncode([b.open,b.high,b.low,b.close,b.volume])) {
          boundary='SOURCE_REVISED';break;
        }
      }
    }
    var fresh=boundary==null?incoming.where((b)=>b.time.millisecondsSinceEpoch>(current!['times'] as List).last).toList():incoming;
    if(fresh.isEmpty)return null;
    var start=0;
    while(start<fresh.length) {
      if(boundary==null) {
        final last=DateTime.fromMillisecondsSinceEpoch((current!['times'] as List).last as int,isUtc:true);
        if(!connected(last,fresh[start].time,source))boundary='OBSERVATION_GAP';
      }
      if(boundary!=null) {
        current={'sequence':history.length+1,'source':source,'boundary':boundary,'times':<int>[],
          'capturedAt':captured.toUtc().toIso8601String(),'captures':<dynamic>[],'journal':ChartWaveJournal(strictMarket:true).toJson()};
        history.add(current);boundary=null;
      }
      var end=start+1;
      while(end<fresh.length&&connected(fresh[end-1].time,fresh[end].time,source)){end++;}
      final active=current!,times=active['times'] as List,journal=ChartWaveJournal.restore(active['journal'] as Map<String,dynamic>);
      final raw=active['journal']['source'] as List;
      final all=[for(var i=0;i<raw.length;i++)MarketBar(DateTime.fromMillisecondsSinceEpoch(times[i] as int,isUtc:true),
        (raw[i][1] as num).toDouble(),(raw[i][2] as num).toDouble(),(raw[i][3] as num).toDouble(),(raw[i][4] as num).toDouble(),(raw[i][5] as num).toDouble()),
        ...fresh.sublist(start,end)];
      journal.append([for(var i=0;i<all.length;i++)all[i].candle(i)]);
      times.addAll(fresh.sublist(start,end).map<int>((b)=>b.time.toUtc().millisecondsSinceEpoch));
      active['journal']=journal.toJson();active['capturedAt']=captured.toUtc().toIso8601String();
      (active['captures'] as List).add({'through':times.length-1,'at':captured.toUtc().toIso8601String()});
      start=end;if(start<fresh.length)boundary='OBSERVATION_GAP';
    }
    // Validate the entire proposed state before the caller's atomic CAS write.
    return DirectWaveArchive.read(next).toJson();
  }
  Map<String,dynamic>? latest(String symbol,String source) {
    final history=epochs(symbol);if(history.isEmpty||history.last['source']!=source)return null;
    return history.last;
  }
  ChartWaveView? view(String symbol,String source) {
    final e=latest(symbol,source);if(e==null)return null;
    final journal=ChartWaveJournal.restore(e['journal'] as Map<String,dynamic>);
    return journal.view(journal.latestTick!);
  }
}
