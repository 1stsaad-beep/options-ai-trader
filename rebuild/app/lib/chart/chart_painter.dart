import 'dart:math' as math;
import 'dart:ui' as ui;

import 'package:flutter/material.dart';
import 'package:trader_core/trader_core.dart';

import 'chart_layers.dart';
import 'chart_viewport.dart';

/// Immutable inputs of one chart: analysis (bars + engine outputs on the same
/// bars) and the account's trade markers resolved to bar indices.
class ChartData {
  final ChartAnalysis analysis;
  final BarTimeframe timeframe;
  final List<({int index, TradeMarker marker})> markers;

  ChartData(this.analysis, this.timeframe, List<TradeMarker> tradeMarkers)
      : markers = [
          for (final m in tradeMarkers)
            if (TradeMarker.candleIndexFor(analysis.candles, m.time, timeframe.duration) case final i when i >= 0)
              (index: i, marker: m)
        ];

  List<Candle> get candles => analysis.candles;
}

class ChartColors {
  final Color up, down, grid, axisText, background, zigzag, harmonic, elliott, classical, divergence, levels, ema20,
      ema50, ema200, entry, exit;
  const ChartColors({
    required this.up,
    required this.down,
    required this.grid,
    required this.axisText,
    required this.background,
    this.zigzag = const Color(0xFFF59E0B),
    this.harmonic = const Color(0xFF8B5CF6),
    this.elliott = const Color(0xFF3B82F6),
    this.classical = const Color(0xFFF97316),
    this.divergence = const Color(0xFFEC4899),
    this.levels = const Color(0xFF14B8A6),
    this.ema20 = const Color(0xFF06B6D4),
    this.ema50 = const Color(0xFFA855F7),
    this.ema200 = const Color(0xFF64748B),
    this.entry = const Color(0xFF2563EB),
    this.exit = const Color(0xFFEA580C),
  });

  factory ChartColors.of(ThemeData t) => ChartColors(
        up: const Color(0xFF16A34A),
        down: const Color(0xFFDC2626),
        grid: t.colorScheme.outlineVariant.withValues(alpha: 0.35),
        axisText: t.colorScheme.onSurfaceVariant,
        background: t.colorScheme.surface,
      );

  Color bias(Bias b) => switch (b) { Bias.bullish => up, Bias.bearish => down, Bias.neutral => axisText };
}

/// Layout shared by the main painter, the crosshair painter and hit-testing.
class ChartLayout {
  static const double axisWidth = 58;
  static const double timeAxisHeight = 18;
  final Size size;
  final bool scorePane;
  const ChartLayout(this.size, this.scorePane);

  double get plotWidth => math.max(1, size.width - axisWidth);
  double get scoreHeight => scorePane ? math.max(40, size.height * 0.17) : 0;
  Rect get plot => Rect.fromLTWH(0, 0, plotWidth, math.max(1, size.height - timeAxisHeight - scoreHeight));
  Rect get score => Rect.fromLTWH(0, plot.bottom + timeAxisHeight, plotWidth, scoreHeight);
}

/// Candle paths for one viewport, reused while only overlays/crosshair change.
class CandleCache {
  Object? _key;
  Path upBodies = Path(), downBodies = Path(), upWicks = Path(), downWicks = Path();
  int builds = 0;

  void ensure(Object key, void Function(CandleCache c) build) {
    if (key == _key) return;
    upBodies = Path();
    downBodies = Path();
    upWicks = Path();
    downWicks = Path();
    build(this);
    _key = key;
    builds++;
  }
}

/// Price range of visible candles (used for the y-scale).
PriceScale priceScaleFor(List<Candle> c, ChartViewport v, Rect plot) {
  final (first, last) = v.visibleRange();
  var lo = double.infinity, hi = -double.infinity;
  for (var i = first; i <= last; i++) {
    lo = math.min(lo, c[i].low);
    hi = math.max(hi, c[i].high);
  }
  if (!lo.isFinite) {
    lo = c.isEmpty ? 1 : c.last.low;
    hi = c.isEmpty ? 2 : c.last.high;
  }
  return PriceScale.fit(lo, hi, plot.top + 4, plot.height - 8);
}

class CandleChartPainter extends CustomPainter {
  final ChartData data;
  final ChartViewport viewport;
  final double rightIndex, barsVisible; // snapshot for shouldRepaint
  final Set<ChartLayer> layers;
  final ChartColors colors;
  final CandleCache cache;

