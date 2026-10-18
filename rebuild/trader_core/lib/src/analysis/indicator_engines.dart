/// Indicator-based engines: trend, momentum and divergence.
///
/// Every engine is a pure function `List<Candle> -> List<EngineSignal>` that
/// looks only at bars up to the last one (causal) and returns an empty list
/// when it has nothing to say or not enough history.
library;

import 'dart:math' as math;

import '../models.dart';
import 'indicators.dart';
import 'geometry.dart';
import 'pivots.dart';
import 'signal.dart';

/// EMA alignment + ADX strength + EMA slope.
List<EngineSignal> trendEngine(List<Candle> c) {
  if (c.length < 60) return const [];
  final v = closes(c);
  final i = c.length - 1;
  final e20 = ema(v, 20), e50 = ema(v, 50), e200 = ema(v, 200);
  final a = atr(c)[i];
  final dx = adx(c);
  final adxNow = dx.adx[i] ?? 0;
  if (e20[i] == null || e50[i] == null || a == null || a <= 0) return const [];
  final close = v[i];
  final longOk = e200[i] == null || close > e200[i]!;
  final shortOk = e200[i] == null || close < e200[i]!;
  Bias bias = Bias.neutral;
  if (close > e20[i]! && e20[i]! > e50[i]! && longOk) bias = Bias.bullish;
  if (close < e20[i]! && e20[i]! < e50[i]! && shortOk) bias = Bias.bearish;
  if (bias == Bias.neutral) return const [];
  final slope = e20[i - 5] == null ? 0.0 : (e20[i]! - e20[i - 5]!) / (a * 5) * bias.sign;
  final strength = 0.4 + 0.3 * math.min(adxNow / 40, 1.0) + 0.3 * slope.clamp(0.0, 1.0);
  return [
    EngineSignal(
      engine: EngineId.trend,
      bias: bias,
      strength: strength,
      pattern: bias == Bias.bullish ? 'EMA_UPTREND' : 'EMA_DOWNTREND',
      reasonAr: '${bias == Bias.bullish ? 'السعر فوق' : 'السعر تحت'} المتوسطين 20 و50'
          '${e200[i] != null ? ' و200' : ''}، ADX=${adxNow.toStringAsFixed(1)}',
      knownAtIndex: i,
      invalidation: e50[i],
      details: {'ema20': e20[i], 'ema50': e50[i], 'ema200': e200[i], 'adx': adxNow, 'atr': a},
    )
  ];
}

/// RSI + MACD histogram + stochastic vote.
List<EngineSignal> momentumEngine(List<Candle> c) {
  if (c.length < 40) return const [];
  final v = closes(c);
  final i = c.length - 1;
  final r = rsi(v)[i];
  final m = macd(v);
  final st = stochastic(c);
  final h = m.histogram[i], hPrev = m.histogram[i - 1];
  final k = st.k[i], d = st.d[i];
  if (r == null || h == null || hPrev == null || k == null || d == null) return const [];
  var votes = 0;
  final why = <String>[];
  if (r > 55) {
    votes++;
    why.add('RSI ${r.toStringAsFixed(0)} فوق 55');
  } else if (r < 45) {
    votes--;
    why.add('RSI ${r.toStringAsFixed(0)} تحت 45');
  }
  if (h > 0 && h >= hPrev) {
    votes++;
    why.add('هيستوغرام MACD موجب ومتصاعد');
  } else if (h < 0 && h <= hPrev) {
    votes--;
    why.add('هيستوغرام MACD سالب ومتراجع');
  }
  if (k > d && k < 80) {
    votes++;
    why.add('الستوكاستك يتقاطع صعودًا');
  } else if (k < d && k > 20) {
    votes--;
    why.add('الستوكاستك يتقاطع هبوطًا');
  }
  if (votes.abs() < 2) return const [];
  final bias = votes > 0 ? Bias.bullish : Bias.bearish;
  var strength = votes.abs() / 3;
  // Exhaustion: strong momentum at extremes is late, not early.
  if ((bias == Bias.bullish && r > 75) || (bias == Bias.bearish && r < 25)) strength *= 0.6;
  return [
    EngineSignal(
      engine: EngineId.momentum,
      bias: bias,
      strength: strength,
      pattern: bias == Bias.bullish ? 'MOMENTUM_UP' : 'MOMENTUM_DOWN',
      reasonAr: why.join('، '),
      knownAtIndex: i,
      details: {'rsi': r, 'macdHist': h, 'stochK': k, 'stochD': d},
    )
  ];
}

