import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:options_ai_trader/direct_alpaca.dart';
import 'package:options_ai_trader/direct_decision_view.dart';
import 'package:options_ai_trader/direct_replay.dart';
import 'package:options_ai_trader/demo/chart_painter.dart';

void main() {
  final rows=List.generate(40,(i)=>MarketBar(DateTime.utc(2026,10,13,14,i),100,110,90,105,1000));
  Map<String,dynamic> event()=>{'account':'a','symbol':'NVDA','at':'2026-10-13T15:01:15.000Z','decision':'OPENED_CALL',
    'fill':{'side':'BUY','price':210,'quantity':1},'evidence':{'observation':'2026-10-13T14:39:00.000Z',
      'recordedAt':'2026-10-13T15:01:00.000Z','rule':'ORIGINAL_RULE',...directBarEvidence(rows)}};
  testWidgets('offline decision cursor never reveals final reason or marker early',(tester)async {
    await tester.pumpWidget(MaterialApp(home:DirectDecisionView(event:event())));await tester.pumpAndSettle();
    final painter=tester.widget<CustomPaint>(find.byKey(const Key('decision-replay-chart'))).painter! as DemoCandlePainter;
    expect(painter.bars.length,40);expect(painter.markers.length,1);
    tester.widget<Slider>(find.byKey(const Key('replay-slider'))).onChanged!(10);await tester.pumpAndSettle();
    final earlier=tester.widget<CustomPaint>(find.byKey(const Key('decision-replay-chart'))).painter! as DemoCandlePainter;
    expect(earlier.bars.length,11);expect(earlier.markers,isEmpty);
    expect(find.byKey(const Key('replay-original-reason')),findsNothing);
    expect(find.byKey(const Key('replay-original-json')),findsNothing);
    expect(find.byKey(const Key('replay-before-decision')),findsOneWidget);
    tester.widget<Slider>(find.byKey(const Key('replay-slider'))).onChanged!(39);await tester.pumpAndSettle();
    await tester.ensureVisible(find.byKey(const Key('replay-original-reason')));
    expect(find.textContaining('ORIGINAL_RULE'),findsWidgets);
    expect(tester.takeException(),isNull);
  });
  testWidgets('invalid saved observations show explicit failure without generated chart',(tester)async {
    final bad=event();bad['evidence']['bars'][0]['c']=9999;
    await tester.pumpWidget(MaterialApp(home:DirectDecisionView(event:bad)));await tester.pumpAndSettle();
    expect(find.byKey(const Key('replay-invalid')),findsOneWidget);
    expect(find.byKey(const Key('decision-replay-chart')),findsNothing);
  });
}
