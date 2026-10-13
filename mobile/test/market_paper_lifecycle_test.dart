import 'dart:convert';
import 'dart:io';
import 'package:flutter_test/flutter_test.dart';
import 'package:options_ai_trader/direct_alpaca.dart';
import 'package:options_ai_trader/market_paper.dart';
import 'package:options_ai_trader/market_paper_policy.dart';
import 'market_paper_safety_test.dart' show FaultPaperStore;

void main() {
  const call='NVDA261016C00200000',put='NVDA261016P00200000';
  late DateTime clock;
  late FaultPaperStore store;
  late MarketPaper paper;
  late String id;
  OptionQuote quote(String c,{int bid=200,int ask=210,int size=10})=>OptionQuote(c,'opra',clock,bid,ask,size,size);
  Future<void> cycle({String signal='CALL',bool reverse=false,bool close=false,bool valid=true,bool broken=false,
    int bid=200,int ask=210,int size=10,bool missing=false})=>paper.evaluate(id:id,symbol:'NVDA',signal:signal,
      confirmedReverse:reverse,dataValid:()=>valid,observation:clock.toIso8601String(),
      quotes:(c)async=>missing?null:quote(c,bid:bid,ask:ask,size:size),forceClose:close,scenarioInvalidated:()=>broken);
  setUp(()async{
    clock=DateTime.utc(2026,10,13,15,1,15);store=FaultPaperStore();paper=MarketPaper(store,clock:()=>clock);
    await paper.load();await paper.add('Lifecycle');id=paper.accounts.single['id'] as String;
    await paper.configure(id,{'enabled':true,'quantity':3,'riskPercent':20,'contracts':{'NVDA:CALL':call,'NVDA:PUT':put}});
  });
  test('partial reversal retains lock and consumes quote liquidity once',()async{
    await cycle();clock=clock.add(const Duration(seconds:1));
    await cycle(signal:'PUT',reverse:true,size:1);
    expect(paper.account(id)['positions']['NVDA']['quantity'],2);
    expect(paper.account(id)['positions']['NVDA']['closeIntent']['remaining'],2);
    final cash=paper.account(id)['cash'];await cycle(signal:'PUT',reverse:true,size:1);
    expect(paper.account(id)['cash'],cash);expect(paper.journal.last['decision'],'CLOSE_WAIT_NEW_QUOTE');
    expect(paper.journal.where((e)=>e['decision']=='OPENED_PUT'),isEmpty);
  });
  test('restart retains remaining close intent without opposite auto-open',()async{
    await cycle();clock=clock.add(const Duration(seconds:1));await cycle(signal:'PUT',reverse:true,size:1);
    paper=MarketPaper(store,clock:()=>clock);await paper.load();
    expect(paper.account(id)['enabled'],false);await paper.configure(id,{'enabled':true});
    clock=clock.add(const Duration(seconds:1));await cycle(signal:'WAIT',valid:false);
    expect(paper.account(id)['positions'],isEmpty);
    expect(paper.account(id)['closedTrades'],1);
    expect(paper.account(id)['fees'],390);
    expect(paper.journal.where((e)=>e['decision']=='OPENED_PUT'),isEmpty);
  });
  test('opposite reopens only after remaining quantity is reconciled and fresh signal',()async{
    await cycle();clock=clock.add(const Duration(seconds:1));await cycle(signal:'PUT',reverse:true,size:1);
    clock=clock.add(const Duration(seconds:1));await cycle(signal:'PUT',reverse:true);
    expect(paper.account(id)['positions']['NVDA']['direction'],'PUT');
    expect(paper.journal.where((e)=>e['decision']=='CLOSED_CONFIRMED_DIVERGENCE').length,1);
    expect(paper.journal.where((e)=>e['decision']=='OPENED_PUT').length,1);
  });
  test('missing quote persists manual close intent with no cash mutation',()async{
    await cycle();final cash=paper.account(id)['cash'];await cycle(close:true,missing:true);
    expect(paper.account(id)['positions']['NVDA']['closeIntent']['reason'],'MANUAL');
    expect(paper.account(id)['cash'],cash);
    clock=clock.add(const Duration(seconds:1));await cycle(signal:'WAIT',valid:false);
    expect(paper.account(id)['positions'],isEmpty);
  });
  test('partial profit cost and fees reconcile and winning round trip is counted once',()async{
    await cycle();clock=clock.add(const Duration(seconds:1));await cycle(bid:260,ask:270);
    expect(paper.account(id)['positions']['NVDA']['quantity'],2);
    expect(paper.account(id)['closedTrades'],0);
    expect(paper.account(id)['positions']['NVDA']['partialTaken'],true);
    await cycle(bid:260,ask:270);expect(paper.account(id)['positions']['NVDA']['quantity'],2);
    clock=clock.add(const Duration(seconds:1));await cycle(close:true,bid:205,ask:215);
    expect(paper.account(id)['positions'],isEmpty);expect(paper.account(id)['winningTrades'],1);
    expect(paper.account(id)['closedTrades'],1);expect(paper.account(id)['cash'],1003610);
    paper=MarketPaper(store,clock:()=>clock);await paper.load();expect(paper.ready,true);
  });
  test('intraday cutoff protects owned position despite optional analysis failure',()async{
    await cycle();clock=DateTime.utc(2026,10,13,19,46);await cycle(valid:false);
    expect(paper.account(id)['positions'],isEmpty);expect(paper.journal.last['decision'],'CLOSED_INTRADAY_EXIT');
  });
  test('overnight missed intraday exit remains pending before open and fills after open',()async{
    await cycle();clock=DateTime.utc(2026,10,14,12);await cycle(valid:false);
    expect(paper.account(id)['positions']['NVDA']['quantity'],3);
    expect(paper.account(id)['positions']['NVDA']['closeIntent']['reason'],'INTRADAY_EXIT');
    clock=DateTime.utc(2026,10,14,14);await cycle(valid:false);expect(paper.account(id)['positions'],isEmpty);
  });
  test('swing does not acquire a false expiry close intent merely because market is closed',()async{
    await paper.configure(id,{'holdingMode':'swing'});await cycle();clock=DateTime.utc(2026,10,13,21);await cycle();
    expect(paper.account(id)['positions']['NVDA']['closeIntent'],isNull);
    expect(paper.journal.last['decision'],'SESSION_CLOSED_NO_FILL');
  });
  test('expiry day blocks entry and closes previously owned qualified inventory',()async{
    await paper.configure(id,{'holdingMode':'swing'});await cycle();clock=DateTime.utc(2026,10,16,14);await cycle(valid:false);
    expect(paper.account(id)['positions'],isEmpty);expect(paper.journal.last['decision'],'CLOSED_EXPIRATION_PROTECTION');
    clock=clock.add(const Duration(seconds:1));await cycle();expect(paper.journal.last['decision'],'EXPIRY_ENTRY_BLOCKED');
  });
  test('expired inventory is retained for explicit review without fabricated settlement',()async{
    await cycle();final cash=paper.account(id)['cash'];clock=DateTime.utc(2026,10,16,20,1);await cycle();
    expect(paper.account(id)['positions']['NVDA']['quantity'],3);expect(paper.account(id)['cash'],cash);
    expect(paper.journal.last['decision'],'EXPIRY_REVIEW_REQUIRED');
  });
  test('optional scenario exit and bounded swing holding use explicit account policy',()async{
    await paper.configure(id,{'holdingMode':'swing','scenarioExit':true});await cycle();
    clock=clock.add(const Duration(seconds:1));await cycle(signal:'WAIT');expect(paper.account(id)['positions'],isNotEmpty);
    await cycle(signal:'WAIT',broken:true);
    expect(paper.journal.last['decision'],'CLOSED_SCENARIO_EXIT');
    await paper.configure(id,{'scenarioExit':false,'maxHoldingDays':1});
    clock=clock.add(const Duration(seconds:1));await cycle();clock=DateTime.utc(2026,10,14,16);await cycle();
    expect(paper.journal.last['decision'],'CLOSED_MAX_HOLDING_EXIT');
  });
  test('calendar matches independently executed server boundary fixtures',() {
    final rows=jsonDecode(File('test/fixtures/paper_session_parity.json').readAsStringSync()) as List;
    for(final row in rows) {
      final s=paperSession(DateTime.parse(row['at'] as String));
      expect(s.date,row['date'],reason:row['at'] as String);
      expect([s.entry,s.fill,s.exitDue],[row['entry'],row['fill'],row['exit']],reason:row['at'] as String);
    }
    expect(paperExpiry('NVDA261225C00200000',DateTime.utc(2026,12,24,17)).entry,false);
    expect(paperExpiry('NVDA261225C00200000',DateTime.utc(2026,12,24,18)).close,false);
    expect(paperSession(DateTime.utc(2028,1,3,15)).entry,false);
  });
}
