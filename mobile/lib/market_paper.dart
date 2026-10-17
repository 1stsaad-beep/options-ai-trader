import 'dart:convert';
import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'direct_alpaca.dart';
import 'market_paper_validation.dart';
import 'market_paper_reports.dart';
import 'market_paper_risk.dart';
import 'market_paper_policy.dart';
import 'market_paper_backup.dart';
import 'market_paper_settlement.dart';
import 'direct_wave_archive.dart';
import 'observed_option_replay.dart';
import 'option_observation_archive.dart';
import 'observed_bar_archive.dart';
import 'paper_money.dart';
import 'delivery_valuation.dart';
import 'paper_execution.dart';
import 'paper_return.dart';
import 'protective_exit.dart';
import 'dart:math' as math;

typedef PaperRow=Map<String,dynamic>;
typedef QuoteReader=Future<OptionQuote?> Function(String contract);

abstract class PaperStore {
  Future<PaperRow?> read();
  Future<void> write(PaperRow value);
}
class OptionalPaperArchiveWriteFailure implements Exception {}
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

/// Android uses real disk readback and atomic compare-and-swap. Legacy prefs
/// migrate once after validation and are retained; no data or key is deleted.
class DevicePaperStore implements PaperStore {
  static const channel=MethodChannel('oat/market_paper_disk');
  final PaperStore legacy;
  String? _observed;
  DevicePaperStore({PaperStore? legacyStore}):legacy=legacyStore??PreferencesPaperStore();
  @override Future<PaperRow?> read() async {
    if(defaultTargetPlatform!=TargetPlatform.android)return legacy.read();
    _observed=await channel.invokeMethod<String>('read');
    if(_observed==null) {
      final saved=await legacy.read();
      if(saved==null)return null;
      validatePaper(saved);
      final text=jsonEncode(saved);
      if(await channel.invokeMethod<bool>('write',{'expected':null,'next':text})!=true)throw StateError('Migration not confirmed');
      _observed=await channel.invokeMethod<String>('read');
      if(_observed!=text)throw StateError('Migration readback differs');
    }
    return jsonDecode(_observed!) as PaperRow;
  }
  @override Future<void> write(PaperRow next) async {
    if(defaultTargetPlatform!=TargetPlatform.android){await legacy.write(next);return;}
    try {
      if(await channel.invokeMethod<bool>('write',{'expected':_observed,'next':jsonEncode(next)})!=true)throw StateError('Disk write not confirmed');
    }on PlatformException catch(error) {
      if(error.code=='PAPER_OPTIONAL_STAGE_FAILED')throw OptionalPaperArchiveWriteFailure();
      rethrow;
    }
  }
}

