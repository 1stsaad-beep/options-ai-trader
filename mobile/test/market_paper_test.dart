import 'dart:async';
import 'dart:convert';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:options_ai_trader/direct_alpaca.dart';
import 'package:options_ai_trader/market_paper.dart';

class MemoryPaperStore implements PaperStore {
  PaperRow? value;bool fail=false;
  @override Future<PaperRow?> read()async=>value==null?null:jsonDecode(jsonEncode(value)) as PaperRow;
  @override Future<void> write(PaperRow v)async{if(fail)throw StateError('disk');value=jsonDecode(jsonEncode(v)) as PaperRow;}
}
class DelayedReadStore extends MemoryPaperStore {
  final reads=<Completer<PaperRow?>>[];
  bool initialized=false;
  @override Future<PaperRow?> read(){
    if(initialized)return super.read();
    final c=Completer<PaperRow?>();reads.add(c);
    return c.future.then((value){initialized=true;return value;});
  }
}
void main(){
  final now=DateTime.utc(2026,10,13,15,1,15);
  const call='NVDA261016C00200000',put='NVDA261016P00200000';
  late MemoryPaperStore store;late MarketPaper paper;late String id;
  OptionQuote quote(String contract,{int bid=200,int ask=210,String feed='opra'})=>OptionQuote(contract,feed,now,bid,ask,10,10);
  Future<void> evaluate({String signal='CALL',bool reverse=false,bool valid=true,QuoteReader? reader,String observation='bar1',bool close=false})=>
    paper.evaluate(id:id,symbol:'NVDA',signal:signal,confirmedReverse:reverse,dataValid:()=>valid,observation:observation,quotes:reader??(c)async=>quote(c),forceClose:close);
  setUp(()async{store=MemoryPaperStore();paper=MarketPaper(store,clock:()=>now);await paper.load();await paper.add('A');id=paper.accounts.first['id'] as String;
    await paper.configure(id,{'enabled':true,'contracts':{'NVDA:CALL':call,'NVDA:PUT':put}});});
  test('separate accounts and no duplicate opposite position',()async{await paper.add('B');final other=paper.accounts.last['id'];await evaluate();await evaluate(signal:'PUT');
    expect((paper.account(id)['positions'] as Map)['NVDA']['direction'],'CALL');expect(paper.account(other)['cash'],1000000);expect(paper.account(other)['positions'],isEmpty);
    expect(paper.journal.last['decision'],'OPPOSITE_POSITION_BLOCKED');});
  test('no fills with stock-only indicative stale or absent quote',()async{await evaluate(reader:(_)async=>null);expect(paper.account(id)['positions'],isEmpty);
    await evaluate(reader:(c)async=>quote(c,feed:'indicative'));expect(paper.account(id)['cash'],1000000);
    await evaluate(valid:false);expect(paper.account(id)['positions'],isEmpty);});
  test('confirmed reversal durably closes first then rechecks opposite quote',()async{await evaluate();var calls=0;
    await evaluate(signal:'PUT',reverse:true,observation:'bar2',reader:(c)async{calls++;if(c==put)expect(paper.account(id)['positions'],isEmpty);return quote(c);});
    expect(calls,2);expect((paper.account(id)['positions'] as Map)['NVDA']['direction'],'PUT');
    expect(paper.journal.map((e)=>e['decision']).toList(),['OPENED_CALL','CLOSED_CONFIRMED_DIVERGENCE','OPENED_PUT']);});
  test('failed closure cannot open opposite',()async{await evaluate();store.fail=true;var reads=0;
    await evaluate(signal:'PUT',reverse:true,reader:(c)async{reads++;return quote(c);});expect(reads,1);expect((paper.account(id)['positions'] as Map)['NVDA']['direction'],'CALL');});
  test('failed quote cannot close or reverse',()async{await evaluate();await evaluate(signal:'PUT',reverse:true,reader:(_)async=>null);
    expect((paper.account(id)['positions'] as Map)['NVDA']['direction'],'CALL');expect(paper.journal.last['decision'],'CLOSE_UNCONFIRMED_NO_REVERSAL');});
  test('successful close does not force opposite with missing quote',()async{await evaluate();await evaluate(signal:'PUT',reverse:true,observation:'bar2',reader:(c)async=>c==call?quote(c):null);
    expect(paper.account(id)['positions'],isEmpty);expect(paper.journal.last['decision'],'OPRA_QUOTE_REQUIRED_NO_FILL');});
  test('account disable invalidates in-flight quote',()async{final pending=Completer<OptionQuote?>();final run=evaluate(reader:(_)async=>pending.future);
    final pause=paper.configure(id,{'enabled':false});pending.complete(quote(call));await run;await pause;
    expect(paper.account(id)['positions'],isEmpty);expect(paper.account(id)['enabled'],false);});
  test('risk budget blocks new position',()async{await paper.configure(id,{'riskPercent':1});await evaluate();expect(paper.journal.last['decision'],'RISK_LIMIT');expect(paper.account(id)['cash'],1000000);});
  test('stop loss uses option bid with commissions and does not immediately reopen',()async{await evaluate();await evaluate(reader:(c)async=>quote(c,bid:160,ask:170));
    expect(paper.account(id)['positions'],isEmpty);expect(paper.journal.last['decision'],'CLOSED_STOP_LOSS');expect(paper.account(id)['cash'],994870);});
  test('take profit closes on eligible option data',()async{await evaluate();await evaluate(reader:(c)async=>quote(c,bid:300,ask:310));expect(paper.journal.last['decision'],'CLOSED_TAKE_PROFIT');});
  test('trailing and one add retain risk limit',()async{await paper.configure(id,{'addEnabled':true});await evaluate();await evaluate(reader:(c)async=>quote(c,bid:235,ask:240));
    expect((paper.account(id)['positions'] as Map)['NVDA']['quantity'],2);
    await evaluate(reader:(c)async=>quote(c,bid:250,ask:255));expect((paper.account(id)['positions'] as Map)['NVDA']['quantity'],2);
    await evaluate(reader:(c)async=>quote(c,bid:210,ask:220));expect(paper.journal.last['decision'],'CLOSED_TRAILING_STOP');});
  test('reload preserves positions and decisions but disarms execution',()async{await evaluate();final restored=MarketPaper(store,clock:()=>now);await restored.load();expect(restored.account(id)['positions'],paper.account(id)['positions']);expect(restored.journal.length,1);expect(restored.account(id)['enabled'],false);});
  test('addition budget includes all previously paid entry commissions',()async{await paper.configure(id,{'addEnabled':true});
    await evaluate(reader:(c)async=>quote(c,bid:230,ask:237));
    await evaluate(reader:(c)async=>quote(c,bid:262,ask:262));
    expect((paper.account(id)['positions'] as Map)['NVDA']['quantity'],1);
    expect(paper.account(id)['cash'],976235);
    expect(paper.journal.last['decision'],'ADD_RISK_LIMIT');
  });
  test('same observation cannot reopen after close',()async{await evaluate();await evaluate(close:true);await evaluate();expect(paper.account(id)['positions'],isEmpty);expect(paper.journal.last['decision'],'CLOSED_MANUAL');});
  test('new preferences namespace preserves unrelated existing Demo data',()async{SharedPreferences.setMockInitialValues({'existing-demo':'unchanged'});final prefs=PreferencesPaperStore();await prefs.write({'version':1,'accounts':[],'journal':[]});expect((await SharedPreferences.getInstance()).getString('existing-demo'),'unchanged');});
  test('overlapping route initialization cannot overwrite a newly created account',()async{
    final delayed=DelayedReadStore();
    // Exercise a second load arriving while the original storage read is pending.
    final active=MarketPaper(delayed,clock:()=>now);
    final load1=active.load(),load2=active.load();delayed.reads.first.complete(null);await load1;
    await active.add('Preserve after first load');
    for(final read in delayed.reads.skip(1)){read.complete(null);}await load2;
    expect(active.accounts.single['name'],'Preserve after first load');
  });
}