  CandleChartPainter({
    required this.data,
    required this.viewport,
    required this.layers,
    required this.colors,
    required this.cache,
  })  : rightIndex = viewport.rightIndex,
        barsVisible = viewport.barsVisible;

  @override
  bool shouldRepaint(CandleChartPainter old) =>
      old.data != data ||
      old.rightIndex != rightIndex ||
      old.barsVisible != barsVisible ||
      !_sameSet(old.layers, layers) ||
      old.colors.background != colors.background;

  static bool _sameSet(Set<ChartLayer> a, Set<ChartLayer> b) => a.length == b.length && a.containsAll(b);

  bool on(ChartLayer l) => layers.contains(l);

  @override
  void paint(Canvas canvas, Size size) {
    final c = data.candles;
    if (c.isEmpty) return;
    final layout = ChartLayout(size, on(ChartLayer.score));
    final plot = layout.plot;
    final w = plot.width;
    final ps = priceScaleFor(c, viewport, plot);
    final (first, last) = viewport.visibleRange();
    final bw = viewport.barWidth(w);
    double x(num i) => viewport.x(i, w);

    _grid(canvas, size, plot, ps, layout);
    _timeAxis(canvas, plot, first, last, x);

    canvas.save();
    canvas.clipRect(plot);

    final a = data.analysis;
    // ---- under the candles ----
    if (on(ChartLayer.levels)) _levels(canvas, plot, ps, a.levels);
    if (on(ChartLayer.harmonic)) _zones(canvas, ps, x, a.findings[EngineId.harmonic], colors.harmonic, bw);
    if (on(ChartLayer.classical)) _zones(canvas, ps, x, a.findings[EngineId.classical], colors.classical, bw);

    _candles(canvas, ps, first, last, x, bw, size);

    // ---- over the candles ----
    if (on(ChartLayer.ema)) {
      _series(canvas, ps, x, a.ema20, first, last, colors.ema20);
      _series(canvas, ps, x, a.ema50, first, last, colors.ema50);
      _series(canvas, ps, x, a.ema200, first, last, colors.ema200);
    }
    if (on(ChartLayer.trendLines)) {
      for (final t in a.trendLines) {
        _segment(canvas, ps, x, t, colors.levels.withValues(alpha: 0.9), 1.2, dash: true, culling: (first, last));
      }
    }
    if (on(ChartLayer.zigzag)) _zigzag(canvas, ps, x, first, last);
    if (on(ChartLayer.classical)) _engine(canvas, ps, x, a.findings[EngineId.classical], colors.classical, first, last);
    if (on(ChartLayer.harmonic)) _engine(canvas, ps, x, a.findings[EngineId.harmonic], colors.harmonic, first, last);
    if (on(ChartLayer.elliott)) _engine(canvas, ps, x, a.findings[EngineId.elliott], colors.elliott, first, last);
    if (on(ChartLayer.divergence)) {
      _engine(canvas, ps, x, a.findings[EngineId.divergence], colors.divergence, first, last);
    }
    if (on(ChartLayer.targets)) _targets(canvas, plot, ps, x);
    if (on(ChartLayer.trades)) _markers(canvas, ps, x, first, last, bw);
    _lastPrice(canvas, plot, ps);
    canvas.restore();

    _lastPriceTag(canvas, plot, ps, size);
    if (layout.scorePane) _scorePane(canvas, layout.score, first, last, x, bw);
  }

  // ---------------------------------------------------------------- helpers

  void _text(Canvas canvas, String s, Offset at,
      {Color? color, double size = 10, Color? bg, bool center = false, bool alignRight = false, FontWeight? weight}) {
    final tp = TextPainter(
      text: TextSpan(text: s, style: TextStyle(color: color ?? colors.axisText, fontSize: size, fontWeight: weight)),
      textDirection: TextDirection.ltr,
    )..layout();
    var o = at;
    if (center) o = o.translate(-tp.width / 2, -tp.height / 2);
    if (alignRight) o = o.translate(-tp.width, 0);
    if (bg != null) {
      canvas.drawRRect(RRect.fromRectAndRadius(Rect.fromLTWH(o.dx - 2, o.dy - 1, tp.width + 4, tp.height + 2), const Radius.circular(3)),
          Paint()..color = bg);
    }
    tp.paint(canvas, o);
  }

  static String fmt(double p) => p >= 1000 ? p.toStringAsFixed(1) : p.toStringAsFixed(2);

