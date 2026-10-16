import 'direct_alpaca.dart';
import 'market_strategy.dart';
import 'paper_time.dart';

const strategyReplayContract='observed-strategy-comparison-v1';

/// This comparison uses the current named contract on an original bar prefix.
/// It does not rewrite the original decision or claim earlier data availability.
Map<String,dynamic> compareStrategies(dynamic query) {
  final base=<String,dynamic>{'version':strategyReplayContract,'strategyContract':marketStrategyContract,
    'counterfactual':true,'executionAllowed':false,'externalOrder':false,'pnlCents':null,'historicalAvailabilityVerified':false};
  try {
    const keys={'account','symbol','source','capturedAt','bars','cursor'};
    if(query is! Map||query.length!=keys.length||!query.keys.every(keys.contains))throw const FormatException('query');
    final account=query['account'],symbol=query['symbol'],raw=query['bars'],cursor=query['cursor'];
    if(account is! String||account.isEmpty||account.runes.length>120||account.trim()!=account||
      symbol is! String||!RegExp(r'^[A-Z][A-Z0-9.]{0,9}$').hasMatch(symbol)||!['alpaca','fixture'].contains(query['source'])||
      raw is! List||raw.isEmpty||raw.length>1000||cursor is! int||cursor<0||cursor>=raw.length)throw const FormatException('identity');
    final captured=observationStamp(query['capturedAt']);
    final rows=<MarketBar>[];
    for(final row in raw) {
      const fields={'at','o','h','l','c','v'};
      if(row is! Map||row.length!=fields.length||!row.keys.every(fields.contains))throw const FormatException('bar');
      for(final key in ['o','h','l','c','v']) {
        final value=row[key];
        if(value is! num||!value.isFinite||value.abs()>1e12)throw const FormatException('bounded numeric bar');
      }
      final at=observationStamp(row['at']);
      if(at.second!=0||at.millisecond!=0||at.microsecond!=0||at.add(const Duration(minutes:1)).isAfter(captured)||
        (rows.isNotEmpty&&!at.isAfter(rows.last.time)))throw const FormatException('clock');
      rows.add(MarketBar.parse({...Map<String,dynamic>.from(row),'t':at.millisecondsSinceEpoch}));
    }
    final prefix=rows.take(cursor+1).toList();
    return {...base,'status':'COMPARED','account':account,'symbol':symbol,'source':query['source'],
      'capturedAt':captured.toIso8601String(),'prefixCount':prefix.length,
      'prefixEndsAt':prefix.last.time.add(const Duration(minutes:1)).toIso8601String(),
      'signals':{for(final strategy in marketStrategies)strategy:MarketSignal.analyze(prefix,strategy:strategy).toJson()}};
  } catch(_) {return {...base,'status':'INVALID_OBSERVED_SOURCE'};}
}
