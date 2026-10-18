import 'package:test/test.dart';
import 'package:trader_core/trader_core.dart';

import 'helpers.dart';
import 'real_bars_test.dart' show loadFixture;

/// Wave-1 up, a-b-c wave 2 with a bullish RSI divergence, then wave 3.
List<double> wave2Path({double cLow = 108}) =>
    path(115, [(15, 100), (20, 120), (4, 108.5), (6, 113), (2, cLow), (17, 125)]);

TfSeries m15(List<double> closes) => TfSeries.of(BarTimeframe.m15, candlesFromCloses(closes));

void main() {
  group('alignment', () {
    test('daily bars end at 16:00 New York; completedAt counts only ended bars', () {
      final d = Candle(time: DateTime.utc(2026, 6, 1, 13, 30), open: 1, high: 1, low: 1, close: 1);
      expect(barEnd(d, BarTimeframe.d1), DateTime.utc(2026, 6, 1, 20)); // EDT
      final s = TfSeries.of(BarTimeframe.h1, [
        for (var i = 0; i < 3; i++) Candle(time: DateTime.utc(2026, 6, 1, 13 + i, 30), open: 1, high: 1, low: 1, close: 1)
      ]);
      expect(s.completedAt(DateTime.utc(2026, 6, 1, 14, 29)), 0);
      expect(s.completedAt(DateTime.utc(2026, 6, 1, 14, 30)), 1);
      expect(s.completedAt(DateTime.utc(2026, 6, 2)), 3);
    });

    test('weekly bars aggregate Mon–Fri and end at the last session close', () {
      final d = loadFixture('spy_d1');
      final w = weeklyFromDaily(d);
      expect(w.bars.length, inInclusiveRange(d.length ~/ 5, d.length ~/ 4 + 2));
      final first = d.takeWhile((b) => w.ends.first.isAfter(b.time)).toList();
      expect(w.bars.first.high, first.map((b) => b.high).reduce((a, b) => a > b ? a : b));
      expect(w.bars.first.close, first.last.close);
      expect(w.ends.first, barEnd(first.last, BarTimeframe.d1));
    });
  });

  group('ATR zig-zag', () {
    test('alternates, confirms after the pivot, and is causal', () {
      final d = loadFixture('aapl_d1');
      final z = atrZigZag(d, k: 1.5);
      expect(z.length, greaterThan(20));
      for (var i = 1; i < z.length; i++) {
        expect(z[i].isHigh, isNot(z[i - 1].isHigh));
      }
      for (final p in z) {
        expect(p.confirmedIndex, greaterThan(p.index));
        expect(p.price, p.isHigh ? d[p.index].high : d[p.index].low);
      }
      final cut = d.length * 2 ~/ 3;
      final prefix = atrZigZag(d.sublist(0, cut), k: 1.5);
      expect(prefix.map((p) => '$p'), knownPivots(z, cut - 1).map((p) => '$p'));
    });

    test('impulse context: higher highs + higher lows = bullish, mirror bearish, mixed none', () {
      ZzPivot p(int i, double v, bool h) => ZzPivot(i, i + 1, v, h);
      final up = [p(0, 100, false), p(1, 110, true), p(2, 104, false), p(3, 118, true), p(4, 109, false)];
      expect(impulseContext(up, 112), 1);
      expect(impulseContext(up, 108), 0, reason: 'price below the last low');
      final down = [p(0, 118, true), p(1, 109, false), p(2, 114, true), p(3, 100, false), p(4, 108, true)];
      expect(impulseContext(down, 105), -1);
      final mixed = [p(0, 100, false), p(1, 110, true), p(2, 104, false), p(3, 108, true), p(4, 105, false)];
      expect(impulseContext(mixed, 106), 0);
      // strict: wave 4 (109) overlapping wave 1's top (110) → no impulse
      final overlap = [p(0, 100, false), p(1, 110, true), p(2, 104, false), p(3, 118, true), p(4, 109.5, false)];
      expect(impulseContext(overlap, 112, strict: true), 0);
      expect(impulseContext(up.sublist(0, 4)..add(p(4, 111, false)), 112, strict: true), 1);
    });
  });

  group('Strategy A — MTF Elliott', () {
    const p = ElliottParams(requireTop: false, requireMid: false, kEntry: 4, kFine: 1);

    test('end of wave 2 with bullish RSI divergence → Call at the confirming bar', () {
      final s = m15(wave2Path());
      final sig = mtfElliottSignals(entry: s, p: p);
      expect(sig, hasLength(1));
      final x = sig.single;
      expect(x.bullish, isTrue);
      expect(x.index, greaterThan(47)); // the c-low bar is 47; signal only after confirmation
      expect(x.features['rsiC'] as double, greaterThan(x.features['rsiA'] as double));
      expect(x.features['retrace'] as double, closeTo(0.6, 0.01));
      expect(x.invalidation, closeTo(107.95, 1e-9));
    });

    test('mirror: end of wave C with bearish divergence → Put', () {
      final s = m15([for (final c in wave2Path()) 230 - c]);
      final sig = mtfElliottSignals(entry: s, p: p);
      expect(sig, hasLength(1));
      expect(sig.single.bullish, isFalse);
    });

    test('wave 2 beyond the start of wave 1 is not a wave 2 → no signal', () {
      expect(mtfElliottSignals(entry: m15(wave2Path(cLow: 99)), p: p), isEmpty);
    });

    test('directions can be disabled; confluence filters only remove signals', () {
      final s = m15(wave2Path());
      expect(mtfElliottSignals(entry: s, p: const ElliottParams(requireTop: false, requireMid: false, kEntry: 4, kFine: 1, calls: false)), isEmpty);
      final d = loadFixture('aapl_d1');
      final e = TfSeries.of(BarTimeframe.d1, d);
      final w = weeklyFromDaily(d);
      const base = ElliottParams(requireTop: false, requireMid: false, kEntry: 1.5);
      final all = {for (final x in mtfElliottSignals(entry: e, mid: w, ma: e, p: base)) x.index};
      for (final f in [
        base.copyWith(maTrend: true),
        base.copyWith(macd: true),
        base.copyWith(fibPrice: true),
        base.copyWith(fibTime: true),
        base.copyWith(waveMa: true),
        base.copyWith(sr: true),
        base.copyWith(classical: true),
        base.copyWith(requireMid: true),
      ]) {
        final sub = mtfElliottSignals(entry: e, mid: w, ma: e, p: f);
        expect(all.containsAll(sub.map((x) => x.index)), isTrue, reason: f.id);
      }
    });

    test('no look-ahead: signals on a prefix equal the full-run signals before the cut', () {
      final d = loadFixture('spy_d1');
      final h = loadFixture('spy_h1');
      const q = ElliottParams(requireTop: false, kEntry: 1.5);
      for (final (entryBars, tf) in [(d, BarTimeframe.d1), (h, BarTimeframe.h1)]) {
        final full = mtfElliottSignals(
            entry: TfSeries.of(tf, entryBars), mid: weeklyFromDaily(d), ma: TfSeries.of(BarTimeframe.d1, d), p: q);
        for (final frac in [0.5, 0.8]) {
          final cut = (entryBars.length * frac).round();
          final pre = mtfElliottSignals(
              entry: TfSeries.of(tf, entryBars.sublist(0, cut)), mid: weeklyFromDaily(d), ma: TfSeries.of(BarTimeframe.d1, d), p: q);
          expect(pre.map((x) => '${x.index}${x.bullish}'), [for (final x in full) if (x.index < cut) '${x.index}${x.bullish}']);
        }
      }
    });
  });

  group('Strategy B — MTF RSI (both directions)', () {
    // fast: 30 rising bars (RSI 100), one sharp drop out of overbought, then back up
    final upCloses = [for (var i = 0; i < 31; i++) 100.0 + i, 122.0, 124.0, 126.0, 128.0, 130.0];
    List<Candle> fastBars(List<double> c) => [
          for (var i = 0; i < c.length; i++)
            Candle(time: DateTime.utc(2026, 6, 1, 13, 30).add(Duration(minutes: 15 * i)), open: c[i], high: c[i], low: c[i], close: c[i])
        ];
    TfSeries slowSeries(List<double> c) => TfSeries.of(BarTimeframe.h1, [
          for (var i = 0; i < c.length; i++)
            Candle(time: DateTime.utc(2026, 5, 29, 13, 30).add(Duration(hours: i)), open: c[i], high: c[i], low: c[i], close: c[i])
        ]);
    final slowUp = slowSeries([for (var i = 0; i < 40; i++) 100.0 + i]);
    final slowDown = slowSeries([for (var i = 0; i < 40; i++) 200.0 - i]);
    final slowFlat = slowSeries([for (var i = 0; i < 40; i++) i.isEven ? 100.0 : 101.0]);

    test('PUT: slow overbought, fast leaves and re-enters overbought within the window', () {
      final fast = TfSeries.of(BarTimeframe.m15, fastBars(upCloses));
      final s = mtfRsiSignals(fast, slowUp, const MtfRsiParams());
      expect(s, hasLength(1));
      expect(s.single.bullish, isFalse);
      expect(s.single.features['gap'], lessThanOrEqualTo(8));
      expect(s.single.reasonAr, contains('Put'));
      expect(mtfRsiSignals(fast, slowUp, const MtfRsiParams(window: 1)), isEmpty, reason: 'came back too late');
      expect(mtfRsiSignals(fast, slowFlat, const MtfRsiParams()), isEmpty, reason: 'slow not overbought');
      expect(mtfRsiSignals(fast, slowUp, const MtfRsiParams(puts: false)), isEmpty);
    });

    test('CALL mirror: slow oversold, fast leaves and re-enters oversold', () {
      final fast = TfSeries.of(BarTimeframe.m15, fastBars([for (final c in upCloses) 300 - c]));
      final s = mtfRsiSignals(fast, slowDown, const MtfRsiParams());
      expect(s, hasLength(1));
      expect(s.single.bullish, isTrue);
      expect(mtfRsiSignals(fast, slowDown, const MtfRsiParams(calls: false)), isEmpty);
    });

    test('threshold 75 is stricter than 70', () {
      final h = loadFixture('aapl_h1');
      final d = loadFixture('aapl_d1');
      final f = TfSeries.of(BarTimeframe.h1, h), sl = TfSeries.of(BarTimeframe.d1, d);
      final n70 = mtfRsiSignals(f, sl, const MtfRsiParams(slowOverbought: 70, slowAtExit: false)).length;
      final n75 = mtfRsiSignals(f, sl, const MtfRsiParams(slowOverbought: 75, slowAtExit: false)).length;
      expect(n75, lessThanOrEqualTo(n70));
    });

    test('no look-ahead: prefix signals equal full signals before the cut; slow bar must be completed', () {
      final h = loadFixture('spy_h1');
      final d = loadFixture('spy_d1');
      final sl = TfSeries.of(BarTimeframe.d1, d);
      final full = mtfRsiSignals(TfSeries.of(BarTimeframe.h1, h), sl, const MtfRsiParams(slowOverbought: 65, window: 16));
      final cut = h.length * 2 ~/ 3;
      final pre = mtfRsiSignals(TfSeries.of(BarTimeframe.h1, h.sublist(0, cut)), sl, const MtfRsiParams(slowOverbought: 65, window: 16));
      expect(pre.map((x) => x.index), [for (final x in full) if (x.index < cut) x.index]);
      for (final x in full) {
        final n = sl.completedAt(x.time);
        expect(sl.ends[n - 1].isAfter(x.time), isFalse);
      }
    });
  });
}
