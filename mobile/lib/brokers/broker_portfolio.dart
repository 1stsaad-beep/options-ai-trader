/// One read-only Paper portfolio observation: balances + positions fetched together.
library;

import 'broker_adapter.dart';
import 'broker_models.dart';

class BrokerPortfolio {
  final BrokerAccount account;
  final BrokerAccountSnapshot snapshot;
  final List<BrokerPosition> positions;
  final DateTime fetchedAt; // local receipt time; broker values are shown exactly as reported
  const BrokerPortfolio(this.account, this.snapshot, this.positions, this.fetchedAt);

  static const staleAfter = Duration(seconds: 60);
  bool isStale(DateTime now) => now.difference(fetchedAt) > staleAfter;
  String get source => account.broker.paperTitle;
}

/// Balances first (authenticates/verifies the Paper account), then positions.
/// Any failure yields no partial portfolio, so stale values are never mixed with new ones.
Future<BrokerPortfolio> loadPortfolio(BrokerAccount account, BrokerAdapter adapter,
    {DateTime Function()? clock}) async {
  final snapshot = await adapter.connect();
  if (!snapshot.paperVerified) throw const BrokerException('NOT_PAPER_ACCOUNT');
  final positions = await adapter.positions();
  return BrokerPortfolio(account, snapshot, List.unmodifiable(positions), (clock ?? DateTime.now)());
}
