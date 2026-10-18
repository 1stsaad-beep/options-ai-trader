import 'package:flutter/material.dart';
import 'package:trader_core/trader_core.dart';

import '../services/app_controller.dart';

/// Filters of the activity log.
enum CycleFilter {
  all('الكل'),
  decisions('قرارات تداول'),
  orders('فيها أوامر'),
  errors('أخطاء'),
  closed('السوق مغلق');

  final String arabic;
  const CycleFilter(this.arabic);
}

/// Arabic label for a [CycleSymbolNote.action].
String cycleActionArabic(String action) {
  if (action == 'analysed') return 'تحليل فقط';
  for (final a in JournalAction.values) {
    if (a.name == action) return a.arabic;
  }
  return action;
}

bool _isDecision(String action) =>
    action == JournalAction.entry.name || action == JournalAction.exit.name || action == JournalAction.scaleIn.name;

/// Pure filter used by the screen (and tests).
List<CycleRecord> filterCycles(List<CycleRecord> cycles, CycleFilter f, {String? symbol}) => [
      for (final c in cycles.reversed)
        if ((symbol == null || c.symbols.containsKey(symbol)) &&
            switch (f) {
              CycleFilter.all => true,
              CycleFilter.decisions => c.symbols.values.any((n) => _isDecision(n.action)),
              CycleFilter.orders => c.hasOrders || c.fills > 0,
              CycleFilter.errors => c.hasErrors,
              CycleFilter.closed => c.marketClosed,
            })
          c,
    ];

String _etTime(DateTime t) => '${NewYorkTime.dateKey(t)} ${NewYorkTime.hm(t)} ET';

/// Per-account activity log: every cycle with market state, scores, the
/// decision and its reason per symbol, orders, fills and errors.
class ActivityLogTab extends StatefulWidget {
  final AppController controller;
  final AccountRuntime rt;
  const ActivityLogTab({super.key, required this.controller, required this.rt});

  @override
  State<ActivityLogTab> createState() => _ActivityLogTabState();
}

class _ActivityLogTabState extends State<ActivityLogTab> {
  CycleFilter _filter = CycleFilter.all;
  String? _symbol;

  @override
  Widget build(BuildContext context) {
    final all = widget.rt.state.cycles;
    final symbols = {for (final c in all) ...c.symbols.keys}.toList()..sort();
    final list = filterCycles(all, _filter, symbol: _symbol);
    return Column(children: [
      SingleChildScrollView(
        scrollDirection: Axis.horizontal,
        padding: const EdgeInsets.fromLTRB(8, 8, 8, 0),
        child: Row(children: [
          for (final f in CycleFilter.values)
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 3),
              child: ChoiceChip(
                key: Key('filter-${f.name}'),
                label: Text(f.arabic),
                selected: _filter == f,
                onSelected: (_) => setState(() => _filter = f),
              ),
            ),
          const SizedBox(width: 8),
          DropdownButton<String?>(
            key: const Key('filter-symbol'),
            value: symbols.contains(_symbol) ? _symbol : null,
            hint: const Text('كل الأسهم'),
            items: [
              const DropdownMenuItem<String?>(value: null, child: Text('كل الأسهم')),
              for (final s in symbols) DropdownMenuItem<String?>(value: s, child: Text(s)),
            ],
            onChanged: (s) => setState(() => _symbol = s),
          ),
        ]),
      ),
      Padding(
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
        child: Text('${list.length} من ${all.length} دورة محفوظة (آخر ${AccountState.maxCycles})',
            style: Theme.of(context).textTheme.bodySmall),
      ),
      Expanded(
        child: list.isEmpty
            ? const Center(child: Text('لا توجد دورات مطابقة'))
            : ListView.builder(
                itemCount: list.length,
                itemBuilder: (context, i) => _CycleTile(c: list[i], symbol: _symbol),
              ),
      ),
    ]);
  }
}