  void _grid(Canvas canvas, Size size, Rect plot, PriceScale ps, ChartLayout layout) {
    final g = Paint()
      ..color = colors.grid
      ..strokeWidth = 1;
    for (final t in ps.ticks()) {
      final y = ps.y(t);
      if (y < plot.top || y > plot.bottom) continue;
      canvas.drawLine(Offset(0, y), Offset(plot.right, y), g);
      _text(canvas, fmt(t), Offset(plot.right + 4, y - 6));
    }
    canvas.drawLine(Offset(plot.right, 0), Offset(plot.right, size.height), g);
    canvas.drawLine(Offset(0, plot.bottom), Offset(plot.right, plot.bottom), g);
  }

  String _timeLabel(DateTime t, DateTime? prev) {
    final l = t.toLocal();
    String two(int v) => v.toString().padLeft(2, '0');
    if (data.timeframe == BarTimeframe.d1) return '${two(l.month)}-${two(l.day)}';
    final newDay = prev == null || prev.toLocal().day != l.day;
    return newDay ? '${two(l.month)}-${two(l.day)}' : '${two(l.hour)}:${two(l.minute)}';
  }

  void _timeAxis(Canvas canvas, Rect plot, int first, int last, double Function(num) x) {
    final c = data.candles;
    final bw = viewport.barWidth(plot.width);
    final every = math.max(1, (80 / bw).ceil());
    for (var i = first; i <= last; i++) {
      if (i % every != 0) continue;
      final px = x(i);
      if (px < 0 || px > plot.right) continue;
      _text(canvas, _timeLabel(c[i].time, i - every >= 0 ? c[i - every].time : null), Offset(px, plot.bottom + 9),
          center: true, size: 9);
    }
  }

  void _candles(Canvas canvas, PriceScale ps, int first, int last, double Function(num) x, double bw, Size size) {
    final c = data.candles;
    cache.ensure((first, last, rightIndex, barsVisible, size, ps.min, ps.max), (cc) {
      final body = math.max(1.0, bw * 0.7);
      for (var i = first; i <= last; i++) {
        final k = c[i];
        final up = k.close >= k.open;
        final cx = x(i);
        final yo = ps.y(k.open), yc = ps.y(k.close);
        final top = math.min(yo, yc), bot = math.max(yo, yc);
        final r = Rect.fromLTRB(cx - body / 2, top, cx + body / 2, math.max(bot, top + 1));
        (up ? cc.upBodies : cc.downBodies).addRect(r);
        final wick = up ? cc.upWicks : cc.downWicks;
        wick
          ..moveTo(cx, ps.y(k.high))
          ..lineTo(cx, ps.y(k.low));
      }
    });
    final wp = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = 1;
    canvas.drawPath(cache.upWicks, wp..color = colors.up);
    canvas.drawPath(cache.downWicks, wp..color = colors.down);
    canvas.drawPath(cache.upBodies, Paint()..color = colors.up);
    canvas.drawPath(cache.downBodies, Paint()..color = colors.down);
  }

  void _series(Canvas canvas, PriceScale ps, double Function(num) x, List<double?> s, int first, int last, Color color) {
    final path = Path();
    var started = false;
    for (var i = first; i <= last && i < s.length; i++) {
      final v = s[i];
      if (v == null) {
        started = false;
        continue;
      }
      final o = Offset(x(i), ps.y(v));
      if (started) {
        path.lineTo(o.dx, o.dy);
      } else {
        path.moveTo(o.dx, o.dy);
        started = true;
      }
    }
    canvas.drawPath(
        path,
        Paint()
          ..style = PaintingStyle.stroke
          ..strokeWidth = 1.3
          ..color = color);
  }

  void _dashed(Canvas canvas, Offset a, Offset b, Paint p, {double dash = 6, double gap = 4}) {
    final d = b - a;
    final len = d.distance;
    if (len == 0) return;
    final u = d / len;
    for (var t = 0.0; t < len; t += dash + gap) {
      canvas.drawLine(a + u * t, a + u * math.min(len, t + dash), p);
    }
  }

  void _segment(Canvas canvas, PriceScale ps, double Function(num) x, GeoSegment s, Color color, double width,
      {bool dash = false, (int, int)? culling}) {
    if (culling != null && (math.max(s.i1, s.i2) < culling.$1 || math.min(s.i1, s.i2) > culling.$2)) return;
    final p = Paint()
      ..color = color
      ..strokeWidth = width
      ..style = PaintingStyle.stroke;
    final a = Offset(x(s.i1), ps.y(s.p1)), b = Offset(x(s.i2), ps.y(s.p2));
    dash ? _dashed(canvas, a, b, p) : canvas.drawLine(a, b, p);
  }

