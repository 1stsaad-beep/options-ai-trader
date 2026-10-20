import 'dart:isolate';

import 'package:flutter/material.dart';
import 'package:trader_core/trader_core.dart';

import '../chart/chart_layers.dart';
import '../chart/chart_painter.dart';
import '../chart/interactive_chart.dart';
import '../services/app_controller.dart';

typedef BarsLoader = Future<List<Candle>> Function(BarTimeframe timeframe);
typedef CompletedFilter = List<Candle> Function(List<Candle> bars, BarTimeframe timeframe);
typedef ChartAnalyzer = Future<ChartAnalysis> Function(String symbol, List<Candle> bars, Map<EngineId, double> weights);

/// Off the UI thread: the full analysis (and per-bar score history) on the
/// exact bars that were loaded.
Future<ChartAnalysis> analyzeInIsolate(String symbol, List<Candle> bars, Map<EngineId, double> weights) =>
    Isolate.run(() => ChartAnalysis.compute(symbol, bars, weights: weights, scoreBars: bars.length));

const _tfLabels = {
  BarTimeframe.m5: '5د',
  BarTimeframe.m15: '15د',
  BarTimeframe.h1: '1س',
  BarTimeframe.d1: 'يومي',
};

/// Per-symbol interactive chart with the account's engine overlays and its own
/// trade markers. Read-only: nothing on this screen places orders.
class ChartScreen extends StatefulWidget {
  final String symbol;
  final String title;
  final BarTimeframe initialTimeframe;

  /// The account's analysis timeframe (marked in the selector).
  final BarTimeframe accountTimeframe;
  final Map<EngineId, double> weights;
  final BarsLoader loadBars;
  final List<JournalEntry> Function() journal;
  final ChartAnalyzer analyze;

  /// Completed bars the engines analyse (drops the forming bar).
  final CompletedFilter completed;

  const ChartScreen({
    super.key,
    required this.symbol,
    required this.title,
    required this.initialTimeframe,
    required this.accountTimeframe,
    required this.weights,
    required this.loadBars,
    required this.journal,
    required this.completed,
    this.analyze = analyzeInIsolate,
  });

  /// Chart for [symbol] using account [accountId]'s adapter, settings and journal.
  factory ChartScreen.forAccount(AppController controller, String accountId, String symbol) {
    final rt = controller.account(accountId)!;
    return ChartScreen(
      symbol: symbol,
      title: rt.profile.name,
      initialTimeframe: rt.profile.settings.timeframe,
      accountTimeframe: rt.profile.settings.timeframe,
      weights: rt.profile.settings.engineWeights,
      loadBars: (tf) => controller.chartBars(accountId, symbol, tf),
      journal: () => controller.account(accountId)?.state.journal ?? const [],
      completed: (bars, tf) => controller.completedBars(accountId, bars, tf),
    );
  }

  @override
  State<ChartScreen> createState() => _ChartScreenState();
}

class _ChartScreenState extends State<ChartScreen> {
  late BarTimeframe _tf = widget.initialTimeframe;
  Set<ChartLayer> _layers = ChartLayer.defaults;
  ChartData? _data;
  String? _error;
  bool _loading = false;
  int _request = 0;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final req = ++_request;
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final bars = await widget.loadBars(_tf);
      final done = widget.completed(bars, _tf);
      if (done.isEmpty) throw const FormatException('لا توجد شموع مكتملة لهذا الرمز/الإطار');
      final analysis = await widget.analyze(widget.symbol, done, widget.weights);
      final markers = TradeMarker.fromJournal(widget.journal(), widget.symbol);
      if (!mounted || req != _request) return;
      setState(() {
        _data = ChartData(analysis, _tf, markers, allBars: bars);
        _loading = false;
      });
    } catch (e) {
      if (!mounted || req != _request) return;
      setState(() {
        _error = '$e';
        _loading = false;
      });
    }
  }

  void _openLayers() {
    showModalBottomSheet<void>(
      context: context,
      showDragHandle: true,
      builder: (c) => StatefulBuilder(
        builder: (c, setSheet) => ListView(shrinkWrap: true, children: [
          for (final l in ChartLayer.values)
            SwitchListTile(
              key: Key('layer-${l.name}'),
              dense: true,
              title: Text(l.labelAr),
              subtitle: l == ChartLayer.elliott ? const Text(kElliottNoticeAr) : null,
              value: _layers.contains(l),
              onChanged: (v) {
                final next = {..._layers};
                v ? next.add(l) : next.remove(l);
                setState(() => _layers = next);
                setSheet(() {});
              },
            ),
        ]),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final data = _data;
    return Scaffold(
      appBar: AppBar(
        title: Text('${widget.symbol} • ${widget.title}', overflow: TextOverflow.ellipsis),
        actions: [
          IconButton(key: const Key('chart-layers'), tooltip: 'الطبقات', icon: const Icon(Icons.layers_outlined), onPressed: _openLayers),
          IconButton(tooltip: 'تحديث', icon: const Icon(Icons.refresh), onPressed: _loading ? null : _load),
        ],
      ),
      body: Column(children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(8, 6, 8, 2),
          child: SegmentedButton<BarTimeframe>(
            showSelectedIcon: false,
            segments: [
              for (final tf in BarTimeframe.values)
                ButtonSegment(
                  value: tf,
                  label: Text(tf == widget.accountTimeframe ? '${_tfLabels[tf]}•' : _tfLabels[tf]!),
                  tooltip: tf == widget.accountTimeframe ? 'إطار تحليل الحساب' : null,
                ),
            ],
            selected: {_tf},
            onSelectionChanged: (s) {
              setState(() => _tf = s.first);
              _load();
            },
          ),
        ),
        if (data != null) _ScoreHeader(data: data, accountTimeframe: _tf == widget.accountTimeframe),
        if (_loading) const LinearProgressIndicator(minHeight: 2),
        Expanded(
          child: _error != null && data == null
              ? Center(child: Padding(padding: const EdgeInsets.all(24), child: Text('تعذر تحميل الشارت:\n$_error')))
              : data == null
                  ? const Center(child: CircularProgressIndicator())
                  : Padding(
                      padding: const EdgeInsets.fromLTRB(4, 4, 0, 4),
                      child: InteractiveChart(key: const Key('interactive-chart'), data: data, layers: _layers),
                    ),
        ),
        if (_error != null && data != null)
          Material(
            color: Theme.of(context).colorScheme.errorContainer,
            child: Padding(padding: const EdgeInsets.all(6), child: Text('آخر تحديث فشل: $_error', maxLines: 2)),
          ),
        if (data != null &&
            _layers.contains(ChartLayer.elliott) &&
            (data.analysis.findings[EngineId.elliott]?.isNotEmpty ?? false))
          Padding(
            key: const Key('elliott-notice'),
            padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
            child: Text('موجات إليوت: $kElliottNoticeAr', style: Theme.of(context).textTheme.bodySmall),
          ),
        if (data != null) _FindingsPanel(data: data),
      ]),
    );
  }
}

