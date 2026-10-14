import 'dart:convert';
import 'dart:io';
import 'package:flutter_test/flutter_test.dart';
import 'package:options_ai_trader/paper_execution.dart';
import 'package:options_ai_trader/observed_option_replay.dart';
void main() {
  final cases=jsonDecode(File('test/fixtures/paper_execution_v2.json').readAsStringSync())['cases'] as List;
  for(final c in cases) {
    test('shared hand expected option model: ${c['name']}',() {
      final before=jsonEncode(c);
      expect(projectOptionExecution(c['quote'] as Map,c['side'] as String,c['requested'] as int,c['consumed'] as int,DateTime.parse(c['at'] as String)),c['expected']);
      expect(jsonEncode(c),before);
    });
  }
  test('Replay retains new actual entry costs and rejects modified model',() {
    final query=Map<String,dynamic>.from(jsonDecode(File('test/fixtures/observed_option_replay_v1.json').readAsStringSync())['cases'][0]['query'] as Map);
    final original=replayObservedOption(query),entry=query['entry'] as Map,fill=entry['fill'] as Map;
    final model=projectOptionExecution(entry['quote'] as Map,'BUY',fill['quantity'] as int,0,DateTime.parse(entry['at'] as String));
    fill.addAll({'execution':model,'price':model['priceCents'],'fee':model['feeCents']});
    final next=replayObservedOption(query);expect(next['pnlCents'],(original['pnlCents'] as int)-105*(fill['quantity'] as int));
    (model['policy'] as Map)['adverseSlippageCents']=0;
    expect(replayObservedOption(query)['status'],'INVALID_ORIGINAL_RECEIPT');
  });
}