  void _levels(Canvas canvas, Rect plot, PriceScale ps, List<PriceLevel> levels) {
    for (final l in levels) {
      final y = ps.y(l.price);
      if (y < plot.top || y > plot.bottom) continue;
      final color = (l.isSupport ? colors.up : colors.down).withValues(alpha: 0.55);
      _dashed(canvas, Offset(0, y), Offset(plot.right, y), Paint()
        ..color = color
        ..strokeWidth = 1 + math.min(2, (l.touches - 1) * 0.6));
      _text(canvas, '${l.isSupport ? 'S' : 'R'}${l.touches > 1 ? '×${l.touches}' : ''} ${fmt(l.price)}',
          Offset(4, y - 13), color: color, size: 9);
    }
  }

  void _zones(Canvas canvas, PriceScale ps, double Function(num) x, List<EngineSignal>? sigs, Color color, double bw) {
    if (sigs == null) return;
    for (final s in sigs) {
      for (final z in s.geometry.zones) {
        final right = z.label == 'PRZ' ? x(z.i2) + bw * 6 : x(z.i2) + bw / 2;
        final r = Rect.fromLTRB(x(z.i1) - bw / 2, ps.y(z.hi), right, ps.y(z.lo));
        canvas.drawRect(r, Paint()..color = color.withValues(alpha: 0.13));
        canvas.drawRect(
            r,
            Paint()
              ..style = PaintingStyle.stroke
              ..color = color.withValues(alpha: 0.6));
        _text(canvas, z.label == '20' ? 'نطاق 20' : z.label, Offset(r.left + 2, r.top + 1), color: color, size: 9);
      }
    }
  }

  void _zigzag(Canvas canvas, PriceScale ps, double Function(num) x, int first, int last) {
    final a = data.analysis;
    final sw = a.swings;
    final p = Paint()
      ..color = colors.zigzag
      ..strokeWidth = 1.4
      ..style = PaintingStyle.stroke;
    final path = Path();
    var started = false;
    for (var k = 0; k < sw.length; k++) {
      final s = sw[k];
      final nextIdx = k + 1 < sw.length ? sw[k + 1].index : s.index;
      final prevIdx = k > 0 ? sw[k - 1].index : s.index;
      if (nextIdx < first || prevIdx > last) {
        started = false;
        continue;
      }
      final o = Offset(x(s.index), ps.y(s.price));
      if (started) {
        path.lineTo(o.dx, o.dy);
      } else {
        path.moveTo(o.dx, o.dy);
        started = true;
      }
    }
    canvas.drawPath(path, p);
    // Provisional leg: last confirmed swing -> last close (not a confirmed pivot).
    if (sw.isNotEmpty) {
      final s = sw.last;
      final c = a.candles;
      _dashed(canvas, Offset(x(s.index), ps.y(s.price)), Offset(x(c.length - 1), ps.y(c.last.close)),
          Paint()
            ..color = colors.zigzag.withValues(alpha: 0.6)
            ..strokeWidth = 1.2);
    }
    // Confirmed fractal pivots.
    final dot = Paint()..color = colors.zigzag;
    for (final pv in a.pivots) {
      if (pv.index < first || pv.index > last) continue;
      final o = Offset(x(pv.index), ps.y(pv.price) + (pv.isHigh ? -4 : 4));
      canvas.drawCircle(o, 2, dot);
    }
  }

