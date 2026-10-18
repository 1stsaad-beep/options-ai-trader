import 'package:test/test.dart';
import 'package:trader_core/trader_core.dart';

import 'helpers.dart';

void main() {
  group('indicators', () {
    test('sma and ema warm-up and values', () {
      final v = [1.0, 2, 3, 4, 5].map((e) => e.toDouble()).toList();
      expect(sma(v, 3), [null, null, 2.0, 3.0, 4.0]);
      final e = ema(v, 3);
      expect(e[1], isNull);
      expect(e[2], 2.0); // seeded with SMA
      expect(e[3], closeTo(3.0, 1e-9)); // 4*0.5 + 2*0.5
    });

    test('rsi is 100 on a strictly rising series and 0 on a falling one', () {
      final up = List<double>.generate(30, (i) => 100.0 + i);
      final down = List<double>.generate(30, (i) => 100.0 - i);
      expect(rsi(up).last, 100);
      expect(rsi(down).last, closeTo(0, 1e-9));
      expect(rsi(up)[13], isNull);
    });

    test('atr of constant-range bars equals the range', () {
      final c = candlesFromCloses(List<double>.filled(40, 50), wick: 0.5);
      expect(atr(c).last, closeTo(1.0, 1e-9));
    });

    test('macd histogram aligns with input length', () {
      final v = List<double>.generate(80, (i) => 100 + i * 0.3);
      final m = macd(v);
      expect(m.histogram.length, 80);
      expect(m.line.last, greaterThan(0));
    });
  });

  group('pivots', () {
    test('a pivot is confirmed only `right` bars later and never changes', () {
      final closes = path(110, [(10, 100), (10, 120), (10, 105)]);
      final all = candlesFromCloses(closes);
      final full = confirmedPivots(all);
      for (var end = 10; end <= all.length; end++) {
        final prefix = confirmedPivots(all.sublist(0, end));
        for (final p in prefix) {
          expect(p.confirmedIndex, lessThan(end));
          final same = full.where((f) => f.index == p.index).single;
          expect(same.price, p.price);
          expect(same.isHigh, p.isHigh);
        }
      }
    });

    test('alternating swings strictly alternate', () {
      final c = candlesFromCloses(path(110, [(10, 100), (10, 120), (10, 107), (10, 115), (10, 104), (3, 105)]));
      final s = alternatingSwings(confirmedPivots(c));
      for (var i = 1; i < s.length; i++) {
        expect(s[i].isHigh, isNot(s[i - 1].isHigh));
      }
    });
  });

  group('engines', () {
    test('harmonic engine detects a bullish Gartley at D', () {
      final c = candlesFromCloses(
          path(110, [(10, 100), (10, 120), (10, 107.64), (10, 115.28), (10, 104.28), (1, 104.6), (1, 104.9), (1, 105.1)]));
      final s = harmonicEngine(c);
      expect(s.map((e) => e.pattern), contains('GARTLEY'));
      final g = s.firstWhere((e) => e.pattern == 'GARTLEY');
      expect(g.bias, Bias.bullish);
      expect(g.invalidation!, lessThan(104.28));
      expect(g.targets.first, greaterThan(105.1));
    });

    test('harmonic engine stays silent when D is not recent', () {
      final closes =
          path(110, [(10, 100), (10, 120), (10, 107.64), (10, 115.28), (10, 104.28), (20, 105.5)]);
      expect(harmonicEngine(candlesFromCloses(closes)).where((e) => e.pattern == 'GARTLEY'), isEmpty);
    });

    test('elliott engine sees a wave-3 start after a 60% wave-2 and a break of wave 1', () {
      final c = candlesFromCloses(path(130, [(40, 100), (10, 110), (10, 104), (8, 111)]));
      final s = elliottEngine(c);
      final w3 = s.where((e) => e.pattern == 'WAVE3_START').toList();
      expect(w3, isNotEmpty);
      expect(w3.first.bias, Bias.bullish);
      expect(w3.first.invalidation, closeTo(99.95, 1e-6)); // start of wave 1
    });

    test('classical engine confirms a double bottom only after the neckline break', () {
      final closes = path(120, [(20, 100), (8, 106), (8, 100.5), (8, 107)]);
      final c = candlesFromCloses(closes);
      expect(classicalEngine(c).map((e) => e.pattern), contains('DOUBLE_BOTTOM'));
      // Before the break (cut 3 bars earlier) there is no signal.
      final early = candlesFromCloses(closes.sublist(0, closes.length - 3));
      expect(classicalEngine(early).map((e) => e.pattern), isNot(contains('DOUBLE_BOTTOM')));
    });

    test('divergence engine finds regular bullish divergence', () {
      final c = candlesFromCloses(path(100, [(30, 110), (5, 95), (6, 102), (15, 94.5), (3, 96)]));
      final s = divergenceEngine(c);
      expect(s.map((e) => e.pattern).any((p) => p.startsWith('REGULAR_BULLISH')), isTrue);
    });

    test('trend engine reads an uptrend', () {
      final c = candlesFromCloses(List<double>.generate(120, (i) => 100 + i * 0.4 + (i % 5) * 0.1));
      final s = trendEngine(c);
      expect(s.single.bias, Bias.bullish);
    });
  });

  group('analyzer', () {
    test('composite score is bounded and silent engines dilute it', () {
      final c = candlesFromCloses(List<double>.generate(150, (i) => 100 + i * 0.5));
      final r = Analyzer().analyze('TEST', c);
      expect(r.score, inInclusiveRange(-100, 100));
      expect(r.score, greaterThan(0));
      final onlyTrend = Analyzer().analyze('TEST', c, weights: {
        EngineId.momentum: 0,
        EngineId.divergence: 0,
        EngineId.harmonic: 0,
        EngineId.elliott: 0,
        EngineId.classical: 0,
      });
      expect(onlyTrend.score, greaterThanOrEqualTo(r.score));
    });

    test('analysis is causal: a prefix report ignores later bars', () {
      final closes = path(110, [(30, 100), (30, 125), (30, 105)]);
      final all = candlesFromCloses(closes);
      final a = Analyzer().analyze('X', all.sublist(0, 70));
      final b = Analyzer().analyze('X', all.sublist(0, 70)); // deterministic
      expect(a.toJson(), b.toJson());
      for (final s in a.signals) {
        expect(s.knownAtIndex, lessThan(70));
      }
    });
  });
}
