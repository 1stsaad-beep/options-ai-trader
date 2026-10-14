import 'dart:convert';
import 'package:flutter_test/flutter_test.dart';
import 'package:options_ai_trader/direct_alpaca.dart';
import 'package:options_ai_trader/market_paper.dart';
import 'package:options_ai_trader/market_paper_validation.dart';
import 'market_paper_safety_test.dart' show FaultPaperStore;

void main() {
  const contract='NVDA261016C00200000';
  late DateTime clock;
  late FaultPaperStore store;
  late MarketPaper paper;
  late String id;
  PaperRow receipt({String action='EXERCISE',String key='exercise-1',int quantity=1,int price=22000})=>{
    'id':key,'action':action,'contract':contract,'quantity':quantity,'feeCents':100,'underlyingCents':price,
    'effectiveAt':clock.toIso8601String(),'recordedAt':clock.toIso8601String(),'source':'fixture','reference':'test-observation',
  };
  Future<void> open() =>paper.evaluate(id:id,symbol:'NVDA',signal:'CALL',confirmedReverse:false,
    dataValid:()=>true,observation:clock.toIso8601String(),
    quotes:(c)async=>OptionQuote(c,'opra',clock,200,210,10,10));
  setUp(()async {
    clock=DateTime.utc(2026,10,13,15,1,15);store=FaultPaperStore();paper=MarketPaper(store,clock:()=>clock);
    await paper.load();await paper.add('Settlement',initialCash:10000000);id=paper.accounts.single['id'] as String;
    await paper.configure(id,{'enabled':true,'contracts':{'NVDA:CALL':contract},'quantity':2,'holdingMode':'swing'});
    await open();expect(paper.account(id)['positions']['NVDA']['quantity'],2);
    await paper.configure(id,{'enabled':false});clock=clock.add(const Duration(minutes:1));
  });
  test('partial exercise capitalizes cost; restart and export reconcile delivery',()async {
    final result=await paper.settle(id,receipt());
    expect(result['externalOrder'],false);expect(paper.account(id)['cash'],7957770);
    expect(paper.account(id)['positions']['NVDA']['quantity'],1);
    expect(paper.account(id)['deliveryPositions']['NVDA'],{'quantity':100,'cost':2021165});
    expect(paper.performance(id)['realizedPnlCents'],0);
    expect(paper.performance(id)['equityCents'],isNull);
    expect(paper.performance(id)['winRatePercent'],isNull);
    final recovered=MarketPaper(store,clock:()=>clock);await recovered.load();
    expect(recovered.ready,true);expect(recovered.account(id)['enabled'],false);
    final restored=MarketPaper(FaultPaperStore(),clock:()=>clock);await restored.load();
    await restored.restoreBackup(paper.exportBackup());
    expect(restored.account(id)['deliveryPositions'],paper.account(id)['deliveryPositions']);
    validatePaper(restored.copy());
  });
  test('receipt retry is exactly idempotent including after restart',()async {
    final request=receipt(),result=await paper.settle(id,receipt());final writes=store.writes;
    final recovered=MarketPaper(store,clock:()=>clock);await recovered.load();
    expect(await recovered.settle(id,request),result);expect(store.writes,writes);
    expect(recovered.journal.where((e)=>e.containsKey('settlement')).length,1);
    await expectLater(recovered.settle(id,{...request,'quantity':2}),throwsStateError);
    expect(store.writes,writes);
  });
  test('full exercise and partial delivery disposals reconcile cents and realized PnL',()async {
    await paper.settle(id,receipt(quantity:2));
    expect(paper.account(id)['positions'],isEmpty);
    expect(paper.account(id)['cash'],5957770);
    expect(paper.account(id)['deliveryPositions']['NVDA']['cost'],4042230);
    await paper.settle(id,receipt(action:'SELL_DELIVERY',key:'sale-1',quantity:50));
    expect(paper.account(id)['deliveryPositions']['NVDA'],{'quantity':150,'cost':3031673});
    expect(paper.performance(id)['realizedPnlCents'],89343);
    await paper.settle(id,receipt(action:'SELL_DELIVERY',key:'sale-2',quantity:150));
    expect(paper.account(id)['deliveryPositions'],isEmpty);
    expect(paper.account(id)['cash'],10357570);
    expect(paper.performance(id)['realizedPnlCents'],357570);
    expect(paper.performance(id)['equityCents'],10357570);
    expect(paper.account(id)['settlementCount'],3);
    expect(paper.account(id)['settlementRealizedPnl'],357570);validatePaper(paper.copy());
  });
  test('explicit worthless expiry removes premium and fees with no fake option fill',()async {
    clock=DateTime.utc(2026,10,16,20);
    await paper.settle(id,receipt(action:'EXPIRE_WORTHLESS',quantity:2,price:19900));
    expect(paper.account(id)['cash'],9957770);expect(paper.account(id)['positions'],isEmpty);
    expect(paper.performance(id)['realizedPnlCents'],-42230);
    expect(paper.journal.last.containsKey('fill'),false);expect(paper.account(id)['closedTrades'],0);
    validatePaper(paper.copy());
  });
  test('exercise is blocked while account automation is armed',()async {
    await paper.configure(id,{'enabled':true});final before=jsonEncode(store.value);
    await expectLater(paper.settle(id,receipt()),throwsStateError);expect(jsonEncode(store.value),before);
  });
  test('unowned shares and overexercise never mutate cash',()async {
    final before=jsonEncode(store.value);
    await expectLater(paper.settle(id,receipt(quantity:3)),throwsFormatException);
    await expectLater(paper.settle(id,receipt(action:'SELL_DELIVERY')),throwsFormatException);
    expect(jsonEncode(store.value),before);
  });
  test('receipt before acquisition is rejected',()async {
    final before=jsonEncode(store.value),request=receipt();
    request['effectiveAt']=DateTime.utc(2026,10,13,15).toIso8601String();
    await expectLater(paper.settle(id,request),throwsFormatException);expect(jsonEncode(store.value),before);
  });
  test('owned Put can acquire only needed shares with cash, then deliver them on exercise',()async {
    await paper.add('Put settlement',initialCash:10000000);id=paper.accounts.last['id'] as String;
    const put='NVDA261016P00200000';
    await paper.configure(id,{'enabled':true,'contracts':{'NVDA:PUT':put},'quantity':2});
    await paper.evaluate(id:id,symbol:'NVDA',signal:'PUT',confirmedReverse:false,dataValid:()=>true,
      observation:clock.toIso8601String(),quotes:(c)async=>OptionQuote(c,'opra',clock,200,210,10,10));
    await paper.configure(id,{'enabled':false});
    final acquire={...receipt(action:'BUY_FOR_PUT',key:'acquire',quantity:100,price:19000),'contract':put};
    await paper.settle(id,acquire);
    expect(paper.account(id)['cash'],8057770);expect(paper.performance(id)['realizedPnlCents'],0);
    final recovered=MarketPaper(store,clock:()=>clock);await recovered.load();
    await recovered.settle(id,{...receipt(),'contract':put});
    expect(recovered.account(id)['cash'],10057670);expect(recovered.performance(id)['realizedPnlCents'],78735);
    expect(recovered.account(id)['deliveryPositions'],isEmpty);
    expect(recovered.account(id)['positions']['NVDA']['quantity'],1);validatePaper(recovered.copy());
  });
  test('insufficient cash rejects exercise with original ownership intact',()async {
    await paper.add('Small',initialCash:1000000);id=paper.accounts.last['id'] as String;
    await paper.configure(id,{'enabled':true,'contracts':{'NVDA:CALL':contract}});await open();
    await paper.configure(id,{'enabled':false});final before=jsonEncode(store.value);
    await expectLater(paper.settle(id,receipt()),throwsFormatException);expect(jsonEncode(store.value),before);
  });
  test('new option exposure is blocked while delivered shares lack valuation',()async {
    await paper.settle(id,receipt(quantity:2));clock=clock.add(const Duration(minutes:1));
    await paper.configure(id,{'enabled':true});await open();
    expect(paper.account(id)['positions'],isEmpty);expect(paper.journal.last['decision'],'DELIVERED_STOCK_REVIEW_REQUIRED');
  });
  test('dropped write rejects receipt; retry may commit once',()async {
    final before=jsonEncode(store.value);store.dropWrite=true;
    await expectLater(paper.settle(id,receipt()),throwsStateError);expect(jsonEncode(store.value),before);
    expect(paper.account(id)['positions']['NVDA']['quantity'],2);
    store.dropWrite=false;await paper.settle(id,receipt());expect(paper.account(id)['settlementCount'],1);
  });
  test('lost write response is resolved by exact readback',()async {
    store.throwAfterWrite=true;await paper.settle(id,receipt());
    expect(paper.account(id)['settlementCount'],1);expect(paper.ready,true);
  });
  test('unknown write outcome latches mutation and restart resolves receipt',()async {
    final request=receipt();store.failReadAfterWrite=true;
    await expectLater(paper.settle(id,request),throwsStateError);expect(paper.ready,false);
    store.unreadable=false;store.failReadAfterWrite=false;final writes=store.writes;
    await expectLater(paper.settle(id,request),throwsStateError);expect(store.writes,writes);
    final recovered=MarketPaper(store,clock:()=>clock);await recovered.load();
    expect(recovered.ready,true);await recovered.settle(id,request);expect(store.writes,writes);
  });
  for(final target in ['cash','shares','basis','result','source','identity','missing_receipt','duplicate','count','realized']) {
    test('restart rejects tampered settlement $target without replacing saved evidence',()async {
      await paper.settle(id,receipt());final book=store.value!,a=book['accounts'][0],event=(book['journal'] as List).last;
      switch(target) {
        case 'cash':a['cash']++;break;
        case 'shares':a['deliveryPositions']['NVDA']['quantity']++;break;
        case 'basis':a['deliveryPositions']['NVDA']['cost']++;break;
        case 'result':event['settlement']['result']['cashDelta']++;break;
        case 'source':event['settlement']['request']['source']='broker';break;
        case 'identity':event['settlement']['request']['id']='';break;
        case 'missing_receipt':event.remove('settlement');break;
        case 'duplicate':(book['journal'] as List).add(jsonDecode(jsonEncode(event)));break;
        case 'count':a['settlementCount']++;break;
        case 'realized':a['settlementRealizedPnl']++;break;
      }
      final before=jsonEncode(store.value),writes=store.writes;
      final recovered=MarketPaper(store,clock:()=>clock);await recovered.load();
      expect(recovered.ready,false);expect(jsonEncode(store.value),before);expect(store.writes,writes);
    });
  }
}
