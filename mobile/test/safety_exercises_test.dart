import 'dart:convert';
import 'dart:io';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:options_ai_trader/demo/engine.dart';
import 'package:options_ai_trader/demo/safety_exercises.dart';
import 'package:options_ai_trader/demo/store.dart';
import 'package:options_ai_trader/main.dart';
import 'demo_widget_test.dart' show destination,NoNetwork;

class DisabledExecution extends DemoEngine {
  @override
  void step({bool enter=true}) {tick++;}
}

void main() {
  for(final name in ['وقف خسارة','جني ربح','وقف متحرك','Call → Put','Put → Call']) {
    test('actual isolated engine exercise: $name',() {
      final result=DemoSafetyExercises.run().singleWhere((r)=>r.name==name);
      expect(result.passed,isTrue,reason:result.evidence.join('\n'));
      final restored=DemoEngine.decode(jsonEncode(result.ledger)),a=restored.accounts.single;
      if(name.contains('→')) {
        expect(restored.rows(a,'reversals').single['state'],'COMPLETED');
        final orders=restored.rows(a,'orders');
        final close=orders.singleWhere((o)=>o['side']=='SELL_TO_CLOSE');
        final entry=orders.singleWhere((o)=>o['reason']=='انعكاس بعد إغلاق ومصالحة');
        final lastClose=(close['fills'] as List).last['tick'];
        expect((entry['fills'] as List).first['tick'],greaterThan(lastClose));
        expect(close['filled'],3);
        expect(restored.rows(a,'positions'),hasLength(1));
      } else {
        expect(restored.rows(a,'positions'),isEmpty);
        expect(restored.rows(a,'trades').single['reason'],name);
        expect(restored.performance(a['id'] as String)['fees'],130);
      }
    });
  }

  test('exercise runner reports failure if actual execution is disabled',() {
    final results=DemoSafetyExercises.run(factory:DisabledExecution.new);
    expect(results.every((r)=>!r.passed),isTrue);
    expect(results.every((r)=>r.evidence.last.startsWith('فشل:')),isTrue);
  });

  testWidgets('phone exercise route uses no network and leaves saved account bytes intact',(t) async {
    final e=DemoEngine()..createAccount('الحساب المحفوظ',2000000);
    final id=e.accounts.single['id'] as String;
    e.configure(id,{'allocation_pct':0,'stop_pct':7,'take_pct':77,'trailing_pct':9});
    final store=MemoryDemoStore(e.encode()),before=store.data;
    final blocker=NoNetwork(),previous=HttpOverrides.current;
    HttpOverrides.global=blocker;addTearDown(()=>HttpOverrides.global=previous);
    t.view.physicalSize=const Size(360,900);t.view.devicePixelRatio=1;
    addTearDown(t.view.resetPhysicalSize);addTearDown(t.view.resetDevicePixelRatio);
    await t.pumpWidget(TraderApp(demoStore:store));await t.pumpAndSettle();
    await destination(t,'الطوارئ واختبار الأعطال');
    await t.ensureVisible(find.byKey(const Key('demo-isolated-tests')));
    await t.tap(find.byKey(const Key('demo-isolated-tests')));await t.pumpAndSettle();
    await t.ensureVisible(find.byKey(const Key('run-safety-exercises')));
    await t.tap(find.byKey(const Key('run-safety-exercises')));await t.pumpAndSettle();
    expect(find.text('نجح 5 من 5'),findsOneWidget);
    expect(store.data,before);expect(blocker.attempts,0);expect(t.takeException(),isNull);
  });
}
