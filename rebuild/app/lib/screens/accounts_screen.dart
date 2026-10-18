import 'package:flutter/material.dart';
import 'package:trader_core/trader_core.dart';

import '../services/app_controller.dart';
import 'account_detail_screen.dart';
import 'add_account_screen.dart';
import '../widgets/market_status_card.dart';
import '../widgets/safety_widgets.dart';

class AccountsScreen extends StatelessWidget {
  final AppController controller;
  const AccountsScreen({super.key, required this.controller});

  @override
  Widget build(BuildContext context) {
    return ListenableBuilder(
      listenable: controller,
      builder: (context, _) {
        final accounts = controller.accounts;
        return Scaffold(
          appBar: AppBar(
            title: const Text('الحسابات'),
            actions: [
              KillSwitchButton(controller: controller),
              IconButton(
                tooltip: 'تشغيل دورة الآن',
                icon: const Icon(Icons.play_circle_outline),
                onPressed: () => controller.runAllCycles(force: true),
              ),
            ],
          ),
          floatingActionButton: FloatingActionButton.extended(
            onPressed: () => Navigator.push(
                context, MaterialPageRoute(builder: (_) => AddAccountScreen(controller: controller))),
            icon: const Icon(Icons.add),
            label: const Text('إضافة حساب'),
          ),
          body: !controller.loaded
              ? const Center(child: CircularProgressIndicator())
              : accounts.isEmpty
                  ? Column(children: [
                      Padding(padding: const EdgeInsets.all(12), child: KillSwitchBanner(controller: controller)),
                      const Expanded(child: _EmptyState()),
                    ])
                  : RefreshIndicator(
                      onRefresh: controller.refreshAll,
                      child: ListView.separated(
                        padding: const EdgeInsets.fromLTRB(12, 12, 12, 96),
                        itemCount: accounts.length + 4,
                        separatorBuilder: (_, __) => const SizedBox(height: 8),
                        itemBuilder: (context, i) => switch (i) {
                          0 => KillSwitchBanner(controller: controller),
                          1 => MarketStatusCard(controller: controller),
                          2 => BackgroundCard(controller: controller),
                          3 => NotificationPrefsCard(controller: controller),
                          _ => _AccountCard(controller: controller, rt: accounts[i - 4]),
                        },
                      ),
                    ),
        );
      },
    );
  }
}

class _EmptyState extends StatelessWidget {
  const _EmptyState();

  @override
  Widget build(BuildContext context) => const Center(
        child: Padding(
          padding: EdgeInsets.all(32),
          child: Text(
            'لا توجد حسابات بعد.\nأضف حسابًا على المحاكي الداخلي للبدء بأموال وهمية، أو اربط حساب Paper لدى وسيطك.',
            textAlign: TextAlign.center,
          ),
        ),
      );
}

class _AccountCard extends StatelessWidget {
  final AppController controller;
  final AccountRuntime rt;
  const _AccountCard({required this.controller, required this.rt});

  @override
  Widget build(BuildContext context) {
    final p = rt.profile;
    final snap = rt.snapshot;
    final scheme = Theme.of(context).colorScheme;
    return Card(
      child: InkWell(
        borderRadius: BorderRadius.circular(12),
        onTap: () => Navigator.push(
            context, MaterialPageRoute(builder: (_) => AccountDetailScreen(controller: controller, accountId: p.id))),
        child: Padding(
          padding: const EdgeInsets.all(14),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(children: [
                Expanded(child: Text(p.name, style: Theme.of(context).textTheme.titleMedium)),
                _ModeChip(mode: p.mode),
                const SizedBox(width: 8),
                Switch(
                  value: p.enabled,
                  onChanged: (v) => controller.updateProfile(p.copyWith(enabled: v)),
                ),
              ]),
              Text('${p.broker.arabic} • ${p.watchlist.isEmpty ? 'لا توجد أسهم محددة' : p.watchlist.join('، ')}'),
              if (p.settings.pauseNewEntries)
                const Text('الدخول الجديد موقوف مؤقتًا — الخروج يعمل', style: TextStyle(fontWeight: FontWeight.w600)),
              const SizedBox(height: 6),
              if (snap != null)
                Text('القيمة: ${formatUsd(snap.equityCents)}   النقد: ${formatUsd(snap.cashCents)}   المراكز: ${rt.positions.length}'),
              if (rt.lastError != null)
                Padding(
                  padding: const EdgeInsets.only(top: 6),
                  child: Text(rt.lastError!, style: TextStyle(color: scheme.error), maxLines: 2, overflow: TextOverflow.ellipsis),
                ),
            ],
          ),
        ),
      ),
    );
  }
}

class _ModeChip extends StatelessWidget {
  final TradingMode mode;
  const _ModeChip({required this.mode});

  @override
  Widget build(BuildContext context) {
    final live = mode == TradingMode.live;
    return Chip(
      visualDensity: VisualDensity.compact,
      label: Text(live ? 'حقيقي' : 'Paper'),
      backgroundColor: live ? Colors.red.withAlpha(38) : Colors.teal.withAlpha(38),
    );
  }
}
