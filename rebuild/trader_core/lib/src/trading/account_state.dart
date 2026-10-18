/// Persistent engine state of ONE account (separate from AccountProfile so the
/// user can edit settings without touching trading memory). Serialised to JSON
/// by the app; nothing here is shared between accounts.
library;

import '../models.dart';
import 'cycle_record.dart';
import 'decision_engine.dart';
import 'journal.dart';

/// An order the engine submitted and is still following.
class TrackedOrder {
  final String orderId;
  final String clientOrderId;
  final String occSymbol;
  final OrderSide side;

  /// 'entry' | 'scaleIn' | exit kind name.
  final String purpose;
  final String reasonAr;
  final int submittedCycle;
  int processedFilled;

  /// Entry-only context captured at decision time.
  final double? underlyingInvalidation;
  final double? underlyingTarget;
  final double score;

  TrackedOrder({
    required this.orderId,
    required this.clientOrderId,
    required this.occSymbol,
    required this.side,
    required this.purpose,
    required this.reasonAr,
    required this.submittedCycle,
    this.processedFilled = 0,
    this.underlyingInvalidation,
    this.underlyingTarget,
    this.score = 0,
  });

  Map<String, Object?> toJson() => {
        'id': orderId,
        'cid': clientOrderId,
        'occ': occSymbol,
        'side': side.name,
        'purpose': purpose,
        'reason': reasonAr,
        'cycle': submittedCycle,
        'done': processedFilled,
        'inval': underlyingInvalidation,
        'target': underlyingTarget,
        'score': score,
      };

  factory TrackedOrder.fromJson(Map<String, dynamic> j) => TrackedOrder(
        orderId: j['id'] as String,
        clientOrderId: j['cid'] as String,
        occSymbol: j['occ'] as String,
        side: OrderSide.values.byName(j['side'] as String),
        purpose: j['purpose'] as String,
        reasonAr: j['reason'] as String? ?? '',
        submittedCycle: j['cycle'] as int,
        processedFilled: j['done'] as int? ?? 0,
        underlyingInvalidation: (j['inval'] as num?)?.toDouble(),
        underlyingTarget: (j['target'] as num?)?.toDouble(),
        score: (j['score'] as num?)?.toDouble() ?? 0,
      );
}

class AccountState {
  static const int maxJournal = 3000;
  static const int maxCurve = 3000;
  static const int maxCycles = 600;

  int cycle;
  final Map<String, PositionMeta> metas;
  final Map<String, TrackedOrder> tracked; // by orderId
  /// Contracts whose next order should be priced at the far side (stale order was cancelled).
  final Set<String> escalate;
  final List<TradeRecord> trades;
  final List<EquityPoint> equityCurve;
  final List<JournalEntry> journal;
  String? dayKey;
  int? dayStartEquityCents;
  String? dailyLimitNotifiedFor;

  /// Raw broker-specific state (the simulator ledger lives here).
  Map<String, dynamic>? brokerState;

  /// Opening orders (entries + scale-ins) sent on New York day [ordersDayKey].
  int ordersToday;
  String? ordersDayKey;

  /// Last entry/exit submission per underlying (cooldown).
  final Map<String, DateTime> lastTradeAt;

  /// Most recent cycles, oldest first (bounded by [maxCycles]).
  final List<CycleRecord> cycles;

  AccountState({
    this.cycle = 0,
    Map<String, PositionMeta>? metas,
    Map<String, TrackedOrder>? tracked,
    Set<String>? escalate,
    List<TradeRecord>? trades,
    List<EquityPoint>? equityCurve,
    List<JournalEntry>? journal,
    this.dayKey,
    this.dayStartEquityCents,
    this.dailyLimitNotifiedFor,
    this.brokerState,
    this.ordersToday = 0,
    this.ordersDayKey,
    Map<String, DateTime>? lastTradeAt,
    List<CycleRecord>? cycles,
  })  : lastTradeAt = lastTradeAt ?? {},
        cycles = cycles ?? [],
        metas = metas ?? {},
        tracked = tracked ?? {},
        escalate = escalate ?? {},
        trades = trades ?? [],
        equityCurve = equityCurve ?? [],
        journal = journal ?? [];

  void log(JournalEntry e) {
    journal.add(e);
    if (journal.length > maxJournal) journal.removeRange(0, journal.length - maxJournal);
  }

  void addCycle(CycleRecord r) {
    cycles.add(r);
    if (cycles.length > maxCycles) cycles.removeRange(0, cycles.length - maxCycles);
  }

  void addEquity(EquityPoint p) {
    // Keep at most one point per 5 minutes to bound storage.
    if (equityCurve.isNotEmpty && p.time.difference(equityCurve.last.time).inMinutes < 5) {
      equityCurve[equityCurve.length - 1] = p;
    } else {
      equityCurve.add(p);
    }
    if (equityCurve.length > maxCurve) equityCurve.removeRange(0, equityCurve.length - maxCurve);
  }

  Map<String, Object?> toJson() => {
        'v': 1,
        'cycle': cycle,
        'metas': [for (final m in metas.values) m.toJson()],
        'tracked': [for (final t in tracked.values) t.toJson()],
        'escalate': escalate.toList(),
        'trades': [for (final t in trades) t.toJson()],
        'curve': [for (final p in equityCurve) p.toJson()],
        'journal': [for (final e in journal) e.toJson()],
        'dayKey': dayKey,
        'dayStart': dayStartEquityCents,
        'dailyNotified': dailyLimitNotifiedFor,
        'broker': brokerState,
        'ordersToday': ordersToday,
        'ordersDay': ordersDayKey,
        'lastTrade': {for (final e in lastTradeAt.entries) e.key: e.value.toIso8601String()},
        'cycles': [for (final c in cycles) c.toJson()],
      };

  factory AccountState.fromJson(Map<String, dynamic> j) {
    if (j['v'] != 1) throw const FormatException('Unknown account state version');
    List<Map<String, dynamic>> maps(String k) =>
        [for (final e in (j[k] as List? ?? const [])) (e as Map).cast<String, dynamic>()];
    return AccountState(
      cycle: j['cycle'] as int? ?? 0,
      metas: {for (final m in maps('metas').map(PositionMeta.fromJson)) m.occSymbol: m},
      tracked: {for (final t in maps('tracked').map(TrackedOrder.fromJson)) t.orderId: t},
      escalate: {for (final e in (j['escalate'] as List? ?? const [])) e as String},
      trades: maps('trades').map(TradeRecord.fromJson).toList(),
      equityCurve: [for (final p in (j['curve'] as List? ?? const [])) EquityPoint.fromJson(p as List)],
      journal: maps('journal').map(JournalEntry.fromJson).toList(),
      dayKey: j['dayKey'] as String?,
      dayStartEquityCents: j['dayStart'] as int?,
      dailyLimitNotifiedFor: j['dailyNotified'] as String?,
      brokerState: (j['broker'] as Map?)?.cast<String, dynamic>(),
      ordersToday: j['ordersToday'] as int? ?? 0,
      ordersDayKey: j['ordersDay'] as String?,
      lastTradeAt: {
        for (final e in ((j['lastTrade'] as Map?) ?? const {}).entries) e.key as String: DateTime.parse(e.value as String)
      },
      cycles: maps('cycles').map(CycleRecord.fromJson).toList(),
    );
  }
}
