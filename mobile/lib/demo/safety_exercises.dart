// In-memory exercises use the production local DemoEngine, never the user's
// engine/store. No network, broker, clock override or mocked signal provider.
import 'dart:convert';
import 'engine.dart';

class DemoExerciseResult {
  final String name;
  final bool passed;
  final List<String> evidence;
  final DemoRow ledger;
  const DemoExerciseResult(this.name,this.passed,this.evidence,this.ledger);
}

class DemoSafetyExercises {
  static List<DemoExerciseResult> run({DemoEngine Function()? factory}) => [
    for(final reason in ['وقف خسارة','جني ربح','وقف متحرك'])
      _run(reason,factory??DemoEngine.new,(e,trace)=>_exit(e,trace,reason)),
    _run('Call → Put',factory??DemoEngine.new,(e,trace)=>_reverse(e,trace,'AAPL','CALL','PUT')),
    _run('Put → Call',factory??DemoEngine.new,(e,trace)=>_reverse(e,trace,'NVDA','PUT','CALL')),
  ];

  static void _check(bool condition,String explanation,List<String> trace) {
    if(!condition)throw StateError(explanation);
    trace.add(explanation);
  }
  static DemoExerciseResult _run(String name,DemoEngine Function() factory,
      void Function(DemoEngine,List<String>) exercise) {
    final e=factory(),trace=<String>[];
    try {
      exercise(e,trace);e.validate();
      return DemoExerciseResult(name,true,List.unmodifiable(trace),jsonDecode(e.encode()) as DemoRow);
    } catch(error) {
      trace.add('فشل: $error');
      return DemoExerciseResult(name,false,List.unmodifiable(trace),{});
    }
  }

  static void _exit(DemoEngine e,List<String> trace,String reason) {
    final a=e.createAccount('حماية معزولة',2000000),id=a['id'] as String;
    final entry=e.submit(id,e.contract('NVDA','CALL'),'BUY',1,'exercise-entry');
    e.step(enter:false);
    _check(entry['status']=='FILLED','شراء اصطناعي كامل عند #${e.tick}',trace);
    e.configure(id,{'automation':true,
      if(reason=='وقف متحرك') ...{'take_pct':500,'trailing_pct':20}});
    final riskBefore=jsonEncode(e.risk(a));
    if(reason=='وقف متحرك') {
      e.scenario='rally';e.step(enter:false);
      _check(e.rows(a,'orders').length==1,'تسجيل قمة 165 سنتًا دون خروج مبكر',trace);
      e.scenario='flat';
    } else {e.scenario=reason=='وقف خسارة'?'drop':'rally';}
    e.step(enter:false);
    final p=e.rows(a,'positions').single,r=e.risk(a);
    final mark=(p['last_bid'] as int)*(p['quantity'] as int)*100;
    final condition=reason=='وقف خسارة'?mark*100<=p['cost']*(100-r['stop_pct']):
      reason=='جني ربح'?mark*100>=p['cost']*(100+r['take_pct']):
      p['high_bid']>p['cost']/p['quantity']/100 && p['last_bid']*100<=p['high_bid']*(100-r['trailing_pct']);
    _check(condition,'تحقق الشرط عند #${e.tick}: mark=$mark cost=${p['cost']} high_bid=${p['high_bid']}',trace);
    final close=e.rows(a,'orders').last;
    _check(close['side']=='SELL_TO_CLOSE' && close['reason']==reason && close['filled']==0,
      'أُنشئ $reason؛ لا تنفيذ في ملاحظة القرار نفسها',trace);
    final decisionTick=e.tick;
    e.step(enter:false);
    _check(close['status']=='FILLED' && e.rows(a,'positions').isEmpty &&
      (close['fills'] as List).every((f)=>f['tick']>decisionTick),'إغلاق كامل في الملاحظة التالية',trace);
    _check(jsonEncode(e.risk(a))==riskBefore,'إعدادات حساب الاختبار ثابتة أثناء تحقق الخروج',trace);
    _check(a['cash']==a['initial']+e.realized(a) && e.performance(id)['fees']==130,
      'مصالحة الرسوم 130 سنتًا والرصيد وP&L=${e.realized(a)} سنت',trace);
    _check(DemoEngine.decode(e.encode()).encode()==e.encode(),'استعادة دفتر الاختبار دون تغيير',trace);
  }

