/// Elliott-wave engine (rule-based, deterministic).
///
/// Works on the alternating swing list and evaluates four scenarios in both
/// directions. Prices are multiplied by `sign` so "up" rules cover downtrends.
///
/// | Scenario      | Swings used             | Bias        | Invalidation      |
/// |---------------|-------------------------|-------------|-------------------|
/// | WAVE3_START   | 0,1,2 (+ break of 1)    | with trend  | start of wave 1   |
/// | WAVE5_START   | 0,1,2,3,4               | with trend  | top of wave 1     |
/// | IMPULSE_DONE  | 0..5                    | against     | end of wave 5     |
/// | WAVE_C        | 0..5, A, B              | against     | end of wave 5     |
///
/// Hard impulse rules enforced: wave 2 never retraces beyond the start of
/// wave 1; wave 3 is never the shortest of 1/3/5; wave 4 never enters wave-1
/// territory. Fibonacci closeness (wave 2 ≈ 0.5–0.618, wave 4 ≈ 0.382,
/// wave 3 ≈ 1.618×wave 1) raises strength.
library;

import 'dart:math' as math;

import '../models.dart';
import 'pivots.dart';
import 'signal.dart';

double _fit(double value, double ideal, double width) => 1 - math.min(1.0, (value - ideal).abs() / width);