  void _engine(Canvas canvas, PriceScale ps, double Function(num) x, List<EngineSignal>? sigs, Color color, int first,
      int last) {
    if (sigs == null) return;
    final best = data.analysis.report.signals;
    for (final s in sigs) {
      final g = s.geometry;
      if (g.isEmpty) continue;
      final strong = best.contains(s);
      final cull = (first, last);
      for (final seg in g.segments) {
        final dash = seg.role == GeoRole.neckline || seg.role == GeoRole.boundary || seg.label == 'XB' || seg.label == 'BD';
        _segment(canvas, ps, x, seg, color.withValues(alpha: strong ? 1 : 0.7), strong ? 2 : 1.3, dash: dash, culling: cull);
      }
      for (final pt in g.points) {
        if (pt.index < first || pt.index > last) continue;
        final o = Offset(x(pt.index), ps.y(pt.price));
        canvas.drawCircle(o, 3, Paint()..color = color);
        final above = _isHighPoint(pt, g.points);
        _text(canvas, pt.label, o.translate(0, above ? -12 : 12), color: Colors.white, bg: color, center: true, size: 9,
            weight: FontWeight.bold);
      }
      // Pattern name at the last point.
      final lastPt = g.points.isNotEmpty ? g.points.last : null;
      if (lastPt != null && lastPt.index >= first && lastPt.index <= last) {
        _text(canvas, '${s.pattern} ${s.bias == Bias.bullish ? '▲' : s.bias == Bias.bearish ? '▼' : ''}',
            Offset(x(lastPt.index) + 6, ps.y(lastPt.price) + (_isHighPoint(lastPt, g.points) ? -26 : 18)),
            color: colors.bias(s.bias), size: 9, weight: FontWeight.bold);
      }
    }
  }

  static bool _isHighPoint(GeoPoint p, List<GeoPoint> all) {
    final i = all.indexOf(p);
    final prev = i > 0 ? all[i - 1].price : null, next = i + 1 < all.length ? all[i + 1].price : null;
    final ref = prev ?? next;
    return ref == null ? true : p.price >= ref;
  }

  void _targets(Canvas canvas, Rect plot, PriceScale ps, double Function(num) x) {
    for (final s in data.analysis.report.signals) {
      final from = x(s.knownAtIndex).clamp(0.0, plot.right);
      final name = s.engine.arabic;
      final inv = s.invalidation;
      if (inv != null) {
        final y = ps.y(inv);
        _dashed(canvas, Offset(from, y), Offset(plot.right, y), Paint()
          ..color = colors.down
          ..strokeWidth = 1.2, dash: 3, gap: 3);
        _text(canvas, 'إبطال $name ${fmt(inv)}', Offset(plot.right - 4, y - 12), color: colors.down, size: 9, alignRight: true);
      }
      for (var k = 0; k < s.targets.length; k++) {
        final y = ps.y(s.targets[k]);
        _dashed(canvas, Offset(from, y), Offset(plot.right, y), Paint()
          ..color = colors.up.withValues(alpha: 0.8)
          ..strokeWidth = 1, dash: 2, gap: 4);
        _text(canvas, 'هدف ${k + 1} $name ${fmt(s.targets[k])}', Offset(plot.right - 4, y - 12),
            color: colors.up, size: 9, alignRight: true);
      }
    }
  }

  void _markers(Canvas canvas, PriceScale ps, double Function(num) x, int first, int last, double bw) {
    final c = data.candles;
    final sz = math.max(5.0, math.min(9.0, bw * 0.8));
    for (final m in data.markers) {
      if (m.index < first || m.index > last) continue;
      final k = c[m.index];
      final kind = m.marker.kind;
      final buy = kind == TradeMarkerKind.entry || kind == TradeMarkerKind.scaleIn || kind == TradeMarkerKind.filledBuy;
      final filled = kind == TradeMarkerKind.filledBuy || kind == TradeMarkerKind.filledSell;
      final cx = x(m.index);
      final color = buy ? colors.entry : colors.exit;
      final path = Path();
      if (buy) {
        final y = ps.y(k.low) + 6;
        path
          ..moveTo(cx, y)
          ..lineTo(cx - sz / 2, y + sz)
          ..lineTo(cx + sz / 2, y + sz)
          ..close();
      } else {
        final y = ps.y(k.high) - 6;
        path
          ..moveTo(cx, y)
          ..lineTo(cx - sz / 2, y - sz)
          ..lineTo(cx + sz / 2, y - sz)
          ..close();
      }
      canvas.drawPath(
          path,
          Paint()
            ..color = color
            ..style = filled ? PaintingStyle.fill : PaintingStyle.stroke
            ..strokeWidth = 1.5);
      final up = m.marker.underlyingPrice;
      if (up != null && kind == TradeMarkerKind.entry) {
        canvas.drawCircle(Offset(cx, ps.y(up)), 2.5, Paint()..color = color);
      }
    }
  }

  void _lastPrice(Canvas canvas, Rect plot, PriceScale ps) {
    final k = data.candles.last;
    final y = ps.y(k.close);
    _dashed(canvas, Offset(0, y), Offset(plot.right, y), Paint()
      ..color = (k.close >= k.open ? colors.up : colors.down).withValues(alpha: 0.7)
      ..strokeWidth = 1, dash: 2, gap: 2);
  }

