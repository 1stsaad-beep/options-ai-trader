import 'direct_alpaca.dart';
import 'paper_time.dart';
import 'paper_money.dart';

const conservativeExecution='conservative-v2';
const legacyExecution='legacy-quote-side-v1';
const executionVersion='paper-option-execution-v2';
const executionPolicy={
  'commissionCents':65,'additionalFeeCents':5,'adverseSlippageCents':1,
  'participationBps':2500,'liquidityPolicy':'minimum_displayed_sides_once_per_quote',
};
int executionFee(Map account)=>account['executionPolicy']==conservativeExecution?70:65;
int executionSlippage(Map account)=>account['executionPolicy']==conservativeExecution?1:0;

/// Conservative deterministic stress model, not a simulated exchange queue.
/// All prices are original observed option prices; stock/Greeks never price fills.
Map<String,dynamic> projectOptionExecution(Map quote,String side,int requested,int consumed,DateTime at) {
  final base=<String,dynamic>{'version':executionVersion,'policy':Map<String,dynamic>.from(executionPolicy),
    'requestedQuantity':requested,'consumedQuantity':consumed,'side':side,'externalOrder':false,
    'queuePositionKnown':false,'priceCents':null,'feeCents':null,'cashDeltaCents':null,'quantity':0};
  Map<String,dynamic> no(String status)=>{...base,'status':status,'unfilledQuantity':requested};
  try {
    if(!['BUY','SELL_TO_CLOSE'].contains(side)||requested<1||requested>1000000||consumed<0||consumed>1000000||
      quote.keys.toSet().difference({'contract','feed','at','bid','ask','bidSize','askSize'}).isNotEmpty) {return no('INVALID_REQUEST');}
    final q=OptionQuote(quote['contract'] as String,quote['feed'] as String,observationStamp(quote['at']),
      quote['bid'] as int,quote['ask'] as int,quote['bidSize'] as int,quote['askSize'] as int);
    if(!q.valid(at))return no('UNQUALIFIED_QUOTE');
    final visible=q.bidSize<q.askSize?q.bidSize:q.askSize;
    final available=visible*2500~/10000-consumed;
    if(available<=0)return no('NO_MODELED_LIQUIDITY');
    final quantity=requested<available?requested:available,price=side=='BUY'?q.ask+1:q.bid-1;
    if(price<=0)return no('NO_POSITIVE_STRESSED_PRICE');
    final fee=paperProduct(quantity,70),gross=paperProduct(paperProduct(quantity,price),100);
    return {...base,'status':quantity==requested?'FILLED':'PARTIAL','quantity':quantity,
      'unfilledQuantity':requested-quantity,'priceCents':price,'feeCents':fee,
      'cashDeltaCents':side=='BUY'?-paperSum(gross,fee):paperSum(gross,-fee)};
  }catch(_){return no('INVALID_REQUEST');}
}

/// Derive consumed displayed liquidity from original account receipts, including
/// legacy fills. A later or changed same-time quote never reopens old capacity.
({int consumed,bool blocked}) optionConsumption(Iterable<Map> events,String account,Map quote) {
  var consumed=0;final at=observationStamp(quote['at']);
  for(final event in events) {
    if(event['account']!=account||event['fill'] is! Map||event['quote'] is! Map||event['quote']['contract']!=quote['contract'])continue;
    final old=event['quote'] as Map,oldAt=observationStamp(old['at']);
    if(oldAt.isAfter(at))return (consumed:consumed,blocked:true);
    if(oldAt==at) {
      if(['feed','bid','ask','bidSize','askSize'].any((k)=>old[k]!=quote[k]))return (consumed:consumed,blocked:true);
      consumed+=event['fill']['quantity'] as int;
    }
  }
  return (consumed:consumed,blocked:false);
}
