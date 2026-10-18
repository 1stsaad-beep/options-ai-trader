import 'package:flutter_test/flutter_test.dart';
import 'package:options_ai_trader_app/chart/chart_viewport.dart';

void main() {
  group('ChartViewport', () {
    test('x and barAt are inverse and the last bar is visible initially', () {
      final v = ChartViewport(barCount: 300);
      const w = 400.0;
      final (first, last) = v.visibleRange();
      expect(last, 299);
      expect(first, greaterThan(150));
      for (final i in [first + 1, 250, 299]) {
        expect(v.barAt(v.x(i, w), w), i);
      }
      expect(v.barAt(-1000, w), -1);
    });

    test('pan moves left into history and is clamped at both ends', () {
      final v = ChartViewport(barCount: 300);
      const w = 400.0;
      final before = v.rightIndex;
      v.pan(100, w); // finger moves right -> older bars
      expect(v.rightIndex, lessThan(before));
      v.pan(1e7, w);
      expect(v.startIndex, greaterThanOrEqualTo(-v.barsVisible * 0.5));
      v.pan(-1e7, w);
      expect(v.rightIndex, lessThanOrEqualTo(299 + v.barsVisible * v.rightPadFraction));
    });

    test('zoom keeps the bar under the focal point and respects limits', () {
      final v = ChartViewport(barCount: 300, barsVisible: 100, rightIndex: 250);
      const w = 500.0, fx = 200.0;
      final idx = v.indexAtX(fx, w);
      v.zoom(2, fx, w);
      expect(v.barsVisible, closeTo(50, 1e-9));
      expect(v.indexAtX(fx, w), closeTo(idx, 1e-9));
      v.zoom(1000, fx, w);
      expect(v.barsVisible, v.minBars);
      v.zoom(0.0001, fx, w);
      expect(v.barsVisible, v.maxBars);
    });

    test('works with fewer bars than the default window', () {
      final v = ChartViewport(barCount: 20);
      final (first, last) = v.visibleRange();
      expect(first, 0);
      expect(last, 19);
    });
  });

  group('PriceScale', () {
    test('y/priceAt round-trip and nice ticks inside the range', () {
      final s = PriceScale.fit(100, 110, 0, 200);
      expect(s.priceAt(s.y(105)), closeTo(105, 1e-9));
      expect(s.y(s.max), 0);
      final t = s.ticks();
      expect(t, isNotEmpty);
      expect(t.every((v) => v >= s.min && v <= s.max), isTrue);
    });

    test('flat price does not divide by zero', () {
      final s = PriceScale.fit(50, 50, 0, 100);
      expect(s.max, greaterThan(s.min));
    });
  });
}
