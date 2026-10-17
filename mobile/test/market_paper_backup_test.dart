import 'dart:convert';
import 'package:flutter_test/flutter_test.dart';
import 'package:options_ai_trader/market_paper.dart';
import 'package:options_ai_trader/market_paper_backup.dart';
import 'market_paper_safety_test.dart' show FaultPaperStore;

void main() {
  late FaultPaperStore store;
  late MarketPaper paper;
  setUp(()async{store=FaultPaperStore();paper=MarketPaper(store);await paper.load();await paper.createComparisonExperiment();});
  test('all experiment accounts round trip into an empty ledger without enablement',()async{
    await paper.configure(paper.accounts.first['id'] as String,{'enabled':true});
    final text=paper.exportBackup(),other=MarketPaper(FaultPaperStore());await other.load();await other.restoreBackup(text);
    expect(other.accounts.length,4);expect(other.accounts.every((a)=>a['enabled']==false),true);
    expect(other.comparison()['status'],'NOT_RUN');expect(paper.accounts.first['enabled'],true);
  });
  test('restore never overwrites any existing device account',()async{
    final original=jsonEncode(store.value),writes=store.writes;
    await expectLater(paper.restoreBackup(paper.exportBackup()),throwsStateError);
    expect(jsonEncode(store.value),original);expect(store.writes,writes);
  });
  test('tampered receipt-account balance is rejected',(){
    final envelope=jsonDecode(paper.exportBackup());envelope['ledger']['accounts'][0]['cash']+=1;
    expect(()=>PaperBackup.inspect(jsonEncode(envelope)),throwsFormatException);
  });
  test('different mode and nested credential payloads are rejected',(){
    expect(()=>PaperBackup.inspect('{"format":"demo","ledger":{}}'),throwsFormatException);
    final envelope=jsonDecode(paper.exportBackup());
    envelope['ledger']['accounts'][0]['name']='{"api_secret":"do-not-export"}';
    expect(()=>PaperBackup.inspect(jsonEncode(envelope)),throwsFormatException);
  });
  test('oversized input is bounded before JSON parsing',(){
    expect(()=>PaperBackup.inspect(' '*(PaperBackup.maxBytes+1)),throwsFormatException);
  });
  test('deep and excessive nested string JSON rejected before restore writes',()async{
    final envelope=jsonDecode(paper.exportBackup());
    envelope['ledger']['accounts'][0]['name']='${'['*2000}0${']'*2000}';
    final original=jsonEncode(store.value),writes=store.writes;
    expect(()=>PaperBackup.inspect(jsonEncode(envelope)),throwsFormatException);
    expect(jsonEncode(store.value),original);expect(store.writes,writes);
  });
  test('duplicate receipt fields cannot be normalized away by JSON decoding',(){
    final text=paper.exportBackup();
    final changed=text.replaceFirst('"version":1','"version":0,"version":1');
    expect(changed,isNot(text));
    expect(()=>PaperBackup.inspect(changed),throwsFormatException);
  });
  test('duplicate keys inside embedded JSON cannot bypass credential screening',(){
    final envelope=jsonDecode(paper.exportBackup());
    envelope['ledger']['accounts'][0]['name']='{"api_secret":"private","api_secret":"hidden"}';
    expect(()=>PaperBackup.inspect(jsonEncode(envelope)),throwsFormatException);
  });
  test('unknown write outcome cannot report a successful restore',()async{
    final target=FaultPaperStore()..failReadAfterWrite=true,other=MarketPaper(FaultPaperStore());
    final recovered=MarketPaper(target);await recovered.load();
    await expectLater(recovered.restoreBackup(paper.exportBackup()),throwsStateError);
    expect(recovered.ready,false);await other.load();expect(other.accounts,isEmpty);
  });
}
