/// Deterministic decision rules: same inputs, same decisions. The only side
/// effect is updating `PositionMeta.peakPremiumCents` (needed by the trailing stop).
///
/// Evaluation order for each account cycle (enforced by TradingEngine):
///   1. Exits for every held position (protective exits first).
///   2. Scale-ins for winners (optional).
///   3. New entries for watchlist symbols that are flat.
///
/// Exit priority (first match wins, all reasons are journaled):
///   stop-loss → underlying invalidation → expiry proximity → trailing stop
///   → full take-profit → opposite signal → max holding time → partial take-profit
library;

import 'dart:math' as math;

import '../analysis/analyzer.dart';
import '../analysis/signal.dart';
import '../models.dart';
import 'account.dart';

/// Engine-side memory about a held position (not reported by brokers).
class PositionMeta {
  final String occSymbol;
  final DateTime entryTime;
  /// Average premium paid; refreshed from the broker's average cost each cycle.
  int entryPremiumCents;
  int peakPremiumCents;
  bool partialTaken;
  int scaleIns;
  int initialQuantity;
  final double? underlyingInvalidation;
  final double? underlyingTarget;
  final double entryScore;
  final String entryReasonAr;

  /// Engines (EngineId names) that supported the entry.
  final List<String> engines;

  PositionMeta({
    required this.occSymbol,
    required this.entryTime,
    required this.entryPremiumCents,
    required this.initialQuantity,
    required this.entryScore,
    required this.entryReasonAr,
    int? peakPremiumCents,
    this.partialTaken = false,
    this.scaleIns = 0,
    this.underlyingInvalidation,
    this.underlyingTarget,
    this.engines = const [],
  }) : peakPremiumCents = peakPremiumCents ?? entryPremiumCents;

  Map<String, Object?> toJson() => {
        'occ': occSymbol,
        'entryTime': entryTime.toIso8601String(),
        'entryPremium': entryPremiumCents,
        'peak': peakPremiumCents,
        'partial': partialTaken,
        'scaleIns': scaleIns,
        'initialQty': initialQuantity,
        'inval': underlyingInvalidation,
        'target': underlyingTarget,
        'score': entryScore,
        'reason': entryReasonAr,
        if (engines.isNotEmpty) 'eng': engines,
      };

  factory PositionMeta.fromJson(Map<String, dynamic> j) => PositionMeta(
        occSymbol: j['occ'] as String,
        entryTime: DateTime.parse(j['entryTime'] as String),
        entryPremiumCents: j['entryPremium'] as int,
        peakPremiumCents: j['peak'] as int?,
        partialTaken: j['partial'] as bool? ?? false,
        scaleIns: j['scaleIns'] as int? ?? 0,
        initialQuantity: j['initialQty'] as int? ?? 1,
        underlyingInvalidation: (j['inval'] as num?)?.toDouble(),
        underlyingTarget: (j['target'] as num?)?.toDouble(),
        entryScore: (j['score'] as num?)?.toDouble() ?? 0,
        entryReasonAr: j['reason'] as String? ?? '',
        engines: [for (final e in (j['eng'] as List? ?? const [])) e as String],
      );
}

enum ExitKind { stopLoss, invalidation, expiry, trailingStop, takeProfit, oppositeSignal, maxHolding, partialProfit }

class ExitDecision {
  final Position position;
  final int quantity;
  final ExitKind kind;
  final String reasonAr;

  /// Protective exits sell at the bid immediately; others start at the
  /// account's aggressiveness and are repriced if stale.
  final bool urgent;
  const ExitDecision(this.position, this.quantity, this.kind, this.reasonAr, {required this.urgent});
}

class EntryIntent {
  final String symbol;
  final OptionRight right;
  final AnalysisReport report;
  final String reasonAr;
  const EntryIntent(this.symbol, this.right, this.report, this.reasonAr);
}

class ScaleIntent {
  final Position position;
  final int quantity;
  final String reasonAr;
  const ScaleIntent(this.position, this.quantity, this.reasonAr);
}

class DecisionEngine {
  final AccountSettings s;
  const DecisionEngine(this.s);