class _CycleTile extends StatelessWidget {
  final CycleRecord c;
  final String? symbol;
  const _CycleTile({required this.c, this.symbol});

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final notes = c.symbols.values.where((n) => symbol == null || n.symbol == symbol).toList();
    final decisions = notes.where((n) => _isDecision(n.action)).map((n) => '${cycleActionArabic(n.action)} ${n.symbol}');
    final IconData icon;
    final Color? color;
    if (c.hasErrors) {
      icon = Icons.error_outline;
      color = scheme.error;
    } else if (c.hasOrders) {
      icon = Icons.swap_horiz;
      color = scheme.primary;
    } else if (c.marketClosed) {
      icon = Icons.bedtime_outlined;
      color = null;
    } else {
      icon = Icons.radar;
      color = null;
    }
    final summary = [
      if (c.marketClosed) 'السوق مغلق',
      if (decisions.isNotEmpty) decisions.join('، ') else if (!c.marketClosed && notes.isNotEmpty) 'لا صفقة',
      if (c.orders.isNotEmpty) '${c.orders.length} أمر',
      if (c.fills > 0) '${c.fills} تنفيذ',
      if (c.errors.isNotEmpty) '${c.errors.length} خطأ',
      if (c.noteAr.isNotEmpty && !c.marketClosed) c.noteAr,
    ].join(' • ');
    return Card(
      margin: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
      child: ExpansionTile(
        key: Key('cycle-${c.cycle}'),
        leading: Icon(icon, color: color),
        title: Text('الدورة #${c.cycle} — ${_etTime(c.start)}'),
        subtitle: Text(summary.isEmpty ? '—' : summary, maxLines: 2, overflow: TextOverflow.ellipsis),
        childrenPadding: const EdgeInsets.fromLTRB(16, 0, 16, 12),
        expandedCrossAxisAlignment: CrossAxisAlignment.start,
        children: [
          _kv(context, 'حالة السوق', c.marketSummaryAr ?? (c.marketPhase == null ? 'محاكي (بدون قيود ساعات السوق)' : c.marketPhase!)),
          if (c.end != null) _kv(context, 'المدة', '${c.end!.difference(c.start).inMilliseconds / 1000} ث'),
          if (notes.isNotEmpty) ...[
            const SizedBox(height: 8),
            Text('التحليل والقرار لكل سهم', style: Theme.of(context).textTheme.labelLarge),
            for (final n in notes)
              Padding(
                padding: const EdgeInsets.symmetric(vertical: 4),
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text(
                      '${n.symbol} • النتيجة ${n.score?.toStringAsFixed(1) ?? '—'}'
                      '${n.bias == null ? '' : ' • ${Bias.values.byName(n.bias!).arabic}'} • القرار: ${cycleActionArabic(n.action)}',
                      style: const TextStyle(fontWeight: FontWeight.w600)),
                  if (n.reasonAr.isNotEmpty) SelectableText(n.reasonAr),
                ]),
              ),
          ],
          if (c.orders.isNotEmpty) ...[
            const SizedBox(height: 8),
            Text('الأوامر المرسلة', style: Theme.of(context).textTheme.labelLarge),
            for (final o in c.orders) SelectableText('• $o'),
          ],
          if (c.fills > 0) _kv(context, 'عمليات التنفيذ', '${c.fills}'),
          if (c.errors.isNotEmpty) ...[
            const SizedBox(height: 8),
            Text('الأخطاء', style: Theme.of(context).textTheme.labelLarge?.copyWith(color: scheme.error)),
            for (final e in c.errors) SelectableText('• $e', style: TextStyle(color: scheme.error)),
          ],
          if (c.noteAr.isNotEmpty) _kv(context, 'ملاحظة', c.noteAr),
        ],
      ),
    );
  }

  Widget _kv(BuildContext context, String k, String v) => Padding(
        padding: const EdgeInsets.only(top: 4),
        child: Text.rich(TextSpan(children: [
          TextSpan(text: '$k: ', style: const TextStyle(fontWeight: FontWeight.w600)),
          TextSpan(text: v),
        ])),
      );
}
