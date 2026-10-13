import 'dart:async';
import 'package:flutter_test/flutter_test.dart';
import 'package:options_ai_trader/direct_alpaca.dart';
import 'package:options_ai_trader/market_paper.dart';
import 'market_paper_safety_test.dart' show FaultPaperStore;

class AdmissionStore extends FaultPaperStore {
  void Function()? onRead, afterWrite;
  @override Future<PaperRow?> read() async {onRead?.call(); return super.read();}
  @override Future<void> write(PaperRow next) async {await super.write(next); afterWrite?.call();}
}

void main() {
  const nvda='NVDA261016C00200000',put='NVDA261016P00200000',aapl='AAPL261016C00200000';
  late DateTime clock;
  late AdmissionStore store;
  late MarketPaper paper;
  late String id;
  OptionQuote quote(String c,{int bid=40,int ask=42})=>OptionQuote(c,'opra',clock,bid,ask,10,10);
  Future<void> cycle({String symbol='NVDA',String observation='first',bool close=false,QuoteReader? reader})=>paper.evaluate(
    id:id,symbol:symbol,signal:'CALL',confirmedReverse:false,dataValid:()=>true,
    observation:observation,quotes:reader??(c)async=>quote(c),forceClose:close);
  setUp(()async{
    clock=DateTime.utc(2026,10,13,15,1,15);store=AdmissionStore();paper=MarketPaper(store,clock:()=>clock);
    await paper.load();await paper.add('Risk isolation',initialCash:100000);id=paper.accounts.single['id'] as String;
    await paper.configure(id,{'enabled':true,'contracts':{'NVDA:CALL':nvda,'NVDA:PUT':put,'AAPL:CALL':aapl}});
  });
  test('aggregate allocation includes all owned premium and entry fees',()async{
    await paper.configure(id,{'allocationPercent':8});await cycle();await cycle(symbol:'AAPL');
    expect((paper.account(id)['positions'] as Map).keys,['NVDA']);
    expect(paper.journal.last['decision'],'ALLOCATION_RISK_LIMIT');
  });
  test('quantity limit is across symbols rather than per order',()async{
    await paper.configure(id,{'maxContracts':1});await cycle();await cycle(symbol:'AAPL');
    expect((paper.account(id)['positions'] as Map).length,1);
    expect(paper.journal.last['decision'],'CONTRACT_COUNT_RISK_LIMIT');
  });
  test('position count is independent from total quantity',()async{
    await paper.configure(id,{'maxPositions':1,'maxContracts':10});await cycle();await cycle(symbol:'AAPL');
    expect(paper.journal.last['decision'],'POSITION_COUNT_RISK_LIMIT');
  });
  test('zero allocation blocks entry but never strands owned close',()async{
    await cycle();await paper.configure(id,{'allocationPercent':0});
    await cycle(symbol:'AAPL');expect(paper.journal.last['decision'],'ALLOCATION_RISK_LIMIT');
    await cycle(close:true);expect(paper.account(id)['positions'],isEmpty);
  });
  test('daily realized losses block later exposure and survive restart',()async{
    await cycle();await cycle(close:true,reader:(c)async=>quote(c,bid:30,ask:32));
    await cycle(symbol:'AAPL');await cycle(symbol:'AAPL',close:true,reader:(c)async=>quote(c,bid:20,ask:22));
    final recovered=MarketPaper(store,clock:()=>clock);await recovered.load();paper=recovered;
    await paper.configure(id,{'enabled':true});await cycle(observation:'later');
    expect(paper.account(id)['positions'],isEmpty);
    expect(paper.journal.last['decision'],'DAILY_LOSS_RISK_LIMIT');
  });
  test('negative open marks participate in daily loss admission',()async{
    await cycle();await cycle(symbol:'AAPL',reader:(c)async=>c==nvda?quote(c,bid:10,ask:11):quote(c));
    expect((paper.account(id)['positions'] as Map).keys,['NVDA']);
    expect(paper.journal.last['decision'],'DAILY_LOSS_RISK_LIMIT');
  });
  test('missing mark on another owned contract blocks fresh exposure',()async{
    await cycle();await cycle(symbol:'AAPL',reader:(c)async=>c==nvda?null:quote(c));
    expect((paper.account(id)['positions'] as Map).keys,['NVDA']);
    expect(paper.journal.last['decision'],'RISK_UNAVAILABLE_OPTION_MARK');
  });
  test('lowered aggregate cap rejects profitable addition',()async{
    await paper.configure(id,{'riskPercent':10,'addEnabled':true});await cycle();
    await paper.configure(id,{'maxContracts':1});
    await cycle(reader:(c)async=>quote(c,bid:47,ask:48));
    expect(paper.account(id)['positions']['NVDA']['quantity'],1);
    expect(paper.journal.last['decision'],'ADD_RISK_LIMIT');
  });
  test('quote expiring during durable preimage read cannot fill',()async{
    final writes=store.writes;
    store.onRead=(){clock=clock.add(const Duration(seconds:31));store.onRead=null;};
    await cycle();
    expect(paper.account(id)['positions'],isEmpty);expect(store.writes,writes);
  });
  test('signal is rechecked after durable closure before opposite entry',()async{
    await cycle();var current='PUT';
    store.afterWrite=(){if((store.value!['accounts'][0]['positions'] as Map).isEmpty)current='WAIT';};
    await paper.evaluate(id:id,symbol:'NVDA',signal:'PUT',confirmedReverse:true,dataValid:()=>true,
      observation:'opposite',quotes:(c)async=>quote(c),currentSignal:()=>current);
    expect(paper.account(id)['positions'],isEmpty);
    expect(paper.journal.last['decision'],'CLOSED_CONFIRMED_DIVERGENCE');
  });
  test('concurrent evaluation serializes before quote and ledger write',()async{
    final pending=Completer<OptionQuote?>();var reads=0;
    final first=cycle(reader:(c){reads++;return pending.future;});
    await cycle(reader:(c)async{reads++;return quote(c);});
    pending.complete(quote(nvda));await first;
    expect(reads,1);expect(paper.journal.where((e)=>e['decision']=='OPENED_CALL').length,1);
    expect(paper.account(id)['cash'],95735);
  });
}
