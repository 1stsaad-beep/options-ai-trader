import 'direct_alpaca.dart';
import 'market_paper_policy.dart';

const observedOptionReplayVersion='observed-option-counterfactual-v1';
int _integer(dynamic value,[int min=0,int max=100000000]) {
  if(value is! int||value<min||value>max)throw const FormatException('Invalid integer');
  return value;
}
DateTime observationStamp(dynamic value) {
  if(value is! String||!RegExp(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?(Z|[+-]\d{2}:\d{2})$').hasMatch(value))throw const FormatException('Invalid timestamp');
  final local=value.substring(0,19),parsed=DateTime.parse('${local}Z');
  if(parsed.year<1||parsed.toIso8601String().substring(0,19)!=local)throw const FormatException('Invalid calendar timestamp');
  if(!value.endsWith('Z')) {
    final offset=value.substring(value.length-5);
    if(int.parse(offset.substring(0,2))>23||int.parse(offset.substring(3))>59)throw const FormatException('Invalid offset');
  }
  return DateTime.parse(value).toUtc();
}

/// Semantic validation is not independent authentication of an imported source.
({DateTime captured,DateTime quoted}) readOptionObservation(dynamic value) {
  if(value is! Map||value.length!=4||!value.keys.toSet().containsAll({'account','source','capturedAt','quote'})||
      value['account'] is! String||(value['account'] as String).trim().isEmpty||(value['account'] as String).length>120||
      !['fixture','alpaca'].contains(value['source'])){throw const FormatException('Invalid observation');}
  final q=value['quote'];
  if(q is! Map||q.length!=7||!q.keys.toSet().containsAll({'contract','feed','at','bid','ask','bidSize','askSize'})||
      q['contract'] is! String){throw const FormatException('Invalid quote');}
  final m=OptionQuote.pattern.firstMatch(q['contract'] as String);
  if(m==null||int.parse(m[6]!)<=0||int.parse(m[6]!)%10!=0)throw const FormatException('Nonstandard contract');
  final captured=observationStamp(value['capturedAt']),quoted=observationStamp(q['at']);
  final bid=_integer(q['bid'],1),ask=_integer(q['ask'],1);
  _integer(q['bidSize'],1,1000000000);_integer(q['askSize'],1,1000000000);
  if(q['feed']!='opra'||ask<bid||(ask-bid)*5>ask||captured.isBefore(quoted)||captured.difference(quoted)>const Duration(seconds:30)||
      !paperSession(captured).fill||!paperExpiry(q['contract'] as String,captured).close){throw const FormatException('Unqualified quote');}
  return (captured:captured,quoted:quoted);
}

/// A cost-explicit fixed-horizon research result. Never creates an execution
/// receipt, interpolates a missing quote or mutates the original decision.
Map<String,dynamic> replayObservedOption(Map<String,dynamic> query) {
  final base=<String,dynamic>{'version':observedOptionReplayVersion,'counterfactual':true,
    'executionAllowed':false,'externalOrder':false,'pnlCents':null};
  Map<String,dynamic> unavailable(String status)=>{...base,'status':status};
  late DateTime asOf;late int horizon,slippage,fee;late List observations;
  try {
    if(query.keys.any((k)=>!{'entry','observations','asOf','horizonSeconds','slippageCents','feePerContractCents'}.contains(k)))throw const FormatException('Invalid query');
    asOf=observationStamp(query['asOf']);horizon=_integer(query.containsKey('horizonSeconds')?query['horizonSeconds']:300,1,86400);
    slippage=_integer(query.containsKey('slippageCents')?query['slippageCents']:0,0,10000);
    fee=_integer(query.containsKey('feePerContractCents')?query['feePerContractCents']:65,0,10000);
    observations=query['observations'] as List;if(observations.length>20000)throw const FormatException('Too many observations');
  }catch(_){return unavailable('INVALID_QUERY');}
  late Map origin,q;late int quantity,entryFee;late DateTime entered;
  try {
    final e=query['entry'] as Map,f=e['fill'] as Map;q=e['quote'] as Map;
    origin={'account':e['account'],'source':e['evidence']['source'],'capturedAt':e['at'],'quote':q};
    entered=readOptionObservation(origin).captured;
    quantity=_integer(f['quantity'],1,100000);entryFee=_integer(f['fee'],0,1000000000);
    if(f['side']!='BUY'||f['price'] is! int||f['price']!=q['ask']||quantity>q['bidSize']||quantity>q['askSize']||
        !paperSession(entered).entry||!paperExpiry(q['contract'] as String,entered).entry){throw const FormatException('Invalid original receipt');}
  }catch(_){return unavailable('INVALID_ORIGINAL_RECEIPT');}
  final target=entered.add(Duration(seconds:horizon));
  if(asOf.isBefore(target))return unavailable('HORIZON_NOT_OBSERVED');
  if(!paperSession(target).fill||!paperExpiry(q['contract'] as String,target).close)return unavailable('HORIZON_OUTSIDE_OPTION_SESSION');
  final candidates=<({DateTime captured,DateTime quoted,Map quote})>[];
  try {
    for(final o in observations) {
      final t=readOptionObservation(o);
      if(o['account']==origin['account']&&o['source']==origin['source']&&o['quote']['contract']==q['contract']&&
          !t.captured.isAfter(target)&&!t.quoted.isBefore(target.subtract(const Duration(seconds:30)))&&!t.quoted.isAfter(target)) {
        candidates.add((captured:t.captured,quoted:t.quoted,quote:o['quote'] as Map));
      }
    }
  }catch(_){return unavailable('INVALID_OBSERVATION');}
  if(candidates.isEmpty)return unavailable('INSUFFICIENT_OBSERVED_DATA');
  candidates.sort((a,b){final byQuote=b.quoted.compareTo(a.quoted);return byQuote==0?a.captured.compareTo(b.captured):byQuote;});
  final selected=candidates.first,exitQuote=selected.quote;
  if(candidates.where((c)=>c.quoted==selected.quoted).any((c)=>exitQuote.keys.where((k)=>k!='at').any((k)=>c.quote[k]!=exitQuote[k])))return unavailable('AMBIGUOUS_OBSERVATION');
  if(quantity>exitQuote['bidSize']||quantity>exitQuote['askSize'])return unavailable('INSUFFICIENT_OBSERVED_LIQUIDITY');
  final price=(exitQuote['bid'] as int)-slippage;if(price<=0)return unavailable('NO_POSITIVE_STRESSED_BID');
  final entryCost=(q['ask'] as int)*quantity*100+entryFee,exitFee=fee*quantity,proceeds=price*quantity*100-exitFee;
  return {...base,'status':'OBSERVED_COUNTERFACTUAL','source':origin['source'],'account':origin['account'],
    'contract':q['contract'],'quantity':quantity,'targetAt':target.toIso8601String(),'quoteAt':selected.quoted.toIso8601String(),
    'capturedAt':selected.captured.toIso8601String(),'entryCostCents':entryCost,'entryFeeCents':entryFee,
    'exitBidCents':exitQuote['bid'],'slippageCents':slippage,'exitPriceCents':price,'exitFeeCents':exitFee,
    'exitProceedsCents':proceeds,'pnlCents':proceeds-entryCost,'model':'observed-bid-minus-adverse-cents',
    'queueModeled':false,'greeksUsedForPricing':false};
}
