import 'package:flutter/material.dart';
import 'package:trader_core/trader_core.dart';

import '../services/app_controller.dart';
import 'add_account_screen.dart';
import 'live_mode_screen.dart';
import 'settings_screen.dart';

class AccountDetailScreen extends StatelessWidget {
  final AppController controller;
  final String accountId;
  const AccountDetailScreen({super.key, required this.controller, required this.accountId});

  @override
  Widget build(BuildContext context) {
    return ListenableBuilder(
      listenable: controller,
      builder: (context, _) {
        final rt = controller.account(accountId);
        if (rt == null) return const Scaffold(body: Center(child: Text('الحساب غير موجود')));
        return DefaultTabController(
          length: 3,
          child: Scaffold(
            appBar: AppBar(
              title: Text(rt.profile.name),
              actions: [
                IconButton(
                  tooltip: 'الإعدادات',
                  icon: const Icon(Icons.tune),
                  onPressed: () => Navigator.push(context,
                      MaterialPageRoute(builder: (_) => SettingsScreen(controller: controller, accountId: accountId))),
                ),
                PopupMenuButton<String>(
                  onSelected: (v) => _menu(context, rt, v),
                  itemBuilder: (_) => const [
                    PopupMenuItem(value: 'cycle', child: Text('تشغيل دورة الآن')),
                    PopupMenuItem(value: 'keys', child: Text('تعديل المفاتيح')),
                    PopupMenuItem(value: 'live', child: Text('وضع التداول الحقيقي')),
                    PopupMenuItem(value: 'delete', child: Text('حذف الحساب')),
                  ],
                ),
              ],
              bottom: const TabBar(tabs: [Tab(text: 'نظرة عامة'), Tab(text: 'سجل القرارات'), Tab(text: 'الأداء')]),
            ),
            body: TabBarView(children: [
              _Overview(controller: controller, rt: rt),
              _JournalTab(rt: rt),
              _PerformanceTab(rt: rt),
            ]),
          ),
        );
      },
    );
  }

  Future<void> _menu(BuildContext context, AccountRuntime rt, String v) async {
    switch (v) {
      case 'cycle':
        final s = await controller.runCycle(rt.profile.id);
        if (context.mounted) {
          ScaffoldMessenger.of(context).showSnackBar(SnackBar(
              content: Text(s == null
                  ? 'تعذر تشغيل الدورة: ${rt.lastError ?? ''}'
                  : s.ran
                      ? 'اكتملت الدورة: ${s.ordersSubmitted} أوامر، ${s.errors} أخطاء'
                      : 'لم تعمل الدورة: ${s.noteAr}')));
        }
      case 'keys':
        await Navigator.push(context,
            MaterialPageRoute(builder: (_) => AddAccountScreen(controller: controller, editAccountId: rt.profile.id)));
      case 'live':
        await Navigator.push(
            context, MaterialPageRoute(builder: (_) => LiveModeScreen(controller: controller, accountId: rt.profile.id)));
      case 'delete':
        final ok = await showDialog<bool>(
          context: context,
          builder: (c) => AlertDialog(
            title: const Text('حذف الحساب؟'),
            content: const Text('سيُحذف الحساب ومفاتيحه وسجله من هذا الجهاز. لا يؤثر ذلك على حسابك لدى الوسيط.'),
            actions: [
              TextButton(onPressed: () => Navigator.pop(c, false), child: const Text('إلغاء')),
              FilledButton(onPressed: () => Navigator.pop(c, true), child: const Text('حذف')),
            ],
          ),
        );
        if (ok == true) {
          await controller.deleteAccount(rt.profile.id);
          if (context.mounted) Navigator.pop(context);
        }
    }
  }
}

class _Overview extends StatefulWidget {
  final AppController controller;
  final AccountRuntime rt;
  const _Overview({required this.controller, required this.rt});

  @override
  State<_Overview> createState() => _OverviewState();
}

class _OverviewState extends State<_Overview> {
  final _symbol = TextEditingController();

  @override
  void dispose() {
    _symbol.dispose();
    super.dispose();
  }

