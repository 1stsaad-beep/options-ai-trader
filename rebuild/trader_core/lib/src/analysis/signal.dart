/// Output types shared by all analysis engines.
library;

import 'geometry.dart';

enum Bias {
  bullish,
  bearish,
  neutral;

  /// +1 / -1 / 0 for scoring.
  int get sign => switch (this) { Bias.bullish => 1, Bias.bearish => -1, Bias.neutral => 0 };

  String get arabic => switch (this) { Bias.bullish => 'صاعد', Bias.bearish => 'هابط', Bias.neutral => 'محايد' };
}

/// Identifies an engine; also the key of its weight in account settings.
enum EngineId {
  trend,
  momentum,
  divergence,
  harmonic,
  elliott,
  classical;

  String get arabic => switch (this) {
        EngineId.trend => 'الاتجاه',
        EngineId.momentum => 'الزخم',
        EngineId.divergence => 'الدايفرجنس',
        EngineId.harmonic => 'الهارمونيك',
        EngineId.elliott => 'موجات إليوت',
        EngineId.classical => 'الأنماط الكلاسيكية',
      };
}

/// One finding of one engine. Engines may return several; the analyzer keeps
/// the strongest per engine.
class EngineSignal {
  final EngineId engine;
  final Bias bias;

  /// 0..1 quality of the finding (ratio fit, confirmation, recency...).
  final double strength;

  /// Machine-readable pattern name, e.g. `GARTLEY`, `REGULAR_BULLISH_RSI`.
  final String pattern;

  /// Human explanation in Arabic, stored in the decision journal.
  final String reasonAr;

  /// Price where the idea is wrong (stop reference), if the pattern defines one.
  final double? invalidation;

  /// Price targets in order, if the pattern defines them.
  final List<double> targets;

  /// Bar index at which the finding became knowable (causality).
  final int knownAtIndex;

  final Map<String, Object?> details;

  /// What to draw on a chart (bar indices into the analysed candles). Not
  /// serialised and never used for decisions.
  final ChartGeometry geometry;

  EngineSignal({
    required this.engine,
    required this.bias,
    required double strength,
    required this.pattern,
    required this.reasonAr,
    required this.knownAtIndex,
    this.invalidation,
    this.targets = const [],
    this.details = const {},
    this.geometry = ChartGeometry.empty,
  }) : strength = strength.clamp(0.0, 1.0).toDouble();

  Map<String, Object?> toJson() => {
        'engine': engine.name,
        'bias': bias.name,
        'strength': double.parse(strength.toStringAsFixed(3)),
        'pattern': pattern,
        'reason': reasonAr,
        'invalidation': invalidation,
        'targets': targets,
        'knownAt': knownAtIndex,
        if (details.isNotEmpty) 'details': details,
      };
}
