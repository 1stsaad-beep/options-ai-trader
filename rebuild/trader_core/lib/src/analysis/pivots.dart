/// Confirmed swing points (the foundation of every pattern engine).
///
/// A pivot high at bar `i` needs `left` bars before and `right` bars after with
/// strictly lower highs, so it becomes *known* only at bar `i + right`
/// ([Pivot.confirmedIndex]). Engines must never use a pivot before that index;
/// this is what keeps the analysis causal (no repainting / look-ahead).
library;

import '../models.dart';

class Pivot {
  final int index;
  final int confirmedIndex;
  final double price;
  final bool isHigh;
  final DateTime time;

  const Pivot({
    required this.index,
    required this.confirmedIndex,
    required this.price,
    required this.isHigh,
    required this.time,
  });

  @override
  String toString() => '${isHigh ? 'H' : 'L'}@$index:${price.toStringAsFixed(2)}';
}

/// Strict fractal pivots. Outside bars that are both a high and a low pivot are
/// skipped because OHLC does not reveal which extreme came first.
List<Pivot> confirmedPivots(List<Candle> c, {int left = 3, int right = 2}) {
  final out = <Pivot>[];
  for (var i = left; i < c.length - right; i++) {
    var high = true, low = true;
    for (var j = i - left; j <= i + right; j++) {
      if (j == i) continue;
      if (c[j].high >= c[i].high) high = false;
      if (c[j].low <= c[i].low) low = false;
    }
    if (high == low) continue;
    out.add(Pivot(
      index: i,
      confirmedIndex: i + right,
      price: high ? c[i].high : c[i].low,
      isHigh: high,
      time: c[i].time,
    ));
  }
  return out;
}

/// Collapses consecutive pivots of the same kind into the most extreme one so
/// the result strictly alternates high/low — the zig-zag used by Elliott,
/// harmonic and classical engines. Also drops swings smaller than
/// [minMoveFraction] of price (noise filter).
List<Pivot> alternatingSwings(List<Pivot> pivots, {double minMoveFraction = 0.0}) {
  final out = <Pivot>[];
  for (final p in pivots) {
    if (out.isEmpty) {
      out.add(p);
      continue;
    }
    final last = out.last;
    if (last.isHigh == p.isHigh) {
      final moreExtreme = p.isHigh ? p.price > last.price : p.price < last.price;
      if (moreExtreme) out[out.length - 1] = p;
      continue;
    }
    if (minMoveFraction > 0 && (p.price - last.price).abs() / last.price < minMoveFraction) {
      continue;
    }
    out.add(p);
  }
  return out;
}
