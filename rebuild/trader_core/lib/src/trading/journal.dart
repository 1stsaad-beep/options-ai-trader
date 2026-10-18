/// Decision journal, closed-trade records and performance report.
///
/// Every decision — including decisions NOT to trade and lock blocks — is
/// recorded with its reason at the moment it was made, together with the
/// analysis snapshot and settings that produced it. Records are never edited.
library;

import 'dart:math' as math;

import '../models.dart';

enum JournalAction { entry, exit, scaleIn, skip, blocked, orderFilled, orderCancelled, error, info }

extension JournalActionAr on JournalAction {
  String get arabic => switch (this) {
        JournalAction.entry => 'دخول',
        JournalAction.exit => 'خروج',
        JournalAction.scaleIn => 'تعزيز',
        JournalAction.skip => 'تجاهل',
        JournalAction.blocked => 'محظور',
        JournalAction.orderFilled => 'تنفيذ',
        JournalAction.orderCancelled => 'إلغاء',
        JournalAction.error => 'خطأ',
        JournalAction.info => 'معلومة',
      };
}

class JournalEntry {
  final DateTime time;
  final JournalAction action;
  final String? symbol;
  final String reasonAr;
  final Map<String, Object?> details;

  const JournalEntry({
    required this.time,
    required this.action,
    required this.reasonAr,
    this.symbol,
    this.details = const {},
  });

  Map<String, Object?> toJson() => {
        't': time.toIso8601String(),
        'a': action.name,
        if (symbol != null) 's': symbol,
        'r': reasonAr,
        if (details.isNotEmpty) 'd': details,
      };

  factory JournalEntry.fromJson(Map<String, dynamic> j) => JournalEntry(
        time: DateTime.parse(j['t'] as String),
        action: JournalAction.values.byName(j['a'] as String),
        symbol: j['s'] as String?,
        reasonAr: j['r'] as String,
        details: (j['d'] as Map?)?.cast<String, Object?>() ?? const {},
      );
}

/// One realised exit (a partial exit produces its own record).
class TradeRecord {
  final String occSymbol;
  final String underlying;
  final OptionRight right;
  final DateTime entryTime;
  final DateTime exitTime;
  final int quantity;
  final int entryPremiumCents;
  final int exitPremiumCents;
  final int multiplier;
  final int feesCents;
  final String exitKind;
  final String entryReasonAr;
  final String exitReasonAr;

  /// Engines (EngineId names) that supported the entry; empty for trades
  /// recorded before v2.0.0-dev.5 or positions not opened by the app.
  final List<String> engines;

  const TradeRecord({
    required this.occSymbol,
    required this.underlying,
    required this.right,
    required this.entryTime,
    required this.exitTime,
    required this.quantity,
    required this.entryPremiumCents,
    required this.exitPremiumCents,
    required this.feesCents,
    required this.exitKind,
    required this.entryReasonAr,
    required this.exitReasonAr,
    this.multiplier = 100,
    this.engines = const [],
  });

  int get pnlCents => (exitPremiumCents - entryPremiumCents) * quantity * multiplier - feesCents;
  double get returnPercent => entryPremiumCents == 0 ? 0 : (exitPremiumCents - entryPremiumCents) / entryPremiumCents * 100;

  Map<String, Object?> toJson() => {
        'occ': occSymbol,
        'u': underlying,
        'r': right.name,
        'et': entryTime.toIso8601String(),
        'xt': exitTime.toIso8601String(),
        'q': quantity,
        'ep': entryPremiumCents,
        'xp': exitPremiumCents,
        'm': multiplier,
        'f': feesCents,
        'k': exitKind,
        'er': entryReasonAr,
        'xr': exitReasonAr,
        if (engines.isNotEmpty) 'eng': engines,
      };

  factory TradeRecord.fromJson(Map<String, dynamic> j) => TradeRecord(
        occSymbol: j['occ'] as String,
        underlying: j['u'] as String,
        right: OptionRight.parse(j['r'] as String),
        entryTime: DateTime.parse(j['et'] as String),
        exitTime: DateTime.parse(j['xt'] as String),
        quantity: j['q'] as int,
        entryPremiumCents: j['ep'] as int,
        exitPremiumCents: j['xp'] as int,
        multiplier: j['m'] as int? ?? 100,
        feesCents: j['f'] as int? ?? 0,
        exitKind: j['k'] as String,
        entryReasonAr: j['er'] as String? ?? '',
        exitReasonAr: j['xr'] as String? ?? '',
        engines: [for (final e in (j['eng'] as List? ?? const [])) e as String],
      );
}

