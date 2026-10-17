/// Deterministic admission for broker Paper option orders.
///
/// Reuses the existing app rules: the versioned US option session calendar
/// ([paperSession]), expiry handling ([paperExpiry]), the qualified-quote
/// thresholds of [OptionQuote.valid] (via [quoteReason]), the conservative fee
/// ([executionFee] for conservative-v2), and the risk-cap fields and defaults of
/// [paperRiskReason] (risk/allocation/contracts/positions/daily loss), plus the
/// same-underlying opposite-direction lock. Long single Call/Put only: buys open,
/// sells only close an owned long position. Closing is never vetoed by
/// entry-only risk caps. Research or AI output has no input here.
library;

import '../market_paper_policy.dart';
import '../paper_execution.dart';
import 'broker_models.dart';
import 'broker_options.dart';
import 'broker_order_journal.dart';
import 'broker_portfolio.dart';
import 'live_gate.dart';

enum TicketSide { buyToOpen, sellToClose }

class BrokerOrderTicket {
  final String contract; // OCC
  final TicketSide side;
  final int quantity, limitCents;
  final String? ibkrConid;
  const BrokerOrderTicket({required this.contract, required this.side, required this.quantity,
      required this.limitCents, this.ibkrConid});
  String get sideCode => side == TicketSide.buyToOpen ? 'BUY_TO_OPEN' : 'SELL_TO_CLOSE';
}

class BrokerRiskPolicy {
  final int riskPercent, allocationPercent, maxContracts, maxPositions, dailyLossPercent;
  const BrokerRiskPolicy({this.riskPercent = 5, this.allocationPercent = 30, this.maxContracts = 10,
      this.maxPositions = 4, this.dailyLossPercent = 3});
  int get feePerContractCents => executionFee(const {'executionPolicy': conservativeExecution});
  Map<String, int> toJson() => {'riskPercent': riskPercent, 'allocationPercent': allocationPercent,
        'maxContracts': maxContracts, 'maxPositions': maxPositions, 'dailyLossPercent': dailyLossPercent,
        'feePerContractCents': feePerContractCents};
}

class BrokerAdmission {
  final String? reason; // null = admitted
  final int costCents, feeCents;
  final List<String> passed;
  const BrokerAdmission(this.reason, this.costCents, this.feeCents, this.passed);
  bool get admitted => reason == null;
}

int _pct(int cents, int percent) => cents * percent ~/ 100;