/// Independent virtual ledger. No Demo imports, no broker submission or stock-price fills.
class MarketPaper extends ChangeNotifier {
  /// One device ledger across routes; a pending quote/save cannot race a second controller.
  static final device=MarketPaper(DevicePaperStore());
  final PaperStore store;
  final DateTime Function() now;
  PaperRow _book={'version':1,'accounts':<dynamic>[],'journal':<dynamic>[]};
  bool ready=false,busy=false;
  String? error;
  String? waveArchiveError;
  String? optionArchiveError;
  String? barArchiveError;
  final _pendingOptionObservations=<PaperRow>[];
  Future<void>? _loading;
  PaperRow? _durable;
  PaperRow? _decisionEvidence;
  final _epochs=<String,int>{};
  final _paused=<String>{};
  MarketPaper(this.store,{DateTime Function()? clock}):now=clock??DateTime.now;
  List<PaperRow> _rows(String key)=>(jsonDecode(jsonEncode(_book[key])) as List).cast<PaperRow>();
  List<PaperRow> get accounts=>_rows('accounts');
  List<PaperRow> get journal=>(jsonDecode(jsonEncode([
    for(final segment in (_book['journalArchive'] as List? ?? [])) ...(segment as List),
    ...(_book['journal'] as List),
  ])) as List).cast<PaperRow>();
  PaperRow account(String id)=>accounts.singleWhere((a)=>a['id']==id);
  PaperRow copy()=>copyPaper(_book);
  PaperRow performance(String id)=>paperPerformance(account(id),now());
  PaperRow comparison()=>paperComparison({...copy(),'journal':journal},now());
  ObservedBarArchive? get barArchive {
    try{return ObservedBarArchive.read(_book['barArchive']);}
    catch(_){barArchiveError='أرشيف شموع القرارات غير متحقق؛ احتُفظ بالأصل. عرض الشارت غير متاح، ودفتر الأموال مستقل عنه.';return null;}
  }
  List<PaperRow> optionObservations(String id) {
    final result=<PaperRow>[];
    try{result.addAll(OptionObservationArchive.read(_book['optionArchive']).observations.where((o)=>o['account']==id));}
    catch(_){optionArchiveError='أرشيف عروض الخيارات غير متحقق؛ احتُفظ بالأصل، ولا يُستبدل بأسعار السهم.';}
    // Original journal receipts already have contemporaneous capture/source
    // facts; old unqualified records are not relabeled or backfilled.
    for(final e in journal.where((e)=>e['account']==id&&e['quote'] is Map)) {
      final o={'account':id,'source':e['evidence']?['source'],'capturedAt':e['at'],'quote':e['quote']};
      try{readOptionObservation(o);result.add(o);}catch(_){ /* Explicitly unavailable legacy evidence. */ }
    }
    final unique=<String,PaperRow>{};
    for(final o in result) {
      final key=paperBytes([o['account'],o['source'],o['quote']]),prior=unique[key];
      if(prior==null||observationStamp(o['capturedAt']).isBefore(observationStamp(prior['capturedAt'])))unique[key]=o;
    }
    return unique.values.toList();
  }
  bool _appendOptionObservations(PaperRow next) {
    if(_pendingOptionObservations.isEmpty)return false;
    try {
      final updated=OptionObservationArchive.read(next['optionArchive']).append(_pendingOptionObservations);
      if(updated==null)return false;
      next['optionArchive']=updated;return true;
    }catch(_){optionArchiveError='تعذر حفظ عروض الخيارات أو بلغ الأرشيف سعته؛ التاريخ السابق محفوظ. إعادة الحساب جزئية.';return false;}
  }
  void _rememberOption(String id,String? source,OptionQuote q) {
    final observation=<String,dynamic>{'account':id,'source':source,'capturedAt':now().toUtc().toIso8601String(),'quote':_quote(q)};
    try{readOptionObservation(observation);_pendingOptionObservations.add(observation);}catch(_){ /* Unqualified observations never enter replay. */ }
  }
  /// Foreground, read-only follow-up for five minutes after an original BUY.
  /// It continues observing a closed position without reopening or rearming it.
  Future<void> observeRecentOptions({required String source,required QuoteReader quotes,required bool Function() active}) async {
    if(!ready||busy||!['alpaca','fixture'].contains(source)||!active())return;
    final targets=<String,Set<String>>{},at=now();
    for(final e in journal) {
      if(e['fill']?['side']!='BUY'||e['evidence']?['source']!=source||e['quote']?['contract'] is! String)continue;
      final age=at.difference(DateTime.parse(e['at'] as String));
      if(age.isNegative||age>const Duration(minutes:5,seconds:30))continue;
      (targets[e['quote']['contract'] as String]??=<String>{}).add(e['account'] as String);
    }
    if(targets.isEmpty)return;
    busy=true;
    try {
      for(final entry in targets.entries.take(20)) {
        if(!ready||!active())return;
        OptionQuote? q;try{q=await quotes(entry.key);}catch(_){continue;}
        if(!ready||!active())return;
        if(q!=null&&q.contract==entry.key){for(final id in entry.value){_rememberOption(id,source,q);}}
      }
      final next=copy();
      if(_appendOptionObservations(next))await _commit(next,admission:()=>ready&&active());
    }finally{_pendingOptionObservations.clear();busy=false;notifyListeners();}
  }
  DirectWaveArchive? get waveArchive {
    try{return DirectWaveArchive.read(_book['waveArchive']);}
    catch(_){waveArchiveError='أرشيف الموجات غير متحقق؛ احتُفظ بأصله دون إعادة كتابة. دفتر التداول مستقل عنه.';return null;}
  }
  Future<void> observeWaves(String symbol,String source,List<MarketBar> bars) async {
    if(!ready||busy||bars.isEmpty)return;
    busy=true;
    try {
      final archive=waveArchive;if(archive==null)return;
      final updated=archive.append(symbol,source,bars,now());if(updated==null)return;
      final next=copy();next['waveArchive']=updated;
      if(await _commit(next)){waveArchiveError=null;}
      else {waveArchiveError='لم يتأكد حفظ رصد الموجات؛ لم يُحذف الأرشيف السابق.';}
    }catch(_){waveArchiveError='تعذر حفظ أرشيف الموجات أو بلغ سعته؛ احتُفظ بالتاريخ السابق. لا ادعاء باستمرارية جديدة.';}
    finally{busy=false;notifyListeners();}
  }
  String exportBackup() {
    if(!ready||busy)throw StateError('Ledger is not stable');
    return PaperBackup.export(copy());
  }
  Future<void> restoreBackup(String text) async {
    if(!ready||busy)throw StateError('Ledger is not stable');
    // Import is allowed only into an empty device ledger. Existing data is never
    // replaced, merged, deleted or silently renamed by a backup operation.
    if(accounts.isNotEmpty||journal.isNotEmpty||_book['waveArchive']!=null||_book['optionArchive']!=null||_book['barArchive']!=null)throw StateError('Restore requires an empty Market Paper ledger and archive');
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
  bool _refreshUnavailableArchives(PaperRow? observed) {
    if(observed==null||_durable==null)return false;
    const keys={'waveArchive','optionArchive','barArchive'};
    PaperRow core(PaperRow value)=>{for(final entry in value.entries)if(!keys.contains(entry.key))entry.key:entry.value};
    if(paperBytes(core(observed))!=paperBytes(core(_durable!)))return false;
    final changed=keys.where((key)=>paperBytes(observed[key])!=paperBytes(_durable![key])).toList();
    if(changed.isEmpty)return false;
    for(final key in changed) {
      final marker=observed[key];
      if(marker is! Map||marker.length!=2||marker['storageUnavailable']!='paper-optional-archive-v1'||
          marker['sha256'] is! String||!RegExp(r'^[0-9a-f]{64}$').hasMatch(marker['sha256'] as String)) {
        return false;
      }
    }
    // Only optional physical availability changed. Discard this uncommitted
    // attempt, retain financial state and let the next cycle use a fresh quote
    // and inline evidence. Never adopt a financial change from another writer.
    for(final key in changed){_book[key]=copyPaper(observed[key] as PaperRow);}
    _durable=copyPaper(observed);
    if(changed.contains('waveArchive'))waveArchiveError='جزء من أرشيف الموجات غير متاح؛ مرجعه الأصلي محفوظ ودفتر الأموال مستقل.';
    if(changed.contains('optionArchive'))optionArchiveError='جزء من أرشيف عروض الخيارات غير متاح؛ لا تُختلق عروض بديلة.';
    if(changed.contains('barArchive'))barArchiveError='جزء من أرشيف الشارت غير متاح؛ تعاد المحاولة بعرض جديد ومصدر القرار المتاح فقط.';
    error='تغير توفر أرشيف اختياري؛ لم تُعتمد العملية الحالية. دفتر الأموال سليم ويمكن إعادة المحاولة.';
    notifyListeners();return true;
  }
  PaperRow _retainPriorArchives(PaperRow candidate) {
    final next=copyPaper(candidate),prior=_durable??{'version':1,'accounts':<dynamic>[],'journal':<dynamic>[]};
    List<dynamic> events(PaperRow value)=>[for(final segment in value['journalArchive'] as List? ?? [])...(segment as List),...(value['journal'] as List)];
    final original=events(prior),updated=events(next);
    if(updated.length<original.length)throw StateError('Original journal shortened');
    for(var i=0;i<original.length;i++) {
      if(paperBytes(original[i])!=paperBytes(updated[i]))throw StateError('Original receipt changed');
    }
    // Only uncommitted new references are materialized from their actual saved
    // candidate source. Original committed decisions are never rewritten.
    for(final event in updated.skip(original.length)) {
      final evidence=event['evidence'];
      if(evidence is Map&&evidence.containsKey('barReference')) {
        final bars=ObservedBarArchive.read(next['barArchive']).resolve(event['symbol'] as String,
          Map<String,dynamic>.from(evidence),observationStamp(event['at']));
        evidence.remove('barReference');evidence['bars']=bars;
      }
    }
    for(final key in const ['waveArchive','optionArchive','barArchive']) {
      if(prior.containsKey(key)){next[key]=prior[key];}else{next.remove(key);}
    }
    return next;
  }
  Future<bool> _commit(PaperRow next,{bool Function()? admission,bool captureOptional=true,bool allowArchiveFallback=true}) async {
    if(!ready)return false;
    if(captureOptional)_appendOptionObservations(next);
    final optionCapture=_pendingOptionObservations.isNotEmpty&&paperBytes(next['optionArchive'])!=paperBytes(_book['optionArchive']);
    final barCapture=paperBytes(next['barArchive'])!=paperBytes(_book['barArchive']);
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
      final observed=await store.read();
      if(paperBytes(observed)!=paperBytes(_durable)) {
        if(!_refreshUnavailableArchives(observed))_uncertain();
        return false;
      }
    }catch(_){_uncertain();return false;}
    if(admission!=null&&!admission())return false;
    var archiveStageFailed=false;
    try {await store.write(copyPaper(next));}
    on OptionalPaperArchiveWriteFailure {archiveStageFailed=true;}
    catch(_){ /* Readback resolves a lost acknowledgement. */ }
    PaperRow? observed;
    try {observed=await store.read();}catch(_){_uncertain();return false;}
    if(paperBytes(observed)==paperBytes(next)) {
      _durable=copyPaper(next);_book=copyPaper(next);error=null;
      if(optionCapture)optionArchiveError=null;
      if(barCapture)barArchiveError=null;
      notifyListeners();return true;
    }
    if(paperBytes(observed)!=paperBytes(_durable)){_uncertain();return false;}
    if(archiveStageFailed&&allowArchiveFallback) {
      final fallback=_retainPriorArchives(next);
      if(paperBytes(fallback)!=paperBytes(_durable)) {
        final committed=await _commit(fallback,admission:admission,captureOptional:false,allowArchiveFallback:false);
        if(optionCapture)optionArchiveError='تعذر حفظ الرصد الاختياري الجديد؛ الأرشيف السابق محفوظ وعروض التعبئة الأصلية في الدفتر.';
        if(barCapture)barArchiveError='تعذرت كتابة أرشيف جديد؛ حُفظ مصدر القرار المتاح داخل سجله فقط عند تأكيد العملية.';
        return committed;
      }
    }
    error='لم يُحفظ التغيير؛ بقي الدفتر السابق مؤكدًا. لم تُعتمد تعبئة أو عملية عكس.';
    if(optionCapture)optionArchiveError='لم يتأكد حفظ عروض الخيارات؛ لم يُعتمد تاريخ جديد.';
    if(barCapture)barArchiveError='لم يتأكد حفظ شموع القرار؛ لم يُعتمد مرجع جديد.';
    notifyListeners();return false;
  }
  PaperRow _in(PaperRow book,String id)=>(book['accounts'] as List).cast<PaperRow>().singleWhere((a)=>a['id']==id);
  PaperRow _quote(OptionQuote q)=>{'contract':q.contract,'feed':q.feed,'at':q.time.toUtc().toIso8601String(),
    'bid':q.bid,'ask':q.ask,'bidSize':q.bidSize,'askSize':q.askSize};
  void _log(PaperRow book,String id,String symbol,String decision,{OptionQuote? quote,PaperRow? fill,DateTime? at}) {
    final eventAt=at??now(),evidence=_decisionEvidence==null?null:copyPaper(_decisionEvidence!);
    if(evidence!=null&&evidence['bars'] is List&&(evidence['bars'] as List).isNotEmpty) {
      try {
        final captured=ObservedBarArchive.read(book['barArchive']).capture(symbol,evidence,eventAt);
        book['barArchive']=captured.archive.toJson();
        evidence.remove('bars');evidence['barReference']=captured.reference;
      }catch(_){barArchiveError='تعذر أرشفة مصدر الشارت أو بلغ سعته؛ المصدر المتاح ضمن القرار بدل مرجع جديد، ويُعتمد فقط بعد تأكيد حفظ الدفتر.';}
    }
    var rows=book['journal'] as List;
    if(rows.length>=1000) {
      final archive=(book['journalArchive']??=<dynamic>[]) as List;
      archive.add(rows);
      rows=<dynamic>[];book['journal']=rows;
    }
    rows.add({'account':id,'symbol':symbol,'at':eventAt.toUtc().toIso8601String(),'decision':decision,
      if(quote!=null)'quote':_quote(quote),if(fill!=null)'fill':copyPaper(fill),
      if(evidence!=null)'evidence':evidence});
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
  Future<void> add(String name,{int initialCash=1000000,String strategy='confluence',String executionPolicy=legacyExecution}) async {
    if(!ready||busy||name.trim().isEmpty)return;
    if(![legacyExecution,conservativeExecution].contains(executionPolicy))throw ArgumentError('executionPolicy');
    if(initialCash<10000||initialCash>100000000||!paperStrategyLabels.containsKey(strategy))throw ArgumentError('account');
    busy=true;
    try {final next=copy();(next['accounts'] as List).add(_newAccount('mp-${now().microsecondsSinceEpoch}-${accounts.length}',name,initialCash,strategy)..['executionPolicy']=executionPolicy);
      await _commit(next);
    }finally{busy=false;notifyListeners();}
  }
  Future<PaperRow> settle(String id,PaperRow request) async {
    if(!ready||busy)throw StateError('Ledger is not available');
    if(account(id)['ledgerPolicy']!='receipt-v2')throw StateError('Complete original receipts required');
    for(final e in journal.where((e)=>e['account']==id&&e['settlement'] is Map)) {
      final prior=e['settlement'] as Map;
      if(prior['request']['id']==request['id']) {
        if(paperBytes(prior['request'])!=paperBytes(request))throw StateError('Receipt identity conflict');
        return copyPaper(prior['result'] as PaperRow);
      }
    }
    if(account(id)['enabled']==true)throw StateError('Stop account automation before a manual settlement');
    if(request['action']!='SELL_DELIVERY') {
      final effective=DateTime.tryParse('${request['effectiveAt']}');
      if(effective==null||journal.any((e)=>e['account']==id&&e['fill']?['side']=='BUY'&&
          e['quote']?['contract']==request['contract']&&DateTime.parse(e['at'] as String).isAfter(effective))) {
        throw const FormatException('Receipt predates acquisition; historical lot reconstruction required');
      }
    }
    busy=true;notifyListeners();final epoch=_epochs[id]??0;
    try {
      final at=now(),next=copy();
      final applied=applyPaperSettlement(account(id),request,at);
      final rows=(next['accounts'] as List);rows[rows.indexWhere((a)=>a['id']==id)]=applied['account'];
      _log(next,id,applied['result']['symbol'] as String,'PAPER_SETTLEMENT_${request['action']}',at:at);
      (next['journal'] as List).last['settlement']={'request':copyPaper(request),'result':applied['result']};
      if(!await _commit(next,admission:()=>ready&&(_epochs[id]??0)==epoch&&account(id)['enabled']==false)) {
        throw StateError('Settlement storage not confirmed');
      }
      return copyPaper(applied['result'] as PaperRow);
    }finally{busy=false;notifyListeners();}
  }
  /// Read-only provider observations; never accepts prices through configure or settlement.
  Future<void> observeDeliveries({required String source,required Future<PaperRow?> Function(String) quotes,
      required bool Function() active}) async {
    if(!ready||busy||!['fixture','alpaca'].contains(source)||!active())return;
    final symbols={for(final a in accounts)...(a['deliveryPositions'] as Map? ?? {}).keys.cast<String>()};
    if(symbols.isEmpty)return;
    busy=true;
    try {
      final observed=<String,PaperRow>{};
      for(final symbol in symbols) {
        if(!active()||!ready)return;
        PaperRow? quote;try{quote=await quotes(symbol);}catch(_){continue;}
        if(!active()||!ready)return;
        if(quote==null)continue;
        final candidate={...quote,'capturedAt':now().toUtc().toIso8601String()};
        final check=valueDeliveries({symbol:{'quantity':1,'cost':1}},{symbol:candidate},now(),source);
        if(check['complete']==true)observed[symbol]=candidate;
      }
      if(observed.isEmpty)return;
      final next=copy();var changed=false;
      for(final a in next['accounts'] as List) {
        final marks=Map<String,dynamic>.from(a['deliveryMarks'] as Map? ?? {});
        for(final symbol in (a['deliveryPositions'] as Map? ?? {}).keys) {
          final quote=observed[symbol];if(quote==null)continue;
          final previous=marks[symbol];
          if(previous is Map&&previous['source']==source&&previous['feed']==quote['feed']) {
            final oldAt=DateTime.tryParse('${previous['at']}'),at=DateTime.parse(quote['at'] as String);
            if(oldAt!=null&&!at.isAfter(oldAt))continue; // Never refresh age or rewrite an equal-time observation.
          }
          marks[symbol]=quote;changed=true;
        }
        a['deliveryMarks']=marks;a['deliveryMarkSource']=source;
      }
      if(changed)await _commit(next,admission:()=>ready&&active());
    }finally{busy=false;notifyListeners();}
  }
  Future<void> createComparisonExperiment({String executionPolicy=legacyExecution}) async {
    if(![legacyExecution,conservativeExecution].contains(executionPolicy))throw ArgumentError('executionPolicy');
    if(!ready||busy||_book['experiment']!=null)return;
    busy=true;
    try {
      final next=copy(),ids=<String>[];
      for(final strategy in paperStrategies) {
        final id='mp-experiment-v1-$strategy';
        if(accounts.any((a)=>a['id']==id))throw StateError('experiment identity conflict');
        ids.add(id);
        (next['accounts'] as List).add(_newAccount(id,'1000 USD • ${paperStrategyLabels[strategy]}',100000,strategy)..['executionPolicy']=executionPolicy);
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
    if(values.containsKey('executionPolicy')&&(account(id)['enabled']==true||values['enabled']==true))throw ArgumentError('Stop before changing execution policy');
    final allowed={'executionPolicy','enabled','contracts','riskPercent','quantity','stopPercent','takePercent','trailPercent','addEnabled','strategy','watchlist',
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
  bool _current(String id,int epoch,{bool manualClose=false})=>ready&&(_epochs[id]??0)==epoch&&
    (manualClose||(!_paused.contains(id)&&account(id)['enabled']==true));
  Future<void> evaluate({required String id,required String symbol,required String signal,
    required bool confirmedReverse,required bool Function() dataValid,required String observation,required QuoteReader quotes,
    bool forceClose=false,PaperRow? evidence,String Function()? currentSignal,
    bool Function()? scenarioInvalidated,bool Function()? currentReverse}) async {
    if(!ready||busy||(!forceClose&&(_paused.contains(id)||account(id)['enabled']!=true)))return;
    busy=true;notifyListeners();final epoch=_epochs[id]??0;
    // Explicit owned-position reduction does not arm automation. Lifecycle and
    // configuration changes still invalidate its in-flight quote/readback.
    bool current()=>_current(id,epoch,manualClose:forceClose);
    bool stockValid(){try{return dataValid();}catch(_){return false;}}
    bool signalCurrent(){try{return currentSignal==null||currentSignal()==signal;}catch(_){return false;}}
    bool scenarioBroken(){try{return scenarioInvalidated?.call()==true;}catch(_){return false;}}
    bool reverseCurrent(){try{return confirmedReverse&&(currentReverse?.call()??true)&&stockValid()&&signalCurrent();}catch(_){return false;}}
    Future<OptionQuote?> readQuote(String contract) async {
      final q=await quotes(contract);
      if(current()&&q!=null&&q.contract==contract)_rememberOption(id,_decisionEvidence?['source'] as String?,q);
      return q;
    }
    PaperRow? execution(OptionQuote q,String side,int quantity) {
      if(account(id)['executionPolicy']!=conservativeExecution)return null;
      final used=optionConsumption(journal,id,_quote(q));
      if(used.blocked)return {'quantity':0,'status':'QUOTE_ALREADY_CONSUMED_OR_REVISED'};
      return projectOptionExecution(_quote(q),side,quantity,used.consumed,now());
    }
    final marks=<String,OptionQuote>{};
    Future<bool> collectMarks() async {
      for(final p in (account(id)['positions'] as Map).values) {
        final contract=p['contract'] as String;
        if(!marks.containsKey(contract)) {
          final q=await readQuote(contract);
          if(!current())return false;
          if(q!=null&&q.contract==contract)marks[contract]=q;
        }
      }
      return current();
    }
    String? risk(int qty,int price,{bool adding=false}) {
      // OPRA quote validity does not establish Greeks or deliverable identity.
      // Only explicit fixtures have standard-contract assumptions. No public
      // input or indicative quote can unlock market-priced entry or addition.
      if(_decisionEvidence?['source']!='fixture')return 'CONTRACT_ELIGIBILITY_UNVERIFIED';
      if(!paperSession(now()).entry)return 'SESSION_ENTRY_BLOCKED';
      if(!paperExpiry(marks.values.firstWhere((q)=>q.underlying==symbol&&q.direction==signal).contract,now()).entry)return 'EXPIRY_ENTRY_BLOCKED';
      if((account(id)['positions'] as Map).values.any((p)=>p['closeIntent']!=null))return 'PENDING_CLOSE_RISK_LIMIT';
      return paperRiskReason(account(id),symbol,qty,price,marks,now(),journal:journal,adding:adding,source:_decisionEvidence?['source'] as String? ?? 'fixture',feePerContract:executionFee(account(id)));
    }
    _decisionEvidence={...copyPaper(evidence??{'source':'fixture'}),'observation':observation,
      'signal':signal,'stockDataValid':stockValid(),'strategy':account(id)['strategy']??'confluence',
      'admissionContract':'observed-contract-admission-v1',
      'protectionContract':account(id)['executionPolicy']==conservativeExecution?'net-liquidation-protection-v1':'legacy-price-thresholds'};
    try {
      var a=account(id);var positions=Map<String,dynamic>.from(a['positions'] as Map);
      final position=positions[symbol] as PaperRow?;
      if(forceClose&&position==null){await _record(id,symbol,'NO_OWNED_POSITION');return;}
      if(position!=null) {
        final reverse=signal!=position['direction']&&['CALL','PUT'].contains(signal)&&reverseCurrent();
        final session=paperSession(now()),expiry=paperExpiry(position['contract'] as String,now());
        final opened=DateTime.parse(position['opened'] as String),qty=position['quantity'] as int;
        final pending=position['closeIntent'] as Map?;
        final overdue=(a['holdingMode']??'swing')=='intraday'&&
          (session.exitDue||paperDate(paperNewYork(opened))!=session.date);
        String? closeReason=forceClose?'MANUAL':pending?['reason'] as String?;
        closeReason??=!expiry.entry?'EXPIRATION_PROTECTION':overdue?'INTRADAY_EXIT':
          now().difference(opened).inHours>=((a['maxHoldingDays']??3) as int)*24?'MAX_HOLDING_EXIT':
          reverse?'CONFIRMED_DIVERGENCE':a['scenarioExit']==true&&stockValid()&&scenarioBroken()?'SCENARIO_EXIT':null;
        Future<void> retainIntent(String reason,String event) async {
          final next=copy();final p=(_in(next,id)['positions'] as Map)[symbol] as PaperRow;
          // Persist only ownership/intent. No missing-price cash or inventory mutation.
          p['closeIntent']={'reason':reason,'remaining':pending!=null&&pending['reason']==reason?pending['remaining']:qty,
            'at':pending!=null&&pending['reason']==reason?pending['at']:now().toUtc().toIso8601String()};
          (_in(next,id)['positions'] as Map)[symbol]=p;
          _log(next,id,symbol,event);await _commit(next,admission:()=>current());
        }
        if(!session.fill||!expiry.close) {
          if(closeReason!=null){await retainIntent(closeReason,!expiry.close?expiry.status:'SESSION_CLOSE_DEFERRED');}
          else{await _record(id,symbol,'SESSION_CLOSED_NO_FILL');}return;
        }
        final q=await readQuote(position['contract'] as String);
        if(!current())return;
        if(q==null||q.contract!=position['contract']||!q.valid(now())) {
          if(closeReason!=null){await retainIntent(closeReason,'CLOSE_UNCONFIRMED_NO_REVERSAL');}
          else{await _record(id,symbol,'CLOSE_UNCONFIRMED_NO_REVERSAL');}return;
        }
        marks[q.contract]=q;
        final average=position['cost']/(qty*100),highest=(position['highBid'] as num).toDouble();
        final net=PaperReturn(a,position,q.bid),costed=a['executionPolicy']==conservativeExecution;
        // Shared rule (protective_exit.dart): raw bid or costed liquidation, same priority everywhere.
        final hundred=BigInt.from(qty*100);
        final protective=costed
            ?protectiveExit(basis:net.basis,value:net.liquidation,peak:net.peak>net.liquidation?net.peak:net.liquidation,
                stopPercent:a['stopPercent'] as int,takePercent:a['takePercent'] as int,trailPercent:a['trailPercent'] as int)
            :protectiveExit(basis:BigInt.from(position['cost'] as int),value:BigInt.from(q.bid)*hundred,
                peak:BigInt.from(math.max(highest.toInt(),q.bid))*hundred,
                stopPercent:a['stopPercent'] as int,takePercent:a['takePercent'] as int,trailPercent:a['trailPercent'] as int);
        // Independent price protection has priority over optional analysis.
        closeReason=forceClose?'MANUAL':(protective??closeReason);
        if(closeReason==null&&qty>=2&&position['partialTaken']!=true&&((a['partialPercent']??0) as int)>0&&
          (costed?net.gainAtLeast(a['partialPercent'] as int):q.bid>=average*(1+((a['partialPercent']??0) as int)/100))) {
          closeReason='PARTIAL_PROFIT';
        }
        if(closeReason!=null) {
          final reason=closeReason;
          final desired=reason=='PARTIAL_PROFIT'?(pending?['remaining'] as int? ?? qty~/2):qty;
          final quoteId='${q.contract}/${q.time.toUtc().toIso8601String()}/${q.bid}/${q.ask}/${q.bidSize}/${q.askSize}';
          if(position['consumedQuote']==quoteId||(position['lastCloseQuoteAt'] is String&&!q.time.isAfter(DateTime.parse(position['lastCloseQuoteAt'] as String)))){await _record(id,symbol,'CLOSE_WAIT_NEW_QUOTE');return;}
          final modeled=execution(q,'SELL_TO_CLOSE',desired);
          if(modeled!=null&&modeled['quantity']==0){await retainIntent(reason,'CLOSE_${modeled['status']}');return;}
          final filled=modeled?['quantity'] as int? ?? math.min(desired,math.min(q.bidSize,q.askSize));
          final fillPrice=modeled?['priceCents'] as int? ?? q.bid,fee=modeled?['feeCents'] as int? ?? filled*65;
          final remaining=qty-filled,unfilled=desired-filled;
          final removedCost=paperPortion(position['cost'] as int,filled,qty);
          final entryFees=paperPortion((position['entryFees']??qty*65) as int,filled,qty);
          final gross=paperProduct(paperProduct(fillPrice,filled),100);
          final pnl=gross-fee-removedCost-entryFees;
          final tradePnl=((position['realizedPnl']??0) as int)+pnl;
          final next=copy(),target=_in(next,id),p=(target['positions'] as Map)[symbol] as PaperRow;
          if(remaining==0){(target['positions'] as Map).remove(symbol);}else{
            p['quantity']=remaining;p['cost']=(position['cost'] as int)-removedCost;
            p['entryFees']=((position['entryFees']??qty*65) as int)-entryFees;p['realizedPnl']=tradePnl;
            p['mark']=_quote(q);p['consumedQuote']=quoteId;p['lastCloseQuoteAt']=q.time.toUtc().toIso8601String();
            if(reason=='PARTIAL_PROFIT')p['partialTaken']=true;
            if(unfilled>0){p['closeIntent']={'reason':reason,'remaining':unfilled,'at':pending?['at']??now().toUtc().toIso8601String()};}
            else{p.remove('closeIntent');}
          }
          target['cash']=paperSum(target['cash'] as int,gross-fee);
          if(target['fees'] is int)target['fees']=(target['fees'] as int)+fee;
          if(remaining==0&&target['closedTrades'] is int)target['closedTrades']=(target['closedTrades'] as int)+1;
          if(remaining==0&&tradePnl>0&&target['winningTrades'] is int)target['winningTrades']=(target['winningTrades'] as int)+1;
          final day=now().toUtc().toIso8601String().substring(0,10);
          final daily=(target['dailyRealized']??=<String,dynamic>{}) as Map;
          daily[day]=((daily[day]??0) as int)+pnl;
          _log(next,id,symbol,'${remaining==0?'CLOSED':'PARTIAL'}_$reason',quote:q,
            fill:{'side':'SELL_TO_CLOSE','quantity':filled,'price':fillPrice,'fee':fee,if(modeled!=null)'execution':modeled,'removedCost':removedCost,
              'entryFees':entryFees,'realizedPnl':pnl,'cashAfter':target['cash']});
          if(!await _commit(next,admission:()=>current()&&q.valid(now(),quantity:filled)&&paperSession(now()).fill&&paperExpiry(q.contract,now()).close&&
            (pending!=null||reason!='CONFIRMED_DIVERGENCE'||reverseCurrent())&&
            (pending!=null||reason!='SCENARIO_EXIT'||(stockValid()&&scenarioBroken())))) {
            return;
          }
          if(remaining>0||forceClose||!reverse||!reverseCurrent()||!current()||!stockValid()||!signalCurrent())return;
          if((account(id)['positions'] as Map).containsKey(symbol))return;
        } else {
          if(!stockValid()){await _record(id,symbol,'INVALID_OR_STALE_STOCK_DATA');return;}
          if(signal!=position['direction']&&['CALL','PUT'].contains(signal)) {await _record(id,symbol,'OPPOSITE_POSITION_BLOCKED');return;}
          final next=copy();final target=_in(next,id);final p=(target['positions'] as Map)[symbol] as PaperRow;
          p['mark']=_quote(q);
          if(q.bid>highest)p['highBid']=q.bid;
          if(a['addEnabled']==true&&p['added']!=true&&(costed?net.gainAtLeast(10):q.bid>=average*1.10)&&signal==p['direction']&&signalCurrent()&&
              (a['watchlist'] is! List||(a['watchlist'] as List).contains(symbol))) {
            if(!await collectMarks())return;
            final modeled=execution(q,'BUY',1),fillPrice=q.ask+executionSlippage(a),fee=executionFee(a);
            final cost=fillPrice*100+fee;
            final additionRisk=risk(1,fillPrice,adding:true);
            final additionBlock=additionRisk=='CONTRACT_ELIGIBILITY_UNVERIFIED'?'CONTRACT_ELIGIBILITY_UNVERIFIED':'ADD_RISK_LIMIT';
            if((modeled==null||modeled['quantity']==1)&&additionRisk==null) {
              p['quantity']=qty+1;p['cost']=(p['cost'] as int)+fillPrice*100;p['added']=true;target['cash']=(target['cash'] as int)-cost;
              p['entryFees']=((p['entryFees']??qty*65) as int)+fee;
              if(target['fees'] is int)target['fees']=(target['fees'] as int)+fee;
              _log(next,id,symbol,'ADD_ON_OPRA',quote:q,fill:{'side':'BUY','quantity':1,'price':fillPrice,'fee':fee,if(modeled!=null)'execution':modeled,'cashAfter':target['cash']});
            } else if(journal.isEmpty||journal.last['account']!=id||journal.last['symbol']!=symbol||journal.last['decision']!=additionBlock) {
              _log(next,id,symbol,additionBlock,quote:q);
            }
          }
          final adds=p['quantity']!=qty;
          await _commit(next,admission:()=>current()&&stockValid()&&signalCurrent()&&q.valid(now(),quantity:qty)&&
            (!adds||risk(1,q.ask+executionSlippage(a),adding:true)==null));return;
        }
      }
      if(!stockValid()){await _record(id,symbol,'INVALID_OR_STALE_STOCK_DATA');return;}
      if(!['CALL','PUT'].contains(signal)||!current())return;
      a=account(id);
      if(a['watchlist'] is List&&!(a['watchlist'] as List).contains(symbol)){await _record(id,symbol,'ACCOUNT_WATCHLIST_BLOCKED');return;}
      if((a['lastSignal'] as Map)[symbol]==observation)return;
      if(!paperSession(now()).entry){await _record(id,symbol,'SESSION_ENTRY_BLOCKED');return;}
      final contract=(a['contracts'] as Map)['$symbol:$signal'] as String?;
      if(contract==null){await _record(id,symbol,'QUALIFIED_OPTION_CONTRACT_REQUIRED');return;}
      if(!paperExpiry(contract,now()).entry){await _record(id,symbol,'EXPIRY_ENTRY_BLOCKED');return;}
      if(_decisionEvidence?['source']!='fixture'){await _record(id,symbol,'CONTRACT_ELIGIBILITY_UNVERIFIED');return;}
      final q=await readQuote(contract);
      if(!current())return;
      final requested=a['quantity'] as int;
      if(q==null||q.contract!=contract||q.underlying!=symbol||q.direction!=signal||!q.valid(now(),quantity:a['executionPolicy']==conservativeExecution?1:requested)||!stockValid()||!signalCurrent()){
        await _record(id,symbol,'OPRA_QUOTE_REQUIRED_NO_FILL');return;
      }
      marks[q.contract]=q;
      if(!await collectMarks())return;
      final modeled=execution(q,'BUY',requested);
      if(modeled!=null&&modeled['quantity']==0){await _record(id,symbol,'ENTRY_${modeled['status']}');return;}
      final quantity=modeled?['quantity'] as int? ?? requested,fillPrice=modeled?['priceCents'] as int? ?? q.ask;
      final riskReason=risk(quantity,fillPrice);
      if(riskReason!=null){await _record(id,symbol,riskReason);return;}
      final next=copy();final target=_in(next,id);positions=Map<String,dynamic>.from(target['positions'] as Map);
      if(positions.containsKey(symbol)){await _record(id,symbol,'OPPOSITE_POSITION_BLOCKED');return;}
      final cost=fillPrice*quantity*100,fee=modeled?['feeCents'] as int? ?? quantity*65;
      if(cost+fee>(target['cash'] as int)||cost+fee>(target['initialCash'] as int)*(target['riskPercent'] as int)/100) {await _record(id,symbol,'RISK_LIMIT');return;}
      final scenarioLevel=evidence?['scenarioLevel'];
      positions[symbol]={'contract':contract,'direction':signal,'quantity':quantity,'cost':cost,'entryFees':fee,'mark':_quote(q),
        if(scenarioLevel is num&&scenarioLevel.isFinite&&scenarioLevel>0)'scenarioLevel':scenarioLevel,
        'highBid':q.bid,'added':false,'realizedPnl':0,'partialTaken':false,'opened':now().toUtc().toIso8601String()};
      target['positions']=positions;target['cash']=(target['cash'] as int)-cost-fee;(target['lastSignal'] as Map)[symbol]=observation;
      if(target['fees'] is int)target['fees']=(target['fees'] as int)+fee;
      _log(next,id,symbol,'OPENED_$signal',quote:q,fill:{'side':'BUY','quantity':quantity,'price':fillPrice,'fee':fee,if(modeled!=null)'execution':modeled,'cashAfter':target['cash']});
      await _commit(next,admission:()=>current()&&stockValid()&&signalCurrent()&&q.valid(now(),quantity:quantity)&&risk(quantity,fillPrice)==null);
    }catch(_){error='توقفت الدورة دون فتح عكسي. راجع البيانات وسعة السجل والتخزين.';notifyListeners();}
    finally{_decisionEvidence=null;_pendingOptionObservations.clear();busy=false;notifyListeners();}
  }
  Future<void> _record(String id,String symbol,String reason) async {
    if(journal.isNotEmpty&&journal.last['account']==id&&journal.last['symbol']==symbol&&journal.last['decision']==reason) {
      final next=copy();if(_appendOptionObservations(next))await _commit(next);return;
    }
    final next=copy();_log(next,id,symbol,reason);await _commit(next);
  }
}
