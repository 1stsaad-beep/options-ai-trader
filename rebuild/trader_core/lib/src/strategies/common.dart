/// Shared pieces of the deterministic multi-timeframe strategies (round 5):
/// strategy signals, timeframe alignment without look-ahead, and an ATR
/// zig-zag whose pivots carry the bar index at which they became known.
library;

import 'dart:math' as math;

import '../analysis/indicators.dart';
import '../brokers/broker_adapter.dart';
import '../market/market_calendar.dart';
import '../models.dart';

/// Strategies selectable per account. [composite] is the default; [elliottDaily]
/// is the experimental round-5 Elliott variant (daily wave-2 end + RSI divergence
/// → Call), Paper only, off by default. MTF RSI is research-only (rebuild/ROUND5.md).
enum StrategyKind { composite, elliottDaily }

/// One entry signal of a strategy, raised at the close of bar [index] of the
/// entry timeframe (fill no earlier than the next bar's open).
class StrategySignal {
  final int index;
  final DateTime time; // close (end) time of the signal bar
  final bool bullish;
  final String reasonAr;

  /// Underlying level that invalidates the idea (wave-2 low, …), if any.
  final double? invalidation;

  /// Optional underlying target.
  final double? target;

  /// Feature values (confluences, ratios) for logging and research.
  final Map<String, Object?> features;

  const StrategySignal({
    required this.index,
    required this.time,
    required this.bullish,
    required this.reasonAr,
    this.invalidation,
    this.target,
    this.features = const {},
  });
}

/// End (close) instant of [c] for [tf]. Daily bars end at 16:00 New York on
/// their date; intraday bars at start + duration (the last, shorter hourly bar
/// is therefore treated as ending 30 min late — conservative, never early).
DateTime barEnd(Candle c, BarTimeframe tf) {
  if (tf == BarTimeframe.d1) {
    final w = NewYorkTime.wall(c.time);
    return NewYorkTime.toUtc(w.year, w.month, w.day, 16);
  }
  return c.time.add(tf.duration);
}

/// A bar series with its timeframe and precomputed end times.
class TfSeries {
  final String label;
  final List<Candle> bars;
  final List<DateTime> ends;
  TfSeries(this.label, this.bars, this.ends) : assert(bars.length == ends.length);
  factory TfSeries.of(BarTimeframe tf, List<Candle> bars) => TfSeries(tf.name, bars, [for (final b in bars) barEnd(b, tf)]);

  /// Number of bars completed at instant [t] (bars with end <= t).
  int completedAt(DateTime t) {
    var lo = 0, hi = ends.length;
    while (lo < hi) {
      final m = (lo + hi) >> 1;
      if (!ends[m].isAfter(t)) {
        lo = m + 1;
      } else {
        hi = m;
      }
    }
    return lo;
  }
}

/// Weekly bars (Mon–Fri, NY dates) aggregated from daily bars; time = first
/// session, end = close of the week's last session.
TfSeries weeklyFromDaily(List<Candle> d) {
  final out = <Candle>[];
  final ends = <DateTime>[];
  String? key;
  late double o, h, l, c, v;
  late DateTime t;
  late DateTime lastEnd;
  for (final b in d) {
    final w = NewYorkTime.wall(b.time);
    final monday = DateTime.utc(w.year, w.month, w.day).subtract(Duration(days: w.weekday - 1));
    final k = '${monday.year}-${monday.month}-${monday.day}';
    if (k != key) {
      if (key != null) {
        out.add(Candle(time: t, open: o, high: h, low: l, close: c, volume: v));
        ends.add(lastEnd);
      }
      key = k;
      t = b.time;
      o = b.open;
      h = b.high;
      l = b.low;
      c = b.close;
      v = b.volume;
    } else {
      h = math.max(h, b.high);
      l = math.min(l, b.low);
      c = b.close;
      v += b.volume;
    }
    lastEnd = barEnd(b, BarTimeframe.d1);
  }
  if (key != null) {
    out.add(Candle(time: t, open: o, high: h, low: l, close: c, volume: v));
    ends.add(lastEnd);
  }
  return TfSeries('w1', out, ends);
}

/// Pivot of the ATR zig-zag. [confirmedIndex] is the first bar at which the
/// pivot is known; nothing may use it before that bar.
class ZzPivot {
  final int index;
  final int confirmedIndex;
  final double price;
  final bool isHigh;
  const ZzPivot(this.index, this.confirmedIndex, this.price, this.isHigh);
  @override
  String toString() => '${isHigh ? 'H' : 'L'}@$index/$confirmedIndex:${price.toStringAsFixed(2)}';
}

