import 'dart:math' as math;

/// Horizontal viewport of the chart in *bar index* space (pure math, no
/// Flutter), so pan/zoom/hit-testing is unit-testable.
///
/// Bar `i` is centred at `x(i) = (i - startIndex + 0.5) * barWidth`, where
/// `startIndex = rightIndex - barsVisible + 1`.
class ChartViewport {
  final int barCount;
  final double minBars;
  final double maxBars;

  /// Fraction of the visible width allowed as empty space right of the last
  /// bar (room for zones/targets projected forward).
  final double rightPadFraction;

  double barsVisible;
  double rightIndex;

  ChartViewport({
    required this.barCount,
    double? barsVisible,
    double? rightIndex,
    this.minBars = 12,
    double? maxBars,
    this.rightPadFraction = 0.25,
  })  : maxBars = math.max(12, maxBars ?? (barCount * 1.25)),
        barsVisible = barsVisible ?? math.min(90, math.max(12, barCount + 3.0)),
        rightIndex = rightIndex ?? (barCount - 1 + 3) {
    _clamp();
  }

  double get startIndex => rightIndex - barsVisible + 1;
  double barWidth(double width) => width / barsVisible;
  double x(num index, double width) => (index - startIndex + 0.5) * barWidth(width);
  double indexAtX(double px, double width) => px / barWidth(width) + startIndex - 0.5;

  /// Nearest existing bar under [px], or -1.
  int barAt(double px, double width) {
    if (barCount == 0) return -1;
    final i = indexAtX(px, width).round();
    return i < 0 || i >= barCount ? -1 : i;
  }

  /// Visible bar range [first, last] (inclusive, clamped, one bar of margin).
  (int, int) visibleRange() {
    if (barCount == 0) return (0, -1);
    final first = math.max(0, startIndex.floor() - 1);
    final last = math.min(barCount - 1, rightIndex.ceil() + 1);
    return (first, last);
  }

  void pan(double dxPixels, double width) {
    rightIndex -= dxPixels / barWidth(width);
    _clamp();
  }

  /// Zooms by [scale] (>1 = zoom in) keeping the bar under [focalX] fixed.
  void zoom(double scale, double focalX, double width) {
    if (scale <= 0) return;
    final focalIndex = indexAtX(focalX, width);
    barsVisible = (barsVisible / scale).clamp(minBars, maxBars);
    // Keep focalIndex at focalX: focalX/bw + start - 0.5 = focalIndex.
    final start = focalIndex + 0.5 - focalX / barWidth(width);
    rightIndex = start + barsVisible - 1;
    _clamp();
  }

  void jumpToLatest() {
    rightIndex = barCount - 1 + 3;
    _clamp();
  }

  void _clamp() {
    barsVisible = barsVisible.clamp(minBars, maxBars);
    final maxRight = barCount - 1 + barsVisible * rightPadFraction;
    final minRight = math.min(maxRight, barsVisible * 0.5);
    rightIndex = rightIndex.clamp(minRight, maxRight);
  }
}

/// Vertical price mapping for the plot area.
class PriceScale {
  final double min;
  final double max;
  final double top;
  final double height;

  const PriceScale(this.min, this.max, this.top, this.height);

  /// Scale fitting [lo]..[hi] with [pad] fraction of headroom on each side.
  factory PriceScale.fit(double lo, double hi, double top, double height, {double pad = 0.06}) {
    if (!(hi > lo)) {
      final mid = hi.isFinite ? hi : 1.0;
      lo = mid * 0.99;
      hi = mid * 1.01;
    }
    final span = hi - lo;
    return PriceScale(lo - span * pad, hi + span * pad, top, height);
  }

  double y(double price) => top + (max - price) / (max - min) * height;
  double priceAt(double py) => max - (py - top) / height * (max - min);

  /// "Nice" tick values (1/2/2.5/5 × 10^k) between min and max.
  List<double> ticks({int target = 6}) {
    final raw = (max - min) / target;
    if (!(raw > 0)) return const [];
    final mag = math.pow(10, (math.log(raw) / math.ln10).floor()).toDouble();
    final step = [1.0, 2.0, 2.5, 5.0, 10.0].map((m) => m * mag).firstWhere((s) => s >= raw, orElse: () => 10 * mag);
    final out = <double>[];
    for (var v = (min / step).ceil() * step; v <= max; v += step) {
      out.add(v);
    }
    return out;
  }
}
