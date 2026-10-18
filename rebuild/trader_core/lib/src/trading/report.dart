/// Per-account performance report and CSV/JSON exports (trades, daily and
/// weekly breakdown by New York date, per-engine contribution, activity log).
library;

import '../analysis/signal.dart';
import '../market/market_calendar.dart';
import 'cycle_record.dart';
import 'journal.dart';

/// Realised P/L of the trades closed in one period (New York date or week).
class PeriodPnl {
  /// `yyyy-mm-dd` (day) or the Monday of the week (week), New York dates.
  final String key;
  int trades = 0;
  int wins = 0;
  int losses = 0;
  int breakevens = 0;
  int pnlCents = 0;
  PeriodPnl(this.key);

  void add(TradeRecord t) {
    trades++;
    pnlCents += t.pnlCents;
    if (t.pnlCents > 0) {
      wins++;
    } else if (t.pnlCents < 0) {
      losses++;
    } else {
      breakevens++;
    }
  }

  Map<String, Object?> toJson() =>
      {'period': key, 'trades': trades, 'wins': wins, 'losses': losses, 'breakevens': breakevens, 'pnlCents': pnlCents};
}

/// Trades an engine supported at entry. A trade backed by 3 engines counts
/// for each of them, so rows overlap and must not be summed.
/// Attribution tag of entries opened by the experimental daily Elliott strategy.
const elliottDailyTag = 'strategy:elliottDaily';

class EngineStats {
  final String engine;
  int trades = 0;
  int wins = 0;
  int losses = 0;
  int pnlCents = 0;
  EngineStats(this.engine);

  double get winRatePercent => trades == 0 ? 0 : wins / trades * 100;

  String get arabic {
    for (final e in EngineId.values) {
      if (e.name == engine) return e.arabic;
    }
    if (engine == elliottDailyTag) return 'إليوت اليومي (تجريبي)';
    return engine;
  }

  Map<String, Object?> toJson() => {'engine': engine, 'trades': trades, 'wins': wins, 'losses': losses, 'pnlCents': pnlCents};
}

class AccountReport {
  final PerformanceReport performance;

  /// Open-position P/L at current quotes; null when not priced.
  final int? unrealizedPnlCents;
  final List<TradeRecord> trades;
  final List<PeriodPnl> daily;
  final List<PeriodPnl> weekly;
  final List<EngineStats> engines;

  /// Closed trades without engine attribution (older records / external positions).
  final int untaggedTrades;
  final DateTime generatedAt;

  const AccountReport({
    required this.performance,
    required this.unrealizedPnlCents,
    required this.trades,
    required this.daily,
    required this.weekly,
    required this.engines,
    required this.untaggedTrades,
    required this.generatedAt,
  });

  /// Monday (New York date) of the week containing [instant].
  static String weekKey(DateTime instant) {
    final w = NewYorkTime.wall(instant);
    final d = DateTime.utc(w.year, w.month, w.day).subtract(Duration(days: w.weekday - DateTime.monday));
    return '${d.year.toString().padLeft(4, '0')}-${d.month.toString().padLeft(2, '0')}-${d.day.toString().padLeft(2, '0')}';
  }

  static AccountReport build(
    List<TradeRecord> trades,
    List<EquityPoint> curve, {
    int? startingEquityCents,
    int? unrealizedPnlCents,
    DateTime? now,
  }) {
    final daily = <String, PeriodPnl>{};
    final weekly = <String, PeriodPnl>{};
    final engines = <String, EngineStats>{};
    var untagged = 0;
    for (final t in trades) {
      daily.putIfAbsent(NewYorkTime.dateKey(t.exitTime), () => PeriodPnl(NewYorkTime.dateKey(t.exitTime))).add(t);
      final wk = weekKey(t.exitTime);
      weekly.putIfAbsent(wk, () => PeriodPnl(wk)).add(t);
      if (t.engines.isEmpty) untagged++;
      for (final e in t.engines.toSet()) {
        final s = engines.putIfAbsent(e, () => EngineStats(e));
        s.trades++;
        s.pnlCents += t.pnlCents;
        if (t.pnlCents > 0) s.wins++;
        if (t.pnlCents < 0) s.losses++;
      }
    }
    List<PeriodPnl> sorted(Map<String, PeriodPnl> m) => m.values.toList()..sort((a, b) => b.key.compareTo(a.key));
    return AccountReport(
      performance: PerformanceReport.compute(trades, curve, startingEquityCents: startingEquityCents),
      unrealizedPnlCents: unrealizedPnlCents,
      trades: List.unmodifiable(trades),
      daily: sorted(daily),
      weekly: sorted(weekly),
      engines: engines.values.toList()..sort((a, b) => b.trades.compareTo(a.trades)),
      untaggedTrades: untagged,
      generatedAt: (now ?? DateTime.now()).toUtc(),
    );
  }

