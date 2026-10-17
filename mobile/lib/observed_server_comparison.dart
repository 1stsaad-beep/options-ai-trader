import 'dart:convert';
import 'package:flutter/material.dart';
import 'observed_server.dart';
import 'market_strategy.dart';
import 'paper_time.dart';

const observedExperimentStrategies = ['trend', 'breakout', 'pullback', 'divergence'];
List<String> observedExperimentIds(String source) => [
  for (final strategy in observedExperimentStrategies) 'experiment_${source}_$strategy',
];

List<ObservedServerAccount> parseObservedExperiment(dynamic raw, String source) {
  final root = observedObject(raw), ids = observedExperimentIds(source);
  if (root['contract'] != 'observed-paper-experiment-v1' || root['source'] != source ||
      root['externalOrder'] != false || root['created'] is! bool ||
      root['accounts'] is! List || (root['accounts'] as List).length != 4) {
    throw const FormatException('Invalid experiment');
  }
  final result = <ObservedServerAccount>[];
  for (var i = 0; i < 4; i++) {
    final account = ObservedServerAccount.parse(root['accounts'][i], ids[i]);
    if (account.state['source'] != source || account.state['initialCash'] != 100000) {
      throw const FormatException('Experiment identity mismatch');
    }
    // A retry may return an evolved account. Only new genesis promises stopped
    // accounts with the four original independent rules and untouched capital.
    if (root['created'] == true && (account.version != 1 || account.state['enabled'] != false ||
        account.state['cash'] != 100000 || account.state['realized'] != 0 || account.state['fees'] != 0 ||
        account.state['config']['strategy'] != observedExperimentStrategies[i] ||
        (account.state['config']['contracts'] as Map).isNotEmpty ||
        (account.state['positions'] as Map).isNotEmpty || (account.state['deliveries'] as Map).isNotEmpty)) {
      throw const FormatException('Unexpected experiment genesis');
    }
    result.add(account);
  }
  return result;
}

Map<String, dynamic> parseObservedComparison(dynamic raw, List<String> ids, String source) {
  final root = observedObject(raw);
  if (ids.isEmpty || ids.length > 4 || ids.toSet().length != ids.length ||
      root['contract'] != 'observed-paper-comparison-v1' || root['source'] != source ||
      root['externalOrder'] != false || root['valuationStatus'] != 'UNMARKED' ||
      root['threeSessionAcceptance'] != 'NOT_RUN' || root['accounts'] is! List ||
      (root['accounts'] as List).length != ids.length) {
    throw const FormatException('Invalid comparison');
  }
  for (var i = 0; i < ids.length; i++) {
    final row = observedObject(root['accounts'][i]), p = observedObject(row['performance']);
    if (row['name'] is! String || row['enabled'] is! bool || !marketStrategies.contains(row['strategy']) ||
        !observedInteger(row['initialCashCents'], minimum: 1) ||
        p['contract'] != 'observed-paper-performance-v1' || p['account'] != ids[i] ||
        p['source'] != source || p['externalOrder'] != false || !observedInteger(p['version']) ||
        !observedHash(p['eventHash']) || !observedInteger(p['realizedPnlCents'], minimum: -9007199254740991)) {
      throw const FormatException('Comparison identity mismatch');
    }
    for (final key in ['cashCents', 'ownedBasisCents', 'bookCapitalCents', 'feesCents',
      'maximumRealizedDrawdownCents', 'closedQuoteRoundTrips', 'winningQuoteRoundTrips',
      'losingQuoteRoundTrips', 'flatQuoteRoundTrips', 'eventCount']) {
      if (!observedInteger(p[key])) {
        throw const FormatException('Invalid comparison amount');
      }
    }
    if (p['cashCents'] + p['ownedBasisCents'] != p['bookCapitalCents'] ||
        p['bookCapitalCents'] != row['initialCashCents'] + p['realizedPnlCents'] ||
        p['winningQuoteRoundTrips'] + p['losingQuoteRoundTrips'] + p['flatQuoteRoundTrips'] != p['closedQuoteRoundTrips'] ||
        p['eventCount'] != p['version'] + 1 || p['valuationStatus'] != 'UNMARKED' ||
        ['liquidationEquityCents', 'unrealizedPnlCents', 'equityDrawdownPercent', 'sharpe'].any((key) => p[key] != null)) {
      throw const FormatException('Comparison accounting mismatch');
    }
    if (p['asOf'] != null) {
      observationStamp(p['asOf']);
    }
  }
  return jsonDecode(jsonEncode(root)) as Map<String, dynamic>;
}

class ObservedComparisonScreen extends StatelessWidget {
  final Map<String, dynamic> report;
  const ObservedComparisonScreen({super.key, required this.report});
  String money(dynamic value) => '${(value / 100).toStringAsFixed(2)} USD';
  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: const Text('مقارنة الحسابات الأربعة')),
    body: ListView(padding: const EdgeInsets.all(16), children: [
      Text('المصدر: ${report['source']} • أرصدة افتراضية مستقلة'),
      const Text('مقارنة الإيصالات الأصلية عند إصدارات الحسابات المعروضة. قد تتغير الحسابات بعد هذه القراءة.'),
      const Text('ثلاث جلسات سوقية فعلية: لم تُقبل بعد. لا قيمة تصفية أو ربح غير محقق دون تقييم مؤهل كامل.'),
      for (final row in report['accounts'] as List) Card(
        key: Key('comparison-${row['performance']['account']}'),
        child: Padding(padding: const EdgeInsets.all(16), child: Column(
          crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text('${row['name']} • ${row['strategy']}', style: Theme.of(context).textTheme.titleMedium),
            Text('الحساب ${row['performance']['account']}'),
            Text('إصدار ${row['performance']['version']} • ${row['enabled'] == true ? "مشغّل" : "متوقف"}'),
            Text('رأس المال الأولي ${money(row['initialCashCents'])}'),
            Text('النقد ${money(row['performance']['cashCents'])}'),
            Text('الربح المحقق ${money(row['performance']['realizedPnlCents'])}'),
            Text('الرسوم ${money(row['performance']['feesCents'])}'),
            Text('أقصى تراجع للمحقق ${money(row['performance']['maximumRealizedDrawdownCents'])}'),
            Text('أساس تكلفة الممتلكات ${money(row['performance']['ownedBasisCents'])}'),
            Text('رأس المال الدفتري ${money(row['performance']['bookCapitalCents'])}؛ ليس قيمة التصفية'),
            Text('دورات خيار مغلقة بالأسعار ${row['performance']['closedQuoteRoundTrips']} • رابحة ${row['performance']['winningQuoteRoundTrips']} • خاسرة ${row['performance']['losingQuoteRoundTrips']}'),
          ],
        )),
      ),
    ]),
  );
}
