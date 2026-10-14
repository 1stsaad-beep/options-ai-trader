import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:options_ai_trader/direct_alpaca.dart';
import 'package:options_ai_trader/market_paper.dart';
import 'package:options_ai_trader/paper_settlement_dialog.dart';
import 'market_paper_safety_test.dart' show FaultPaperStore;

void main() {
  testWidgets('paper settlement requires preview; editing invalidates it; save persists owned delivery',(tester)async {
    tester.view.physicalSize=const Size(1000,1400);tester.view.devicePixelRatio=1;
    addTearDown(tester.view.resetPhysicalSize);addTearDown(tester.view.resetDevicePixelRatio);
    final clock=DateTime.utc(2026,10,13,15,5),paper=MarketPaper(FaultPaperStore(),clock:()=>clock);
    await paper.load();await paper.add('UI',initialCash:10000000);final id=paper.accounts.single['id'] as String;
    const contract='NVDA261016C00200000';
    await paper.configure(id,{'enabled':true,'contracts':{'NVDA:CALL':contract}});
    await paper.evaluate(id:id,symbol:'NVDA',signal:'CALL',confirmedReverse:false,dataValid:()=>true,observation:'bar',
      quotes:(c)async=>OptionQuote(c,'opra',clock,200,210,10,10));
    await paper.configure(id,{'enabled':false});
    await tester.pumpWidget(MaterialApp(home:Builder(builder:(context)=>Scaffold(body:TextButton(
      onPressed:()=>showDialog<bool>(context:context,builder:(_)=>PaperSettlementDialog(paper:paper,accountId:id,contract:contract)),
      child:const Text('Open'))))));
    await tester.tap(find.text('Open'));await tester.pumpAndSettle();
    FilledButton save()=>tester.widget<FilledButton>(find.byKey(const Key('settlement-save')));
    expect(save().onPressed,isNull);
    await tester.enterText(find.byKey(const Key('settlement-price')),'220.00');
    await tester.enterText(find.byKey(const Key('settlement-reference')),'manual observation');
    await tester.tap(find.byKey(const Key('settlement-preview')));await tester.pumpAndSettle();
    expect(find.byKey(const Key('settlement-preview-result')),findsOneWidget);expect(save().onPressed,isNotNull);
    await tester.enterText(find.byKey(const Key('settlement-fee')),'1.00');await tester.pump();
    expect(save().onPressed,isNull);
    await tester.tap(find.byKey(const Key('settlement-preview')));await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('settlement-save')));await tester.pumpAndSettle();
    expect(find.byType(PaperSettlementDialog),findsNothing);expect(paper.account(id)['positions'],isEmpty);
    expect(paper.account(id)['deliveryPositions']['NVDA'],{'quantity':100,'cost':2021165});
    expect(paper.journal.last['settlement']['request']['source'],'manual_paper');
    expect(tester.takeException(),isNull);
  });
}