/// Regular and hidden divergence between price swings and RSI / MACD histogram.
///
/// * Regular bullish: price lower low, oscillator higher low (reversal up).
/// * Hidden bullish: price higher low, oscillator lower low (trend continuation up).
/// * Mirror rules for bearish on swing highs.
/// The second swing must be confirmed within the last [recency] bars and the
/// two swings must be 5..60 bars apart.
List<EngineSignal> divergenceEngine(List<Candle> c, {int recency = 8}) {
  if (c.length < 50) return const [];
  final v = closes(c);
  final last = c.length - 1;
  final r = rsi(v);
  final h = macd(v).histogram;
  final pivots = confirmedPivots(c);
  final out = <EngineSignal>[];
  for (final isHigh in [false, true]) {
    final same = pivots.where((p) => p.isHigh == isHigh).toList();
    if (same.length < 2) continue;
    final p2 = same.last, p1 = same[same.length - 2];
    final gap = p2.index - p1.index;
    if (gap < 5 || gap > 60 || p2.confirmedIndex < last - recency) continue;
    final r1 = r[p1.index], r2 = r[p2.index], h1 = h[p1.index], h2 = h[p2.index];
    if (r1 == null || r2 == null) continue;

    String? kind;
    Bias bias = Bias.neutral;
    if (!isHigh) {
      if (p2.price < p1.price && r2 > r1) kind = 'REGULAR_BULLISH';
      if (p2.price > p1.price && r2 < r1) kind = 'HIDDEN_BULLISH';
      bias = Bias.bullish;
    } else {
      if (p2.price > p1.price && r2 < r1) kind = 'REGULAR_BEARISH';
      if (p2.price < p1.price && r2 > r1) kind = 'HIDDEN_BEARISH';
      bias = Bias.bearish;
    }
    if (kind == null) continue;
    final macdAgrees = h1 != null && h2 != null && ((r2 > r1) == (h2 > h1));
    var strength = 0.5 + (macdAgrees ? 0.25 : 0) + 0.25 * math.min((r2 - r1).abs() / 10, 1.0);
    if (kind == 'REGULAR_BULLISH' && r2 < 40) strength += 0.1;
    if (kind == 'REGULAR_BEARISH' && r2 > 60) strength += 0.1;
    // Target: the opposite swing between the two pivots.
    final between = pivots.where((p) => p.isHigh != isHigh && p.index > p1.index && p.index < p2.index);
    double? target;
    if (between.isNotEmpty) {
      target = isHigh
          ? between.map((p) => p.price).reduce(math.min)
          : between.map((p) => p.price).reduce(math.max);
    }
    // Already invalidated?
    if ((bias == Bias.bullish && v[last] < p2.price) || (bias == Bias.bearish && v[last] > p2.price)) continue;
    final regular = kind.startsWith('REGULAR');
    out.add(EngineSignal(
      engine: EngineId.divergence,
      bias: bias,
      strength: strength,
      pattern: '${kind}_RSI${macdAgrees ? '_MACD' : ''}',
      reasonAr: 'دايفرجنس ${regular ? 'عادي' : 'مخفي'} ${bias.arabic}: '
          'السعر ${p2.price > p1.price ? 'أعلى' : 'أدنى'} و RSI ${r2 > r1 ? 'أعلى' : 'أدنى'}'
          '${macdAgrees ? ' ويؤكده MACD' : ''}',
      knownAtIndex: p2.confirmedIndex,
      invalidation: p2.price,
      targets: target == null ? const [] : [target],
      details: {'p1': p1.price, 'p2': p2.price, 'rsi1': r1, 'rsi2': r2, 'gap': gap},
      geometry: ChartGeometry(
        points: [
          GeoPoint(p1.index, p1.price, 'RSI ${r1.toStringAsFixed(0)}'),
          GeoPoint(p2.index, p2.price, 'RSI ${r2.toStringAsFixed(0)}'),
        ],
        segments: [GeoSegment(p1.index, p1.price, p2.index, p2.price, role: GeoRole.divergence, label: kind)],
      ),
    ));
  }
  return out;
}
