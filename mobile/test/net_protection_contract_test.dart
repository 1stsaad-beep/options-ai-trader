import 'dart:convert';
import 'dart:io';
import 'package:flutter_test/flutter_test.dart';
import 'package:options_ai_trader/direct_alpaca.dart';
import 'package:options_ai_trader/market_paper.dart';
import 'package:options_ai_trader/market_paper_validation.dart';
import 'package:options_ai_trader/paper_execution.dart';
import 'market_paper_safety_test.dart' show FaultPaperStore;

void main() {
  final fixture = jsonDecode(File('test/fixtures/net_protection_v1.json').readAsStringSync()) as Map;
  for (final scenario in fixture['cases'] as List) {
    test('original Python v2 net protection parity: ${scenario['name']}', () async {
      final observations = scenario['observations'] as List, config = scenario['config'] as Map;
      var clock = DateTime.parse(observations.first['capturedAt'] as String);
      final paper = MarketPaper(FaultPaperStore(), clock: () => clock);
      await paper.load(); await paper.add('Parity', initialCash: 10000000, executionPolicy: conservativeExecution);
      final id = paper.accounts.single['id'] as String;
      await paper.configure(id, {'enabled': true, 'quantity': config['quantity'], 'holdingMode': config['holdingMode'],
        'partialPercent': config['partialPercent'], 'addEnabled': config['addEnabled'],
        'contracts': {'NVDA:CALL': observations.first['quotes'][0]['contract']}});
      for (final observation in observations) {
        clock = DateTime.parse(observation['capturedAt'] as String);
        final quote = observation['quotes'][0];
        await paper.evaluate(id: id, symbol: 'NVDA', signal: 'CALL', confirmedReverse: false, dataValid: () => true,
          observation: clock.toIso8601String(), evidence: {'source': 'fixture'}, quotes: (contract) async =>
            OptionQuote(contract, 'opra', clock, quote['bid'] as int, quote['ask'] as int, 40, 40));
      }
      final account = paper.account(id), position = account['positions']['NVDA'], expected = scenario['expected'];
      expect(account['cash'], expected['cash']); expect(account['fees'], expected['fees']);
      expect(position == null ? 0 : position['quantity'], expected['quantity']);
      expect(position == null ? 0 : position['cost'] + position['entryFees'], expected['basis']);
      final latest = paper.journal.where((e) => e['at'] == clock.toIso8601String() && e['fill'] != null).toList();
      expect(latest.map((e) => e['fill']['side']).toList(), expected['fillSides']);
      expect(latest.map((e) => e['fill']['quantity']).toList(), expected['fillQuantities']);
      validatePaper(paper.copy());
    });
  }
}
