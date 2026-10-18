/// Everything a chart needs to draw the engines' view of one symbol, computed
/// from **the same candle list the engines analyse** so every overlay lines up
/// with its bars (all geometry uses bar indices into [ChartAnalysis.candles]).
///
/// Pure Dart and deterministic; the app runs it off the UI thread.
library;

import 'dart:math' as math;

import '../models.dart';
import '../trading/journal.dart';
import 'analyzer.dart';
import 'geometry.dart';
import 'indicators.dart';
import 'pivots.dart';
import 'signal.dart';

/// Horizontal support / resistance level derived from confirmed swings.
class PriceLevel {
  final double price;
  final bool isSupport;

  /// Number of confirmed swings within the clustering tolerance.
  final int touches;

  /// Bar index of the most recent swing that formed the level.
  final int lastIndex;

  const PriceLevel(this.price, this.isSupport, this.touches, this.lastIndex);
}

class ChartAnalysis {
  final String symbol;
  final List<Candle> candles;
  final AnalysisReport report;

  /// Every finding of every enabled engine (strongest-per-engine is in [report]).
  final Map<EngineId, List<EngineSignal>> findings;

  /// Confirmed fractal pivots (left 3 / right 2), as used by all pattern engines.
  final List<Pivot> pivots;

  /// Alternating zig-zag of [pivots] (noise filter [swingFilter]).
  final List<Pivot> swings;
  final double swingFilter;

  final List<double?> ema20;
  final List<double?> ema50;
  final List<double?> ema200;

  /// Nearest confirmed support/resistance levels around the last close.
  final List<PriceLevel> levels;

  /// Lines through the last two confirmed swing highs / lows.
  final List<GeoSegment> trendLines;

  /// Composite score as it was known at each bar (index-aligned with
  /// [candles]; null where not computed).
  final List<double?> scoreHistory;

  const ChartAnalysis({
    required this.symbol,
    required this.candles,
    required this.report,
    required this.findings,
    required this.pivots,
    required this.swings,
    required this.swingFilter,
    required this.ema20,
    required this.ema50,
    required this.ema200,
    required this.levels,
    required this.trendLines,
    required this.scoreHistory,
  });

  static ChartAnalysis compute(
    String symbol,
    List<Candle> candles, {
    Map<EngineId, double> weights = const {},
    Analyzer? analyzer,
    int scoreBars = 60,
    int minBarsForScore = 60,
    double swingFilter = 0.005,
  }) {
    final a = analyzer ?? Analyzer();
    final full = a.analyzeWithFindings(symbol, candles, weights: weights);
    final pivots = confirmedPivots(candles);
    final swings = alternatingSwings(pivots, minMoveFraction: swingFilter);
    final v = closes(candles);

    // Causal score history: re-run the analyzer on each prefix.
    final hist = List<double?>.filled(candles.length, null);
    final from = math.max(minBarsForScore - 1, candles.length - scoreBars);
    for (var i = from; i < candles.length - 1; i++) {
      hist[i] = a.analyze(symbol, candles.sublist(0, i + 1), weights: weights).score;
    }
    if (candles.isNotEmpty) hist[candles.length - 1] = full.report.score;

    return ChartAnalysis(
      symbol: symbol,
      candles: candles,
      report: full.report,
      findings: full.findings,
      pivots: pivots,
      swings: swings,
      swingFilter: swingFilter,
      ema20: ema(v, 20),
      ema50: ema(v, 50),
      ema200: ema(v, 200),
      levels: supportResistance(swings, candles.isEmpty ? 0 : candles.last.close),
      trendLines: trendLinesFrom(swings, candles.length - 1),
      scoreHistory: hist,
    );
  }

