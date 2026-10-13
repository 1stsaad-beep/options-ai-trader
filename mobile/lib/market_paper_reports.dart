import 'direct_alpaca.dart';

const paperStrategies = ['trend', 'breakout', 'pullback', 'divergence'];
const paperStrategyLabels = {
  'confluence': 'توافق المؤشرات — القاعدة السابقة',
  'trend': 'اتجاه SMA / MACD / RSI',
  'breakout': 'اختراق نطاق مع حجم',
  'pullback': 'تراجع إلى المتوسط مع تأكيد',
  'divergence': 'دايفرجنس مع كسر بنية السعر',
};

Map<String, dynamic> paperPerformance(Map<String, dynamic> account, DateTime now) {
  var basis = 0, entryFees = 0, liquidation = 0;
  var complete = true;
  for (final raw in (account['positions'] as Map).values) {
    final p = raw as Map;
    final quantity = p['quantity'] as int;
    basis += p['cost'] as int;
    entryFees += (p['entryFees'] ?? quantity * 65) as int;
    final mark = p['mark'];
    if (mark is! Map) { complete = false; continue; }
    final quote = OptionQuote(p['contract'] as String, mark['feed'] as String,
      DateTime.parse(mark['at'] as String), mark['bid'] as int, mark['ask'] as int,
      mark['bidSize'] as int, mark['askSize'] as int);
    if (!quote.valid(now, quantity: quantity)) { complete = false; continue; }
    liquidation += quote.bid * quantity * 100 - quantity * 65;
  }
  final cash = account['cash'] as int, initial = account['initialCash'] as int;
  // Original V1 charged USD0.65 on every entry; this basis is derivable for
  // still-owned inventory. Unknown historical trade/fee totals remain null.
  final realized = cash + basis + entryFees - initial;
  final equity = complete ? cash + liquidation : null;
  final trades = account['closedTrades'] as int?;
  return {
    'source': 'independent_market_paper', 'executionModel': 'approximate_quote_side',
    'initialCashCents': initial, 'cashCents': cash, 'realizedPnlCents': realized,
    'unrealizedPnlCents': complete ? liquidation - basis - entryFees : null,
    'equityCents': equity, 'returnPercent': equity == null ? null : (equity - initial) * 100 / initial,
    'valuationComplete': complete, 'totalFeesCents': account['fees'],
    'closedTrades': trades, 'winningTrades': account['winningTrades'],
    'winRatePercent': trades == null || trades == 0 ? null : (account['winningTrades'] as int) * 100 / trades,
    'sampledMaxDrawdownCents': account['maxDrawdown'],
    'drawdownPolicy': 'observed_fresh_option_bid_equity_after_modeled_closing_fees',
    'unknownLegacyTotals': account['fees'] == null,
  };
}

Map<String, dynamic> paperComparison(Map<String, dynamic> book, DateTime now) {
  final experiment = book['experiment'] as Map?;
  final ids = (experiment?['accounts'] as List? ?? []).cast<String>();
  final accounts = (book['accounts'] as List).cast<Map<String, dynamic>>()
      .where((a) => ids.contains(a['id'])).toList();
  final events = (book['journal'] as List).cast<Map<String, dynamic>>()
      .where((event) => ids.contains(event['account'])).toList();
  final actual = events.where((event) => event['evidence'] is Map &&
      event['evidence']['source'] == 'alpaca' && event['evidence']['stockDataValid'] == true);
  final dates = actual.map((event) => (event['evidence']['observation'] as String).substring(0, 10)).toSet().toList()..sort();
  return {
    'schema': 'paper-comparison-v1', 'generatedAt': now.toUtc().toIso8601String(),
    'experimentCreated': experiment != null, 'targetSessions': 3,
    'sourcePolicy': 'only_original_alpaca_observations_count_toward_sessions',
    'status': dates.isEmpty ? 'NOT_RUN' : 'PARTIAL_OBSERVATIONS_NOT_FULL_SESSION_ACCEPTANCE',
    'accounts': [for (final a in accounts) {
      'id': a['id'], 'name': a['name'], 'strategy': a['strategy'], 'watchlist': a['watchlist'],
      'performance': paperPerformance(a, now),
      'riskViolations': null,
      'riskViolationPolicy': 'Not measured; rejected admissions are riskBlocks, not proven violations',
      'riskBlocks': events.where((e) => e['account'] == a['id'] && (e['decision'] as String).contains('RISK')).length,
      'dataInterruptions': events.where((e) => e['account'] == a['id'] &&
        ['INVALID_OR_STALE_STOCK_DATA', 'OPRA_QUOTE_REQUIRED_NO_FILL', 'CLOSE_UNCONFIRMED_NO_REVERSAL'].contains(e['decision'])).length,
    }],
    'sessions': [for (var i = 0; i < 3; i++) {
      'number': i + 1, 'date': i < dates.length ? dates[i] : null,
      'status': i < dates.length ? 'PARTIALLY_OBSERVED' : 'NOT_RUN',
      'accounts': [for (final a in accounts) {
        'id': a['id'],
        'decisions': i < dates.length ? actual.where((e) => e['account'] == a['id'] &&
          (e['evidence']['observation'] as String).startsWith(dates[i])).length : null,
        'realizedPnlCents': i < dates.length ? actual.where((e) => e['account'] == a['id'] &&
          (e['evidence']['observation'] as String).startsWith(dates[i])).fold<int>(0, (sum, e) => sum + ((e['fill']?['realizedPnl'] ?? 0) as int)) : null,
      }],
    }],
    'originalDecisions': events,
    'limitations': ['No external orders', 'No claim of real execution or profitability',
      'Three full sessions require future observed evidence; fixtures never count',
      'Drawdown is sampled; missing/stale marks are not zero P&L'],
  };
}
