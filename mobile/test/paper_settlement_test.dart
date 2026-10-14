import 'dart:convert';
import 'dart:io';
import 'package:flutter_test/flutter_test.dart';
import 'package:options_ai_trader/paper_settlement.dart';

void main() {
  final fixture=jsonDecode(File('test/fixtures/paper_settlement_v1.json').readAsStringSync()) as Map;
  for(final raw in fixture['cases'] as List) {
    final c=Map<String,dynamic>.from(raw as Map);
    test('Python/Dart settlement parity: ${c['name']}',() {
      Map<String,dynamic> run()=>projectPaperSettlement(c['position'] as Map?,c['delivery'] as Map?,c['cash'] as int,
        Map<String,dynamic>.from(c['request'] as Map),DateTime.parse(c['now'] as String));
      if(c['rejected']==true){expect(run,throwsFormatException);}else{expect(run(),c['expected']);}
    });
  }
}
