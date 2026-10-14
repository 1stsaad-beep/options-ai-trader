import 'dart:convert';
import 'direct_alpaca.dart';
import 'observed_option_replay.dart' show observationStamp;

/// Original observations shared by new decisions. A pointer proves neither
/// provider authenticity nor ledger integrity; it only resolves saved evidence.
/// Old inline receipts are never migrated or rewritten by this archive.
class ObservedBarArchive {
  static const maxBars=50000,maxBytes=8*1024*1024;
  final Map<String,dynamic> _state;
  static String? _verified;
  ObservedBarArchive._(this._state);
  static Map<String,dynamic> _copy(Object value)=>jsonDecode(jsonEncode(value)) as Map<String,dynamic>;
  static void _keys(dynamic value,Set<String> keys) {
    if(value is! Map||value.length!=keys.length||!value.keys.toSet().containsAll(keys))throw const FormatException('Invalid bar archive shape');
  }
  static String _source(Map evidence) {
    if(!['fixture','alpaca'].contains(evidence['source'])||!['iex','sip'].contains(evidence['feed'])||
      !['regular','extended'].contains(evidence['session'])){throw const FormatException('Unknown bar source');}
    return '${evidence['source']}|${evidence['feed']}|${evidence['session']}';
  }
  static void _symbol(dynamic symbol) {
    if(symbol is! String||!RegExp(r'^[A-Z]{1,6}$').hasMatch(symbol))throw const FormatException('Invalid bar symbol');
  }
  static MarketBar _bar(dynamic value) {
    if(value is! List||value.length!=6||value.first is! int)throw const FormatException('Invalid compact bar');
    return MarketBar.parse({'t':value[0],'o':value[1],'h':value[2],'l':value[3],'c':value[4],'v':value[5]});
  }
  static List<num> _compact(MarketBar b)=>[b.time.millisecondsSinceEpoch,b.open,b.high,b.low,b.close,b.volume];
  static bool _same(List a,List b) {
    for(var i=0;i<6;i++){if(a[i]!=b[i])return false;}return true;
  }
  factory ObservedBarArchive.read(Object? value) {
    final state=value==null?<String,dynamic>{'version':1,'epochs':<dynamic>[]}:_copy(value);
    final encoded=jsonEncode(state);
    if(encoded.length>maxBytes||utf8.encode(encoded).length>maxBytes)throw const FormatException('Bar archive capacity exceeded');
    if(encoded!=_verified) {
      _keys(state,{'version','epochs'});
      if(state['version']!=1||state['epochs'] is! List)throw const FormatException('Invalid bar archive');
      var count=0,sequence=0;
      for(final e in state['epochs'] as List) {
        _keys(e,{'sequence','symbol','source','rows','captures'});_symbol(e['symbol']);
        if(e['sequence'] is! int||e['sequence']!=++sequence||e['source'] is! String||
          !RegExp(r'^(fixture|alpaca)\|(iex|sip)\|(regular|extended)$').hasMatch(e['source'] as String)||
          e['rows'] is! List||e['captures'] is! List){throw const FormatException('Invalid bar epoch');}
        final rows=e['rows'] as List,captures=e['captures'] as List;
        if(rows.isEmpty||captures.isEmpty||(count+=rows.length)>maxBars)throw const FormatException('Bar archive capacity exceeded');
        DateTime? prior;
        for(final row in rows) {
          final b=_bar(row);
          if(prior!=null&&!b.time.isAfter(prior))throw const FormatException('Unordered bars');
          prior=b.time;
        }
        var through=0;DateTime? captured;
        for(final c in captures) {
          _keys(c,{'through','at'});
          if(c['through'] is! int||c['through']<=through||c['through']>rows.length)throw const FormatException('Invalid capture range');
          final at=observationStamp(c['at']);
          if((captured!=null&&at.isBefore(captured))||_bar(rows[(c['through'] as int)-1]).time.add(const Duration(minutes:1)).isAfter(at)) {
            throw const FormatException('Future or reordered capture');
          }
          captured=at;through=c['through'] as int;
        }
        if(through!=rows.length)throw const FormatException('Missing bar capture');
      }
      _verified=encoded;
    }
    return ObservedBarArchive._(state);
  }
  Map<String,dynamic> toJson()=>_copy(_state);

