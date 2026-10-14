import 'observed_option_replay.dart' show observationStamp;

const deliveryValuationVersion='paper-delivery-valuation-v1';
const _max=9007199254740991;
int _integer(dynamic value,[int minimum=0]) {
  if(value is! int||value<minimum||value>_max)throw const FormatException('Invalid share valuation integer');
  return value;
}
int _product(int a,int b) {
  final value=BigInt.from(a)*BigInt.from(b);
  if(value>BigInt.from(_max))throw const FormatException('Share valuation exceeds exact range');
  return value.toInt();
}

/// Gross observed bid marks only. No settlement receipt, fill or external order.
/// IEX can inform display; new risk requires consolidated SIP observations.
Map<String,dynamic> valueDeliveries(Map deliveries,Map observations,DateTime now,String source) {
  if(!['fixture','alpaca'].contains(source))throw const FormatException('Explicit observation source required');
  const fields={'version','symbol','source','feed','at','capturedAt','bidCents','askCents'};
  final rows=<Map<String,dynamic>>[];
  var basis=0,liquidation=0,exposure=0,loss=0,complete=true,riskComplete=true;
  for(final entry in deliveries.entries) {
    final symbol=entry.key,position=entry.value;
    final qty=_integer(position['quantity'],1),cost=_integer(position['cost'],1);
    basis=_integer(basis+cost);
    final observation=observations[symbol];
    var status='MISSING';int? amount,reserve,pnl;
    try {
      if(observation!=null) {
        status='INVALID';
        if(observation is! Map||observation.keys.toSet().difference(fields).isNotEmpty||fields.difference(observation.keys.toSet()).isNotEmpty||
            observation['version']!=deliveryValuationVersion||observation['symbol']!=symbol||symbol is! String||
            !RegExp(r'^[A-Z]{1,6}$').hasMatch(symbol)||!['iex','sip'].contains(observation['feed'])) {
          throw const FormatException();
        }
        final bid=_integer(observation['bidCents'],1),ask=_integer(observation['askCents'],1);
        if(ask>100000000||bid>ask||(ask-bid)*5>ask)throw const FormatException();
        final at=observationStamp(observation['at']),captured=observationStamp(observation['capturedAt']);
        if(at.isAfter(captured))throw const FormatException();
        status='SOURCE_MISMATCH';if(observation['source']!=source)throw const FormatException();
        status='NOT_YET_KNOWN';if(captured.isAfter(now))throw const FormatException();
        status='STALE';if(now.difference(at).inMicroseconds>30000000)throw const FormatException();
        status='INVALID';amount=_product(bid,qty);final askValue=_product(ask,qty);reserve=cost>askValue?cost:askValue;
        _integer(liquidation+amount);_integer(exposure+reserve);_integer(loss+(cost>amount?cost-amount:0));
        pnl=amount-cost;status=observation['feed']=='sip'?'QUALIFIED':'IEX_PARTIAL_MARK';
      }
    }catch(_){amount=null;reserve=null;pnl=null;}
    if(amount==null){complete=false;}else{liquidation+=amount;exposure+=reserve!;loss+=pnl!<0?-pnl:0;}
    if(status!='QUALIFIED')riskComplete=false;
    rows.add({'symbol':symbol,'quantity':qty,'basisCents':cost,'status':status,'valueCents':amount,'unrealizedPnlCents':pnl,'exposureCents':reserve});
  }
  return {'version':deliveryValuationVersion,'complete':complete,'riskComplete':riskComplete,'basisCents':basis,
    'valueCents':complete?liquidation:null,'unrealizedPnlCents':complete?liquidation-basis:null,
    'exposureCents':riskComplete?exposure:null,'openLossCents':riskComplete?loss:null,'positions':rows,
    'modeledExitFeeCents':0,'externalOrder':false,
    'policy':'observed_bid_gross_no_guaranteed_fill;iex_display_only;sip_required_for_new_risk'};
}
