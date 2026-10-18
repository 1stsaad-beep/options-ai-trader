import 'package:flutter/material.dart';
import 'package:trader_core/trader_core.dart';

import 'chart_layers.dart';
import 'chart_painter.dart';
import 'chart_viewport.dart';

/// Candles + engine overlays with pan (drag), pinch zoom, long-press crosshair
/// with an OHLC readout, tap to dismiss, double-tap to jump to the latest bar.
/// Always laid out left-to-right (time axis) even inside the RTL app.
class InteractiveChart extends StatefulWidget {
  final ChartData data;
  final Set<ChartLayer> layers;
  const InteractiveChart({super.key, required this.data, required this.layers});

  @override
  State<InteractiveChart> createState() => InteractiveChartState();
}

class InteractiveChartState extends State<InteractiveChart> {
  late ChartViewport viewport;
  final CandleCache cache = CandleCache();
  int? crossIndex;
  double? crossY;
  double _lastScale = 1;
  Size _size = Size.zero;

  @override
  void initState() {
    super.initState();
    viewport = ChartViewport(barCount: widget.data.candles.length);
  }

  @override
  void didUpdateWidget(InteractiveChart oldWidget) {
    super.didUpdateWidget(oldWidget);
    final old = oldWidget;
    if (old.data != widget.data) {
      final sameLength = old.data.candles.length == widget.data.candles.length && old.data.timeframe == widget.data.timeframe;
      viewport = sameLength
          ? ChartViewport(
              barCount: widget.data.candles.length, barsVisible: viewport.barsVisible, rightIndex: viewport.rightIndex)
          : ChartViewport(barCount: widget.data.candles.length);
      crossIndex = null;
    }
  }

  bool get _scorePane => widget.layers.contains(ChartLayer.score);
  double get _plotWidth => ChartLayout(_size, _scorePane).plotWidth;

  void _setCross(Offset p) {
    final i = viewport.barAt(p.dx, _plotWidth);
    setState(() {
      crossIndex = i < 0 ? null : i;
      crossY = p.dy;
    });
  }

  @override
  Widget build(BuildContext context) {
    final colors = ChartColors.of(Theme.of(context));
    return Directionality(
      textDirection: TextDirection.ltr,
      child: LayoutBuilder(builder: (context, box) {
        _size = Size(box.maxWidth, box.maxHeight);
        final layout = ChartLayout(_size, _scorePane);
        final ps = priceScaleFor(widget.data.candles, viewport, layout.plot);
        final cy = crossY;
        final crossPrice = cy != null && cy >= layout.plot.top && cy <= layout.plot.bottom ? ps.priceAt(cy) : null;
        return GestureDetector(
          behavior: HitTestBehavior.opaque,
          onScaleStart: (_) => _lastScale = 1,
          onScaleUpdate: (d) {
            setState(() {
              if (d.pointerCount >= 2 && d.scale != _lastScale) {
                viewport.zoom(d.scale / _lastScale, d.localFocalPoint.dx, _plotWidth);
                _lastScale = d.scale;
              }
              if (d.focalPointDelta.dx != 0) viewport.pan(d.focalPointDelta.dx, _plotWidth);
              crossIndex = null;
            });
          },
          onLongPressStart: (d) => _setCross(d.localPosition),
          onLongPressMoveUpdate: (d) => _setCross(d.localPosition),
          onTapUp: (_) => setState(() => crossIndex = null),
          onDoubleTap: () => setState(() => viewport.jumpToLatest()),
          child: Stack(children: [
            Positioned.fill(
              child: RepaintBoundary(
                child: CustomPaint(
                  painter: CandleChartPainter(
                    data: widget.data,
                    viewport: viewport,
                    layers: widget.layers,
                    colors: colors,
                    cache: cache,
                  ),
                ),
              ),
            ),
            Positioned.fill(
              child: CustomPaint(
                painter: CrosshairPainter(
                  index: crossIndex,
                  y: crossY,
                  viewport: viewport,
                  scorePane: _scorePane,
                  colors: colors,
                  price: crossPrice,
                ),
              ),
            ),
            if (crossIndex != null)
              Positioned(left: 4, top: 4, child: OhlcReadout(data: widget.data, index: crossIndex!)),
          ]),
        );
      }),
    );
  }
}

/// OHLC (+volume, score, account decisions) of the bar under the crosshair.
class OhlcReadout extends StatelessWidget {
  final ChartData data;
  final int index;
  const OhlcReadout({super.key, required this.data, required this.index});

  /// Bar start in New York time, labelled ET.
  static String timeText(DateTime t, BarTimeframe tf) {
    final d = NewYorkTime.dateKey(t);
    return tf == BarTimeframe.d1 ? d : '$d ${NewYorkTime.hm(t)} ET';
  }

  @override
  Widget build(BuildContext context) {
    final k = data.candles[index];
    final t = Theme.of(context);
    final change = index > 0 ? (k.close - data.candles[index - 1].close) / data.candles[index - 1].close * 100 : null;
    final score = index < data.analysis.scoreHistory.length ? data.analysis.scoreHistory[index] : null;
    final marks = data.markers.where((m) => m.index == index).toList();
    String f(double v) => CandleChartPainter.fmt(v);
    final style = TextStyle(fontSize: 11, color: t.colorScheme.onSurface, fontFeatures: const []);
    return ConstrainedBox(
      constraints: const BoxConstraints(maxWidth: 260),
      child: DecoratedBox(
        decoration: BoxDecoration(
          color: t.colorScheme.surfaceContainerHighest.withValues(alpha: 0.92),
          borderRadius: BorderRadius.circular(6),
        ),
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 5),
          child: DefaultTextStyle(
            style: style,
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
              Text(timeText(k.time, data.timeframe), key: const Key('readout-time')),
              Text('O ${f(k.open)}  H ${f(k.high)}', key: const Key('readout-oh')),
              Text('L ${f(k.low)}  C ${f(k.close)}${change == null ? '' : '  ${change >= 0 ? '+' : ''}${change.toStringAsFixed(2)}%'}',
                  key: const Key('readout-lc')),
              Text('V ${k.volume.toStringAsFixed(0)}${score == null ? '' : '   Score ${score.toStringAsFixed(0)}'}'),
              if (data.isForming(index))
                const Text('شمعة قيد التكوين — خارج التحليل',
                    key: Key('readout-forming'), textDirection: TextDirection.rtl),
              for (final m in marks.take(3))
                Text(_markLabel(m.marker),
                    textDirection: TextDirection.rtl, maxLines: 2, overflow: TextOverflow.ellipsis),
            ]),
          ),
        ),
      ),
    );
  }

  static String _markLabel(TradeMarker m) {
    final kind = switch (m.kind) {
      TradeMarkerKind.entry => 'أمر دخول',
      TradeMarkerKind.exit => 'أمر خروج',
      TradeMarkerKind.scaleIn => 'تعزيز',
      TradeMarkerKind.filledBuy => 'تنفيذ شراء',
      TradeMarkerKind.filledSell => 'تنفيذ بيع',
    };
    return '$kind${m.contract != null ? ' ${m.contract}' : ''}';
  }
}