  Map<String, Object?> toJson() {
    final p = performance;
    return {
      'generatedAt': generatedAt.toIso8601String(),
      'summary': {
        'trades': p.trades,
        'wins': p.wins,
        'losses': p.losses,
        'breakevens': p.breakevens,
        'winRatePercent': double.parse(p.winRatePercent.toStringAsFixed(2)),
        'realizedPnlCents': p.realizedPnlCents,
        'unrealizedPnlCents': unrealizedPnlCents,
        'grossProfitCents': p.grossProfitCents,
        'grossLossCents': p.grossLossCents,
        'feesCents': p.feesCents,
        'maxDrawdownPercent': double.parse(p.maxDrawdownPercent.toStringAsFixed(2)),
        'maxDrawdownCents': p.maxDrawdownCents,
        'totalReturnPercent': p.totalReturnPercent == null ? null : double.parse(p.totalReturnPercent!.toStringAsFixed(2)),
      },
      'daily': [for (final d in daily) d.toJson()],
      'weekly': [for (final w in weekly) w.toJson()],
      'engines': [for (final e in engines) e.toJson()],
      'untaggedTrades': untaggedTrades,
      'trades': [for (final t in trades) _tradeRow(t)],
    };
  }

  static Map<String, Object?> _tradeRow(TradeRecord t) => {
        'contract': t.occSymbol,
        'underlying': t.underlying,
        'right': t.right.name,
        'entryTimeUtc': t.entryTime.toUtc().toIso8601String(),
        'exitTimeUtc': t.exitTime.toUtc().toIso8601String(),
        'exitDateNY': NewYorkTime.dateKey(t.exitTime),
        'quantity': t.quantity,
        'entryPremium': t.entryPremiumCents / 100,
        'exitPremium': t.exitPremiumCents / 100,
        'fees': t.feesCents / 100,
        'pnl': t.pnlCents / 100,
        'returnPercent': double.parse(t.returnPercent.toStringAsFixed(2)),
        'result': t.pnlCents > 0 ? 'win' : (t.pnlCents < 0 ? 'loss' : 'breakeven'),
        'exitKind': t.exitKind,
        'engines': t.engines.join('|'),
        'entryReason': t.entryReasonAr,
        'exitReason': t.exitReasonAr,
      };

  String tradesCsv() {
    final rows = [for (final t in trades) _tradeRow(t)];
    const header = [
      'contract', 'underlying', 'right', 'entryTimeUtc', 'exitTimeUtc', 'exitDateNY', 'quantity', 'entryPremium',
      'exitPremium', 'fees', 'pnl', 'returnPercent', 'result', 'exitKind', 'engines', 'entryReason', 'exitReason',
    ];
    return toCsv(header, [for (final r in rows) [for (final h in header) r[h]]]);
  }

  String periodsCsv() => toCsv(const ['period', 'type', 'trades', 'wins', 'losses', 'breakevens', 'pnl'], [
        for (final d in daily) [d.key, 'day', d.trades, d.wins, d.losses, d.breakevens, d.pnlCents / 100],
        for (final w in weekly) [w.key, 'week', w.trades, w.wins, w.losses, w.breakevens, w.pnlCents / 100],
      ]);
}

/// Activity-log export rows (one row per symbol per cycle; cycles without
/// symbols get one row).
String cyclesCsv(List<CycleRecord> cycles) {
  const header = [
    'cycle', 'startUtc', 'dateNY', 'timeNY', 'marketPhase', 'market', 'symbol', 'score', 'bias', 'decision', 'reason',
    'orders', 'fills', 'errors', 'note',
  ];
  final rows = <List<Object?>>[];
  for (final c in cycles) {
    final base = [c.cycle, c.start.toUtc().toIso8601String(), NewYorkTime.dateKey(c.start), NewYorkTime.hm(c.start), c.marketPhase ?? '', c.marketSummaryAr ?? ''];
    final tail = [c.orders.join(' ; '), c.fills, c.errors.join(' ; '), c.noteAr];
    if (c.symbols.isEmpty) {
      rows.add([...base, '', '', '', '', '', ...tail]);
    } else {
      for (final n in c.symbols.values) {
        rows.add([...base, n.symbol, n.score?.toStringAsFixed(1) ?? '', n.bias ?? '', n.action, n.reasonAr, ...tail]);
      }
    }
  }
  return toCsv(header, rows);
}

/// RFC 4180 CSV (CRLF, quotes doubled when needed).
String toCsv(List<String> header, List<List<Object?>> rows) {
  String cell(Object? v) {
    final s = v == null ? '' : '$v';
    return s.contains(RegExp('[",\r\n]')) ? '"${s.replaceAll('"', '""')}"' : s;
  }

  final b = StringBuffer()..write(header.map(cell).join(','))..write('\r\n');
  for (final r in rows) {
    b
      ..write(r.map(cell).join(','))
      ..write('\r\n');
  }
  return b.toString();
}
