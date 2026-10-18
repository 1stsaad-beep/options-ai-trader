import 'package:test/test.dart';
import 'package:trader_core/trader_core.dart';

import 'helpers.dart';

void main() {
  group('engine geometry', () {
    test('harmonic Gartley carries XABCD points matching swings and a PRZ containing D', () {
      final c = candlesFromCloses(
          path(110, [(10, 100), (10, 120), (10, 107.64), (10, 115.28), (10, 104.28), (1, 104.6), (1, 104.9), (1, 105.1)]));
      final g = harmonicEngine(c).firstWhere((e) => e.pattern == 'GARTLEY');
      expect(g.geometry.points.map((p) => p.label), ['X', 'A', 'B', 'C', 'D']);
      final swings = alternatingSwings(confirmedPivots(c), minMoveFraction: 0.004);
      final last5 = swings.sublist(swings.length - 5);
      for (var k = 0; k < 5; k++) {
        expect(g.geometry.points[k].index, last5[k].index);
        expect(g.geometry.points[k].price, last5[k].price);
      }
      final prz = g.geometry.zones.single;
      final d = g.geometry.points.last.price;
      expect(prz.lo, lessThanOrEqualTo(d));
      expect(prz.hi, greaterThanOrEqualTo(d));
      expect(g.geometry.maxIndex, lessThan(c.length));
    });

    test('elliott geometry labels equal the details labels and indices', () {
      final c = candlesFromCloses(path(130, [(40, 100), (10, 110), (10, 104), (8, 111)]));
      final w3 = elliottEngine(c).firstWhere((e) => e.pattern == 'WAVE3_START');
      expect(w3.geometry.points.map((p) => p.label), w3.details['labels']);
      expect(w3.geometry.points.map((p) => p.index), w3.details['indices']);
      expect(w3.geometry.segments, hasLength(2));
    });

    test('double bottom geometry has a neckline at the middle swing ending at the break bar', () {
      final c = candlesFromCloses(path(120, [(20, 100), (8, 106), (8, 100.5), (8, 107)]));
      final s = classicalEngine(c).firstWhere((e) => e.pattern == 'DOUBLE_BOTTOM');
      final neck = s.geometry.segments.firstWhere((g) => g.role == GeoRole.neckline);
      expect(neck.p1, s.details['neckline']);
      expect(neck.i2, s.knownAtIndex);
      expect(c[neck.i2].close, greaterThan(neck.p1));
    });

    test('divergence geometry joins the two swings', () {
      final c = candlesFromCloses(path(100, [(30, 110), (5, 95), (6, 102), (15, 94.5), (3, 96)]));
      final s = divergenceEngine(c).firstWhere((e) => e.pattern.startsWith('REGULAR_BULLISH'));
      final seg = s.geometry.segments.single;
      expect(seg.role, GeoRole.divergence);
      expect(seg.p1, s.details['p1']);
      expect(seg.p2, s.details['p2']);
    });

    test('geometry is not written into the journal JSON', () {
      final c = candlesFromCloses(
          path(110, [(10, 100), (10, 120), (10, 107.64), (10, 115.28), (10, 104.28), (1, 104.6), (1, 104.9), (1, 105.1)]));
      final g = harmonicEngine(c).firstWhere((e) => e.pattern == 'GARTLEY');
      expect(g.toJson().containsKey('geometry'), isFalse);
    });
  });

  group('chart analysis', () {
    final c = candlesFromCloses(path(110, [(30, 100), (30, 125), (30, 105), (30, 118), (20, 108)]));

    test('report equals the analyzer report on the same bars', () {
      final ca = ChartAnalysis.compute('X', c);
      expect(ca.report.toJson(), Analyzer().analyze('X', c).toJson());
      expect(identical(ca.candles, c), isTrue);
      for (final list in ca.findings.values) {
        for (final s in list) {
          expect(s.geometry.maxIndex, lessThan(c.length));
        }
      }
    });

    test('score history is causal and ends with the current score', () {
      final ca = ChartAnalysis.compute('X', c, scoreBars: 20);
      expect(ca.scoreHistory.length, c.length);
      expect(ca.scoreHistory.last, ca.report.score);
      final i = c.length - 10;
      expect(ca.scoreHistory[i], Analyzer().analyze('X', c.sublist(0, i + 1)).score);
      expect(ca.scoreHistory[c.length - 25], isNull);
    });

    test('swings alternate and levels sit on the correct side of the close', () {
      final ca = ChartAnalysis.compute('X', c, scoreBars: 1);
      for (var k = 1; k < ca.swings.length; k++) {
        expect(ca.swings[k].isHigh, isNot(ca.swings[k - 1].isHigh));
      }
      final close = c.last.close;
      for (final l in ca.levels) {
        expect(l.isSupport ? l.price < close : l.price >= close, isTrue);
      }
      expect(ca.trendLines.every((t) => t.i2 == c.length - 1), isTrue);
      expect(ca.ema20.length, c.length);
    });
  });

  group('trade markers', () {
    test('built from journal entries of the symbol and placed on the right candle', () {
      final j = [
        JournalEntry(time: t0.add(const Duration(minutes: 31)), action: JournalAction.entry, symbol: 'AAPL', reasonAr: 'دخول',
            details: {'analysis': {'close': 101.5}, 'contract': 'AAPL261120C00150000'}),
        JournalEntry(time: t0.add(const Duration(minutes: 40)), action: JournalAction.orderFilled, symbol: 'AAPL',
            reasonAr: 'تنفيذ شراء 1 عقد', details: {'side': 'buyToOpen'}),
        JournalEntry(time: t0.add(const Duration(minutes: 90)), action: JournalAction.orderFilled, symbol: 'AAPL',
            reasonAr: 'تنفيذ بيع 1 عقد'),
        JournalEntry(time: t0, action: JournalAction.skip, symbol: 'AAPL', reasonAr: 'x'),
        JournalEntry(time: t0, action: JournalAction.entry, symbol: 'MSFT', reasonAr: 'x'),
      ];
      final m = TradeMarker.fromJournal(j, 'AAPL');
      expect(m.map((e) => e.kind), [TradeMarkerKind.entry, TradeMarkerKind.filledBuy, TradeMarkerKind.filledSell]);
      expect(m.first.underlyingPrice, 101.5);
      expect(m.first.contract, 'AAPL261120C00150000');
      final bars = candlesFromCloses(List<double>.generate(20, (i) => 100.0 + i));
      expect(TradeMarker.candleIndexFor(bars, m[0].time, const Duration(minutes: 15)), 2);
      expect(TradeMarker.candleIndexFor(bars, t0.subtract(const Duration(minutes: 1)), const Duration(minutes: 15)), -1);
      expect(TradeMarker.candleIndexFor(bars, t0.add(const Duration(days: 3)), const Duration(minutes: 15)), -1);
    });
  });

  test('chart analysis of 300 bars with full score history is fast enough', () {
    final bars = List<Candle>.generate(300, (i) {
      final p = 100 + 10 * (i % 37) / 37 + (i ~/ 37);
      return Candle(time: t0.add(Duration(minutes: 15 * i)), open: p, high: p + .5, low: p - .5, close: p + .1);
    });
    final sw = Stopwatch()..start();
    final ca = ChartAnalysis.compute('X', bars, scoreBars: 300);
    expect(ca.scoreHistory.whereType<double>().length, 300 - 59);
    sw.stop();
    // ignore: avoid_print
    print('chart analysis 300 bars: ${sw.elapsedMilliseconds} ms');
    expect(sw.elapsedMilliseconds, lessThan(10000));
  });
}