class EquityPoint {
  final DateTime time;
  final int equityCents;
  const EquityPoint(this.time, this.equityCents);
  List<Object> toJson() => [time.toIso8601String(), equityCents];
  factory EquityPoint.fromJson(List<dynamic> j) => EquityPoint(DateTime.parse(j[0] as String), j[1] as int);
}

class PerformanceReport {
  final int trades;
  final int wins;
  final int losses;

  /// Trades with exactly zero P/L after fees (neither a win nor a loss).
  final int breakevens;
  final int realizedPnlCents;
  final int grossProfitCents;
  final int grossLossCents;
  final int feesCents;
  final int bestTradeCents;
  final int worstTradeCents;

  /// Largest peak-to-trough fall of the equity curve, % of the peak.
  final double maxDrawdownPercent;
  final int maxDrawdownCents;
  final int? currentEquityCents;
  final double? totalReturnPercent;

  const PerformanceReport({
    required this.trades,
    required this.wins,
    required this.losses,
    this.breakevens = 0,
    required this.realizedPnlCents,
    required this.grossProfitCents,
    required this.grossLossCents,
    required this.feesCents,
    required this.bestTradeCents,
    required this.worstTradeCents,
    required this.maxDrawdownPercent,
    required this.maxDrawdownCents,
    this.currentEquityCents,
    this.totalReturnPercent,
  });

  double get winRatePercent => trades == 0 ? 0 : wins / trades * 100;

  /// Gross profit / gross loss; infinite when there are no losses.
  double get profitFactor => grossLossCents == 0 ? (grossProfitCents > 0 ? double.infinity : 0) : grossProfitCents / grossLossCents;
  double get averageWinCents => wins == 0 ? 0 : grossProfitCents / wins;
  double get averageLossCents => losses == 0 ? 0 : grossLossCents / losses;

  static PerformanceReport compute(List<TradeRecord> trades, List<EquityPoint> curve, {int? startingEquityCents}) {
    var wins = 0, losses = 0, even = 0, pnl = 0, gp = 0, gl = 0, fees = 0, best = 0, worst = 0;
    for (final t in trades) {
      final p = t.pnlCents;
      pnl += p;
      fees += t.feesCents;
      if (p > 0) {
        wins++;
        gp += p;
      } else if (p < 0) {
        losses++;
        gl += -p;
      } else {
        even++;
      }
      best = math.max(best, p);
      worst = math.min(worst, p);
    }
    var peak = 0, maxDd = 0;
    var maxDdPct = 0.0;
    for (final e in curve) {
      peak = math.max(peak, e.equityCents);
      final dd = peak - e.equityCents;
      if (dd > maxDd) maxDd = dd;
      if (peak > 0) maxDdPct = math.max(maxDdPct, dd / peak * 100);
    }
    final current = curve.isEmpty ? null : curve.last.equityCents;
    final start = startingEquityCents ?? (curve.isEmpty ? null : curve.first.equityCents);
    return PerformanceReport(
      trades: trades.length,
      wins: wins,
      losses: losses,
      breakevens: even,
      realizedPnlCents: pnl,
      grossProfitCents: gp,
      grossLossCents: gl,
      feesCents: fees,
      bestTradeCents: best,
      worstTradeCents: worst,
      maxDrawdownPercent: maxDdPct,
      maxDrawdownCents: maxDd,
      currentEquityCents: current,
      totalReturnPercent: (current == null || start == null || start == 0) ? null : (current - start) / start * 100,
    );
  }
}

/// Formats cents as `$1,234.56` (no locale dependency).
String formatUsd(int cents) {
  final neg = cents < 0;
  final abs = cents.abs();
  final dollars = (abs ~/ 100).toString();
  final buf = StringBuffer();
  for (var i = 0; i < dollars.length; i++) {
    if (i > 0 && (dollars.length - i) % 3 == 0) buf.write(',');
    buf.write(dollars[i]);
  }
  return '${neg ? '-' : ''}\$$buf.${(abs % 100).toString().padLeft(2, '0')}';
}
