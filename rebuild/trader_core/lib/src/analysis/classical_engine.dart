/// Classical chart patterns on confirmed swings:
/// double top / bottom, head & shoulders (and inverse), triangles
/// (ascending / descending / symmetrical) and range (Donchian) breakouts.
///
/// Reversal patterns signal only after a **close** beyond the neckline, and
/// only while that break is fresh (within [recency] bars) and price has not yet
/// reached the measured-move target. Necklines and boundaries come strictly from
/// observed swing points — nothing is extrapolated beyond what the swings define.
library;

import 'dart:math' as math;

import '../models.dart';
import 'geometry.dart';
import 'pivots.dart';
import 'signal.dart';

/// First bar index after [from] whose close crosses [level] in the direction
/// [above]; -1 if none.
int _breakIndex(List<Candle> c, int from, double level, bool above) {
  for (var i = from + 1; i < c.length; i++) {
    if (above ? c[i].close > level : c[i].close < level) return i;
  }
  return -1;
}

List<EngineSignal> classicalEngine(List<Candle> c, {double tolerance = 0.015, int recency = 6}) {
  if (c.length < 40) return const [];
  final swings = alternatingSwings(confirmedPivots(c), minMoveFraction: 0.005);
  final last = c.length - 1;
  final close = c[last].close;
  final out = <EngineSignal>[];
  final n = swings.length;

  bool fresh(int breakAt) => breakAt >= 0 && breakAt >= last - recency;

  // ---- Double top / bottom: [peak1, trough, peak2] ----
  if (n >= 3) {
    final p1 = swings[n - 3], mid = swings[n - 2], p2 = swings[n - 1];
    final similar = (p1.price - p2.price).abs() / p1.price <= tolerance;
    final depth = (p1.price - mid.price).abs() / p1.price;
    if (similar && depth >= 0.02 && p2.index - p1.index >= 8) {
      final top = p1.isHigh;
      final neckline = mid.price;
      final at = _breakIndex(c, p2.confirmedIndex, neckline, !top);
      final height = ((p1.price + p2.price) / 2 - neckline).abs();
      final target = top ? neckline - height : neckline + height;
      final beforeTarget = top ? close > target : close < target;
      if (fresh(at) && beforeTarget) {
        final bias = top ? Bias.bearish : Bias.bullish;
        out.add(EngineSignal(
          engine: EngineId.classical,
          bias: bias,
          strength: 0.55 + 0.25 * (1 - (p1.price - p2.price).abs() / p1.price / tolerance) + math.min(0.2, depth),
          pattern: top ? 'DOUBLE_TOP' : 'DOUBLE_BOTTOM',
          reasonAr: '${top ? 'قمة مزدوجة' : 'قاع مزدوج'} مع إغلاق ${top ? 'تحت' : 'فوق'} خط العنق ${neckline.toStringAsFixed(2)}',
          knownAtIndex: at,
          invalidation: top ? math.max(p1.price, p2.price) : math.min(p1.price, p2.price),
          targets: [top ? neckline - height * 0.618 : neckline + height * 0.618, target],
          details: {'neckline': neckline, 'height': height},
          geometry: () {
            final pts = [
              GeoPoint(p1.index, p1.price, top ? 'T1' : 'B1'),
              GeoPoint(mid.index, mid.price, 'N'),
              GeoPoint(p2.index, p2.price, top ? 'T2' : 'B2'),
            ];
            return ChartGeometry(points: pts, segments: [
              ...ChartGeometry.polyline(pts),
              GeoSegment(mid.index, neckline, at, neckline, role: GeoRole.neckline, label: 'neckline'),
            ]);
          }(),
        ));
      }
    }
  }

  // ---- Head & shoulders: [LS, T1, H, T2, RS] ----
  if (n >= 5) {
    final ls = swings[n - 5], t1 = swings[n - 4], h = swings[n - 3], t2 = swings[n - 2], rs = swings[n - 1];
    final top = ls.isHigh; // regular H&S top when shoulders are highs
    final s = top ? 1.0 : -1.0;
    final headProminent = h.price * s > ls.price * s && h.price * s > rs.price * s;
    final shouldersSimilar = (ls.price - rs.price).abs() / ls.price <= tolerance * 2;
    if (headProminent && shouldersSimilar) {
      // Sloping neckline through T1 and T2, evaluated at each bar.
      final slope = (t2.price - t1.price) / (t2.index - t1.index);
      double neckAt(int i) => t1.price + slope * (i - t1.index);
      var at = -1;
      for (var i = rs.confirmedIndex + 1; i <= last; i++) {
        if (top ? c[i].close < neckAt(i) : c[i].close > neckAt(i)) {
          at = i;
          break;
        }
      }
      final height = (h.price - neckAt(h.index)).abs();
      final neckNow = neckAt(last);
      final target = top ? neckNow - height : neckNow + height;
      final beforeTarget = top ? close > target : close < target;
      if (fresh(at) && beforeTarget) {
        final bias = top ? Bias.bearish : Bias.bullish;
        out.add(EngineSignal(
          engine: EngineId.classical,
          bias: bias,
          strength: 0.7 + 0.3 * (1 - (ls.price - rs.price).abs() / ls.price / (tolerance * 2)),
          pattern: top ? 'HEAD_SHOULDERS' : 'INVERSE_HEAD_SHOULDERS',
          reasonAr: '${top ? 'رأس وكتفين' : 'رأس وكتفين مقلوب'} مع كسر خط العنق عند ${neckNow.toStringAsFixed(2)}',
          knownAtIndex: at,
          invalidation: rs.price,
          targets: [top ? neckNow - height * 0.618 : neckNow + height * 0.618, target],
          details: {'neckline': neckNow, 'head': h.price},
          geometry: () {
            final pts = [
              GeoPoint(ls.index, ls.price, 'LS'),
              GeoPoint(t1.index, t1.price, 'N1'),
              GeoPoint(h.index, h.price, 'H'),
              GeoPoint(t2.index, t2.price, 'N2'),
              GeoPoint(rs.index, rs.price, 'RS'),
            ];
            return ChartGeometry(points: pts, segments: [
              ...ChartGeometry.polyline(pts),
              GeoSegment(t1.index, t1.price, last, neckNow, role: GeoRole.neckline, label: 'neckline'),
            ]);
          }(),
        ));
      }
    }
  }

  // ---- Triangles: last 4 swings (2 highs, 2 lows) converging, then a close outside ----
  if (n >= 4) {
    final w = swings.sublist(n - 4);
    final highs = w.where((p) => p.isHigh).toList(), lows = w.where((p) => !p.isHigh).toList();
    if (highs.length == 2 && lows.length == 2) {
      final hSlope = (highs[1].price - highs[0].price) / (highs[1].index - highs[0].index);
      final lSlope = (lows[1].price - lows[0].price) / (lows[1].index - lows[0].index);
      final ref = (highs[0].price + lows[0].price) / 2;
      final flat = ref * 0.0005; // per-bar slope considered flat
      String? kind;
      if (hSlope.abs() <= flat && lSlope > flat) kind = 'ASCENDING_TRIANGLE';
      if (lSlope.abs() <= flat && hSlope < -flat) kind = 'DESCENDING_TRIANGLE';
      if (hSlope < -flat && lSlope > flat) kind = 'SYMMETRICAL_TRIANGLE';
      if (kind != null) {
        final start = w.last.confirmedIndex;
        double upperAt(int i) => highs[1].price + hSlope * (i - highs[1].index);
        double lowerAt(int i) => lows[1].price + lSlope * (i - lows[1].index);
        var at = -1;
        var up = false;
        for (var i = start + 1; i <= last; i++) {
          if (c[i].close > upperAt(i)) {
            at = i;
            up = true;
            break;
          }
          if (c[i].close < lowerAt(i)) {
            at = i;
            break;
          }
        }
        final height = highs[0].price - lows[0].price;
        if (fresh(at) && height > 0) {
          final bias = up ? Bias.bullish : Bias.bearish;
          final base = up ? upperAt(at) : lowerAt(at);
          final target = up ? base + height : base - height;
          final beforeTarget = up ? close < target : close > target;
          // Breakouts in the triangle's natural direction are stronger.
          final natural = (kind == 'ASCENDING_TRIANGLE' && up) || (kind == 'DESCENDING_TRIANGLE' && !up) || kind == 'SYMMETRICAL_TRIANGLE';
          if (beforeTarget) {
            out.add(EngineSignal(
              engine: EngineId.classical,
              bias: bias,
              strength: natural ? 0.7 : 0.5,
              pattern: kind,
              reasonAr: 'اختراق ${up ? 'صاعد' : 'هابط'} لمثلث ${switch (kind) {
                'ASCENDING_TRIANGLE' => 'صاعد',
                'DESCENDING_TRIANGLE' => 'هابط',
                _ => 'متماثل',
              }} عند ${base.toStringAsFixed(2)}',
              knownAtIndex: at,
              invalidation: up ? lowerAt(last) : upperAt(last),
              targets: [up ? base + height * 0.618 : base - height * 0.618, target],
              details: {'upperSlope': hSlope, 'lowerSlope': lSlope},
              geometry: ChartGeometry(
                points: [for (final p in w) GeoPoint(p.index, p.price, p.isHigh ? 'H' : 'L')],
                segments: [
                  GeoSegment(highs[0].index, highs[0].price, at, upperAt(at), role: GeoRole.boundary),
                  GeoSegment(lows[0].index, lows[0].price, at, lowerAt(at), role: GeoRole.boundary),
                ],
              ),
            ));
          }
        }
      }
    }
  }

  // ---- Range breakout: close beyond the prior 20-bar high/low ----
  if (c.length >= 22) {
    var hh = c[last - 20].high, ll = c[last - 20].low;
    for (var i = last - 20; i < last; i++) {
      hh = math.max(hh, c[i].high);
      ll = math.min(ll, c[i].low);
    }
    final range = hh - ll;
    if (range > 0 && range / close < 0.12) {
      if (close > hh) {
        out.add(EngineSignal(
          engine: EngineId.classical,
          bias: Bias.bullish,
          strength: 0.45,
          pattern: 'RANGE_BREAKOUT_UP',
          reasonAr: 'إغلاق فوق أعلى سعر لآخر 20 شمعة (${hh.toStringAsFixed(2)})',
          knownAtIndex: last,
          invalidation: (hh + ll) / 2,
          targets: [hh + range * 0.618, hh + range],
          geometry: ChartGeometry(zones: [GeoZone(last - 20, last, ll, hh, '20')]),
        ));
      } else if (close < ll) {
        out.add(EngineSignal(
          engine: EngineId.classical,
          bias: Bias.bearish,
          strength: 0.45,
          pattern: 'RANGE_BREAKOUT_DOWN',
          reasonAr: 'إغلاق تحت أدنى سعر لآخر 20 شمعة (${ll.toStringAsFixed(2)})',
          knownAtIndex: last,
          invalidation: (hh + ll) / 2,
          targets: [ll - range * 0.618, ll - range],
          geometry: ChartGeometry(zones: [GeoZone(last - 20, last, ll, hh, '20')]),
        ));
      }
    }
  }
  return out;
}