  Future<void> _addSymbol() async {
    final s = AccountProfile.normalizeSymbol(_symbol.text);
    if (!AccountProfile.symbolPattern.hasMatch(s)) {
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('رمز غير صالح')));
      return;
    }
    final p = widget.rt.profile;
    if (!p.watchlist.contains(s)) await widget.controller.updateProfile(p.copyWith(watchlist: [...p.watchlist, s]));
    _symbol.clear();
  }

  @override
  Widget build(BuildContext context) {
    final rt = widget.rt;
    final p = rt.profile;
    final snap = rt.snapshot;
    return RefreshIndicator(
      onRefresh: () => widget.controller.refresh(p.id),
      child: ListView(
        padding: const EdgeInsets.all(12),
        children: [
          Card(
            child: SwitchListTile(
              title: const Text('التداول الآلي'),
              subtitle: Text(p.enabled
                  ? 'مفعّل — يعمل كل دقيقة أثناء فتح التطبيق (${p.mode == TradingMode.paper ? 'Paper' : 'حقيقي'})'
                  : 'متوقف'),
              value: p.enabled,
              onChanged: (v) => widget.controller.updateProfile(p.copyWith(enabled: v)),
            ),
          ),
          if (rt.lastError != null)
            Card(
              color: Theme.of(context).colorScheme.errorContainer,
              child: Padding(padding: const EdgeInsets.all(12), child: Text(rt.lastError!)),
            ),
          Card(
            child: Padding(
              padding: const EdgeInsets.all(12),
              child: snap == null
                  ? const Text('لا توجد بيانات رصيد بعد — اسحب للتحديث')
                  : Wrap(spacing: 24, runSpacing: 8, children: [
                      _Stat('القيمة الكلية', formatUsd(snap.equityCents)),
                      _Stat('النقد', formatUsd(snap.cashCents)),
                      _Stat('القوة الشرائية', formatUsd(snap.buyingPowerCents)),
                    ]),
            ),
          ),
          const _SectionTitle('الأسهم المسموح تداولها'),
          Card(
            child: Padding(
              padding: const EdgeInsets.all(12),
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Wrap(spacing: 8, runSpacing: 4, children: [
                  for (final s in p.watchlist)
                    InputChip(
                      label: Text(s),
                      onDeleted: () => widget.controller
                          .updateProfile(p.copyWith(watchlist: p.watchlist.where((x) => x != s).toList())),
                    ),
                  if (p.watchlist.isEmpty) const Text('لن يفتح الحساب أي صفقة قبل إضافة أسهم'),
                ]),
                Row(children: [
                  Expanded(
                    child: TextField(
                      controller: _symbol,
                      textDirection: TextDirection.ltr,
                      textCapitalization: TextCapitalization.characters,
                      decoration: const InputDecoration(hintText: 'رمز السهم، مثل AAPL'),
                      onSubmitted: (_) => _addSymbol(),
                    ),
                  ),
                  IconButton(onPressed: _addSymbol, icon: const Icon(Icons.add)),
                ]),
              ]),
            ),
          ),
          const _SectionTitle('المراكز المفتوحة'),
          if (rt.positions.isEmpty)
            const Card(child: ListTile(title: Text('لا توجد مراكز')))
          else
            for (final pos in rt.positions)
              Card(
                child: ListTile(
                  title: Text('${pos.contract.underlying} ${pos.contract.right.arabic} ${pos.contract.strike.toStringAsFixed(2)}',
                      textDirection: TextDirection.rtl),
                  subtitle: Text(
                      'انتهاء ${pos.contract.expiry.toIso8601String().substring(0, 10)} • ${pos.quantity} عقد • تكلفة ${formatUsd(pos.averageCostCents)}'),
                ),
              ),
        ],
      ),
    );
  }
}

class _JournalTab extends StatelessWidget {
  final AccountRuntime rt;
  const _JournalTab({required this.rt});

  IconData _icon(JournalAction a) => switch (a) {
        JournalAction.entry => Icons.login,
        JournalAction.exit => Icons.logout,
        JournalAction.scaleIn => Icons.add_circle_outline,
        JournalAction.orderFilled => Icons.check_circle_outline,
        JournalAction.orderCancelled => Icons.cancel_outlined,
        JournalAction.blocked => Icons.block,
        JournalAction.error => Icons.error_outline,
        _ => Icons.info_outline,
      };