List<EngineSignal> elliottEngine(List<Candle> c, {int recency = 20}) {
  if (c.length < 60) return const [];
  final swings = alternatingSwings(confirmedPivots(c), minMoveFraction: 0.006);
  if (swings.length < 3) return const [];
  final last = c.length - 1;
  final out = <EngineSignal>[];

  for (final sign in [1.0, -1.0]) {
    final bias = sign > 0 ? Bias.bullish : Bias.bearish;
    final against = sign > 0 ? Bias.bearish : Bias.bullish;
    final close = c[last].close * sign;
    // Signed prices; a "low" in signed space is a real low when sign=+1.
    final s = [for (final p in swings) p.price * sign];
    bool isLow(int k) => sign > 0 ? !swings[k].isHigh : swings[k].isHigh;
    final n = s.length;
    bool recent(int k) => swings[k].confirmedIndex >= last - recency;

    EngineSignal make(String pattern, Bias b, double strength, String why, int knownAt, double inval,
            List<double> targets, List<String> labels, int from) =>
        EngineSignal(
          engine: EngineId.elliott,
          bias: b,
          strength: strength,
          pattern: pattern,
          reasonAr: why,
          knownAtIndex: knownAt,
          invalidation: inval * sign,
          targets: [for (final t in targets) t * sign],
          details: {
            'labels': labels,
            'points': [for (var k = 0; k < labels.length; k++) swings[from + k].price],
            'indices': [for (var k = 0; k < labels.length; k++) swings[from + k].index],
          },
        );

    // --- WAVE3_START: [L0, H1, L2] at the end, wave 2 retraced 38–79% ---
    if (n >= 3 && isLow(n - 3) && recent(n - 1)) {
      final p0 = s[n - 3], p1 = s[n - 2], p2 = s[n - 1];
      final w1 = p1 - p0, retr = (p1 - p2) / w1;
      if (w1 > 0 && p2 > p0 && retr >= 0.36 && retr <= 0.80 && close > p2) {
        final target = p2 + 1.618 * w1;
        if (close < target) {
          final broke = close > p1;
          final strength = 0.45 + (broke ? 0.25 : 0) + 0.3 * _fit(retr, 0.59, 0.25);
          out.add(make(
            'WAVE3_START',
            bias,
            strength,
            'موجة 2 انتهت عند تصحيح ${(retr * 100).toStringAsFixed(0)}% من الموجة 1'
                '${broke ? ' واخترق السعر قمة الموجة 1' : ''}؛ المتوقع موجة 3 ${bias.arabic}',
            swings[n - 1].confirmedIndex,
            p0,
            [p1 + (p1 - p0) * 0.618, target],
            ['0', '1', '2'],
            n - 3,
          ));
        }
      }
    }

    // --- WAVE5_START: [L0,H1,L2,H3,L4] valid impulse so far ---
    if (n >= 5 && isLow(n - 5) && recent(n - 1)) {
      final p = s.sublist(n - 5);
      final w1 = p[1] - p[0], w3 = p[3] - p[2];
      final r2 = (p[1] - p[2]) / w1, r4 = (p[3] - p[4]) / w3;
      final valid = w1 > 0 && w3 > 0 && p[2] > p[0] && p[3] > p[1] && p[4] > p[1] && w3 >= w1 && r4 >= 0.2 && r4 <= 0.62;
      if (valid && close > p[4]) {
        final target = p[4] + w1;
        if (close < target) {
          final strength = 0.4 + 0.2 * _fit(r4, 0.382, 0.2) + 0.2 * _fit(w3 / w1, 1.618, 0.8) + 0.2 * _fit(r2, 0.59, 0.3);
          out.add(make(
            'WAVE5_START',
            bias,
            strength,
            'دافعة صحيحة 1-4: الموجة 3 = ${(w3 / w1).toStringAsFixed(2)}× الموجة 1 وتصحيح الموجة 4 '
                '${(r4 * 100).toStringAsFixed(0)}%؛ المتوقع موجة 5 ${bias.arabic}',
            swings[n - 1].confirmedIndex,
            p[1],
            [p[4] + 0.618 * w1, target],
            ['0', '1', '2', '3', '4'],
            n - 5,
          ));
        }
      }
    }

    // Helper: does s[from..from+5] form a complete impulse?
    bool impulseAt(int from) {
      if (from < 0 || from + 5 >= n || !isLow(from)) return false;
      final p = s.sublist(from, from + 6);
      final w1 = p[1] - p[0], w3 = p[3] - p[2], w5 = p[5] - p[4];
      if (w1 <= 0 || w3 <= 0 || w5 <= 0) return false;
      if (!(p[2] > p[0] && p[3] > p[1] && p[4] > p[1] && p[5] > p[3])) return false;
      return !(w3 < w1 && w3 < w5); // wave 3 not the shortest
    }

    // --- IMPULSE_DONE: last six swings complete an impulse -> expect correction ---
    if (impulseAt(n - 6) && recent(n - 1)) {
      final p = s.sublist(n - 6);
      final total = p[5] - p[0];
      final t1 = p[5] - 0.382 * total, t2 = p[5] - 0.618 * total;
      if (close < p[5] && close > t1) {
        out.add(make(
          'IMPULSE_DONE',
          against,
          0.5,
          'اكتملت دافعة خماسية ${bias.arabic}؛ المتوقع تصحيح ABC ${against.arabic}',
          swings[n - 1].confirmedIndex,
          p[5],
          [t1, t2],
          ['0', '1', '2', '3', '4', '5'],
          n - 6,
        ));
      }
    }

    // --- WAVE_C: impulse, then A down and B up (38–89% of A) -> expect C ---
    if (impulseAt(n - 8) && recent(n - 1)) {
      final top = s[n - 3], a = s[n - 2], b = s[n - 1];
      final lenA = top - a, rb = (b - a) / lenA;
      if (lenA > 0 && rb >= 0.38 && rb <= 0.89 && b < top && close < b) {
        final target = b - lenA; // C = A
        if (close > target) {
          out.add(make(
            'WAVE_C',
            against,
            0.45 + 0.3 * _fit(rb, 0.618, 0.3),
            'بعد الدافعة: الموجة A ثم B بنسبة ${(rb * 100).toStringAsFixed(0)}%؛ المتوقع الموجة C ${against.arabic}',
            swings[n - 1].confirmedIndex,
            top,
            [b - 0.618 * lenA, target],
            ['5', 'A', 'B'],
            n - 3,
          ));
        }
      }
    }
  }
  return out;
}
