import 'package:flutter/material.dart';
import 'package:trader_core/trader_core.dart';

import '../services/app_controller.dart';
import 'chart_screen.dart';

/// Unrealised P/L of a position from a quote (mid when two-sided, else bid).
({int markCents, int pnlCents, double pnlPercent})? positionPnl(Position p, OptionQuote? q) {
  if (q == null) return null;
  final mark = q.isTwoSided ? q.midCents : q.bidCents;
  if (mark <= 0) return null;
  final pnl = (mark - p.averageCostCents) * p.quantity * p.contract.multiplier;
  final pct = p.averageCostCents == 0 ? 0.0 : (mark - p.averageCostCents) / p.averageCostCents * 100;
  return (markCents: mark, pnlCents: pnl, pnlPercent: pct);
}

/// Open positions with P/L, Greeks (when the broker provides them), the
/// entry reason, invalidation / target levels and a link to the chart.
class PositionsTab extends StatelessWidget {
  final AppController controller;
  final AccountRuntime rt;
  const PositionsTab({super.key, required this.controller, required this.rt});

  @override
  Widget build(BuildContext context) {
    final positions = rt.positions;
    var total = 0;
    var priced = 0;
    for (final p in positions) {
      final r = positionPnl(p, rt.quotes[p.contract.occSymbol]);
      if (r != null) {
        total += r.pnlCents;
        priced++;
      }
    }
    return RefreshIndicator(
      onRefresh: () => controller.refresh(rt.profile.id),
      child: ListView(
        padding: const EdgeInsets.all(12),
        children: [
          if (positions.isEmpty)
            const Card(child: ListTile(title: Text('لا توجد مراكز مفتوحة'), subtitle: Text('اسحب للتحديث')))
          else
            Card(
              child: ListTile(
                title: const Text('الربح/الخسارة غير المحققة'),
                subtitle: Text('${positions.length} مركز${priced < positions.length ? ' • ${positions.length - priced} بدون سعر حالي' : ''}'),
                trailing: Text(formatUsd(total),
                    textDirection: TextDirection.ltr,
                    style: Theme.of(context).textTheme.titleLarge?.copyWith(color: _pnlColor(context, total))),
              ),
            ),
          for (final p in positions)
            PositionCard(
              position: p,
              quote: rt.quotes[p.contract.occSymbol],
              meta: rt.state.metas[p.contract.occSymbol],
              onChart: () => Navigator.push(context,
                  MaterialPageRoute(builder: (_) => ChartScreen.forAccount(controller, rt.profile.id, p.contract.underlying))),
            ),
        ],
      ),
    );
  }
}

Color? _pnlColor(BuildContext context, int cents) =>
    cents > 0 ? Colors.green.shade700 : (cents < 0 ? Theme.of(context).colorScheme.error : null);

class PositionCard extends StatelessWidget {
  final Position position;
  final OptionQuote? quote;
  final PositionMeta? meta;
  final VoidCallback onChart;
  const PositionCard({super.key, required this.position, this.quote, this.meta, required this.onChart});

  @override
  Widget build(BuildContext context) {
    final p = position;
    final c = p.contract;
    final q = quote;
    final m = meta;
    final r = positionPnl(p, q);
    final text = Theme.of(context).textTheme;
    final greeks = <String>[
      if (q?.delta != null) 'Δ دلتا ${q!.delta!.toStringAsFixed(2)}',
      if (q?.gamma != null) 'Γ جاما ${q!.gamma!.toStringAsFixed(3)}',
      if (q?.theta != null) 'Θ ثيتا ${q!.theta!.toStringAsFixed(3)}',
      if (q?.vega != null) 'ν فيغا ${q!.vega!.toStringAsFixed(3)}',
      if (q?.impliedVolatility != null) 'IV ${(q!.impliedVolatility! * 100).toStringAsFixed(1)}%',
    ];
    return Card(
      key: Key('position-${c.occSymbol}'),
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            Expanded(
              child: Text('${c.underlying} ${c.right.arabic} ${c.strike.toStringAsFixed(2)}', style: text.titleMedium),
            ),
            if (r != null)
              Text('${formatUsd(r.pnlCents)} (${r.pnlPercent >= 0 ? '+' : ''}${r.pnlPercent.toStringAsFixed(1)}%)',
                  textDirection: TextDirection.ltr,
                  style: text.titleMedium?.copyWith(color: _pnlColor(context, r.pnlCents))),
          ]),
          Text('انتهاء ${c.expiry.toIso8601String().substring(0, 10)} • ${p.quantity} عقد • متوسط التكلفة ${formatUsd(p.averageCostCents)}'
              '${r == null ? ' • لا يوجد سعر حالي' : ' • السعر الحالي ${formatUsd(r.markCents)}'}'),
          if (greeks.isNotEmpty) ...[
            const SizedBox(height: 4),
            Wrap(spacing: 12, children: [for (final g in greeks) Text(g, style: text.bodySmall)]),
          ] else
            Text('اليونانيات (Greeks) غير متاحة من الوسيط لهذا العقد', style: text.bodySmall),
          const Divider(),
          if (m == null)
            const Text('لا توجد بيانات دخول — المركز لم يفتحه التطبيق أو فُتح قبل هذه النسخة')
          else ...[
            Text('سبب الدخول (النتيجة ${m.entryScore.toStringAsFixed(1)} • ${_et(m.entryTime)}):', style: text.labelLarge),
            SelectableText(m.entryReasonAr),
            const SizedBox(height: 4),
            Text('مستوى الإبطال للسهم: ${m.underlyingInvalidation?.toStringAsFixed(2) ?? 'غير محدد'}'
                '   •   الهدف: ${m.underlyingTarget?.toStringAsFixed(2) ?? 'غير محدد'}'),
            if (m.partialTaken || m.scaleIns > 0)
              Text('${m.partialTaken ? 'تم جني ربح جزئي' : ''}${m.partialTaken && m.scaleIns > 0 ? ' • ' : ''}'
                  '${m.scaleIns > 0 ? 'تعزيزات: ${m.scaleIns}' : ''}'),
          ],
          Align(
            alignment: AlignmentDirectional.centerEnd,
            child: TextButton.icon(
              onPressed: onChart,
              icon: const Icon(Icons.candlestick_chart_outlined),
              label: Text('شارت ${c.underlying}'),
            ),
          ),
        ]),
      ),
    );
  }

  static String _et(DateTime t) => '${NewYorkTime.dateKey(t)} ${NewYorkTime.hm(t)} ET';
}