  @override
  Widget build(BuildContext context) {
    final entries = rt.state.journal.reversed.toList();
    if (entries.isEmpty) return const Center(child: Text('لا توجد قرارات بعد'));
    return ListView.builder(
      itemCount: entries.length,
      itemBuilder: (context, i) {
        final e = entries[i];
        final t = e.time.toLocal();
        return ExpansionTile(
          leading: Icon(_icon(e.action)),
          title: Text('${e.action.arabic}${e.symbol != null ? ' • ${e.symbol}' : ''}'),
          subtitle: Text(
              '${t.year}-${t.month.toString().padLeft(2, '0')}-${t.day.toString().padLeft(2, '0')} '
              '${t.hour.toString().padLeft(2, '0')}:${t.minute.toString().padLeft(2, '0')}',
              textDirection: TextDirection.ltr,
              textAlign: TextAlign.right),
          childrenPadding: const EdgeInsets.fromLTRB(16, 0, 16, 12),
          expandedCrossAxisAlignment: CrossAxisAlignment.start,
          children: [SelectableText(e.reasonAr)],
        );
      },
    );
  }
}

class _PerformanceTab extends StatelessWidget {
  final AccountRuntime rt;
  const _PerformanceTab({required this.rt});

  @override
  Widget build(BuildContext context) {
    final r = PerformanceReport.compute(rt.state.trades, rt.state.equityCurve,
        startingEquityCents: rt.profile.broker == BrokerKind.simulator ? rt.profile.startingCashCents : null);
    final trades = rt.state.trades.reversed.toList();
    return ListView(
      padding: const EdgeInsets.all(12),
      children: [
        Card(
          child: Padding(
            padding: const EdgeInsets.all(12),
            child: Wrap(spacing: 24, runSpacing: 12, children: [
              _Stat('الربح/الخسارة المحققة', formatUsd(r.realizedPnlCents)),
              _Stat('العائد الكلي', r.totalReturnPercent == null ? '—' : '${r.totalReturnPercent!.toStringAsFixed(2)}%'),
              _Stat('أقصى تراجع (Drawdown)', '${r.maxDrawdownPercent.toStringAsFixed(2)}%'),
              _Stat('عدد الصفقات', '${r.trades}'),
              _Stat('نسبة الربح', '${r.winRatePercent.toStringAsFixed(1)}%'),
              _Stat('معامل الربح', r.profitFactor.isInfinite ? '∞' : r.profitFactor.toStringAsFixed(2)),
              _Stat('أفضل صفقة', formatUsd(r.bestTradeCents)),
              _Stat('أسوأ صفقة', formatUsd(r.worstTradeCents)),
              _Stat('العمولات', formatUsd(r.feesCents)),
            ]),
          ),
        ),
        const _SectionTitle('الصفقات المغلقة'),
        if (trades.isEmpty) const Card(child: ListTile(title: Text('لا توجد صفقات مغلقة بعد'))),
        for (final t in trades)
          Card(
            child: ExpansionTile(
              title: Text('${t.underlying} ${t.right.arabic} • ${formatUsd(t.pnlCents)}'),
              subtitle: Text('${t.quantity} عقد • ${t.returnPercent.toStringAsFixed(1)}% • ${t.exitKind}'),
              childrenPadding: const EdgeInsets.fromLTRB(16, 0, 16, 12),
              expandedCrossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text('سبب الدخول:', style: Theme.of(context).textTheme.labelLarge),
                SelectableText(t.entryReasonAr),
                const SizedBox(height: 8),
                Text('سبب الخروج:', style: Theme.of(context).textTheme.labelLarge),
                SelectableText(t.exitReasonAr),
              ],
            ),
          ),
      ],
    );
  }
}

class _Stat extends StatelessWidget {
  final String label;
  final String value;
  const _Stat(this.label, this.value);

  @override
  Widget build(BuildContext context) => Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
        Text(label, style: Theme.of(context).textTheme.bodySmall),
        Text(value, style: Theme.of(context).textTheme.titleMedium, textDirection: TextDirection.ltr),
      ]);
}

class _SectionTitle extends StatelessWidget {
  final String text;
  const _SectionTitle(this.text);

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.fromLTRB(4, 16, 4, 6),
        child: Text(text, style: Theme.of(context).textTheme.titleSmall),
      );
}