  void _lastPriceTag(Canvas canvas, Rect plot, PriceScale ps, Size size) {
    final k = data.candles.last;
    final y = ps.y(k.close).clamp(plot.top, plot.bottom - 12);
    _text(canvas, fmt(k.close), Offset(plot.right + 2, y - 6),
        color: Colors.white, bg: k.close >= k.open ? colors.up : colors.down, size: 10, weight: FontWeight.bold);
  }

  void _scorePane(Canvas canvas, Rect r, int first, int last, double Function(num) x, double bw) {
    final g = Paint()
      ..color = colors.grid
      ..strokeWidth = 1;
    double y(double v) => r.center.dy - v / 100 * (r.height / 2 - 2);
    canvas.drawLine(Offset(0, r.top), Offset(r.right, r.top), g);
    canvas.drawLine(Offset(0, y(0)), Offset(r.right, y(0)), g);
    for (final lv in [50.0, -50.0]) {
      _dashed(canvas, Offset(0, y(lv)), Offset(r.right, y(lv)), g, dash: 2, gap: 4);
    }
    final h = data.analysis.scoreHistory;
    final barW = math.max(1.0, bw * 0.6);
    final up = Paint()..color = colors.up.withValues(alpha: 0.8), dn = Paint()..color = colors.down.withValues(alpha: 0.8);
    canvas.save();
    canvas.clipRect(r);
    for (var i = first; i <= last && i < h.length; i++) {
      final v = h[i];
      if (v == null) continue;
      final cx = x(i);
      canvas.drawRect(Rect.fromLTRB(cx - barW / 2, math.min(y(0), y(v)), cx + barW / 2, math.max(y(0), y(v))), v >= 0 ? up : dn);
    }
    canvas.restore();
    final s = data.analysis.report.score;
    _text(canvas, 'النتيجة ${s >= 0 ? '+' : ''}${s.toStringAsFixed(0)}', Offset(4, r.top + 2),
        color: s >= 0 ? colors.up : colors.down, size: 9, weight: FontWeight.bold);
    _text(canvas, '+100', Offset(r.right + 4, r.top), size: 8);
    _text(canvas, '0', Offset(r.right + 4, y(0) - 5), size: 8);
    _text(canvas, '-100', Offset(r.right + 4, r.bottom - 10), size: 8);
  }
}

/// Crosshair only — repaints alone while the finger moves, candles stay cached.
class CrosshairPainter extends CustomPainter {
  final int? index;
  final double? y;
  final ChartViewport viewport;
  final double rightIndex, barsVisible;
  final bool scorePane;
  final ChartColors colors;
  final double? price;

  CrosshairPainter({
    required this.index,
    required this.y,
    required this.viewport,
    required this.scorePane,
    required this.colors,
    required this.price,
  })  : rightIndex = viewport.rightIndex,
        barsVisible = viewport.barsVisible;

  @override
  bool shouldRepaint(CrosshairPainter o) =>
      o.index != index || o.y != y || o.rightIndex != rightIndex || o.barsVisible != barsVisible || o.price != price;

  @override
  void paint(Canvas canvas, Size size) {
    final i = index, py = y;
    if (i == null || py == null) return;
    final layout = ChartLayout(size, scorePane);
    final plot = layout.plot;
    final p = Paint()
      ..color = colors.axisText.withValues(alpha: 0.8)
      ..strokeWidth = 0.8;
    final px = viewport.x(i, plot.width);
    canvas.drawLine(Offset(px, 0), Offset(px, size.height - (scorePane ? 0 : ChartLayout.timeAxisHeight)), p);
    if (py >= plot.top && py <= plot.bottom) {
      canvas.drawLine(Offset(0, py), Offset(plot.right, py), p);
      if (price != null) {
        final tp = TextPainter(
          text: TextSpan(text: CandleChartPainter.fmt(price!), style: const TextStyle(color: Colors.white, fontSize: 10)),
          textDirection: ui.TextDirection.ltr,
        )..layout();
        final r = Rect.fromLTWH(plot.right + 1, py - tp.height / 2 - 1, tp.width + 6, tp.height + 2);
        canvas.drawRect(r, Paint()..color = colors.axisText);
        tp.paint(canvas, Offset(r.left + 3, r.top + 1));
      }
    }
  }
}
