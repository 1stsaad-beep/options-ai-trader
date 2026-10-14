import 'dart:async';
import 'package:flutter_test/flutter_test.dart';
import 'package:options_ai_trader/direct_alpaca.dart';
import 'package:options_ai_trader/market_paper.dart';
import 'market_paper_test.dart' show MemoryPaperStore;

void main() {
  var clock=DateTime.utc(2026,10,13,15,1,15);
  const call='NVDA261016C00200000',put='NVDA261016P00200000';
  late MemoryPaperStore store;
  late MarketPaper paper;
  late String id;
  OptionQuote quote(String c,{int size=10})=>OptionQuote(c,'opra',clock,200,210,size,size);
  Future<void> close({QuoteReader? quotes})=>paper.evaluate(id:id,symbol:'NVDA',signal:'PUT',
    confirmedReverse:true,dataValid:()=>true,observation:'new',forceClose:true,
    quotes:quotes??(c)async=>quote(c));
  setUp(()async {
    clock=DateTime.utc(2026,10,13,15,1,15);store=MemoryPaperStore();paper=MarketPaper(store,clock:()=>clock);
    await paper.load();await paper.add('A');id=paper.accounts.single['id'] as String;
    await paper.configure(id,{'enabled':true,'quantity':2,'contracts':{'NVDA:CALL':call,'NVDA:PUT':put}});
    await paper.evaluate(id:id,symbol:'NVDA',signal:'CALL',confirmedReverse:false,dataValid:()=>true,
      observation:'open',quotes:(c)async=>quote(c));
    expect((paper.account(id)['positions'] as Map)['NVDA']['quantity'],2);
    await paper.configure(id,{'enabled':false});
  });
  test('manual reduction works while disabled without arming or reversing',()async {
    final reads=<String>[];await close(quotes:(c)async{reads.add(c);return quote(c);});
    expect(reads,[call]);expect(paper.account(id)['positions'],isEmpty);
    expect(paper.account(id)['enabled'],false);expect(paper.journal.last['decision'],'CLOSED_MANUAL');
    expect(paper.account(id)['cash'],997740);
  });
  test('restart and pauseAll retain explicit manual reduction authority only',()async {
    paper=MarketPaper(store,clock:()=>clock);await paper.load();await paper.pauseAll();
    await close();expect(paper.account(id)['positions'],isEmpty);expect(paper.account(id)['enabled'],false);
  });
  test('automatic evaluation remains blocked on the same disabled account',()async {
    var reads=0;await paper.evaluate(id:id,symbol:'NVDA',signal:'PUT',confirmedReverse:true,
      dataValid:()=>true,observation:'new',quotes:(c)async{reads++;return quote(c);});
    expect(reads,0);expect((paper.account(id)['positions'] as Map)['NVDA']['quantity'],2);
  });
  test('pause during a manual quote invalidates reduction before persistence',()async {
    final pending=Completer<OptionQuote?>();final closing=close(quotes:(_)async=>pending.future);
    final pause=paper.pauseAll();pending.complete(quote(call));await closing;await pause;
    expect((paper.account(id)['positions'] as Map)['NVDA']['quantity'],2);
    expect(paper.journal.where((e)=>e['fill']?['side']=='SELL_TO_CLOSE'),isEmpty);
  });
  test('account change during manual quote also invalidates reduction',()async {
    final pending=Completer<OptionQuote?>();final closing=close(quotes:(_)async=>pending.future);
    final change=paper.configure(id,{'stopPercent':25});pending.complete(quote(call));await closing;await change;
    expect((paper.account(id)['positions'] as Map)['NVDA']['quantity'],2);
  });
  test('missing quote retains intent but no fill and no enablement',()async {
    final cash=paper.account(id)['cash'];await close(quotes:(_)async=>null);
    expect(paper.account(id)['cash'],cash);expect(paper.account(id)['enabled'],false);
    expect((paper.account(id)['positions'] as Map)['NVDA']['closeIntent']['remaining'],2);
  });
  test('partial manual reduction survives restart and requires a newer quote',()async {
    await close(quotes:(c)async=>quote(c,size:1));
    paper=MarketPaper(store,clock:()=>clock);await paper.load();
    await close(quotes:(c)async=>quote(c,size:1));
    expect((paper.account(id)['positions'] as Map)['NVDA']['quantity'],1);
    clock=clock.add(const Duration(seconds:1));await close();
    expect(paper.account(id)['positions'],isEmpty);expect(paper.account(id)['enabled'],false);
    expect(paper.account(id)['closedTrades'],1);
  });
  test('failed manual persistence preserves ownership and stopped state',()async {
    store.fail=true;await close();expect((paper.account(id)['positions'] as Map)['NVDA']['quantity'],2);
    expect(paper.account(id)['enabled'],false);
  });
}
