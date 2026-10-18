import 'package:flutter/material.dart';
import 'package:trader_core/trader_core.dart';

import '../services/app_controller.dart';

/// Explicit, per-account approval for live trading. In this build the
/// compile-time switch is off, so the readiness list always contains a
/// blocking item and the approval button stays disabled.
class LiveModeScreen extends StatefulWidget {
  final AppController controller;
  final String accountId;
  const LiveModeScreen({super.key, required this.controller, required this.accountId});

  @override
  State<LiveModeScreen> createState() => _LiveModeScreenState();
}

class _LiveModeScreenState extends State<LiveModeScreen> {
  final _ack = TextEditingController();

  @override
  void dispose() {
    _ack.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final rt = widget.controller.account(widget.accountId)!;
    final issues = widget.controller.liveReadinessIssues(rt);
    final isLive = rt.profile.mode == TradingMode.live;
    return Scaffold(
      appBar: AppBar(title: const Text('التداول الحقيقي')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Text(isLive ? 'هذا الحساب في وضع التداول الحقيقي.' : 'هذا الحساب في وضع Paper (أموال وهمية).',
              style: Theme.of(context).textTheme.titleMedium),
          const SizedBox(height: 12),
          if (isLive)
            FilledButton(
              onPressed: () async {
                await widget.controller.updateProfile(
                    rt.profile.copyWith(mode: TradingMode.paper, enabled: false, clearLiveApproval: true));
                if (context.mounted) Navigator.pop(context);
              },
              child: const Text('العودة إلى Paper وإيقاف الحساب'),
            )
          else ...[
            const Text('شروط الجاهزية:'),
            const SizedBox(height: 8),
            if (issues.isEmpty) const ListTile(leading: Icon(Icons.check_circle), title: Text('كل الشروط متحققة')),
            for (final i in issues) ListTile(leading: const Icon(Icons.block), title: Text(i)),
            const SizedBox(height: 12),
            Text('للتفعيل اكتب الجملة التالية حرفيًا:\n«${LiveApproval.requiredAcknowledgement}»'),
            TextField(controller: _ack, enabled: issues.isEmpty),
            const SizedBox(height: 12),
            FilledButton(
              style: FilledButton.styleFrom(backgroundColor: Colors.red),
              onPressed: issues.isNotEmpty
                  ? null
                  : () async {
                      final approval = LiveApproval(
                          accountId: rt.profile.id, approvedAt: DateTime.now().toUtc(), acknowledgement: _ack.text);
                      if (!approval.isValid) {
                        ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('الجملة غير مطابقة')));
                        return;
                      }
                      await widget.controller.updateProfile(
                          rt.profile.copyWith(mode: TradingMode.live, enabled: false, liveApproval: approval));
                      if (context.mounted) Navigator.pop(context);
                    },
              child: const Text('تفعيل التداول الحقيقي لهذا الحساب'),
            ),
          ],
        ],
      ),
    );
  }
}