class _ScoreHeader extends StatelessWidget {
  final ChartData data;
  final bool accountTimeframe;
  const _ScoreHeader({required this.data, required this.accountTimeframe});

  @override
  Widget build(BuildContext context) {
    final r = data.analysis.report;
    final colors = ChartColors.of(Theme.of(context));
    final n = data.analysis.candles.length;
    final forming = data.candles.length - n;
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
      child: Row(children: [
        Chip(
          key: const Key('score-chip'),
          visualDensity: VisualDensity.compact,
          backgroundColor: colors.bias(r.bias).withValues(alpha: 0.15),
          label: Text('النتيجة ${r.score >= 0 ? '+' : ''}${r.score.toStringAsFixed(0)} • ${r.bias.arabic}',
              style: TextStyle(color: colors.bias(r.bias), fontWeight: FontWeight.bold)),
        ),
        const SizedBox(width: 6),
        Expanded(
          child: Text(
            '$n شمعة مكتملة${forming > 0 ? ' + $forming قيد التكوين' : ''}'
            '${n < 60 ? ' (أقل من 60: المحركات لا تحلل)' : ''}'
            '${accountTimeframe ? '' : ' • ليس إطار الحساب'}',
            style: Theme.of(context).textTheme.bodySmall,
            overflow: TextOverflow.ellipsis,
          ),
        ),
      ]),
    );
  }
}

class _FindingsPanel extends StatelessWidget {
  final ChartData data;
  const _FindingsPanel({required this.data});

  @override
  Widget build(BuildContext context) {
    final a = data.analysis;
    final colors = ChartColors.of(Theme.of(context));
    final all = [for (final e in a.findings.entries) ...e.value];
    final counted = a.report.signals;
    return ExpansionTile(
      dense: true,
      title: Text('ما تراه المحركات (${all.length})'),
      subtitle: Text('${counted.length} محرك يدخل في النتيجة', style: Theme.of(context).textTheme.bodySmall),
      children: [
        ConstrainedBox(
          constraints: const BoxConstraints(maxHeight: 220),
          child: all.isEmpty
              ? const Padding(padding: EdgeInsets.all(12), child: Text('لا توجد إشارات على هذه الشموع'))
              : ListView(shrinkWrap: true, children: [
                  for (final s in all)
                    ListTile(
                      dense: true,
                      leading: Icon(
                        s.bias == Bias.bullish ? Icons.trending_up : s.bias == Bias.bearish ? Icons.trending_down : Icons.remove,
                        color: colors.bias(s.bias),
                      ),
                      title: Text('${s.engine.arabic} • ${s.pattern}${counted.contains(s) ? ' ✓' : ''}'),
                      subtitle: Text('${s.engine.descriptiveOnly ? '$kElliottNoticeAr\n' : ''}${s.reasonAr}\nالقوة ${(s.strength * 100).toStringAsFixed(0)}%'
                          '${s.invalidation != null ? ' • الإبطال ${CandleChartPainter.fmt(s.invalidation!)}' : ''}'),
                    ),
                ]),
        ),
      ],
    );
  }
}