  /// Clusters confirmed swings within [tolerance] (fraction of price) and keeps
  /// the [perSide] nearest levels above (resistance) and below (support) [close].
  static List<PriceLevel> supportResistance(List<Pivot> swings, double close,
      {double tolerance = 0.004, int perSide = 3}) {
    final clusters = <({double sum, int n, int last})>[];
    final sorted = [...swings]..sort((x, y) => x.price.compareTo(y.price));
    for (final p in sorted) {
      if (clusters.isNotEmpty) {
        final c = clusters.last;
        final mean = c.sum / c.n;
        if ((p.price - mean).abs() / mean <= tolerance) {
          clusters[clusters.length - 1] = (sum: c.sum + p.price, n: c.n + 1, last: math.max(c.last, p.index));
          continue;
        }
      }
      clusters.add((sum: p.price, n: 1, last: p.index));
    }
    final levels = [for (final c in clusters) PriceLevel(c.sum / c.n, c.sum / c.n < close, c.n, c.last)];
    final below = levels.where((l) => l.isSupport).toList()..sort((x, y) => y.price.compareTo(x.price));
    final above = levels.where((l) => !l.isSupport).toList()..sort((x, y) => x.price.compareTo(y.price));
    return [...below.take(perSide), ...above.take(perSide)];
  }

  /// Line through the last two swing highs and the last two swing lows,
  /// extended to [lastIndex].
  static List<GeoSegment> trendLinesFrom(List<Pivot> swings, int lastIndex) {
    final out = <GeoSegment>[];
    for (final high in [true, false]) {
      final s = swings.where((p) => p.isHigh == high).toList();
      if (s.length < 2) continue;
      final p1 = s[s.length - 2], p2 = s.last;
      final seg = GeoSegment(p1.index, p1.price, p2.index, p2.price, role: GeoRole.boundary);
      out.add(GeoSegment(p1.index, p1.price, lastIndex, seg.priceAt(lastIndex),
          role: GeoRole.boundary, label: high ? 'resistance' : 'support'));
    }
    return out;
  }
}

enum TradeMarkerKind { entry, exit, scaleIn, filledBuy, filledSell }

/// One of the account's own decisions, placed on the chart of its underlying.
class TradeMarker {
  final DateTime time;
  final TradeMarkerKind kind;

  /// Underlying price recorded with the decision, when available.
  final double? underlyingPrice;
  final String? contract;
  final String reasonAr;

  const TradeMarker(this.time, this.kind, this.underlyingPrice, this.contract, this.reasonAr);

  /// Markers for [symbol] from the decision journal (entries, exits,
  /// scale-ins and fills), oldest first.
  static List<TradeMarker> fromJournal(Iterable<JournalEntry> journal, String symbol) {
    final out = <TradeMarker>[];
    for (final e in journal) {
      if (e.symbol != symbol) continue;
      final d = e.details;
      final kind = switch (e.action) {
        JournalAction.entry => TradeMarkerKind.entry,
        JournalAction.exit => TradeMarkerKind.exit,
        JournalAction.scaleIn => TradeMarkerKind.scaleIn,
        JournalAction.orderFilled =>
          (d['side'] == 'sellToClose' || e.reasonAr.startsWith('تنفيذ بيع')) ? TradeMarkerKind.filledSell : TradeMarkerKind.filledBuy,
        _ => null,
      };
      if (kind == null) continue;
      final analysis = d['analysis'];
      final close = analysis is Map ? analysis['close'] : null;
      out.add(TradeMarker(
        e.time,
        kind,
        close is num ? close.toDouble() : null,
        d['contract'] as String?,
        e.reasonAr,
      ));
    }
    out.sort((a, b) => a.time.compareTo(b.time));
    return out;
  }

  /// Index of the candle whose period contains [time] (last candle starting at
  /// or before it), or -1 when it is outside the candles' range.
  static int candleIndexFor(List<Candle> candles, DateTime time, Duration barLength) {
    if (candles.isEmpty) return -1;
    final t = time.toUtc();
    if (t.isBefore(candles.first.time)) return -1;
    var lo = 0, hi = candles.length - 1;
    while (lo < hi) {
      final mid = (lo + hi + 1) >> 1;
      if (!candles[mid].time.isAfter(t)) {
        lo = mid;
      } else {
        hi = mid - 1;
      }
    }
    // Beyond the last bar's period (e.g. a decision after the data ends).
    if (lo == candles.length - 1 && t.isAfter(candles[lo].time.add(barLength * 2))) return -1;
    return lo;
  }
}
