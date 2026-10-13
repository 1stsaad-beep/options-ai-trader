import 'dart:convert';
import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'direct_alpaca.dart';

typedef PaperRow=Map<String,dynamic>;
typedef QuoteReader=Future<OptionQuote?> Function(String contract);

abstract class PaperStore {
  Future<PaperRow?> read();
  Future<void> write(PaperRow value);
}
class PreferencesPaperStore implements PaperStore {
  static const key='oat.direct.market_paper.v1';
  @override Future<PaperRow?> read() async {final text=(await SharedPreferences.getInstance()).getString(key);return text==null?null:jsonDecode(text) as PaperRow;}
  @override Future<void> write(PaperRow value) async {
    if(!await (await SharedPreferences.getInstance()).setString(key,jsonEncode(value)))throw StateError('storage');
  }
}

/// Independent virtual ledger. No Demo imports, no broker submission or stock-price fills.
class MarketPaper extends ChangeNotifier {
  /// One device ledger across routes; a pending quote/save cannot race a second controller.
  static final device=MarketPaper(PreferencesPaperStore());
  final PaperStore store;
  final DateTime Function() now;
  PaperRow _book={'version':1,'accounts':<dynamic>[],'journal':<dynamic>[]};
  bool ready=false,busy=false;
  String? error;
  Future<void>? _loading;
  final _epochs=<String,int>{};
  final _paused=<String>{};
  MarketPaper(this.store,{DateTime Function()? clock}):now=clock??DateTime.now;
  List<PaperRow> get accounts=>(_book['accounts'] as List).map((x)=>Map<String,dynamic>.from(x as Map)).toList();
  List<PaperRow> get journal=>(_book['journal'] as List).map((x)=>Map<String,dynamic>.from(x as Map)).toList();
  PaperRow account(String id)=>accounts.singleWhere((a)=>a['id']==id);
  PaperRow copy()=>jsonDecode(jsonEncode(_book)) as PaperRow;
  Future<void> load()=>_loading??=_load();
  Future<void> _load() async {try {final saved=await store.read();if(saved!=null){
    if(saved['version']!=1||saved['accounts'] is! List||saved['journal'] is! List)throw const FormatException();
    _book=saved;
    // Never auto-resume virtual execution after process restart.
    for(final a in _book['accounts'] as List){a['enabled']=false;}
  }ready=true;}catch(_){error='تعذر قراءة دفتر Market Paper؛ لم يُستبدل أو يُحذف.';}notifyListeners();}
  Future<bool> commit(PaperRow next) async {
    try {await store.write(next);_book=next;error=null;notifyListeners();return true;}
    catch(_){error='فشل حفظ دفتر Market Paper. لم تُعتمد العملية أو أي عملية عكس.';notifyListeners();return false;}
  }
  PaperRow _in(PaperRow book,String id)=>(book['accounts'] as List).cast<PaperRow>().singleWhere((a)=>a['id']==id);
  void _log(PaperRow book,String id,String symbol,String decision,{OptionQuote? quote}) {
    final rows=book['journal'] as List;
    if(rows.length>=10000)throw StateError('journal capacity');
    rows.add({'account':id,'symbol':symbol,'at':now().toUtc().toIso8601String(),'decision':decision,
      if(quote!=null)'quote':{'contract':quote.contract,'feed':quote.feed,'at':quote.time.toIso8601String(),'bid':quote.bid,'ask':quote.ask}});
  }
  Future<void> add(String name) async {
    if(!ready||busy||name.trim().isEmpty)return;
    busy=true;
    try {final next=copy();(next['accounts'] as List).add({'id':'mp-${now().microsecondsSinceEpoch}-${accounts.length}',
      'name':name.trim(),'cash':1000000,'initialCash':1000000,'enabled':false,'positions':<String,dynamic>{},'contracts':<String,dynamic>{},
      'riskPercent':5,'quantity':1,'stopPercent':20,'takePercent':40,'trailPercent':15,'addEnabled':false,'lastSignal':<String,dynamic>{}});
      await commit(next);
    }finally{busy=false;notifyListeners();}
  }
  Future<void> configure(String id,PaperRow values) async {
    // Invalidates an in-flight quote even while the durable setting waits.
    _epochs[id]=(_epochs[id]??0)+1;
    if(values['enabled']==false)_paused.add(id);
    while(busy){await Future<void>.delayed(const Duration(milliseconds:20));}
    final allowed={'enabled','contracts','riskPercent','quantity','stopPercent','takePercent','trailPercent','addEnabled'};
    if(values.keys.any((k)=>!allowed.contains(k)))throw ArgumentError('setting');
    for(final k in ['riskPercent','stopPercent','takePercent','trailPercent']) {
      if(values.containsKey(k)&&(values[k] is! int||values[k]<1||values[k]>50))throw ArgumentError('risk');
    }
    if(values.containsKey('quantity')&&(values['quantity'] is! int||values['quantity']<1||values['quantity']>10))throw ArgumentError('quantity');
    busy=true;try{final next=copy();_in(next,id).addAll(values);if(await commit(next)&&values['enabled']==true)_paused.remove(id);}finally{busy=false;notifyListeners();}
  }
  Future<void> pauseAll() async {
    if(!ready)return;
    for(final a in accounts){_epochs[a['id'] as String]=(_epochs[a['id']]??0)+1;_paused.add(a['id'] as String);}
    // The active operation sees its epoch change; wait for it before persisting pause.
    while(busy){await Future<void>.delayed(const Duration(milliseconds:20));}
    busy=true;
    try{final next=copy();for(final a in next['accounts'] as List){a['enabled']=false;}await commit(next);}
    finally{busy=false;notifyListeners();}
  }
  bool _current(String id,int epoch)=>ready&&!_paused.contains(id)&&(_epochs[id]??0)==epoch&&account(id)['enabled']==true;
  Future<void> evaluate({required String id,required String symbol,required String signal,
    required bool confirmedReverse,required bool Function() dataValid,required String observation,required QuoteReader quotes,bool forceClose=false}) async {
    if(!ready||busy||_paused.contains(id)||account(id)['enabled']!=true)return;
    busy=true;notifyListeners();final epoch=_epochs[id]??0;
    try {
      if(!dataValid()){await _record(id,symbol,'INVALID_OR_STALE_STOCK_DATA');return;}
      var a=account(id);var positions=Map<String,dynamic>.from(a['positions'] as Map);
      final position=positions[symbol] as PaperRow?;
      if(position!=null) {
        final q=await quotes(position['contract'] as String);
        if(!_current(id,epoch))return;
        final qty=position['quantity'] as int;
        if(q==null||q.contract!=position['contract']||!q.valid(now(),quantity:qty)||!dataValid()) {await _record(id,symbol,'CLOSE_UNCONFIRMED_NO_REVERSAL');return;}
        final average=position['cost']/(qty*100),highest=(position['highBid'] as num).toDouble();
        final reverse=signal!=position['direction']&&['CALL','PUT'].contains(signal)&&confirmedReverse;
        final closeReason=forceClose?'MANUAL':q.bid<=average*(1-(a['stopPercent'] as int)/100)?'STOP_LOSS':
          q.bid>=average*(1+(a['takePercent'] as int)/100)?'TAKE_PROFIT':
          highest>average&&q.bid<=highest*(1-(a['trailPercent'] as int)/100)?'TRAILING_STOP':reverse?'CONFIRMED_DIVERGENCE':null;
        if(closeReason!=null) {
          final next=copy();final target=_in(next,id);(target['positions'] as Map).remove(symbol);
          target['cash']=(target['cash'] as int)+q.bid*qty*100-qty*65;
          _log(next,id,symbol,'CLOSED_$closeReason',quote:q);
          if(!await commit(next))return; // closure must be durable before a second quote/open
          if(forceClose||!reverse||!_current(id,epoch)||!dataValid())return;
          if((account(id)['positions'] as Map).containsKey(symbol))return;
        } else {
          if(signal!=position['direction']&&['CALL','PUT'].contains(signal)) {await _record(id,symbol,'OPPOSITE_POSITION_BLOCKED');return;}
          final next=copy();final target=_in(next,id);final p=(target['positions'] as Map)[symbol] as PaperRow;
          if(q.bid>highest)p['highBid']=q.bid;
          if(a['addEnabled']==true&&p['added']!=true&&q.bid>=average*1.10&&signal==p['direction']) {
            final cost=q.ask*100+65;
            if((p['cost'] as int)+qty*65+cost<=(target['initialCash'] as int)*(target['riskPercent'] as int)/100&&cost<=(target['cash'] as int)) {
              p['quantity']=qty+1;p['cost']=(p['cost'] as int)+q.ask*100;p['added']=true;target['cash']=(target['cash'] as int)-cost;
              _log(next,id,symbol,'ADD_ON_OPRA',quote:q);
            } else if(journal.isEmpty||journal.last['account']!=id||journal.last['symbol']!=symbol||journal.last['decision']!='ADD_RISK_LIMIT') {
              _log(next,id,symbol,'ADD_RISK_LIMIT',quote:q);
            }
          }
          await commit(next);return;
        }
      }
      if(!['CALL','PUT'].contains(signal)||!_current(id,epoch))return;
      a=account(id);
      if((a['lastSignal'] as Map)[symbol]==observation)return;
      final contract=(a['contracts'] as Map)['$symbol:$signal'] as String?;
      if(contract==null){await _record(id,symbol,'QUALIFIED_OPTION_CONTRACT_REQUIRED');return;}
      final q=await quotes(contract);
      if(!_current(id,epoch))return;
      final quantity=a['quantity'] as int;
      if(q==null||q.contract!=contract||q.underlying!=symbol||q.direction!=signal||!q.valid(now(),quantity:quantity)||!dataValid()){
        await _record(id,symbol,'OPRA_QUOTE_REQUIRED_NO_FILL');return;
      }
      final next=copy();final target=_in(next,id);positions=Map<String,dynamic>.from(target['positions'] as Map);
      if(positions.containsKey(symbol)){await _record(id,symbol,'OPPOSITE_POSITION_BLOCKED');return;}
      final cost=q.ask*quantity*100,fee=quantity*65;
      if(cost+fee>(target['cash'] as int)||cost+fee>(target['initialCash'] as int)*(target['riskPercent'] as int)/100) {await _record(id,symbol,'RISK_LIMIT');return;}
      positions[symbol]={'contract':contract,'direction':signal,'quantity':quantity,'cost':cost,'highBid':q.bid,'added':false,'opened':now().toUtc().toIso8601String()};
      target['positions']=positions;target['cash']=(target['cash'] as int)-cost-fee;(target['lastSignal'] as Map)[symbol]=observation;
      _log(next,id,symbol,'OPENED_$signal',quote:q);await commit(next);
    }catch(_){error='توقفت الدورة دون فتح عكسي. راجع البيانات وسعة السجل والتخزين.';notifyListeners();}
    finally{busy=false;notifyListeners();}
  }
  Future<void> _record(String id,String symbol,String reason) async {
    if(journal.isNotEmpty&&journal.last['account']==id&&journal.last['symbol']==symbol&&journal.last['decision']==reason)return;
    final next=copy();_log(next,id,symbol,reason);await commit(next);
  }
}