/// Deterministic ATR zig-zag: a swing high is confirmed when a later bar's low
/// is at least [k] × ATR([atrPeriod]) below the running high (ATR taken at the
/// confirming bar); symmetric for lows. The extreme of the confirming bar
/// itself does not count toward the old swing (no intrabar ordering assumed).
/// Pivots strictly alternate.
List<ZzPivot> atrZigZag(List<Candle> c, {double k = 2.0, int atrPeriod = 14}) {
  final a = atr(c, period: atrPeriod);
  final out = <ZzPivot>[];
  if (c.length < 3) return out;
  int? dir; // 1 = up-leg (tracking high), -1 = down-leg (tracking low)
  var hiI = 0, loI = 0;
  for (var i = 1; i < c.length; i++) {
    final atrI = a[i];
    if (atrI == null) {
      if (c[i].high > c[hiI].high) hiI = i;
      if (c[i].low < c[loI].low) loI = i;
      continue;
    }
    final th = k * atrI;
    if (dir == null) {
      if (c[i].low <= c[hiI].high - th && hiI < i) {
        out.add(ZzPivot(hiI, i, c[hiI].high, true));
        dir = -1;
        loI = i;
      } else if (c[i].high >= c[loI].low + th && loI < i) {
        out.add(ZzPivot(loI, i, c[loI].low, false));
        dir = 1;
        hiI = i;
      } else {
        if (c[i].high > c[hiI].high) hiI = i;
        if (c[i].low < c[loI].low) loI = i;
      }
      continue;
    }
    if (dir == 1) {
      if (c[i].low <= c[hiI].high - th) {
        out.add(ZzPivot(hiI, i, c[hiI].high, true));
        dir = -1;
        loI = i;
      } else if (c[i].high > c[hiI].high) {
        hiI = i;
      }
    } else {
      if (c[i].high >= c[loI].low + th) {
        out.add(ZzPivot(loI, i, c[loI].low, false));
        dir = 1;
        hiI = i;
      } else if (c[i].low < c[loI].low) {
        loI = i;
      }
    }
  }
  return out;
}

/// Pivots known at bar [i] (confirmedIndex <= i), as a view of the prefix.
List<ZzPivot> knownPivots(List<ZzPivot> p, int i) {
  var n = 0;
  while (n < p.length && p[n].confirmedIndex <= i) {
    n++;
  }
  return p.sublist(0, n);
}

/// Higher-degree Elliott context from confirmed pivots and the latest price.
///  +1 = bullish impulse underway: the last confirmed low is above the low before
///       it (a valid wave 2/4 — it did not retrace beyond the start of the prior
///       up-leg), the last confirmed high is above the high before it, and price
///       holds above the last low;
///  -1 = mirror (bearish impulse), 0 = none / mixed.
/// With [strict], when the last five pivots form a complete 0-1-2-3-4 the
/// impulse rules are also enforced: wave 4 must not overlap wave 1, and wave 3
/// must not be the shorter of waves 1 and 3.
int impulseContext(List<ZzPivot> p, double price, {bool strict = false}) {
  if (p.length < 4) return 0;
  ZzPivot? lastLow, prevLow, lastHigh, prevHigh;
  for (var j = p.length - 1; j >= 0 && (prevLow == null || prevHigh == null); j--) {
    final q = p[j];
    if (q.isHigh) {
      if (lastHigh == null) {
        lastHigh = q;
      } else {
        prevHigh ??= q;
      }
    } else {
      if (lastLow == null) {
        lastLow = q;
      } else {
        prevLow ??= q;
      }
    }
  }
  if (prevLow == null || prevHigh == null) return 0;
  final bull = lastLow!.price > prevLow.price && lastHigh!.price > prevHigh.price && price > lastLow.price;
  final bear = lastLow.price < prevLow.price && lastHigh!.price < prevHigh.price && price < lastHigh.price;
  if (!bull && !bear) return 0;
  if (strict && p.length >= 5) {
    final q = p.sublist(p.length - 5);
    // 0-1-2-3-4 ending with the last pivot
    final w1 = (q[1].price - q[0].price).abs(), w3 = (q[3].price - q[2].price).abs();
    final up = !q[4].isHigh; // last pivot is a low → wave 4 of an up impulse
    if (bull && up) {
      if (q[4].price <= q[1].price) return 0;
      if (w3 < w1) return 0;
    }
    if (bear && !up) {
      if (q[4].price >= q[1].price) return 0;
      if (w3 < w1) return 0;
    }
  }
  return bull ? 1 : -1;
}
