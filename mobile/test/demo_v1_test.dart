import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:options_ai_trader/demo/engine.dart';
import 'package:options_ai_trader/demo/store.dart';
import 'package:options_ai_trader/demo/chart_analysis.dart';
import 'package:options_ai_trader/demo/chart_lab.dart';

void main() {
  late DemoEngine e; late DemoRow a; late String id;
  final rejected=throwsA(isA<DemoRejected>());
  setUp(() {e=DemoEngine();a=e.createAccount('V1',2000000);id=a['id'];});
  void step([int count=1]) {for(var i=0;i<count;i++){e.step(enter:false);e.validate();}}
  DemoRow buy({String right='CALL',int quantity=1,String key='entry'})=>
    e.submit(id,e.contract('NVDA',right),'BUY',quantity,key);

  test('first install creates four independent fixtures without a count cap',() async {
    final c=DemoController(MemoryDemoStore());await c.load();
    expect(c.engine.accounts.length,4);
    c.engine.createAccount('fifth',1000000);expect(c.engine.accounts.length,5);
    c.engine.watch(c.engine.accounts.first['id'],'NVDA',enabled:false);
    expect(c.engine.accounts.last['watch']['NVDA'],true);c.dispose();
  });
  test('allocation 0 prevents entry; elevated risk needs explicit acknowledgement',(){
    e.configure(id,{'allocation_pct':0});expect(()=>buy(),rejected);
    expect(()=>e.configure(id,{'allocation_pct':100,'trade_pct':100}),rejected);
    e.configure(id,{'allocation_pct':100,'trade_pct':100,'daily_pct':100,'exposure_pct':100,'elevated_risk_ack':true});
    expect(buy(quantity:5)['quantity'],5);
    expect(()=>e.configure(id,{'daily_pct':99}),rejected);
    e.configure(id,{'daily_pct':99,'elevated_risk_ack':true});
    final b=e.createAccount('independent',1000000);expect(e.risk(b)['trade_pct'],2);
  });
  test('opposing lock covers unresolved orders and ownership across strikes',(){
    final entry=buy();
    expect(()=>buy(right:'PUT',key:'opposite'),rejected);
    step();expect(entry['status'],'FILLED');
    expect(()=>e.submit(id,e.contract('NVDA','PUT',strike:30000),'BUY',1,'different-strike'),rejected);
    final b=e.createAccount('other',2000000);
    expect(e.submit(b['id'],e.contract('NVDA','PUT'),'BUY',1,'other')['account_id'],b['id']);
  });
  test('direction lock rechecked at fill after ledger restores',(){
    final entry=buy();e.cancel(id,entry['id']);
    buy(right:'PUT',key:'other');step();
    entry['status']='OPEN';e.tick++;
    expect(()=>e.fill(id,entry['id']),rejected);
    expect(e.rows(a,'positions').single['right'],'PUT');
  });
  test('full reversal waits for partial closes, disconnect and reconciliation',(){
    buy(right:'PUT',quantity:3);step(3);
    final v=e.requestReversal(id,'NVDA','CALL','reverse');
    expect(v['state'],'CLOSING');step();
    expect(e.rows(a,'positions').single['right'],'PUT');
    expect(e.rows(a,'positions').single['quantity'],2);
    e.disconnect(id);step();expect(v['state'],'CLOSING');
    e=DemoEngine.decode(e.encode());a=e.account(id);e.reconcile(id);
    step(2);
    final restored=e.rows(a,'reversals').single;
    expect(restored['state'],'ENTERING');
    expect(e.rows(a,'positions'),isEmpty);
    step();expect(restored['state'],'COMPLETED');
    expect(e.rows(a,'positions').single['right'],'CALL');
    expect(e.requestReversal(id,'NVDA','CALL','reverse')['entry_order'],restored['entry_order']);
    expect(e.rows(a,'orders').where((o)=>o['request_key']=='reverse-entry-reverse').length,1);
  });
  test('opt in automation starts reversal from a fresh quantitative signal',(){
    buy(right:'PUT');step();e.configure(id,{'automation':true,'reversal_enabled':true});
    e.step();expect(e.rows(a,'reversals').single['state'],'CLOSING');
    step();expect(e.rows(a,'reversals').single['state'],'ENTERING');
    step();expect(e.rows(a,'positions').where((p)=>p['symbol']=='NVDA').single['right'],'CALL');
  });
  test('cancelled reversal close never opens opposite direction',(){
    buy(right:'PUT');step();
    final v=e.requestReversal(id,'NVDA','CALL','cancel');
    e.cancel(id,(v['close_orders'] as List).single);step(15);
    expect(e.rows(a,'positions').single['right'],'PUT');
    expect(e.rows(a,'orders').where((o)=>o['right']=='CALL'),isEmpty);
  });
  test('emergency after reversal close blocks opposite entry',(){
    buy(right:'PUT');step();e.requestReversal(id,'NVDA','CALL','stop');e.stop(id:id);step();
    expect(e.rows(a,'positions'),isEmpty);
    expect(e.rows(a,'reversals').single['state'],'BLOCKED');
  });
  test('trailing exit uses historical high and next observation execution',(){
    buy();step();e.configure(id,{'automation':true,'take_pct':500,'trailing_pct':20});
    e.scenario='rally';step();expect(e.rows(a,'orders').length,1);
    e.scenario='flat';step();expect(e.rows(a,'orders').last['reason'],'وقف متحرك');
    expect(e.rows(a,'positions'),isNotEmpty);step();expect(e.rows(a,'positions'),isEmpty);
  });
  test('staged profit never sells more than owned and later stop closes rest',(){
    buy(quantity:2);step(2);e.configure(id,{'automation':true,'take_pct':500,'partial_take_pct':20});
    e.scenario='rally';step();expect(e.rows(a,'orders').last['quantity'],1);
    step();expect(e.rows(a,'positions').single['quantity'],1);step();
    expect(e.rows(a,'orders').where((o)=>o['reason']=='جني ربح مرحلي').length,1);
    e.scenario='drop';step(2);expect(e.rows(a,'positions'),isEmpty);
  });
  test('Swing time limit and expiry guard submit exits',(){
    buy();step();e.configure(id,{'automation':true,'holding':'swing','swing_max_ticks':2});step(2);
    expect(e.rows(a,'orders').last['reason'],'خروج Swing زمني');step();
    final c=e.contract('NVDA','CALL',expiry:'2026-01-06');e.submit(id,c,'BUY',1,'near');step();
    expect(e.rows(a,'orders').last['reason'],'حماية اقتراب الانتهاء');
  });
  test('market outage retains owned position and never fabricates trailing fill',(){
    buy();step();e.configure(id,{'automation':true,'trailing_pct':10,'take_pct':500});
    e.scenario='rally';step();e.marketAvailable=false;e.scenario='drop';step(4);
    expect(e.rows(a,'positions').single['quantity'],1);
    expect(e.rows(a,'orders').length,1);e.marketAvailable=true;step(2);expect(e.rows(a,'positions'),isEmpty);
  });
  test('scaling default off and loss positions cannot be scaled',(){
    buy();step();expect(()=>e.scale(id,e.rows(a,'positions').single),rejected);
    e.configure(id,{'scaling_enabled':true,'scaling_cooldown':1});step();
    expect(()=>e.scale(id,e.rows(a,'positions').single),rejected);
  });
  test('lost scaling response persists reservation and cannot double add',(){
    buy();step();e.configure(id,{'scaling_enabled':true,'scaling_cooldown':1,'scaling_max':1});
    e.scenario='rally';step();
    expect(()=>e.scale(id,e.rows(a,'positions').single,loseResponse:true),rejected);
    e=DemoEngine.decode(e.encode());a=e.account(id);
    expect(e.rows(a,'positions').single['scale_count'],1);
    expect(()=>e.scale(id,e.rows(a,'positions').single),rejected);
    e.reconcile(id);step();expect(e.rows(a,'positions').single['quantity'],2);
    expect(()=>e.scale(id,e.rows(a,'positions').single),rejected);
    expect(e.rows(a,'orders').length,2);
  });
  test('scale fill rechecks aggregate position premium after risk decreases',(){
    buy();step();e.configure(id,{'scaling_enabled':true,'scaling_cooldown':1});
    e.scenario='rally';step();final added=e.scale(id,e.rows(a,'positions').single);
    e.configure(id,{'trade_pct':1});step();
    expect(added['filled'],0);expect(e.rows(a,'positions').single['quantity'],1);
  });
  test('decision snapshot is fixed before later configuration and exit',(){
    final evidence=<String,dynamic>{'rule':'breakout','as_of':e.tick};
    final o=e.submit(id,e.contract('NVDA','CALL'),'BUY',1,'snapshot',reason:'quant-rule',evidence:evidence);
    final original=o['decision_json'];evidence['rule']='mutated';step();
    e.configure(id,{'trade_pct':1});e.submit(id,e.rows(a,'positions').single,'SELL_TO_CLOSE',1,'close');step();
    final t=e.rows(a,'trades').single;
    expect((t['entry_decisions'] as List).single,original);
    expect(jsonDecode(original)['evidence']['rule'],'breakout');
    expect(t['exit_fee'],65);expect(t['exit_price'],99);
    final restored=DemoEngine.decode(e.encode());expect(restored.rows(restored.account(id),'trades').single['entry_decisions'],[original]);
  });
  test('V0.5 schema migration preserves balances and marks absent decisions',(){
    buy();step();final raw=jsonDecode(e.encode()) as DemoRow;raw['version']=1;
    raw['accounts'][0].remove('reversals');
    for(final key in ['exposure_pct','elevated_risk_ack','entry_profile','entry_method','trailing_pct','partial_take_pct','swing_max_ticks','expiry_guard_days','scaling_enabled','reversal_enabled','scaling_max','scaling_quantity','scaling_cooldown','scaling_decreasing']) {
      raw['accounts'][0]['risk'].remove(key);
    }
    final restored=DemoEngine.decode(jsonEncode(raw));final saved=restored.account(id);
    expect(saved['cash'],a['cash']);expect(restored.rows(saved,'orders').single['decision_json'],isNull);
    expect(restored.rows(saved,'positions').single['entry_decisions'],isEmpty);
    expect(restored.toJson()['version'],2);
  });
  test('chart and signal replay refuse future observations',(){
    expect(()=>DemoChartAnalysis.bars(e,'NVDA',25),rejected);
    expect(()=>e.opportunities(id,at:25),rejected);
    final before=DemoChartAnalysis.summary(DemoChartAnalysis.bars(e,'NVDA',24));
    step(50);expect(DemoChartAnalysis.summary(DemoChartAnalysis.bars(e,'NVDA',24)),before);
  });
  test('confirmed pivots are append-only and never visible before confirmation',(){
    final values=[1.0,2.0,4.0,2.0,1.0,3.0,5.0,3.0,1.0];
    final bars=List.generate(values.length,(i)=>DemoCandle(i,values[i],values[i]+.1,values[i]-.1,values[i],100));
    final p=DemoChartAnalysis.pivots(bars.take(5).toList());expect(p.single.index,2);expect(p.single.confirmedAt,4);
    expect(DemoChartAnalysis.pivots(bars.take(4).toList()),isEmpty);
    final later=DemoChartAnalysis.pivots(bars);expect(later.first.index,p.first.index);expect(later.first.price,p.first.price);
  });
  test('indicator outputs and harmonic geometry are deterministic',(){
    expect(DemoChartAnalysis.sma([1,2,3],2),[null,1.5,2.5]);
    expect(DemoChartAnalysis.rsi(List.generate(20,(i)=>i.toDouble())).last,100);
    final invalid=List.generate(5,(i)=>ChartPivot(i,i+2,i.toDouble(),i.isEven));
    expect(DemoChartAnalysis.harmonics(invalid),isEmpty);
    // A=100, B=50, C=75, D=11.4 gives valid Bat ratios.
    final valid=[const ChartPivot(0,2,0,false),const ChartPivot(3,5,100,true),
      const ChartPivot(6,8,50,false),const ChartPivot(9,11,75,true),const ChartPivot(12,14,11.4,false)];
    expect(DemoChartAnalysis.harmonics(valid).single.name,'Bat');
  });
  testWidgets('five chart labs and causal cursor render on narrow RTL phone',(t) async {
    e.tick=40;t.view.physicalSize=const Size(360,800);t.view.devicePixelRatio=1;
    addTearDown(t.view.resetPhysicalSize);addTearDown(t.view.resetDevicePixelRatio);
    await t.pumpWidget(MaterialApp(home:Directionality(textDirection:TextDirection.rtl,
      child:Scaffold(body:SingleChildScrollView(child:DemoChartLab(engine:e,symbol:'NVDA'))))));
    await t.pumpAndSettle();
    for(var i=0;i<5;i++) {
      await t.ensureVisible(find.byKey(Key('chart-lab-$i')));await t.tap(find.byKey(Key('chart-lab-$i')));await t.pumpAndSettle();
      expect(t.takeException(),isNull);
    }
    expect(find.byKey(const Key('chart-pan-zoom')),findsOneWidget);
    await t.ensureVisible(find.text('ملاحظة سابقة'));await t.tap(find.text('ملاحظة سابقة'));await t.pump();
    expect(find.textContaining('الملاحظة 39 من 40'),findsOneWidget);expect(t.takeException(),isNull);
  });
}
