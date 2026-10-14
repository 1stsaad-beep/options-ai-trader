import 'dart:convert';
import 'observed_option_replay.dart';

/// Append-only observations, independent of execution authority and balances.
/// Bounded segments retain originals; reaching capacity never evicts history.
class OptionObservationArchive {
  static const maxObservations=20000,maxBytes=8*1024*1024,segmentSize=1000;
  final Map<String,dynamic> _state;
  static String? _verified;
  OptionObservationArchive._(this._state);
  static String _identity(Map o) {
    final q=o['quote'] as Map;
    return jsonEncode([o['account'],o['source'],q['contract'],q['feed'],observationStamp(q['at']).toIso8601String(),q['bid'],q['ask'],q['bidSize'],q['askSize']]);
  }
  factory OptionObservationArchive.read(Object? value) {
    final state=value==null?{'version':1,'segments':<dynamic>[]}:jsonDecode(jsonEncode(value));
    final encoded=jsonEncode(state);
    if(encoded.length>maxBytes||utf8.encode(encoded).length>maxBytes)throw const FormatException('Option archive capacity exceeded');
    if(encoded!=_verified) {
      if(state is! Map<String,dynamic>||state.length!=2||state['version']!=1||state['segments'] is! List)throw const FormatException('Invalid option archive');
      final segments=state['segments'] as List,ids=<String>{};DateTime? prior;var count=0;
      for(var i=0;i<segments.length;i++) {
        final rows=segments[i];
        if(rows is! List||rows.isEmpty||rows.length>segmentSize||(i<segments.length-1&&rows.length!=segmentSize))throw const FormatException('Invalid option archive segment');
        for(final o in rows) {
          final at=readOptionObservation(o).captured;
          if((prior!=null&&at.isBefore(prior))||!ids.add(_identity(o as Map)))throw const FormatException('Repeated or reordered option observation');
          prior=at;if(++count>maxObservations)throw const FormatException('Option archive capacity exceeded');
        }
      }
      _verified=encoded;
    }
    return OptionObservationArchive._(state as Map<String,dynamic>);
  }
  Map<String,dynamic> toJson()=>jsonDecode(jsonEncode(_state)) as Map<String,dynamic>;
  List<Map<String,dynamic>> get observations=>[
    for(final segment in toJson()['segments'] as List)...(segment as List).cast<Map<String,dynamic>>(),
  ];
  Map<String,dynamic>? append(List<Map<String,dynamic>> additions) {
    if(additions.isEmpty)return null;
    final next=toJson(),segments=next['segments'] as List,ids={for(final o in observations)_identity(o)};
    var changed=false;
    for(final o in additions) {
      readOptionObservation(o);
      if(!ids.add(_identity(o)))continue; // The first actual capture remains authoritative.
      if(segments.isEmpty||(segments.last as List).length==segmentSize)segments.add(<dynamic>[]);
      (segments.last as List).add(jsonDecode(jsonEncode(o)));changed=true;
    }
    return changed?OptionObservationArchive.read(next).toJson():null;
  }
}
