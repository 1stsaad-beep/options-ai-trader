import 'dart:convert';
import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'direct_alpaca.dart';
import 'market_paper_validation.dart';
import 'market_paper_reports.dart';
import 'market_paper_risk.dart';
import 'market_paper_policy.dart';
import 'market_paper_backup.dart';
import 'dart:math' as math;

typedef PaperRow=Map<String,dynamic>;
typedef QuoteReader=Future<OptionQuote?> Function(String contract);

abstract class PaperStore {
  Future<PaperRow?> read();
  Future<void> write(PaperRow value);
}
class PreferencesPaperStore implements PaperStore {
  static const key='oat.direct.market_paper.v1';
  @override Future<PaperRow?> read() async {
    final preferences=await SharedPreferences.getInstance();
    await preferences.reload();
    final text=preferences.getString(key);
    return text==null?null:jsonDecode(text) as PaperRow;
  }
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
  PaperRow? _durable;
  PaperRow? _decisionEvidence;
  final _epochs=<String,int>{};
  final _paused=<String>{};
  MarketPaper(this.store,{DateTime Function()? clock}):now=clock??DateTime.now;
  List<PaperRow> _rows(String key)=>(jsonDecode(jsonEncode(_book[key])) as List).cast<PaperRow>();
  List<PaperRow> get accounts=>_rows('accounts');
  List<PaperRow> get journal=>[
    for(final segment in (copy()['journalArchive'] as List? ?? [])) ...(segment as List).cast<PaperRow>(),
    ..._rows('journal'),
  ];
  PaperRow account(String id)=>accounts.singleWhere((a)=>a['id']==id);
  PaperRow copy()=>copyPaper(_book);
  PaperRow performance(String id)=>paperPerformance(account(id),now());
  PaperRow comparison()=>paperComparison({...copy(),'journal':journal},now());
  String exportBackup() {
    if(!ready||busy)throw StateError('Ledger is not stable');
    return PaperBackup.export(copy());
  }
  Future<void> restoreBackup(String text) async {
    if(!ready||busy)throw StateError('Ledger is not stable');
    // Import is allowed only into an empty device ledger. Existing data is never
    // replaced, merged, deleted or silently renamed by a backup operation.
    if(accounts.isNotEmpty||journal.isNotEmpty)throw StateError('Restore requires an empty Market Paper ledger');
    final restored=PaperBackup.prepare(text);
    busy=true;notifyListeners();
    try{if(!await _commit(restored))throw StateError('Restore was not confirmed');}
    finally{busy=false;notifyListeners();}
  }
  Future<void> load()=>_loading??=_load();
  Future<void> _load() async {try {final saved=await store.read();if(saved!=null){
    validatePaper(saved);
    _durable=copyPaper(saved);
    _book=copyPaper(saved);
    // Never auto-resume virtual execution after process restart.
    for(final a in _book['accounts'] as List){a['enabled']=false;}
  }ready=true;}catch(_){error='تعذر قراءة دفتر Market Paper؛ لم يُستبدل أو يُحذف.';}notifyListeners();}
  void _uncertain() {
    ready=false;
    error='حالة الحفظ غير مؤكدة؛ توقفت كل التغييرات والعكس. احتُفظ بالدفتر دون استبدال. أعد فتح التطبيق لاستعادة الحالة المحفوظة وفحصها.';
    notifyListeners();
  }
  Future<bool> _commit(PaperRow next,{bool Function()? admission}) async {
    if(!ready)return false;
    for(final a in (next['accounts'] as List).cast<PaperRow>()) {
      if(a['peakEquity'] is! int)continue;
      final equity=paperPerformance(a,now())['equityCents'] as int?;
      if(equity==null)continue;
      if(equity>(a['peakEquity'] as int))a['peakEquity']=equity;
      final drawdown=(a['peakEquity'] as int)-equity;
      if(drawdown>(a['maxDrawdown'] as int))a['maxDrawdown']=drawdown;
    }
    validatePaper(next);
    // Compare the durable preimage before writing; never overwrite a second owner.
    try {
      if(paperBytes(await store.read())!=paperBytes(_durable)){_uncertain();return false;}
    }catch(_){_uncertain();return false;}
    if(admission!=null&&!admission())return false;
    try {await store.write(copyPaper(next));}catch(_){ /* Readback resolves a lost acknowledgement. */ }
    PaperRow? observed;
    try {observed=await store.read();}catch(_){_uncertain();return false;}
    if(paperBytes(observed)==paperBytes(next)) {
      _durable=copyPaper(next);_book=copyPaper(next);error=null;notifyListeners();return true;
    }
    if(paperBytes(observed)!=paperBytes(_durable)){_uncertain();return false;}
    error='لم يُحفظ التغيير؛ بقي الدفتر السابق مؤكدًا. لم تُعتمد تعبئة أو عملية عكس.';
    notifyListeners();return false;
  }
  PaperRow _in(PaperRow book,String id)=>(book['accounts'] as List).cast<PaperRow>().singleWhere((a)=>a['id']==id);
  PaperRow _quote(OptionQuote q)=>{'contract':q.contract,'feed':q.feed,'at':q.time.toUtc().toIso8601String(),
    'bid':q.bid,'ask':q.ask,'bidSize':q.bidSize,'askSize':q.askSize};
  void _log(PaperRow book,String id,String symbol,String decision,{OptionQuote? quote,PaperRow? fill}) {
    var rows=book['journal'] as List;
    if(rows.length>=1000) {
      final archive=(book['journalArchive']??=<dynamic>[]) as List;
      archive.add(rows);
      rows=<dynamic>[];book['journal']=rows;
    }
    rows.add({'account':id,'symbol':symbol,'at':now().toUtc().toIso8601String(),'decision':decision,
      if(quote!=null)'quote':_quote(quote),if(fill!=null)'fill':copyPaper(fill),
      if(_decisionEvidence!=null)'evidence':copyPaper(_decisionEvidence!)});
  }
  PaperRow _newAccount(String id,String name,int initialCash,String strategy)=>{
    'id':id,'name':name.trim(),'cash':initialCash,'initialCash':initialCash,'enabled':false,
    'positions':<String,dynamic>{},'contracts':<String,dynamic>{},'riskPercent':5,'quantity':1,
    'stopPercent':20,'takePercent':40,'trailPercent':15,'addEnabled':false,'lastSignal':<String,dynamic>{},
    'ledgerPolicy':'receipt-v2','strategy':strategy,'watchlist':['NVDA','AAPL','TSLA'],'fees':0,'closedTrades':0,'winningTrades':0,
    'peakEquity':initialCash,'maxDrawdown':0,'dailyRealized':<String,dynamic>{},
    'allocationPercent':30,'dailyLossPercent':3,'maxPositions':4,'maxContracts':10,
    'holdingMode':'intraday','maxHoldingDays':3,'partialPercent':20,'scenarioExit':false,
  };
  Future<void> add(String name,{int initialCash=1000000,String strategy='confluence'}) async {
    if(!ready||busy||name.trim().isEmpty)return;
    if(initialCash<10000||initialCash>100000000||!paperStrategyLabels.containsKey(strategy))throw ArgumentError('account');
    busy=true;
    try {final next=copy();(next['accounts'] as List).add(_newAccount('mp-${now().microsecondsSinceEpoch}-${accounts.length}',name,initialCash,strategy));
      await _commit(next);
    }finally{busy=false;notifyListeners();}
  }
  Future<void> createComparisonExperiment() async {
    if(!ready||busy||_book['experiment']!=null)return;
    busy=true;
    try {
      final next=copy(),ids=<String>[];
      for(final strategy in paperStrategies) {
        final id='mp-experiment-v1-$strategy';
        if(accounts.any((a)=>a['id']==id))throw StateError('experiment identity conflict');
        ids.add(id);
        (next['accounts'] as List).add(_newAccount(id,'1000 USD • ${paperStrategyLabels[strategy]}',100000,strategy));
      }
      next['experiment']={'id':'four-accounts-three-sessions-v1','createdAt':now().toUtc().toIso8601String(),'accounts':ids};
      await _commit(next);
    }finally{busy=false;notifyListeners();}
  }
  Future<void> configure(String id,PaperRow values) async {
    if(!ready)return;
    // Invalidates an in-flight quote even while the durable setting waits.
    _epochs[id]=(_epochs[id]??0)+1;
    if(values['enabled']==false)_paused.add(id);
    while(busy){await Future<void>.delayed(const Duration(milliseconds:20));}
    final allowed={'enabled','contracts','riskPercent','quantity','stopPercent','takePercent','trailPercent','addEnabled','strategy','watchlist',
      'allocationPercent','dailyLossPercent','maxPositions','maxContracts','holdingMode','maxHoldingDays','partialPercent','scenarioExit'};
    if(values.keys.any((k)=>!allowed.contains(k)))throw ArgumentError('setting');
    for(final k in ['riskPercent','stopPercent','takePercent','trailPercent']) {
      if(values.containsKey(k)&&(values[k] is! int||values[k]<1||values[k]>50))throw ArgumentError('risk');
    }
    if(values.containsKey('quantity')&&(values['quantity'] is! int||values['quantity']<1||values['quantity']>10))throw ArgumentError('quantity');
    if(!ready)return;
    final next=copy();_in(next,id).addAll(copyPaper(values));
    try{validatePaper(next);}on FormatException{throw ArgumentError('setting');}
    busy=true;try{if(await _commit(next)&&values['enabled']==true)_paused.remove(id);}finally{busy=false;notifyListeners();}
  }
  Future<void> pauseAll() async {
    if(!ready)return;
    for(final a in accounts){_epochs[a['id'] as String]=(_epochs[a['id']]??0)+1;_paused.add(a['id'] as String);}
    // The active operation sees its epoch change; wait for it before persisting pause.
    while(busy){await Future<void>.delayed(const Duration(milliseconds:20));}
    busy=true;
    try{final next=copy();for(final a in next['accounts'] as List){a['enabled']=false;}await _commit(next);}
    finally{busy=false;notifyListeners();}
  }
  bool _current(String id,int epoch)=>ready&&!_paused.contains(id)&&(_epochs[id]??0)==epoch&&account(id)['enabled']==true;
  Future<void> evaluate({required String id,required String symbol,required String signal,
    required bool confirmedReverse,required bool Function() dataValid,required String observation,required QuoteReader quotes,
    bool forceClose=false,PaperRow? evidence,String Function()? currentSignal}) async {
    if(!ready||busy||_paused.contains(id)||account(id)['enabled']!=true)return;
    busy=true;notifyListeners();final epoch=_epochs[id]??0;
    bool stockValid(){try{return dataValid();}catch(_){return false;}}
    bool signalCurrent(){try{return currentSignal==null||currentSignal()==signal;}catch(_){return false;}}
    final marks=<String,OptionQuote>{};
    Future<bool> collectMarks() async {
      for(final p in (account(id)['positions'] as Map).values) {
        final contract=p['contract'] as String;
        if(!marks.containsKey(contract)) {
          final q=await quotes(contract);
          if(!_current(id,epoch))return false;
          if(q!=null&&q.contract==contract)marks[contract]=q;
        }
      }
      return _current(id,epoch);
    }
    String? risk(int qty,int price,{bool adding=false}) {
      if(!paperSession(now()).entry)return 'SESSION_ENTRY_BLOCKED';
      if(!paperExpiry(marks.values.firstWhere((q)=>q.underlying==symbol&&q.direction==signal).contract,now()).entry)return 'EXPIRY_ENTRY_BLOCKED';
      if((account(id)['positions'] as Map).values.any((p)=>p['closeIntent']!=null))return 'PENDING_CLOSE_RISK_LIMIT';
      return paperRiskReason(account(id),symbol,qty,price,marks,now(),journal:journal,adding:adding);
    }
    _decisionEvidence={...copyPaper(evidence??{'source':'fixture'}),'observation':observation,
      'signal':signal,'stockDataValid':stockValid(),'strategy':account(id)['strategy']??'confluence'};
    try {
      var a=account(id);var positions=Map<String,dynamic>.from(a['positions'] as Map);
      final position=positions[symbol] as PaperRow?;
      if(forceClose&&position==null){await _record(id,symbol,'NO_OWNED_POSITION');return;}
      if(position!=null) {
        final reverse=signal!=position['direction']&&['CALL','PUT'].contains(signal)&&confirmedReverse&&stockValid()&&signalCurrent();
        final session=paperSession(now()),expiry=paperExpiry(position['contract'] as String,now());
        final opened=DateTime.parse(position['opened'] as String),qty=position['quantity'] as int;
        final pending=position['closeIntent'] as Map?;
        final overdue=(a['holdingMode']??'swing')=='intraday'&&
          (session.exitDue||paperDate(paperNewYork(opened))!=session.date);
        String? closeReason=forceClose?'MANUAL':pending?['reason'] as String?;
        closeReason??=!expiry.entry?'EXPIRATION_PROTECTION':overdue?'INTRADAY_EXIT':
          now().difference(opened).inHours>=((a['maxHoldingDays']??3) as int)*24?'MAX_HOLDING_EXIT':
          reverse?'CONFIRMED_DIVERGENCE':a['scenarioExit']==true&&stockValid()&&signalCurrent()&&signal=='WAIT'?'SCENARIO_EXIT':null;
        Future<void> retainIntent(String reason,String event) async {
          final next=copy();final p=(_in(next,id)['positions'] as Map)[symbol] as PaperRow;
          // Persist only ownership/intent. No missing-price cash or inventory mutation.
          p['closeIntent']={'reason':reason,'remaining':qty,'at':now().toUtc().toIso8601String()};
          (_in(next,id)['positions'] as Map)[symbol]=p;
          _log(next,id,symbol,event);await _commit(next,admission:()=>_current(id,epoch));
        }
        if(!session.fill||!expiry.close) {
          if(closeReason!=null){await retainIntent(closeReason,!expiry.close?expiry.status:'SESSION_CLOSE_DEFERRED');}
          else{await _record(id,symbol,'SESSION_CLOSED_NO_FILL');}return;
        }
        final q=await quotes(position['contract'] as String);
        if(!_current(id,epoch))return;
        if(q==null||q.contract!=position['contract']||!q.valid(now())) {
          if(closeReason!=null){await retainIntent(closeReason,'CLOSE_UNCONFIRMED_NO_REVERSAL');}
          else{await _record(id,symbol,'CLOSE_UNCONFIRMED_NO_REVERSAL');}return;
        }
        marks[q.contract]=q;
        final average=position['cost']/(qty*100),highest=(position['highBid'] as num).toDouble();
        // Independent price protection has priority over optional analysis.
        closeReason=forceClose?'MANUAL':
          (q.bid<=average*(1-(a['stopPercent'] as int)/100)?'STOP_LOSS':
          q.bid>=average*(1+(a['takePercent'] as int)/100)?'TAKE_PROFIT':
          highest>average&&q.bid<=highest*(1-(a['trailPercent'] as int)/100)?'TRAILING_STOP':closeReason);
        if(closeReason==null&&qty>=2&&position['partialTaken']!=true&&((a['partialPercent']??0) as int)>0&&
          q.bid>=average*(1+((a['partialPercent']??0) as int)/100)) {
          closeReason='PARTIAL_PROFIT';
        }
        if(closeReason!=null) {
          final reason=closeReason;
          final desired=reason=='PARTIAL_PROFIT'?(pending?['remaining'] as int? ?? qty~/2):qty;
          final quoteId='${q.contract}/${q.time.toUtc().toIso8601String()}/${q.bid}/${q.ask}/${q.bidSize}/${q.askSize}';
          if(position['consumedQuote']==quoteId){await _record(id,symbol,'CLOSE_WAIT_NEW_QUOTE');return;}
          final filled=math.min(desired,math.min(q.bidSize,q.askSize));
          final remaining=qty-filled,unfilled=desired-filled;
          final removedCost=(position['cost'] as int)*filled~/qty;
          final entryFees=((position['entryFees']??qty*65) as int)*filled~/qty;
          final pnl=q.bid*filled*100-filled*65-removedCost-entryFees;
          final tradePnl=((position['realizedPnl']??0) as int)+pnl;
          final next=copy(),target=_in(next,id),p=(target['positions'] as Map)[symbol] as PaperRow;
          if(remaining==0){(target['positions'] as Map).remove(symbol);}else{
            p['quantity']=remaining;p['cost']=(position['cost'] as int)-removedCost;
            p['entryFees']=((position['entryFees']??qty*65) as int)-entryFees;p['realizedPnl']=tradePnl;
            p['mark']=_quote(q);p['consumedQuote']=quoteId;
            if(reason=='PARTIAL_PROFIT')p['partialTaken']=true;
            if(unfilled>0){p['closeIntent']={'reason':reason,'remaining':unfilled,'at':pending?['at']??now().toUtc().toIso8601String()};}
            else{p.remove('closeIntent');}
          }
          target['cash']=(target['cash'] as int)+q.bid*filled*100-filled*65;
          if(target['fees'] is int)target['fees']=(target['fees'] as int)+filled*65;
          if(remaining==0&&target['closedTrades'] is int)target['closedTrades']=(target['closedTrades'] as int)+1;
          if(remaining==0&&tradePnl>0&&target['winningTrades'] is int)target['winningTrades']=(target['winningTrades'] as int)+1;
          final day=now().toUtc().toIso8601String().substring(0,10);
          final daily=(target['dailyRealized']??=<String,dynamic>{}) as Map;
          daily[day]=((daily[day]??0) as int)+pnl;
          _log(next,id,symbol,'${remaining==0?'CLOSED':'PARTIAL'}_$reason',quote:q,
            fill:{'side':'SELL_TO_CLOSE','quantity':filled,'price':q.bid,'fee':filled*65,'removedCost':removedCost,
              'entryFees':entryFees,'realizedPnl':pnl,'cashAfter':target['cash']});
          if(!await _commit(next,admission:()=>_current(id,epoch)&&q.valid(now(),quantity:filled)&&paperSession(now()).fill&&paperExpiry(q.contract,now()).close))return;
          if(remaining>0||forceClose||!reverse||!_current(id,epoch)||!stockValid()||!signalCurrent())return;
          if((account(id)['positions'] as Map).containsKey(symbol))return;
        } else {
          if(!stockValid()){await _record(id,symbol,'INVALID_OR_STALE_STOCK_DATA');return;}
          if(signal!=position['direction']&&['CALL','PUT'].contains(signal)) {await _record(id,symbol,'OPPOSITE_POSITION_BLOCKED');return;}
          final next=copy();final target=_in(next,id);final p=(target['positions'] as Map)[symbol] as PaperRow;
          p['mark']=_quote(q);
          if(q.bid>highest)p['highBid']=q.bid;
          if(a['addEnabled']==true&&p['added']!=true&&q.bid>=average*1.10&&signal==p['direction']&&signalCurrent()&&
              (a['watchlist'] is! List||(a['watchlist'] as List).contains(symbol))) {
            if(!await collectMarks())return;
            final cost=q.ask*100+65;
            if(risk(1,q.ask,adding:true)==null) {
              p['quantity']=qty+1;p['cost']=(p['cost'] as int)+q.ask*100;p['added']=true;target['cash']=(target['cash'] as int)-cost;
              p['entryFees']=((p['entryFees']??qty*65) as int)+65;
              if(target['fees'] is int)target['fees']=(target['fees'] as int)+65;
              _log(next,id,symbol,'ADD_ON_OPRA',quote:q,fill:{'side':'BUY','quantity':1,'price':q.ask,'fee':65,'cashAfter':target['cash']});
            } else if(journal.isEmpty||journal.last['account']!=id||journal.last['symbol']!=symbol||journal.last['decision']!='ADD_RISK_LIMIT') {
              _log(next,id,symbol,'ADD_RISK_LIMIT',quote:q);
            }
          }
          final adds=p['quantity']!=qty;
          await _commit(next,admission:()=>_current(id,epoch)&&stockValid()&&signalCurrent()&&q.valid(now(),quantity:qty)&&
            (!adds||risk(1,q.ask,adding:true)==null));return;
        }
      }
      if(!stockValid()){await _record(id,symbol,'INVALID_OR_STALE_STOCK_DATA');return;}
      if(!['CALL','PUT'].contains(signal)||!_current(id,epoch))return;
      a=account(id);
      if(a['watchlist'] is List&&!(a['watchlist'] as List).contains(symbol)){await _record(id,symbol,'ACCOUNT_WATCHLIST_BLOCKED');return;}
      if((a['lastSignal'] as Map)[symbol]==observation)return;
      if(!paperSession(now()).entry){await _record(id,symbol,'SESSION_ENTRY_BLOCKED');return;}
      final contract=(a['contracts'] as Map)['$symbol:$signal'] as String?;
      if(contract==null){await _record(id,symbol,'QUALIFIED_OPTION_CONTRACT_REQUIRED');return;}
      if(!paperExpiry(contract,now()).entry){await _record(id,symbol,'EXPIRY_ENTRY_BLOCKED');return;}
      final q=await quotes(contract);
      if(!_current(id,epoch))return;
      final quantity=a['quantity'] as int;
      if(q==null||q.contract!=contract||q.underlying!=symbol||q.direction!=signal||!q.valid(now(),quantity:quantity)||!stockValid()||!signalCurrent()){
        await _record(id,symbol,'OPRA_QUOTE_REQUIRED_NO_FILL');return;
      }
      marks[q.contract]=q;
      if(!await collectMarks())return;
      final riskReason=risk(quantity,q.ask);
      if(riskReason!=null){await _record(id,symbol,riskReason);return;}
      final next=copy();final target=_in(next,id);positions=Map<String,dynamic>.from(target['positions'] as Map);
      if(positions.containsKey(symbol)){await _record(id,symbol,'OPPOSITE_POSITION_BLOCKED');return;}
      final cost=q.ask*quantity*100,fee=quantity*65;
      if(cost+fee>(target['cash'] as int)||cost+fee>(target['initialCash'] as int)*(target['riskPercent'] as int)/100) {await _record(id,symbol,'RISK_LIMIT');return;}
      positions[symbol]={'contract':contract,'direction':signal,'quantity':quantity,'cost':cost,'entryFees':fee,'mark':_quote(q),
        'highBid':q.bid,'added':false,'realizedPnl':0,'partialTaken':false,'opened':now().toUtc().toIso8601String()};
      target['positions']=positions;target['cash']=(target['cash'] as int)-cost-fee;(target['lastSignal'] as Map)[symbol]=observation;
      if(target['fees'] is int)target['fees']=(target['fees'] as int)+fee;
      _log(next,id,symbol,'OPENED_$signal',quote:q,fill:{'side':'BUY','quantity':quantity,'price':q.ask,'fee':fee,'cashAfter':target['cash']});
      await _commit(next,admission:()=>_current(id,epoch)&&stockValid()&&signalCurrent()&&q.valid(now(),quantity:quantity)&&risk(quantity,q.ask)==null);
    }catch(_){error='توقفت الدورة دون فتح عكسي. راجع البيانات وسعة السجل والتخزين.';notifyListeners();}
    finally{_decisionEvidence=null;busy=false;notifyListeners();}
  }
  Future<void> _record(String id,String symbol,String reason) async {
    if(journal.isNotEmpty&&journal.last['account']==id&&journal.last['symbol']==symbol&&journal.last['decision']==reason)return;
    final next=copy();_log(next,id,symbol,reason);await _commit(next);
  }
}
