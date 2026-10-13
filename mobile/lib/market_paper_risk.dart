import 'direct_alpaca.dart';

/// Pure admission over current account truth and qualified observed option marks.
/// Research labels, confidence scores and caller narratives cannot override it.
String? paperRiskReason(Map<String, dynamic> account, String symbol, int quantity,
    int price, Map<String, OptionQuote> marks, DateTime now,
    {required Iterable<Map<String, dynamic>> journal, bool adding = false}) {
  final positions = account['positions'] as Map;
  final initial = account['initialCash'] as int;
  final additional = quantity * (price * 100 + 65);
  final existing = positions[symbol] as Map?;
  final currentCost = existing == null ? 0 : (existing['cost'] as int) +
      ((existing['entryFees'] ?? (existing['quantity'] as int) * 65) as int);
  if (additional > (account['cash'] as int) ||
      currentCost + additional > initial * (account['riskPercent'] as int) / 100) {
    return 'RISK_LIMIT';
  }
  var exposure = 0, contracts = 0, openLoss = 0;
  for (final raw in positions.values) {
    final p = raw as Map;
    final qty = p['quantity'] as int, cost = (p['cost'] as int) + ((p['entryFees'] ?? qty * 65) as int);
    exposure += cost; contracts += qty;
    final q = marks[p['contract']];
    if (q == null || q.contract != p['contract'] || !q.valid(now, quantity: qty)) return 'RISK_UNAVAILABLE_OPTION_MARK';
    final pnl = q.bid * qty * 100 - qty * 65 - cost;
    if (pnl < 0) openLoss -= pnl;
  }
  if (exposure + additional > initial * ((account['allocationPercent'] ?? 30) as int) / 100) return 'ALLOCATION_RISK_LIMIT';
  if (contracts + quantity > ((account['maxContracts'] ?? 10) as int)) return 'CONTRACT_COUNT_RISK_LIMIT';
  if (!adding && positions.length + 1 > ((account['maxPositions'] ?? 4) as int)) return 'POSITION_COUNT_RISK_LIMIT';
  final day = now.toUtc().toIso8601String().substring(0, 10);
  if (journal.any((event) => event['account'] == account['id'] &&
      (event['at'] as String).startsWith(day) && (event['decision'] as String).startsWith('CLOSED_') &&
      event['fill'] == null)) {
    return 'RISK_LEGACY_DAILY_HISTORY_UNAVAILABLE';
  }
  final realized = (((account['dailyRealized'] as Map?)?[day]) ?? 0) as int;
  final dailyLoss = (realized < 0 ? -realized : 0) + openLoss;
  final dailyBudget = initial * ((account['dailyLossPercent'] ?? 3) as int) / 100;
  // A cutoff for new exposure based on realized and current negative marks;
  // it cannot guarantee that a price gap/stop fill will never exceed the cap.
  if (dailyLoss >= dailyBudget) return 'DAILY_LOSS_RISK_LIMIT';
  return null;
}
