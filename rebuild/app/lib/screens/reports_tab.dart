import 'package:flutter/material.dart';
import 'package:trader_core/trader_core.dart';

import '../services/app_controller.dart';

String _pct(double? v) => v == null ? '—' : '${v.toStringAsFixed(2)}%';

/// Per-account performance report with CSV / JSON export.
class ReportsTab extends StatefulWidget {
  final AppController controller;
  final AccountRuntime rt;
  const ReportsTab({super.key, required this.controller, required this.rt});

  @override
  State<ReportsTab> createState() => _ReportsTabState();
}

class _ReportsTabState extends State<ReportsTab> {
  bool _weekly = false;
  bool _exporting = false;

  Future<void> _export(bool json) async {
    setState(() => _exporting = true);
    try {
      final rt = widget.rt;
      final files = await widget.controller.exporter.exportReport(rt.profile, widget.controller.report(rt), json: json);
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('تم تجهيز ${files.length} ملف للمشاركة')));
      }
    } catch (e) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('تعذر التصدير: $e')));
    } finally {
      if (mounted) setState(() => _exporting = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final rt = widget.rt;
    final r = widget.controller.report(rt);
    final p = r.performance;
    final text = Theme.of(context).textTheme;
    final periods = _weekly ? r.weekly : r.daily;
    final trades = r.trades.reversed.toList();
    return ListView(
      padding: const EdgeInsets.all(12),
      children: [
        Card(
          child: Padding(
            padding: const EdgeInsets.all(12),
            child: Wrap(spacing: 24, runSpacing: 12, children: [
              _Stat('الربح/الخسارة المحققة', formatUsd(p.realizedPnlCents), key: const Key('stat-realized')),
              _Stat('غير المحققة (المراكز المفتوحة)',
                  r.unrealizedPnlCents == null ? (rt.positions.isEmpty ? '\$0.00' : 'لا يوجد سعر') : formatUsd(r.unrealizedPnlCents!)),
              _Stat('العائد الكلي', _pct(p.totalReturnPercent)),
              _Stat('أقصى تراجع (Drawdown)', '${p.maxDrawdownPercent.toStringAsFixed(2)}% (${formatUsd(p.maxDrawdownCents)})'),
              _Stat('الصفقات المغلقة', '${p.trades}'),
              _Stat('رابحة / خاسرة / تعادل', '${p.wins} / ${p.losses} / ${p.breakevens}', key: const Key('stat-wl')),
              _Stat('نسبة الربح', '${p.winRatePercent.toStringAsFixed(1)}%'),
              _Stat('معامل الربح', p.profitFactor.isInfinite ? '∞' : p.profitFactor.toStringAsFixed(2)),
              _Stat('متوسط الربح', formatUsd(p.averageWinCents.round())),
              _Stat('متوسط الخسارة', formatUsd(-p.averageLossCents.round())),
              _Stat('العمولات', formatUsd(p.feesCents)),
            ]),
          ),
        ),
        Padding(
          padding: const EdgeInsets.symmetric(vertical: 4),
          child: Text(
              'الأرقام بعد العمولات. "تعادل" = صفقة صافي ربحها صفر، ولا تُحسب ربحًا ولا خسارة. نسبة الربح = الرابحة ÷ كل الصفقات. '
              'التراجع محسوب من منحنى قيمة الحساب المسجل في كل دورة.',
              style: text.bodySmall),
        ),
        Row(children: [
          Expanded(
            child: FilledButton.tonalIcon(
              key: const Key('export-csv'),
              onPressed: _exporting ? null : () => _export(false),
              icon: const Icon(Icons.table_view),
              label: const Text('تصدير CSV'),
            ),
          ),
          const SizedBox(width: 8),
          Expanded(
            child: FilledButton.tonalIcon(
              key: const Key('export-json'),
              onPressed: _exporting ? null : () => _export(true),
              icon: const Icon(Icons.data_object),
              label: const Text('تصدير JSON'),
            ),
          ),
        ]),
        _title(context, 'حسب الفترة (تاريخ نيويورك، عند الإغلاق)'),
        Card(
          child: Column(children: [
            Padding(
              padding: const EdgeInsets.all(8),
              child: SegmentedButton<bool>(
                segments: const [
                  ButtonSegment(value: false, label: Text('يومي')),
                  ButtonSegment(value: true, label: Text('أسبوعي')),
                ],
                selected: {_weekly},
                onSelectionChanged: (v) => setState(() => _weekly = v.first),
              ),
            ),
            if (periods.isEmpty) const ListTile(title: Text('لا توجد صفقات مغلقة بعد')),
            for (final d in periods.take(30))
              ListTile(
                dense: true,
                title: Text(_weekly ? 'أسبوع ${d.key}' : d.key, textDirection: TextDirection.ltr, textAlign: TextAlign.right),
                subtitle: Text('${d.trades} صفقة • ${d.wins} رابحة • ${d.losses} خاسرة${d.breakevens > 0 ? ' • ${d.breakevens} تعادل' : ''}'),
                trailing: Text(formatUsd(d.pnlCents), textDirection: TextDirection.ltr, style: TextStyle(color: _color(context, d.pnlCents))),
              ),
          ]),
        ),
        _title(context, 'مساهمة المحركات'),
        Card(
          child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 12, 16, 4),
              child: Text(
                  'الصفقة تُحسب لكل محرك أيّد اتجاهها عند الدخول، لذلك تتداخل الصفوف ولا تُجمع.'
                  '${r.untaggedTrades > 0 ? ' ${r.untaggedTrades} صفقة بدون بيانات محركات (أقدم من هذه النسخة أو مركز خارجي).' : ''}',
                  style: text.bodySmall),
            ),
            if (r.engines.isEmpty) const ListTile(title: Text('لا توجد بيانات بعد')),
            for (final e in r.engines)
              ListTile(
                dense: true,
                title: Text(e.arabic),
                subtitle: Text('${e.trades} صفقة • ${e.wins} رابحة • ${e.losses} خاسرة • نسبة الربح ${e.winRatePercent.toStringAsFixed(0)}%'),
                trailing: Text(formatUsd(e.pnlCents), textDirection: TextDirection.ltr, style: TextStyle(color: _color(context, e.pnlCents))),
              ),
          ]),
        ),
        _title(context, 'الصفقات المغلقة'),
        if (trades.isEmpty) const Card(child: ListTile(title: Text('لا توجد صفقات مغلقة بعد'))),
        for (final t in trades)
          Card(
            child: ExpansionTile(
              title: Text('${t.underlying} ${t.right.arabic} • ${formatUsd(t.pnlCents)}'),
              subtitle: Text('${NewYorkTime.dateKey(t.exitTime)} • ${t.quantity} عقد • ${t.returnPercent.toStringAsFixed(1)}% • '
                  '${t.pnlCents > 0 ? 'رابحة' : t.pnlCents < 0 ? 'خاسرة' : 'تعادل'}'),
              childrenPadding: const EdgeInsets.fromLTRB(16, 0, 16, 12),
              expandedCrossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text('الدخول ${NewYorkTime.dateKey(t.entryTime)} ${NewYorkTime.hm(t.entryTime)} ET بسعر ${formatUsd(t.entryPremiumCents)} • '
                    'الخروج ${NewYorkTime.hm(t.exitTime)} ET بسعر ${formatUsd(t.exitPremiumCents)} • العمولات ${formatUsd(t.feesCents)}'),
                if (t.engines.isNotEmpty)
                  Text('المحركات: ${t.engines.map((e) => EngineStats(e).arabic).join('، ')}'),
                const SizedBox(height: 6),
                Text('سبب الدخول:', style: text.labelLarge),
                SelectableText(t.entryReasonAr.isEmpty ? '—' : t.entryReasonAr),
                const SizedBox(height: 8),
                Text('سبب الخروج:', style: text.labelLarge),
                SelectableText(t.exitReasonAr.isEmpty ? '—' : t.exitReasonAr),
              ],
            ),
          ),
      ],
    );
  }

  static Color? _color(BuildContext context, int cents) =>
      cents > 0 ? Colors.green.shade700 : (cents < 0 ? Theme.of(context).colorScheme.error : null);

  Widget _title(BuildContext context, String s) => Padding(
        padding: const EdgeInsets.fromLTRB(4, 16, 4, 6),
        child: Text(s, style: Theme.of(context).textTheme.titleSmall),
      );
}

class _Stat extends StatelessWidget {
  final String label;
  final String value;
  const _Stat(this.label, this.value, {super.key});

  @override
  Widget build(BuildContext context) => Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
        Text(label, style: Theme.of(context).textTheme.bodySmall),
        Text(value, style: Theme.of(context).textTheme.titleMedium, textDirection: TextDirection.ltr),
      ]);
}
