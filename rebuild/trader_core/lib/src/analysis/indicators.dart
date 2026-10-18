/// Classic technical indicators. Pure functions, causal: value at index `i`
/// uses only bars `0..i`. Outputs are aligned with the input (same length)
/// and contain `null` until the indicator has enough history (warm-up).
library;

import 'dart:math' as math;

import '../models.dart';

List<double> closes(List<Candle> c) => [for (final x in c) x.close];

List<double?> sma(List<double> v, int period) {
  final out = List<double?>.filled(v.length, null);
  var sum = 0.0;
  for (var i = 0; i < v.length; i++) {
    sum += v[i];
    if (i >= period) sum -= v[i - period];
    if (i >= period - 1) out[i] = sum / period;
  }
  return out;
}

/// EMA seeded with the SMA of the first [period] values.
List<double?> ema(List<double> v, int period) {
  final out = List<double?>.filled(v.length, null);
  if (v.length < period) return out;
  final k = 2 / (period + 1);
  var prev = v.take(period).reduce((a, b) => a + b) / period;
  out[period - 1] = prev;
  for (var i = period; i < v.length; i++) {
    prev = v[i] * k + prev * (1 - k);
    out[i] = prev;
  }
  return out;
}

/// EMA over a series that itself starts with nulls.
List<double?> emaOfNullable(List<double?> v, int period) {
  final start = v.indexWhere((x) => x != null);
  final out = List<double?>.filled(v.length, null);
  if (start < 0) return out;
  final dense = [for (var i = start; i < v.length; i++) v[i]!];
  final e = ema(dense, period);
  for (var i = 0; i < e.length; i++) {
    out[start + i] = e[i];
  }
  return out;
}

/// Wilder RSI.
List<double?> rsi(List<double> v, {int period = 14}) {
  final out = List<double?>.filled(v.length, null);
  if (v.length <= period) return out;
  var gain = 0.0, loss = 0.0;
  for (var i = 1; i <= period; i++) {
    final d = v[i] - v[i - 1];
    if (d >= 0) {
      gain += d;
    } else {
      loss -= d;
    }
  }
  gain /= period;
  loss /= period;
  double value(double g, double l) => l == 0 ? (g == 0 ? 50 : 100) : 100 - 100 / (1 + g / l);
  out[period] = value(gain, loss);
  for (var i = period + 1; i < v.length; i++) {
    final d = v[i] - v[i - 1];
    gain = (gain * (period - 1) + math.max(d, 0)) / period;
    loss = (loss * (period - 1) + math.max(-d, 0)) / period;
    out[i] = value(gain, loss);
  }
  return out;
}

class Macd {
  final List<double?> line;
  final List<double?> signal;
  final List<double?> histogram;
  const Macd(this.line, this.signal, this.histogram);
}

Macd macd(List<double> v, {int fast = 12, int slow = 26, int signalPeriod = 9}) {
  final f = ema(v, fast), s = ema(v, slow);
  final line = [for (var i = 0; i < v.length; i++) (f[i] != null && s[i] != null) ? f[i]! - s[i]! : null];
  final sig = emaOfNullable(line, signalPeriod);
  final hist = [for (var i = 0; i < v.length; i++) (line[i] != null && sig[i] != null) ? line[i]! - sig[i]! : null];
  return Macd(line, sig, hist);
}

class Bands {
  final List<double?> middle;
  final List<double?> upper;
  final List<double?> lower;
  const Bands(this.middle, this.upper, this.lower);

  /// (upper-lower)/middle — small values indicate a squeeze.
  double? width(int i) =>
      middle[i] == null || middle[i] == 0 ? null : (upper[i]! - lower[i]!) / middle[i]!;
}

Bands bollinger(List<double> v, {int period = 20, double k = 2}) {
  final mid = sma(v, period);
  final up = List<double?>.filled(v.length, null), lo = List<double?>.filled(v.length, null);
  for (var i = period - 1; i < v.length; i++) {
    var sq = 0.0;
    for (var j = i - period + 1; j <= i; j++) {
      final d = v[j] - mid[i]!;
      sq += d * d;
    }
    final sd = math.sqrt(sq / period);
    up[i] = mid[i]! + k * sd;
    lo[i] = mid[i]! - k * sd;
  }
  return Bands(mid, up, lo);
}

List<double> trueRange(List<Candle> c) => [
      for (var i = 0; i < c.length; i++)
        i == 0
            ? c[i].high - c[i].low
            : math.max(c[i].high - c[i].low,
                math.max((c[i].high - c[i - 1].close).abs(), (c[i].low - c[i - 1].close).abs()))
    ];

