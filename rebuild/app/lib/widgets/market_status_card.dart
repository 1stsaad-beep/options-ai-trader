import 'dart:async';

import 'package:flutter/material.dart';
import 'package:trader_core/trader_core.dart';

import '../services/app_controller.dart';

String _localHm(DateTime utc) {
  final l = utc.toLocal();
  return '${l.hour.toString().padLeft(2, '0')}:${l.minute.toString().padLeft(2, '0')}';
}

String _etDateTime(DateTime utc) {
  final w = NewYorkTime.wall(utc);
  const days = ['الاثنين', 'الثلاثاء', 'الأربعاء', 'الخميس', 'الجمعة', 'السبت', 'الأحد'];
  return '${days[w.weekday - 1]} ${NewYorkTime.dateKey(utc).substring(5)} ${NewYorkTime.hm(utc)} ET';
}

/// US market state (open / closed / pre / post), next open/close in New York
/// time and in the phone's time. Refreshes every 30 seconds.
class MarketStatusCard extends StatefulWidget {
  final AppController controller;
  final DateTime Function()? clock;
  const MarketStatusCard({super.key, required this.controller, this.clock});

  @override
  State<MarketStatusCard> createState() => _MarketStatusCardState();
}

class _MarketStatusCardState extends State<MarketStatusCard> {
  Timer? _timer;

  @override
  void initState() {
    super.initState();
    _timer = Timer.periodic(const Duration(seconds: 30), (_) {
      if (mounted) setState(() {});
    });
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return ListenableBuilder(
      listenable: widget.controller,
      builder: (context, _) {
        final now = widget.clock?.call() ?? DateTime.now().toUtc();
        final st = widget.controller.marketStatus(now: now);
        final cs = Theme.of(context).colorScheme;
        final color = switch (st.phase) {
          MarketPhase.open => const Color(0xFF16A34A),
          MarketPhase.preMarket || MarketPhase.postMarket => const Color(0xFFD97706),
          MarketPhase.closed => cs.error,
        };
        final next = st.isOpen
            ? 'يغلق ${_etDateTime(st.nextClose)} (بتوقيتك ${_localHm(st.nextClose)})'
            : 'يفتح ${_etDateTime(st.nextOpen)} (بتوقيتك ${_localHm(st.nextOpen)})';
        return Card(
          key: const Key('market-status'),
          child: Padding(
            padding: const EdgeInsets.all(12),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Row(children: [
                Icon(Icons.circle, size: 12, color: color),
                const SizedBox(width: 8),
                Text('السوق الأمريكي: ${st.phase.arabic}',
                    key: const Key('market-phase'), style: TextStyle(fontWeight: FontWeight.bold, color: color)),
                if (st.closedReasonAr != null) Text(' • ${st.closedReasonAr}'),
                if (st.today?.earlyClose == true) const Text(' • إغلاق مبكر 13:00 ET'),
              ]),
              const SizedBox(height: 4),
              Text(next, key: const Key('market-next')),
              const SizedBox(height: 2),
              Text(
                'الآن ${NewYorkTime.hm(now)} ET • التداول الآلي يرسل أوامر فقط بين 09:30 و16:00 ET'
                '${st.source == StatusSource.broker ? ' • مؤكد من ساعة الوسيط' : ' • حسب تقويم NYSE'}',
                style: Theme.of(context).textTheme.bodySmall,
              ),
              if (st.noteAr != null) Text(st.noteAr!, style: TextStyle(color: cs.error, fontSize: 12)),
            ]),
          ),
        );
      },
    );
  }
}
