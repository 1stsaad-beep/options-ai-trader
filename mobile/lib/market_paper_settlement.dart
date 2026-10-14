import 'dart:convert';
import 'paper_settlement.dart';

/// Applies an already explicitly requested virtual receipt to a detached account.
/// Trade win counts are not invented for stock conversions; reports distinguish
/// ordinary option closes from settlement/delivery accounting.
Map<String,dynamic> applyPaperSettlement(Map<String,dynamic> account,
    Map<String,dynamic> request,DateTime now) {
  final next=jsonDecode(jsonEncode(account)) as Map<String,dynamic>;
  final positions=next['positions'] as Map;
  final deliveries=(next['deliveryPositions']??=<String,dynamic>{}) as Map;
  final symbol=RegExp(r'^([A-Z]{1,6})\d').firstMatch('${request['contract']}')?.group(1);
  final position=positions[symbol] as Map?;
  final result=projectPaperSettlement(position,deliveries[symbol] as Map?,next['cash'] as int,request,now);
  final owned=deliveries[symbol] as Map? ?? {'quantity':0,'cost':0};
  final shares=(owned['quantity'] as int)+(result['shareDelta'] as int);
  final basis=(owned['cost'] as int)+(result['shareBasisDelta'] as int);
  if(shares==0){deliveries.remove(symbol);}else{deliveries[symbol]={'quantity':shares,'cost':basis};}
  final removed=result['optionQuantity'] as int;
  if(removed>0) {
    final p=position!;
    if(removed==p['quantity']){positions.remove(symbol);}else {
      p['quantity']=(p['quantity'] as int)-removed;p['cost']=(p['cost'] as int)-(result['removedCost'] as int);
      p['entryFees']=((p['entryFees']??0) as int)-(result['removedEntryFees'] as int);
      p['realizedPnl']=((p['realizedPnl']??0) as int)+(result['realizedPnl'] as int);
      p.remove('closeIntent');
    }
  }
  next['cash']=(next['cash'] as int)+(result['cashDelta'] as int);
  if(next['fees'] is int)next['fees']=(next['fees'] as int)+(result['feeCents'] as int);
  next['settlementCount']=((next['settlementCount']??0) as int)+1;
  next['settlementRealizedPnl']=((next['settlementRealizedPnl']??0) as int)+(result['realizedPnl'] as int);
  final day=now.toUtc().toIso8601String().substring(0,10),daily=(next['dailyRealized']??=<String,dynamic>{}) as Map;
  daily[day]=((daily[day]??0) as int)+(result['realizedPnl'] as int);
  next['enabled']=false;
  return {'account':next,'result':result};
}
