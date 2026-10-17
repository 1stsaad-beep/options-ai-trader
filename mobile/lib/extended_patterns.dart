/// Additional classical chart patterns (B11), contract `extended-classic-v1`.
///
/// Phone-side research only (mode SHADOW, never executable). Inputs are confirmed,
/// alternating pivots (no pivot is used before its confirmation bar) and the observed
/// close at the cursor. The canonical server-parity set (double top/bottom, H&S,
/// converging triangle) stays in `MarketGeometry.classicPatterns` unchanged.
library;

import 'dart:math' as math;

import 'demo/chart_analysis.dart';

const extendedClassicContract = 'extended-classic-v1';
const twoBoundaryKinds = {'ASCENDING_TRIANGLE', 'DESCENDING_TRIANGLE', 'RECTANGLE', 'RISING_WEDGE', 'FALLING_WEDGE'};

bool _alternating(List<ChartPivot> p) => List.generate(p.length - 1, (i) => p[i].high != p[i + 1].high).every((v) => v);
double _spread(List<double> v) {
  final mean = v.reduce((a, b) => a + b) / v.length;
  return (v.reduce(math.max) - v.reduce(math.min)) / mean;
}
List<dynamic> _points(List<ChartPivot> p) => [for (final v in p) [v.index, v.confirmedAt, v.price, v.high]];

/// Slope of a least-squares line through (index, price), normalized by mean price per bar.
double _slope(List<ChartPivot> p) {
  final n = p.length, mx = p.map((v) => v.index).reduce((a, b) => a + b) / n;
  final my = p.map((v) => v.price).reduce((a, b) => a + b) / n;
  var num = 0.0, den = 0.0;
  for (final v in p) {
    num += (v.index - mx) * (v.price - my);
    den += (v.index - mx) * (v.index - mx);
  }
  return den == 0 ? 0 : num / den / my;
}

List<Map<String, dynamic>> extendedPatterns(List<ChartPivot> points, double close,
    {double flat = .015, double equal = .02}) {
  if (!close.isFinite || close <= 0) throw ArgumentError('Positive observed close required');
  for (var i = 0; i < points.length; i++) {
    final p = points[i];
    if (!p.price.isFinite || p.price <= 0 || p.confirmedAt <= p.index || (i > 0 && p.index <= points[i - 1].index)) {
      throw const FormatException('Invalid confirmed pivots');
    }
  }
  final out = <Map<String, dynamic>>[];
  Map<String, dynamic> base(String kind, List<ChartPivot> p, String bias) => {
        'contract': extendedClassicContract, 'kind': kind, 'bias': bias, 'points': _points(p),
        'mode': 'SHADOW', 'executable': false, 'observedAt': p.map((v) => v.confirmedAt).reduce(math.max)};

  // Triple top / bottom: last five alternating pivots starting and ending on the extreme side.
  if (points.length >= 5) {
    final p = points.sublist(points.length - 5);
    if (_alternating(p)) {
      final top = p.first.high, peaks = [p[0].price, p[2].price, p[4].price], troughs = [p[1].price, p[3].price];
      final separated = top ? troughs.reduce(math.max) < peaks.reduce(math.min) : troughs.reduce(math.min) > peaks.reduce(math.max);
      if (separated && _spread(peaks) <= equal) {
        final neckline = top ? troughs.reduce(math.min) : troughs.reduce(math.max);
        out.add(base(top ? 'TRIPLE_TOP' : 'TRIPLE_BOTTOM', p, top ? 'BEARISH' : 'BULLISH')
          ..addAll({'neckline': neckline, 'confirmed': top ? close < neckline : close > neckline}));
      }
    }
  }
  // Two-boundary formations on the last six alternating pivots (three highs, three lows).
  if (points.length >= 6) {
    final p = points.sublist(points.length - 6);
    if (_alternating(p)) {
      final highs = p.where((v) => v.high).toList(), lows = p.where((v) => !v.high).toList();
      final hp = highs.map((v) => v.price).toList(), lp = lows.map((v) => v.price).toList();
      final upper = hp.last, lower = lp.last;
      if (hp.reduce(math.min) > lp.reduce(math.max)) {
        final flatHigh = _spread(hp) <= flat, flatLow = _spread(lp) <= flat;
        final risingLows = lp[0] < lp[1] && lp[1] < lp[2], fallingHighs = hp[0] > hp[1] && hp[1] > hp[2];
        final risingHighs = hp[0] < hp[1] && hp[1] < hp[2], fallingLows = lp[0] > lp[1] && lp[1] > lp[2];
        final sh = _slope(highs), sl = _slope(lows);
        String? kind, bias;
        if (flatHigh && flatLow) {
          kind = 'RECTANGLE'; bias = 'NEUTRAL';
        } else if (flatHigh && risingLows) {
          kind = 'ASCENDING_TRIANGLE'; bias = 'BULLISH';
        } else if (flatLow && fallingHighs) {
          kind = 'DESCENDING_TRIANGLE'; bias = 'BEARISH';
        } else if (risingHighs && risingLows && sl > sh && !flatHigh) {
          kind = 'RISING_WEDGE'; bias = 'BEARISH';
        } else if (fallingHighs && fallingLows && sh < sl && !flatLow) {
          kind = 'FALLING_WEDGE'; bias = 'BULLISH';
        }
        if (kind != null) {
          final top = kind == 'RECTANGLE' || kind == 'ASCENDING_TRIANGLE' ? hp.reduce(math.max) : upper;
          final bottom = kind == 'RECTANGLE' || kind == 'DESCENDING_TRIANGLE' ? lp.reduce(math.min) : lower;
          out.add(base(kind, p, bias!)..addAll({'upper': top, 'lower': bottom, 'confirmed': close > top || close < bottom,
            'breakout': close > top ? 'UP' : close < bottom ? 'DOWN' : null}));
        }
      }
    }
  }
  return out;
}

List<ChartClassic> extendedDrawings(List<ChartPivot> points, double close) => [
      for (final p in extendedPatterns(points, close))
        () {
          final v = [for (final q in p['points'] as List) ChartPivot(q[0] as int, q[1] as int, (q[2] as num).toDouble(), q[3] as bool)];
          final labels = v.length == 5 ? ['P1', 'N1', 'P2', 'N2', 'P3'] : [for (var i = 0; i < v.length; i++) '${v[i].high ? 'H' : 'L'}${i ~/ 2 + 1}'];
          return ChartClassic(p['kind'] as String, List.unmodifiable(v), List.unmodifiable(labels), p['confirmed'] as bool,
              neckline: (p['neckline'] as num?)?.toDouble());
        }()
    ];
