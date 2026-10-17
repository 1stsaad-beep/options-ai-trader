/// Per-account Paper balances and positions (read-only; no order controls).
library;

import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;

import 'broker_accounts_screen.dart' show brokerMessage;
import 'broker_adapter.dart';
import 'broker_models.dart';
import 'broker_portfolio.dart';
import 'broker_store.dart';
import 'live_gate.dart';

class BrokerPortfolioScreen extends StatefulWidget {
  final BrokerAccount account;
  final BrokerAccountRegistry registry;
  final http.Client? client;
  final DateTime Function()? clock;
  const BrokerPortfolioScreen({super.key, required this.account, required this.registry, this.client, this.clock});
  @override
  State<BrokerPortfolioScreen> createState() => _BrokerPortfolioScreenState();
}

class _BrokerPortfolioScreenState extends State<BrokerPortfolioScreen> {
  BrokerPortfolio? portfolio;
  String? error;
  bool loading = false;
  DateTime _now() => (widget.clock ?? DateTime.now)();

  @override
  void initState() {
    super.initState();
    _refresh();
  }

  Future<void> _refresh() async {
    if (loading) return;
    setState(() { loading = true; error = null; });
    try {
      final a = widget.account;
      final adapter = createPaperAdapter(a, await widget.registry.credentials(a.id), client: widget.client,
          onRefreshTokenRotated: (t) => widget.registry.updateSecret(a.id, 'refreshToken', t));
      final p = await loadPortfolio(a, adapter, clock: widget.clock);
      if (mounted) setState(() { portfolio = p; loading = false; });
    } on BrokerException catch (e) {
      _fail(e.code);
    } on BrokerStoreException catch (e) {
      _fail(e.code);
    } on LiveTradingDisabled catch (e) {
      _fail(e.message);
    } catch (_) {
      _fail('UNKNOWN');
    }
  }

  // Keep the previous observation visible but clearly marked; never merge it with failed data.
  void _fail(String code) {
    if (mounted) setState(() { error = brokerMessage(code); loading = false; });
  }

  String _time(DateTime t) {
    final l = t.toLocal();
    String two(int v) => v.toString().padLeft(2, '0');
    return '${l.year}-${two(l.month)}-${two(l.day)} ${two(l.hour)}:${two(l.minute)}:${two(l.second)}';
  }

  Widget _row(String label, String? value) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 2),
        child: Row(children: [Expanded(child: Text(label)), Text(value ?? '—', textDirection: TextDirection.ltr)]),
      );

  Color? _plColor(BuildContext context, String? v) {
    if (v == null) return null;
    if (v.startsWith('-')) return Theme.of(context).colorScheme.error;
    return RegExp(r'[1-9]').hasMatch(v) ? Colors.green.shade700 : null;
  }

  @override
  Widget build(BuildContext context) {
    final p = portfolio;
    final stale = p != null && (error != null || p.isStale(_now()));
    return Scaffold(
      appBar: AppBar(title: Text(widget.account.label), actions: [
        IconButton(tooltip: 'تحديث', onPressed: loading ? null : _refresh, icon: const Icon(Icons.refresh)),
      ]),
      body: RefreshIndicator(
        onRefresh: _refresh,
        child: ListView(padding: const EdgeInsets.all(12), children: [
          Card(child: ListTile(
            leading: const Icon(Icons.science_outlined),
            title: Text('Paper • ${widget.account.broker.title}'),
            subtitle: Text('${widget.account.broker.paperTitle}\nقراءة فقط — لا أوامر من هذه الصفحة. Live معطل.'),
            isThreeLine: true,
          )),
          if (loading) const LinearProgressIndicator(),
          if (error != null) Padding(padding: const EdgeInsets.all(8),
              child: Text(error!, key: const ValueKey('portfolio-error'),
                  style: TextStyle(color: Theme.of(context).colorScheme.error))),
          if (p == null && !loading && error == null) const Text('لا توجد بيانات بعد.'),
          if (p != null) ...[
            Card(child: Padding(padding: const EdgeInsets.all(12), child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text('الرصيد', style: Theme.of(context).textTheme.titleMedium),
                _row('رقم الحساب لدى الوسيط', p.snapshot.brokerAccountId),
                _row('العملة', p.snapshot.currency),
                _row('النقد', p.snapshot.cash),
                _row('قيمة الحساب', p.snapshot.equity),
                _row('القوة الشرائية', p.snapshot.buyingPower),
                _row('حالة الحساب', p.snapshot.status),
                const Divider(),
                Text('وقت الاستلام: ${_time(p.fetchedAt)}', key: const ValueKey('portfolio-fetched')),
                if (stale) Text('بيانات قديمة — حدّث قبل الاعتماد عليها.', key: const ValueKey('portfolio-stale'),
                    style: TextStyle(color: Theme.of(context).colorScheme.error)),
              ],
            ))),
            Padding(padding: const EdgeInsets.only(top: 8, bottom: 4),
                child: Text('المراكز (${p.positions.length})', style: Theme.of(context).textTheme.titleMedium)),
            if (p.positions.isEmpty) const Text('لا توجد مراكز مفتوحة.'),
            for (final pos in p.positions)
              Card(child: ListTile(
                title: Text(pos.symbol, textDirection: TextDirection.ltr),
                subtitle: Text('الكمية ${pos.quantity} • متوسط ${pos.averagePrice ?? '—'} • القيمة ${pos.marketValue ?? '—'}'),
                trailing: Text(pos.unrealizedPl ?? '—', textDirection: TextDirection.ltr,
                    style: TextStyle(color: _plColor(context, pos.unrealizedPl))),
              )),
          ],
        ]),
      ),
    );
  }
}
