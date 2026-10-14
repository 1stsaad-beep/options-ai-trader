import 'dart:convert';
import 'package:flutter_test/flutter_test.dart';
import 'package:options_ai_trader/market_paper.dart';
import 'package:options_ai_trader/paper_execution.dart';
import 'package:options_ai_trader/direct_alpaca.dart';
import 'package:options_ai_trader/market_paper_validation.dart';
import 'market_paper_safety_test.dart' show FaultPaperStore;
void main() {
  const contract='NVDA261016C00200000';late DateTime clock;late MarketPaper paper;late FaultPaperStore store;late String id;
  Future<void> cycle({bool close=false,int size=10,int bid=200,int ask=210,DateTime? quoted})=>paper.evaluate(
    id:id,symbol:'NVDA',signal:close?'WAIT':'CALL',confirmedReverse:false,dataValid:()=>true,
    observation:clock.toIso8601String(),forceClose:close,
    quotes:(c)async=>OptionQuote(c,'opra',quoted??clock,bid,ask,size,size));
  setUp(()async {
    clock=DateTime.utc(2026,10,13,15,1,15);store=FaultPaperStore();paper=MarketPaper(store,clock:()=>clock);
    await paper.load();await paper.add('Costed',initialCash:10000000,executionPolicy:conservativeExecution);
    id=paper.accounts.single['id'] as String;
    await paper.configure(id,{'enabled':true,'quantity':3,'contracts':{'NVDA:CALL':contract},'holdingMode':'swing'});
  });
  test('new model fills only observed fraction and reserves real cost plus fees',()async {
    await cycle();final a=paper.account(id),f=paper.journal.last['fill'];
    expect(a['positions']['NVDA']['quantity'],2);expect(a['positions']['NVDA']['cost'],42200);
    expect(a['cash'],9957660);expect(f['fee'],140);expect(f['execution']['unfilledQuantity'],1);
    expect(paper.performance(id)['unrealizedPnlCents'],-2680);validatePaper(paper.copy());
  });
  test('partial closes preserve intent across restart without reusing old quote',()async {
    await cycle();final original=clock;await cycle(close:true);
    expect(paper.account(id)['positions']['NVDA']['quantity'],2);expect(paper.journal.last['decision'],'CLOSE_NO_MODELED_LIQUIDITY');
    clock=clock.add(const Duration(seconds:1));await cycle(close:true,size:4);
    expect(paper.account(id)['positions']['NVDA']['quantity'],1);expect(paper.account(id)['cash'],9977490);
    expect(paper.account(id)['positions']['NVDA']['closeIntent']['remaining'],1);
    paper=MarketPaper(store,clock:()=>clock);await paper.load();expect(paper.account(id)['enabled'],false);
    await cycle(close:true,quoted:original);expect(paper.account(id)['positions']['NVDA']['quantity'],1);
    clock=clock.add(const Duration(seconds:1));await cycle(close:true,size:4);
    expect(paper.account(id)['positions'],isEmpty);expect(paper.account(id)['cash'],9997320);validatePaper(paper.copy());
  });
  test('legacy originals survive stopped policy change and mixed receipt recovery',()async {
    await paper.configure(id,{'enabled':false});await paper.configure(id,{'executionPolicy':legacyExecution});await paper.configure(id,{'enabled':true});
    await cycle();final original=paper.journal.first;expect(original['fill']['execution'],isNull);
    await expectLater(paper.configure(id,{'executionPolicy':conservativeExecution}),throwsArgumentError);
    await paper.configure(id,{'enabled':false});await paper.configure(id,{'executionPolicy':conservativeExecution});
    clock=clock.add(const Duration(seconds:1));await cycle(close:true);
    expect(paper.journal.first,original);expect(paper.account(id)['positions']['NVDA']['quantity'],1);
    final restored=MarketPaper(FaultPaperStore(),clock:()=>clock);await restored.load();await restored.restoreBackup(paper.exportBackup());
    expect(restored.ready,true);expect(restored.journal,paper.journal);validatePaper(restored.copy());
  });
  test('small quote and dropped write never manufacture a fill or consume liquidity',()async {
    await cycle(size:3);expect(paper.account(id)['positions'],isEmpty);
    store.dropWrite=true;await cycle();expect(paper.account(id)['positions'],isEmpty);
    store.dropWrite=false;store.throwAfterWrite=true;await cycle();expect(paper.account(id)['positions']['NVDA']['quantity'],2);
    expect(paper.journal.where((e)=>e['fill']!=null).length,1);
  });
  test('addition charges adverse ask and updated fees once',()async {
    await paper.configure(id,{'quantity':1,'addEnabled':true,'partialPercent':0});await cycle();
    clock=clock.add(const Duration(seconds:1));await cycle(size:4,bid:240,ask:250);
    final p=paper.account(id)['positions']['NVDA'];expect(p['quantity'],2);expect(p['cost'],46200);expect(p['entryFees'],140);
    expect(paper.journal.last['fill']['execution']['quantity'],1);validatePaper(paper.copy());
  });
  for(final field in ['fee','price','consumedQuantity','policy','quantity']) {
    test('tampered modeled $field cannot reconcile or replace stored evidence',()async {
      await cycle();final event=(store.value!['journal'] as List).last as Map,fill=event['fill'] as Map;
      if(field=='fee'||field=='price'){fill[field]=(fill[field] as int)+1;}
      else if(field=='policy'){fill['execution']['policy']['additionalFeeCents']=0;}
      else{fill['execution'][field]=(fill['execution'][field] as int)+1;}
      final before=jsonEncode(store.value),writes=store.writes;
      final recovered=MarketPaper(store,clock:()=>clock);await recovered.load();
      expect(recovered.ready,false);expect(jsonEncode(store.value),before);expect(store.writes,writes);
    });
  }
}
