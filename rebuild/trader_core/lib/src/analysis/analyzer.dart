/// Runs every engine and merges the findings into one [AnalysisReport].
///
/// Composite score (−100..+100):
///   score = 100 × Σ(weightₑ × strengthₑ × signₑ) / Σ(weightₑ for all enabled engines)
/// where each engine contributes its single strongest signal (0 if silent).
/// Silent engines still count in the denominator, so agreement across many
/// engines is required for a high score — a single loud engine cannot max it out.
library;

import 'dart:math' as math;

import '../models.dart';
import 'classical_engine.dart';
import 'elliott_engine.dart';
import 'harmonic_engine.dart';
import 'indicator_engines.dart';
import 'indicators.dart';
import 'signal.dart';

typedef EngineFn = List<EngineSignal> Function(List<Candle> candles);

class AnalysisReport {
  final String symbol;
  final DateTime time;
  final double lastClose;
  final double? atr;
  final List<EngineSignal> signals; // strongest per engine
  final double score;

  const AnalysisReport({
    required this.symbol,
    required this.time,
    required this.lastClose,
    required this.atr,
    required this.signals,
    required this.score,
  });

  Bias get bias => score > 0 ? Bias.bullish : score < 0 ? Bias.bearish : Bias.neutral;

  /// Signals agreeing with [b].
  List<EngineSignal> supporting(Bias b) => signals.where((s) => s.bias == b).toList();

  /// Number of engines agreeing with [b].
  int agreeingEngines(Bias b) => supporting(b).length;

  /// Tightest pattern-defined invalidation agreeing with [b] (closest to price).
  double? invalidationFor(Bias b) {
    final levels = supporting(b).map((s) => s.invalidation).whereType<double>().where(
        (l) => b == Bias.bullish ? l < lastClose : l > lastClose);
    if (levels.isEmpty) return null;
    return b == Bias.bullish ? levels.reduce(math.max) : levels.reduce(math.min);
  }

  /// Nearest pattern target agreeing with [b].
  double? firstTargetFor(Bias b) {
    final t = supporting(b).expand((s) => s.targets).where((x) => b == Bias.bullish ? x > lastClose : x < lastClose);
    if (t.isEmpty) return null;
    return b == Bias.bullish ? t.reduce(math.min) : t.reduce(math.max);
  }

  String summaryAr() {
    if (signals.isEmpty) return 'لا توجد إشارات فنية';
    final parts = signals.map((s) => '${s.engine.arabic}: ${s.reasonAr}');
    return 'النتيجة ${score.toStringAsFixed(0)} (${bias.arabic}) — ${parts.join(' | ')}';
  }

  Map<String, Object?> toJson() => {
        'symbol': symbol,
        'time': time.toIso8601String(),
        'close': lastClose,
        'atr': atr,
        'score': double.parse(score.toStringAsFixed(2)),
        'signals': [for (final s in signals) s.toJson()],
      };
}

class Analyzer {
  final Map<EngineId, EngineFn> engines;

  Analyzer({Map<EngineId, EngineFn>? engines}) : engines = engines ?? defaultEngines;

  static final Map<EngineId, EngineFn> defaultEngines = {
    EngineId.trend: trendEngine,
    EngineId.momentum: momentumEngine,
    EngineId.divergence: (c) => divergenceEngine(c),
    EngineId.harmonic: (c) => harmonicEngine(c),
    EngineId.elliott: (c) => elliottEngine(c),
    EngineId.classical: (c) => classicalEngine(c),
  };

  /// [weights]: engine -> weight (0 disables). Missing engines default to 1.
  AnalysisReport analyze(String symbol, List<Candle> candles, {Map<EngineId, double> weights = const {}}) =>
      analyzeWithFindings(symbol, candles, weights: weights).report;

  /// Same as [analyze] but also returns every finding of every enabled engine
  /// (not only the strongest), for charting. The report is identical.
  ({AnalysisReport report, Map<EngineId, List<EngineSignal>> findings}) analyzeWithFindings(
    String symbol,
    List<Candle> candles, {
    Map<EngineId, double> weights = const {},
  }) {
    final findings = <EngineId, List<EngineSignal>>{};
    if (candles.isEmpty) throw ArgumentError('No candles for $symbol');
    final best = <EngineSignal>[];
    var numerator = 0.0, denominator = 0.0;
    for (final entry in engines.entries) {
      final w = weights[entry.key] ?? 1.0;
      if (w <= 0) continue;
      denominator += w;
      final found = entry.value(candles);
      findings[entry.key] = found;
      if (found.isEmpty) continue;
      // Strongest directional signal of this engine.
      final top = found.reduce((a, b) => b.strength > a.strength ? b : a);
      if (top.bias == Bias.neutral) continue;
      // If the engine produced conflicting directions with similar strength, it abstains.
      final conflict = found.any((s) => s.bias == top.bias.opposite && s.strength >= top.strength - 0.1);
      if (conflict) continue;
      best.add(top);
      numerator += w * top.strength * top.bias.sign;
    }
    final score = denominator == 0 ? 0.0 : 100 * numerator / denominator;
    final report = AnalysisReport(
      symbol: symbol,
      time: candles.last.time,
      lastClose: candles.last.close,
      atr: atr(candles).last,
      signals: best,
      score: score,
    );
    return (report: report, findings: findings);
  }
}

extension on Bias {
  Bias get opposite => switch (this) { Bias.bullish => Bias.bearish, Bias.bearish => Bias.bullish, _ => Bias.neutral };
}