  /// Exit rules for one held position. [markCents] is the current bid (what we
  /// could sell at). [report] is the latest analysis of the underlying, if any.
  ExitDecision? evaluateExit({
    required Position position,
    required PositionMeta meta,
    required int markCents,
    required double? underlyingPrice,
    required AnalysisReport? report,
    required DateTime now,
  }) {
    final entry = meta.entryPremiumCents;
    if (entry <= 0) return null;
    meta.peakPremiumCents = math.max(meta.peakPremiumCents, markCents);
    final pnlPct = (markCents - entry) / entry * 100;
    final c = position.contract;
    final isCall = c.right == OptionRight.call;
    String pct(double v) => '${v >= 0 ? '+' : ''}${v.toStringAsFixed(1)}%';

    if (pnlPct <= -s.stopLossPercent) {
      return ExitDecision(position, position.quantity, ExitKind.stopLoss,
          'وقف الخسارة: العقد ${pct(pnlPct)} (الحد ${s.stopLossPercent.toStringAsFixed(0)}%)', urgent: true);
    }
    final inval = meta.underlyingInvalidation;
    if (s.exitOnUnderlyingInvalidation && inval != null && underlyingPrice != null) {
      final broken = isCall ? underlyingPrice < inval : underlyingPrice > inval;
      if (broken) {
        return ExitDecision(position, position.quantity, ExitKind.invalidation,
            'كسر مستوى إبطال النمط ${inval.toStringAsFixed(2)} (السعر ${underlyingPrice.toStringAsFixed(2)})',
            urgent: true);
      }
    }
    final dte = c.daysToExpiry(now);
    if (dte <= s.exitDaysBeforeExpiry) {
      return ExitDecision(position, position.quantity, ExitKind.expiry, 'اقتراب الانتهاء: $dte يوم متبقٍ', urgent: true);
    }
    final peakPct = (meta.peakPremiumCents - entry) / entry * 100;
    if (peakPct >= s.trailingActivationPercent) {
      final drop = (meta.peakPremiumCents - markCents) / meta.peakPremiumCents * 100;
      if (drop >= s.trailingStopPercent) {
        return ExitDecision(position, position.quantity, ExitKind.trailingStop,
            'وقف متحرك: تراجع ${drop.toStringAsFixed(1)}% من القمة (ربح القمة ${pct(peakPct)}، الآن ${pct(pnlPct)})',
            urgent: true);
      }
    }
    if (pnlPct >= s.takeProfitPercent) {
      return ExitDecision(position, position.quantity, ExitKind.takeProfit, 'هدف الربح: ${pct(pnlPct)}', urgent: false);
    }
    if (s.exitOnOppositeSignal && report != null) {
      final against = isCall ? report.score <= -s.minScore : report.score >= s.minScore;
      if (against) {
        return ExitDecision(position, position.quantity, ExitKind.oppositeSignal,
            'إشارة معاكسة: النتيجة ${report.score.toStringAsFixed(0)} — ${report.summaryAr()}', urgent: false);
      }
    }
    if (now.difference(meta.entryTime).inDays >= s.maxHoldingDays) {
      return ExitDecision(position, position.quantity, ExitKind.maxHolding,
          'تجاوز مدة الاحتفاظ القصوى (${s.maxHoldingDays} يوم)', urgent: false);
    }
    if (!meta.partialTaken && s.partialTakeProfitFraction > 0 && pnlPct >= s.partialTakeProfitPercent && position.quantity > 1) {
      final q = math.max(1, (position.quantity * s.partialTakeProfitFraction).floor());
      if (q < position.quantity) {
        return ExitDecision(position, q, ExitKind.partialProfit, 'جني ربح جزئي: ${pct(pnlPct)} — بيع $q عقد', urgent: false);
      }
    }
    return null;
  }

  /// Should we add to a winning position?
  ScaleIntent? evaluateScaleIn({
    required Position position,
    required PositionMeta meta,
    required int markCents,
    required AnalysisReport? report,
  }) {
    if (!s.scaleInEnabled || report == null || meta.scaleIns >= s.maxScaleIns) return null;
    final pnlPct = (markCents - meta.entryPremiumCents) / meta.entryPremiumCents * 100;
    if (pnlPct < s.scaleInMinProfitPercent) return null;
    final isCall = position.contract.right == OptionRight.call;
    final aligned = isCall ? report.score >= s.scaleInMinScore : report.score <= -s.scaleInMinScore;
    if (!aligned) return null;
    final q = math.max(1, (meta.initialQuantity * s.scaleInFraction).round());
    return ScaleIntent(position, q,
        'تعزيز: المركز ${pnlPct.toStringAsFixed(1)}% والنتيجة ${report.score.toStringAsFixed(0)} بنفس الاتجاه');
  }

  /// Entry rules for one flat watchlist symbol. Returns null with a reason in
  /// [rejection] (for the journal) when no trade is warranted.
  EntryIntent? evaluateEntry(String symbol, AnalysisReport report, {void Function(String reasonAr)? rejection}) {
    void no(String r) => rejection?.call(r);
    final score = report.score;
    if (score.abs() < s.minScore) {
      no('النتيجة ${score.toStringAsFixed(0)} أقل من الحد ${s.minScore.toStringAsFixed(0)}');
      return null;
    }
    final bias = score > 0 ? Bias.bullish : Bias.bearish;
    final right = bias == Bias.bullish ? OptionRight.call : OptionRight.put;
    if (right == OptionRight.call && !s.allowCalls) {
      no('عقود Call غير مسموحة في هذا الحساب');
      return null;
    }
    if (right == OptionRight.put && !s.allowPuts) {
      no('عقود Put غير مسموحة في هذا الحساب');
      return null;
    }
    final agree = report.agreeingEngines(bias);
    if (agree < s.minAgreeingEngines) {
      no('عدد المحركات المتوافقة $agree أقل من ${s.minAgreeingEngines}');
      return null;
    }
    if (s.requireTrendAlignment) {
      final trend = report.signals.where((x) => x.engine == EngineId.trend);
      if (trend.isNotEmpty && trend.first.bias != bias) {
        no('الاتجاه العام معاكس للإشارة');
        return null;
      }
    }
    final reasons = report.supporting(bias).map((x) => '• ${x.engine.arabic}: ${x.reasonAr}').join('\n');
    return EntryIntent(
      symbol,
      right,
      report,
      'دخول ${right.arabic} على $symbol — النتيجة ${score.toStringAsFixed(0)}، $agree محركات متوافقة:\n$reasons',
    );
  }
}