BrokerAdmission admitBrokerOrder(BrokerOrderTicket t, BrokerPortfolio portfolio, BrokerQuote? quote,
    List<BrokerOrderRecord> orders, DateTime now, {BrokerRiskPolicy policy = const BrokerRiskPolicy()}) {
  final passed = <String>[];
  BrokerAdmission no(String reason) => BrokerAdmission(reason, 0, 0, List.unmodifiable(passed));
  final account = portfolio.account, broker = account.broker;

  try {
    LiveTradingGate.requirePaper(account.environment);
  } on LiveTradingDisabled catch (e) {
    return no(e.message);
  }
  if (account.archived) return no('ACCOUNT_ARCHIVED');
  if (!portfolio.snapshot.paperVerified) return no('NOT_PAPER_ACCOUNT');
  passed.add('PAPER_ONLY');
  if (portfolio.isStale(now)) return no('PORTFOLIO_STALE');
  passed.add('FRESH_ACCOUNT_STATE');
  if (orders.any((o) => o.unresolved)) return no('UNRESOLVED_ORDER_RECONCILE_REQUIRED');
  passed.add('NO_UNRESOLVED_ORDERS');

  final c = OccContract.parse(t.contract);
  if (c == null || c.occ != t.contract) return no('INVALID_CONTRACT');
  if (t.quantity < 1 || t.quantity > 1000 || t.limitCents < 1 || t.limitCents > 10000000) return no('INVALID_ORDER');
  if (broker == BrokerKind.ibkr && (t.ibkrConid == null || !RegExp(r'^\d{1,12}$').hasMatch(t.ibkrConid!))) {
    return no('IBKR_CONID_REQUIRED');
  }
  final buy = t.side == TicketSide.buyToOpen;
  final expiry = paperExpiry(c.occ, now);
  if (buy ? !expiry.entry : !expiry.close) return no('EXPIRY_${expiry.status}');
  passed.add('EXPIRY');
  final session = paperSession(now);
  if (buy ? !session.entry : !session.fill) return no('SESSION_${session.status}');
  passed.add('SESSION');
  final q = quoteReason(quote, c.occ, t.quantity, now);
  if (q != null) return no(q);
  passed.add('QUALIFIED_QUOTE');
  if (t.limitCents < quote!.bid || t.limitCents > quote.ask) return no('LIMIT_OUTSIDE_QUOTE');
  passed.add('LIMIT_WITHIN_QUOTE');

  // Current holdings by OCC; non-option rows still count toward exposure/positions.
  final held = <String, int>{};
  var exposure = 0, contracts = 0, openLoss = 0, positionsCount = 0;
  for (final p in portfolio.positions) {
    final qty = decimalCents(p.quantity);
    if (qty == null) return no('POSITION_UNREADABLE');
    final occ = positionOcc(broker, p);
    if (occ != null && qty < 0) return no('SHORT_OPTION_REVIEW_REQUIRED');
    if (qty == 0) continue;
    positionsCount++;
    if (occ != null) {
      held[occ] = (held[occ] ?? 0) + qty ~/ 100;
      contracts += qty ~/ 100;
    }
    final mv = decimalCents(p.marketValue, up: true);
    if (mv == null) return no('RISK_UNAVAILABLE_POSITION_MARK');
    exposure += mv.abs();
    final pl = decimalCents(p.unrealizedPl);
    if (pl == null) return no('RISK_UNAVAILABLE_POSITION_MARK');
    if (pl < 0) openLoss -= pl;
  }
  // Acknowledged, not yet terminal orders still reserve risk until reconciled.
  final pending = orders.where((o) => !o.terminal).toList();

  if (!buy) {
    final reserved = pending.where((o) => o.side == 'SELL_TO_CLOSE' && o.contract == c.occ)
        .fold<int>(0, (s, o) => s + o.remaining);
    if ((held[c.occ] ?? 0) - reserved < t.quantity) return no('CLOSE_EXCEEDS_POSITION');
    passed.add('OWNED_LONG_POSITION');
    final fee = t.quantity * policy.feePerContractCents;
    return BrokerAdmission(null, -(t.quantity * t.limitCents * 100) + fee, fee, List.unmodifiable(passed));
  }

  final opposite = c.right == 'C' ? 'P' : 'C';
  bool oppositeOcc(String occ) {
    final o = OccContract.parse(occ);
    return o != null && o.root == c.root && o.right == opposite;
  }
  if (held.entries.any((e) => e.value > 0 && oppositeOcc(e.key)) ||
      pending.any((o) => o.side == 'BUY_TO_OPEN' && oppositeOcc(o.contract))) {
    return no('OPPOSITE_DIRECTION_LOCK');
  }
  passed.add('OPPOSITE_DIRECTION_LOCK');

  final fee = t.quantity * policy.feePerContractCents;
  final cost = t.quantity * t.limitCents * 100 + fee;
  final s = portfolio.snapshot;
  final cash = decimalCents(s.cash), buyingPower = decimalCents(s.buyingPower), equity = decimalCents(s.equity);
  if (cash == null || equity == null || equity <= 0) return no('BALANCE_UNAVAILABLE');
  if (cost > cash || (buyingPower != null && cost > buyingPower)) return no('RISK_LIMIT');
  final pendingBuys = pending.where((o) => o.side == 'BUY_TO_OPEN');
  final pendingCost = pendingBuys.fold<int>(0, (a, o) => a + ((o.intent['costCents'] as int?) ?? 0));
  final sameContractCost = portfolio.positions
      .where((p) => positionOcc(broker, p) == c.occ)
      .fold<int>(0, (a, p) => a + (decimalCents(p.marketValue, up: true) ?? 0).abs()) +
      pendingBuys.where((o) => o.contract == c.occ).fold<int>(0, (a, o) => a + ((o.intent['costCents'] as int?) ?? 0));
  if (sameContractCost + cost > _pct(equity, policy.riskPercent)) return no('RISK_LIMIT');
  passed.add('TRADE_RISK');
  if (exposure + pendingCost + cost > _pct(equity, policy.allocationPercent)) return no('ALLOCATION_RISK_LIMIT');
  passed.add('ALLOCATION');
  final pendingContracts = pendingBuys.fold<int>(0, (a, o) => a + o.remaining);
  if (contracts + pendingContracts + t.quantity > policy.maxContracts) return no('CONTRACT_COUNT_RISK_LIMIT');
  passed.add('CONTRACT_COUNT');
  final adding = (held[c.occ] ?? 0) > 0 || pendingBuys.any((o) => o.contract == c.occ);
  final pendingNew = pendingBuys.map((o) => o.contract).where((x) => (held[x] ?? 0) == 0).toSet().length;
  if (!adding && positionsCount + pendingNew + 1 > policy.maxPositions) return no('POSITION_COUNT_RISK_LIMIT');
  passed.add('POSITION_COUNT');
  // Broker data lacks a reliable same-day realized P/L across all three APIs; the
  // cutoff uses current open losses only (documented limit).
  if (openLoss >= _pct(equity, policy.dailyLossPercent)) return no('DAILY_LOSS_RISK_LIMIT');
  passed.add('OPEN_LOSS');
  return BrokerAdmission(null, cost, fee, List.unmodifiable(passed));
}
