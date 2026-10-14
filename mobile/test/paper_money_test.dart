import 'dart:convert';
import 'package:flutter_test/flutter_test.dart';
import 'package:options_ai_trader/direct_alpaca.dart';
import 'package:options_ai_trader/market_paper.dart';
import 'package:options_ai_trader/market_paper_validation.dart';
import 'package:options_ai_trader/paper_money.dart';
import 'market_paper_safety_test.dart' show FaultPaperStore;

void main() {
  final now=DateTime.utc(2026,10,13,15,1),at=DateTime.utc(2026,10,13,15,1).toIso8601String();
  const contract='NVDA261016C00200000';
  Future<PaperRow> book({required int quantity,required int price,required int cost,required int initial}) async {
    final paper=MarketPaper(FaultPaperStore(),clock:()=>now);await paper.load();await paper.add('exact arithmetic');
    final value=paper.copy(),a=(value['accounts'] as List).single as PaperRow,fee=quantity*65;
    final q={'contract':contract,'feed':'opra','at':at,'bid':price,'ask':price,'bidSize':quantity,'askSize':quantity};
    a.addAll({'initialCash':initial,'cash':initial-cost-fee,'fees':fee,'peakEquity':initial,
      'positions':{'NVDA':{'contract':contract,'direction':'CALL','quantity':quantity,'cost':cost,'entryFees':fee,
        'opened':at,'mark':q,'highBid':price,'added':false,'realizedPnl':0,'partialTaken':false}}});
    value['journal']=[{'account':a['id'],'symbol':'NVDA','at':at,'decision':'OPENED_CALL','quote':q,
      'fill':{'side':'BUY','quantity':quantity,'price':price,'fee':fee,'cashAfter':a['cash']}}];
    return value;
  }
  test('proportional basis uses exact product before division',() {
    expect(paperPortion(8000000000000000,500000,1000000),4000000000000000);
    expect(paperPortion(paperMaxMoney,1,3),3002399751580330);
    expect(()=>paperProduct(184467440737096,100000),throwsFormatException);
    expect(()=>paperSum(paperMaxMoney,1),throwsFormatException);
    expect(()=>paperSum(-paperMaxMoney,-1),throwsFormatException);
    expect(()=>paperPortion(100,2,1),throwsFormatException);
  });
  test('large valid partial close reconciles exact basis and fees after restart',()async {
    final value=await book(quantity:1000000,price:80000000,cost:8000000000000000,initial:9000000000000000);
    validatePaper(value);final store=FaultPaperStore();await store.write(value);
    final paper=MarketPaper(store,clock:()=>now);await paper.load();expect(paper.ready,true);
    final id=paper.accounts.single['id'] as String;
    await paper.evaluate(id:id,symbol:'NVDA',signal:'WAIT',confirmedReverse:false,dataValid:()=>false,
      observation:'manual',forceClose:true,quotes:(_)async=>OptionQuote(contract,'opra',now,80000000,80000000,500000,500000));
    final p=paper.account(id)['positions']['NVDA'];
    expect(p['quantity'],500000);expect(p['cost'],4000000000000000);expect(p['entryFees'],32500000);
    expect(paper.journal.last['fill']['realizedPnl'],-65000000);
    final recovered=MarketPaper(store,clock:()=>now);await recovered.load();expect(recovered.ready,true);
    expect(recovered.account(id),paper.account(id));
  });
  test('wrapped 64-bit forged receipt cannot validate or overwrite retained storage',()async {
    // 184467440737096 * 1000 * 100 == 2^64 + 48384, not48384.
    final value=await book(quantity:1000,price:184467440737096,cost:48384,initial:1000000);
    expect(()=>validatePaper(value),throwsFormatException);
    final store=FaultPaperStore();await store.write(value);final before=jsonEncode(store.value);
    final paper=MarketPaper(store,clock:()=>now);await paper.load();expect(paper.ready,false);
    expect(jsonEncode(store.value),before);
  });
}