  static void _reverse(DemoEngine e,List<String> trace,String symbol,String oldRight,String newRight) {
    var a=e.createAccount('انعكاس معزول',2000000);final id=a['id'] as String;
    final contract=e.contract(symbol,oldRight);
    try {e.submit(id,contract,'BUY',3,'exercise-entry',loseResponse:true);} on DemoRejected { /* receipt checked below */ }
    _check(a['known']==false && e.rows(a,'orders').length==1,'فقد الرد: أمر واحد محفوظ والحساب غير محسوم',trace);
    final retry=e.submit(id,contract,'BUY',3,'exercise-entry');
    _check(retry['filled']==0 && e.rows(a,'orders').length==1,'إعادة الطلب بالمفتاح نفسه لا تنشئ أمرًا مكررًا',trace);
    e.step(enter:false);_check(retry['filled']==0,'عدم اليقين يمنع التنفيذ',trace);
    e.reconcile(id);
    for(var i=0;i<3;i++) {e.step(enter:false);}
    // Lost-response time consumed one tick; order TTL can cancel the unfilled
    // remainder. Use a fresh owned entry only after a known terminal status.
    final owned=e.rows(a,'positions').single['quantity'] as int;
    if(owned<3) {
      e.submit(id,contract,'BUY',3-owned,'exercise-known-remainder');
      for(var i=owned;i<3;i++) {e.step(enter:false);}
    }
    _check(e.rows(a,'positions').single['quantity']==3,'ثلاثة عقود مملوكة بإيصالات فعلية',trace);
    final pending=e.submit(id,e.contract(symbol,oldRight,
      strike:(contract['strike'] as int)+500),'BUY',1,'exercise-pending');
    final reversal=e.requestReversal(id,symbol,newRight,'exercise-reversal');
    _check(pending['status']=='CANCELLED' && reversal['state']=='CLOSING',
      'إشارة كمية أصلية إلى $newRight؛ أُلغي الدخول المعلق قبل الإغلاق',trace);
    e.step(enter:false);
    _check(e.rows(a,'positions').single['quantity']==2 && reversal['entry_order']==null,
      'إغلاق جزئي 1/3؛ لم يُفتح الاتجاه المقابل',trace);
    e.disconnect(id);e.step(enter:false);
    _check(e.rows(a,'positions').single['quantity']==2 && reversal['entry_order']==null,
      'الانقطاع يوقف التقدم ويحفظ المملوك',trace);
    // Exercise serialized restart through the real decoder, then copy only
    // the restored temporary state into this isolated instance for evidence.
    final restored=DemoEngine.decode(e.encode());
    e.accounts.clear();e.accounts.addAll(restored.accounts);e.sequence=restored.sequence;
    a=e.account(id);e.reconcile(id);
    e.step(enter:false);e.step(enter:false);
    final v=e.rows(a,'reversals').single;
    _check(e.rows(a,'positions').isEmpty && v['state']=='ENTERING',
      'أُغلق القديم بالكامل؛ الاتجاه الجديد مجرد أمر غير منفذ',trace);
    final closes=(v['close_orders'] as List).map((oid)=>e.order(id,oid as String)).toList();
    final next=e.order(id,v['entry_order'] as String),audit=e.rows(a,'audit');
    final submitted=audit.lastIndexWhere((r)=>r['event']=='أمر محلي');
    _check(closes.every((o)=>o['status']=='FILLED') && submitted>0 &&
      audit[submitted-1]['event']=='مصالحة','إيصالات الإغلاق الكامل ثم المصالحة ثم قبول أمر $newRight',trace);
    final lastClose=closes.expand((o)=>(o['fills'] as List).cast<DemoRow>())
      .map((f)=>f['tick'] as int).reduce((a,b)=>a>b?a:b);
    _check(next['created_tick']>=lastClose && next['filled']==0,'إعادة فحص الإشارة والعقد والمخاطر بعد آخر إغلاق',trace);
    e.step(enter:false);
    _check(v['state']=='COMPLETED' && e.rows(a,'positions').single['right']==newRight &&
      (next['fills'] as List).every((f)=>f['tick']>lastClose),
      'اكتمل $oldRight → $newRight دون تزامن المراكز',trace);
    _check(e.requestReversal(id,symbol,newRight,'exercise-reversal')['entry_order']==next['id'] &&
      e.rows(a,'orders').where((o)=>o['request_key']=='reverse-entry-exercise-reversal').length==1,
      'إعادة طلب الانعكاس لا تكرر الأمر',trace);
  }
}