  /// Validate only observations actually supplied by this decision. Missing
  /// minutes stay missing; source revisions begin another immutable epoch.
  ({ObservedBarArchive archive,Map<String,dynamic> reference}) capture(String symbol,Map<String,dynamic> evidence,DateTime eventAt) {
    _symbol(symbol);final source=_source(evidence),at=observationStamp(evidence['recordedAt']);
    if(at.isAfter(eventAt)||evidence.containsKey('barReference'))throw const FormatException('Invalid capture time or competing source');
    final raw=evidence['bars'];
    if(raw is! List||raw.isEmpty||raw.length>1000)throw const FormatException('Invalid source window');
    final incoming=<List<num>>[];DateTime? prior;
    for(final row in raw) {
      _keys(row,{'at','o','h','l','c','v'});
      final time=observationStamp(row['at']);
      if(time.microsecondsSinceEpoch%60000000!=0)throw const FormatException('Invalid minute');
      final b=MarketBar.parse({...Map<String,dynamic>.from(row as Map),'t':time.millisecondsSinceEpoch});
      if(b.time.add(const Duration(minutes:1)).isAfter(at)||(prior!=null&&!b.time.isAfter(prior)))throw const FormatException('Incomplete or unordered source');
      incoming.add(_compact(b));prior=b.time;
    }
    _window(evidence['sourceWindow'],incoming);
    final next=toJson(),epochs=next['epochs'] as List;
    Map<String,dynamic>? epoch;
    for(final candidate in epochs.reversed) {
      if(candidate['symbol']==symbol){if(candidate['source']==source)epoch=candidate as Map<String,dynamic>;break;}
    }
    var start=-1;
    if(epoch!=null) {
      final rows=epoch['rows'] as List;
      start=rows.indexWhere((row)=>row[0]==incoming.first[0]);
      // A genuinely contiguous new window can extend the original epoch too.
      if(start<0&&incoming.first[0]==rows.last[0]+60000)start=rows.length;
      if(start>=0) {
        for(var i=0;i<incoming.length&&start+i<rows.length;i++) {
          if(!_same(incoming[i],rows[start+i] as List)){start=-1;break;}
        }
      }
    }
    if(start<0) {
      epoch={'sequence':epochs.length+1,'symbol':symbol,'source':source,'rows':<dynamic>[], 'captures':<dynamic>[]};
      epochs.add(epoch);start=0;
    }
    final rows=epoch!['rows'] as List;
    if(start+incoming.length>rows.length) {
      rows.addAll(incoming.skip(rows.length-start));
      (epoch['captures'] as List).add({'through':rows.length,'at':at.toIso8601String()});
    }
    final archive=ObservedBarArchive.read(next);
    final reference=<String,dynamic>{'version':1,'symbol':symbol,'source':source,
      'epoch':epoch['sequence'],'start':start,'count':incoming.length,'knownAt':at.toIso8601String()};
    archive.resolve(symbol,{...evidence,'barReference':reference}..remove('bars'),eventAt);
    return (archive:archive,reference:reference);
  }
  static void _window(dynamic value,List rows) {
    _keys(value,{'version','count','firstAt','lastAt'});
    if(value['version']!=1||value['count'] is! int||value['count']!=rows.length||rows.isEmpty||
      observationStamp(value['firstAt']).millisecondsSinceEpoch!=rows.first[0]||
      observationStamp(value['lastAt']).millisecondsSinceEpoch!=rows.last[0]||
      observationStamp(value['firstAt']).microsecondsSinceEpoch%60000000!=0||
      observationStamp(value['lastAt']).microsecondsSinceEpoch%60000000!=0){throw const FormatException('Source window mismatch');}
  }
  List<Map<String,dynamic>> resolve(String symbol,Map<String,dynamic> evidence,DateTime eventAt) {
    final ref=evidence['barReference'];_keys(ref,{'version','symbol','source','epoch','start','count','knownAt'});
    final at=observationStamp(evidence['recordedAt']);
    if(evidence.containsKey('bars')||ref['version']!=1||ref['symbol']!=symbol||ref['source']!=_source(evidence)||
      ref['epoch'] is! int||ref['epoch']<1||ref['epoch']>maxBars||ref['start'] is! int||ref['start']<0||ref['start']>maxBars||ref['count'] is! int||ref['count']<1||ref['count']>1000||
      !observationStamp(ref['knownAt']).isAtSameMomentAs(at)||at.isAfter(eventAt)){throw const FormatException('Invalid source reference');}
    final epochs=_state['epochs'] as List,index=(ref['epoch'] as int)-1;
    if(index<0||index>=epochs.length)throw const FormatException('Missing source epoch');
    final e=epochs[index] as Map,rows=e['rows'] as List,start=ref['start'] as int,end=start+(ref['count'] as int);
    if(e['symbol']!=symbol||e['source']!=ref['source']||start>rows.length||end>rows.length)throw const FormatException('Source reference mismatch');
    var prior=0;
    for(final c in e['captures'] as List) {
      if(prior<end&&c['through']>start&&observationStamp(c['at']).isAfter(at))throw const FormatException('Source first known after decision');
      prior=c['through'] as int;
    }
    final selected=rows.sublist(start,end);_window(evidence['sourceWindow'],selected);
    return [for(final row in selected){'at':_bar(row).time.toIso8601String(),'o':row[1],'h':row[2],'l':row[3],'c':row[4],'v':row[5]}];
  }
}