/// Wilder-smoothed series (used by ATR and ADX).
List<double?> wilder(List<double> v, int period, {int startAt = 0}) {
  final out = List<double?>.filled(v.length, null);
  if (v.length < startAt + period) return out;
  var prev = 0.0;
  for (var i = startAt; i < startAt + period; i++) {
    prev += v[i];
  }
  prev /= period;
  out[startAt + period - 1] = prev;
  for (var i = startAt + period; i < v.length; i++) {
    prev = (prev * (period - 1) + v[i]) / period;
    out[i] = prev;
  }
  return out;
}

List<double?> atr(List<Candle> c, {int period = 14}) => wilder(trueRange(c), period, startAt: 1);

class Stochastic {
  final List<double?> k;
  final List<double?> d;
  const Stochastic(this.k, this.d);
}

Stochastic stochastic(List<Candle> c, {int period = 14, int smoothK = 3, int smoothD = 3}) {
  final raw = List<double?>.filled(c.length, null);
  for (var i = period - 1; i < c.length; i++) {
    var hh = c[i].high, ll = c[i].low;
    for (var j = i - period + 1; j <= i; j++) {
      hh = math.max(hh, c[j].high);
      ll = math.min(ll, c[j].low);
    }
    raw[i] = hh == ll ? 50 : 100 * (c[i].close - ll) / (hh - ll);
  }
  final k = _smaNullable(raw, smoothK);
  return Stochastic(k, _smaNullable(k, smoothD));
}

List<double?> _smaNullable(List<double?> v, int period) {
  final out = List<double?>.filled(v.length, null);
  for (var i = 0; i < v.length; i++) {
    if (i < period - 1) continue;
    var ok = true;
    var s = 0.0;
    for (var j = i - period + 1; j <= i; j++) {
      if (v[j] == null) {
        ok = false;
        break;
      }
      s += v[j]!;
    }
    if (ok) out[i] = s / period;
  }
  return out;
}

class Adx {
  final List<double?> adx;
  final List<double?> plusDi;
  final List<double?> minusDi;
  const Adx(this.adx, this.plusDi, this.minusDi);
}

Adx adx(List<Candle> c, {int period = 14}) {
  final n = c.length;
  final plusDm = List<double>.filled(n, 0), minusDm = List<double>.filled(n, 0);
  for (var i = 1; i < n; i++) {
    final up = c[i].high - c[i - 1].high, down = c[i - 1].low - c[i].low;
    plusDm[i] = up > down && up > 0 ? up : 0;
    minusDm[i] = down > up && down > 0 ? down : 0;
  }
  final tr = wilder(trueRange(c), period, startAt: 1);
  final pdm = wilder(plusDm, period, startAt: 1), mdm = wilder(minusDm, period, startAt: 1);
  final pdi = List<double?>.filled(n, null), mdi = List<double?>.filled(n, null);
  final dx = List<double>.filled(n, 0);
  var firstDx = -1;
  for (var i = 0; i < n; i++) {
    if (tr[i] == null || tr[i] == 0) continue;
    pdi[i] = 100 * pdm[i]! / tr[i]!;
    mdi[i] = 100 * mdm[i]! / tr[i]!;
    final sum = pdi[i]! + mdi[i]!;
    dx[i] = sum == 0 ? 0 : 100 * (pdi[i]! - mdi[i]!).abs() / sum;
    if (firstDx < 0) firstDx = i;
  }
  final a = firstDx < 0 ? List<double?>.filled(n, null) : wilder(dx, period, startAt: firstDx);
  return Adx(a, pdi, mdi);
}

/// On-balance volume.
List<double> obv(List<Candle> c) {
  final out = List<double>.filled(c.length, 0);
  for (var i = 1; i < c.length; i++) {
    final d = c[i].close.compareTo(c[i - 1].close);
    out[i] = out[i - 1] + c[i].volume * d;
  }
  return out;
}

/// Linear-regression slope of the last [n] values, normalised by their mean
/// (fraction per bar). Used for OBV/trend direction tests.
double? normalizedSlope(List<double?> v, int n) {
  if (v.length < n) return null;
  final ys = v.sublist(v.length - n);
  if (ys.any((y) => y == null)) return null;
  final xm = (n - 1) / 2;
  final ym = ys.fold<double>(0, (s, y) => s + y!) / n;
  var nu = 0.0, den = 0.0;
  for (var i = 0; i < n; i++) {
    nu += (i - xm) * (ys[i]! - ym);
    den += (i - xm) * (i - xm);
  }
  if (den == 0) return 0;
  final scale = ym.abs() < 1e-9 ? 1.0 : ym.abs();
  return nu / den / scale;
}
