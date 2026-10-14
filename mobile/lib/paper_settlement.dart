import 'direct_alpaca.dart';
import 'market_paper_policy.dart';

const paperSettlementVersion='paper-equity-delivery-v1';
const _max=9007199254740991;
int _integer(dynamic v,[int min=0]) {
  if(v is! int||v<min||v>_max)throw const FormatException('Invalid integer amount');
  return v;
}
DateTime _stamp(dynamic v) {
  final m=v is String?RegExp(r'^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d{1,6})?(Z|([+-])(\d{2}):(\d{2}))$').firstMatch(v):null;
  if(m==null)throw const FormatException('Explicit ISO timestamp required');
  final date=DateTime.utc(int.parse(m[1]!),int.parse(m[2]!),int.parse(m[3]!));
  if(int.parse(m[1]!)<1||date.year!=int.parse(m[1]!)||date.month!=int.parse(m[2]!)||date.day!=int.parse(m[3]!)||
      int.parse(m[4]!)>23||int.parse(m[5]!)>59||int.parse(m[6]!)>59||
      (m[7]!='Z'&&(int.parse(m[9]!)>23||int.parse(m[10]!)>59))) {
    throw const FormatException('Invalid timestamp components');
  }
  return DateTime.parse(v).toUtc();
}
int _product(int a,int b) {
  final result=BigInt.from(a)*BigInt.from(b);
  if(result>BigInt.from(_max))throw const FormatException('Gross amount exceeds exact range');
  return result.toInt();
}
int _portion(int cost,int quantity,int total)=>(BigInt.from(cost)*BigInt.from(quantity)~/BigInt.from(total)).toInt();

/// Explicit virtual receipts only. No network, option-price substitution or
/// automatic exercise. Result must commit atomically with original evidence.
Map<String,dynamic> projectPaperSettlement(Map? position,Map? delivery,int cash,
    Map<String,dynamic> request,DateTime now) {
  const fields={'id','action','contract','quantity','feeCents','underlyingCents','effectiveAt','recordedAt','source','reference'};
  if(request.keys.toSet().difference(fields).isNotEmpty||fields.difference(request.keys.toSet()).isNotEmpty||
    !['manual_paper','fixture'].contains(request['source'])) {
    throw const FormatException('Strict paper receipt required');
  }
  for(final key in ['id','reference']) {
    if(request[key] is! String||(request[key] as String).trim().isEmpty||(request[key] as String).length>120)throw const FormatException('Receipt identity required');
  }
  final match=request['contract'] is String?OptionQuote.pattern.firstMatch(request['contract'] as String):null;
  if(match==null||int.parse(match[6]!)<=0||int.parse(match[6]!)%10!=0)throw const FormatException('Whole-cent OCC contract required');
  final symbol=match[1]!,right=match[5]!,strike=int.parse(match[6]!)~/10;
  final expiry=DateTime.utc(2000+int.parse(match[2]!),int.parse(match[3]!),int.parse(match[4]!));
  if(expiry.month!=int.parse(match[3]!)||expiry.day!=int.parse(match[4]!))throw const FormatException('Invalid expiry');
  final effective=_stamp(request['effectiveAt']),recorded=_stamp(request['recordedAt']);
  if(effective.isAfter(recorded)||recorded.isAfter(now))throw const FormatException('Receipt chronology invalid');
  final qty=_integer(request['quantity'],1),fee=_integer(request['feeCents']),spot=_integer(request['underlyingCents'],1);
  _integer(cash);
  final stocks=delivery??{'quantity':0,'cost':0};
  final stockQty=_integer(stocks['quantity']),stockCost=_integer(stocks['cost']);
  if((stockQty==0)!=(stockCost==0))throw const FormatException('Delivery inventory inconsistent');
  var removedCost=0,removedFees=0,optionQty=0,stockDelta=0,basisDelta=0,cashDelta=0,pnl=0;
  final action=request['action'];
  if(action=='SELL_DELIVERY') {
    if(qty>stockQty)throw const FormatException('Owned shares required; no short stock');
    basisDelta=-_portion(stockCost,qty,stockQty);stockDelta=-qty;cashDelta=_product(spot,qty)-fee;pnl=cashDelta+basisDelta;
  }else if(['EXERCISE','EXPIRE_WORTHLESS'].contains(action)) {
    if(position==null||position['contract']!=request['contract']||qty>_integer(position['quantity'],1))throw const FormatException('Owned option quantity required');
    if(effective.isBefore(_stamp(position['opened'])))throw const FormatException('Receipt predates ownership');
    DateTime? cutoff;
    for(var back=0;back<8;back++) {
      final s=paperSession(DateTime.utc(expiry.year,expiry.month,expiry.day,12).subtract(Duration(days:back)));
      if(s.status=='NO_SESSION')continue;
      cutoff=s.closes;break;
    }
    if(cutoff==null)throw const FormatException('Known contract calendar required');
    optionQty=qty;removedCost=_portion(_integer(position['cost'],1),qty,position['quantity'] as int);
    removedFees=_portion(_integer(position['entryFees']??0),qty,position['quantity'] as int);
    if(action=='EXPIRE_WORTHLESS') {
      if(effective!=cutoff||(right=='C'?spot>strike:spot<strike))throw const FormatException('Explicit non-ITM cutoff observation required');
      cashDelta=-fee;pnl=-removedCost-removedFees-fee;
    }else {
      if(effective.isAfter(cutoff))throw const FormatException('Exercise after cutoff prohibited');
      final shares=_product(qty,100),gross=_product(strike,shares);
      if(right=='C') {cashDelta=-gross-fee;stockDelta=shares;basisDelta=gross+removedCost+removedFees+fee;}
      else {
        if(shares>stockQty)throw const FormatException('Put exercise requires owned shares');
        stockDelta=-shares;basisDelta=-_portion(stockCost,shares,stockQty);cashDelta=gross-fee;pnl=cashDelta+basisDelta-removedCost-removedFees;
      }
    }
  }else {throw const FormatException('No assignment or cash settlement of long equity options');}
  _integer(cash+cashDelta);_integer(stockQty+stockDelta);_integer(stockCost+basisDelta);
  if([cashDelta,basisDelta,pnl,removedCost,removedFees].any((v)=>v.abs()>_max))throw const FormatException('Arithmetic overflow');
  return {'version':paperSettlementVersion,'symbol':symbol,'cashDelta':cashDelta,'optionQuantity':optionQty,
    'removedCost':removedCost,'removedEntryFees':removedFees,'shareDelta':stockDelta,'shareBasisDelta':basisDelta,
    'realizedPnl':pnl,'feeCents':fee,'externalOrder':false,'source':'paper_receipt'};
}
