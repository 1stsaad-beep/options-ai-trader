/// Harmonic XABCD patterns: Gartley, Bat, Butterfly, Crab, Cypher.
///
/// Works on the alternating swing list. Prices are multiplied by `sign`
/// (+1 bullish pattern: X is a low; -1 bearish: X is a high) so one set of
/// inequalities covers both directions.
///
/// A pattern is actionable only when D is the most recent swing, confirmed
/// within [recency] bars, D lies inside the PRZ (intersection of the XA and BC
/// projections), and price has neither broken the invalidation nor already
/// reached the first target.
library;

import 'dart:math' as math;

import '../models.dart';
import 'pivots.dart';
import 'signal.dart';

class _Def {
  final String name;
  final double bMin, bMax; // AB/XA
  final double cdMin, cdMax; // CD/BC extension
  final double adMin, adMax; // AD/XA (D retracement of XA, or extension when >1)
  final bool dInsideXa; // true: D between X and A; false: D beyond X
  const _Def(this.name, this.bMin, this.bMax, this.cdMin, this.cdMax, this.adMin, this.adMax, this.dInsideXa);
}

const _defs = [
  _Def('GARTLEY', .618, .618, 1.272, 1.618, .786, .786, true),
  _Def('BAT', .382, .5, 1.618, 2.618, .886, .886, true),
  _Def('BUTTERFLY', .786, .786, 1.618, 2.618, 1.272, 1.618, false),
  _Def('CRAB', .382, .618, 2.24, 3.618, 1.618, 1.618, false),
];

const _arabicNames = {
  'GARTLEY': 'جارتلي',
  'BAT': 'الخفاش',
  'BUTTERFLY': 'الفراشة',
  'CRAB': 'السلطعون',
  'CYPHER': 'سايفر',
};

bool _within(double v, double lo, double hi, double tol) => v >= lo - tol && v <= hi + tol;

List<EngineSignal> harmonicEngine(List<Candle> c, {double tolerance = 0.04, int recency = 6}) {
  if (c.length < 40) return const [];
  final swings = alternatingSwings(confirmedPivots(c), minMoveFraction: 0.004);
  if (swings.length < 5) return const [];
  final last = c.length - 1;
  final p = swings.sublist(swings.length - 5);
  final dPivot = p[4];
  if (dPivot.confirmedIndex < last - recency) return const [];

  final sign = p[0].isHigh ? -1.0 : 1.0; // X low => bullish pattern
  final x = p[0].price * sign, a = p[1].price * sign, b = p[2].price * sign, cc = p[3].price * sign, d = p[4].price * sign;
  final xa = a - x, ab = a - b, bc = cc - b, cd = cc - d;
  if (math.min(math.min(xa, ab), math.min(bc, cd)) <= 0) return const [];
  final abXa = ab / xa, bcAb = bc / ab, cdBc = cd / bc, adXa = (a - d) / xa;
  final close = c[last].close * sign;
  final out = <EngineSignal>[];

  void emit(String name, double fit, double przLo, double przHi, Map<String, double> ratios) {
    final invalidation = d - xa * 0.08; // a little beyond D in the losing direction
    final ad = a - d;
    final t1 = d + ad * 0.382, t2 = d + ad * 0.618;
    if (close <= invalidation || close >= t1) return; // broken or already played out
    final bias = sign > 0 ? Bias.bullish : Bias.bearish;
    out.add(EngineSignal(
      engine: EngineId.harmonic,
      bias: bias,
      strength: 0.45 + 0.55 * fit,
      pattern: name,
      reasonAr: 'نمط ${_arabicNames[name]} ${bias.arabic} مكتمل عند D ضمن منطقة الانعكاس '
          '(${math.min(przLo * sign, przHi * sign).toStringAsFixed(2)}–${math.max(przLo * sign, przHi * sign).toStringAsFixed(2)})',
      knownAtIndex: dPivot.confirmedIndex,
      invalidation: invalidation * sign,
      targets: [t1 * sign, t2 * sign],
      details: {for (final e in ratios.entries) e.key: double.parse(e.value.toStringAsFixed(3))},
    ));
  }

  // Classic four: B between X and A, C between B and A.
  if (x < b && b < a && b < cc && cc < a && d < b) {
    for (final def in _defs) {
      if (def.dInsideXa ? !(d > x) : !(d < x)) continue;
      if (!_within(abXa, def.bMin, def.bMax, tolerance) ||
          !_within(bcAb, .382, .886, tolerance) ||
          !_within(cdBc, def.cdMin, def.cdMax, tolerance * 2) ||
          !_within(adXa, def.adMin, def.adMax, tolerance)) {
        continue;
      }
      // PRZ = overlap of the XA-derived and BC-derived D zones.
      final xaLo = a - (def.adMax + tolerance) * xa, xaHi = a - (def.adMin - tolerance) * xa;
      final bcLo = cc - (def.cdMax + tolerance * 2) * bc, bcHi = cc - (def.cdMin - tolerance * 2) * bc;
      final lo = math.max(xaLo, bcLo), hi = math.min(xaHi, bcHi);
      if (lo > hi || d < lo || d > hi) continue;
      final ideal = (def.adMin + def.adMax) / 2;
      final fit = (1 - math.min(1.0, (adXa - ideal).abs() / (tolerance * 3))).toDouble();
      emit(def.name, fit, lo, hi, {'AB/XA': abXa, 'BC/AB': bcAb, 'CD/BC': cdBc, 'AD/XA': adXa});
    }
  }

  // Cypher: C extends beyond A (XC = 1.272..1.414 XA), D = 0.786 retracement of XC.
  final xc = cc - x;
  if (cc > a && d > x && d < b && xc > 0) {
    final xcXa = xc / xa, cdXc = cd / xc;
    if (_within(abXa, .382, .618, tolerance) &&
        _within(xcXa, 1.272, 1.414, tolerance) &&
        _within(cdXc, .786, .786, tolerance)) {
      final fit = (1 - math.min(1.0, (cdXc - .786).abs() / (tolerance * 2))).toDouble();
      emit('CYPHER', fit, cc - (.786 + tolerance) * xc, cc - (.786 - tolerance) * xc,
          {'AB/XA': abXa, 'XC/XA': xcXa, 'CD/XC': cdXc});
    }
  }
  return out;
}
