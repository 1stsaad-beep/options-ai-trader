/// Per-account Paper balances and positions (read-only; no order controls).
library;

import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;

import 'broker_accounts_screen.dart' show brokerMessage;
import 'broker_adapter.dart';
import '../direct_alpaca.dart' show DirectAlpaca;
import 'broker_models.dart';
import 'broker_options.dart';
import 'broker_order_admission.dart';
import 'broker_order_journal.dart';
import 'broker_order_service.dart';
import 'option_eligibility.dart';
import 'broker_order_ticket.dart';
import 'broker_portfolio.dart';
import 'broker_protective.dart';
import 'broker_store.dart';
import 'live_gate.dart';

class BrokerPortfolioScreen extends StatefulWidget {
  final BrokerAccount account;
  final BrokerAccountRegistry registry;
  final http.Client? client;
  final DateTime Function()? clock;
  final BrokerOrderService? orderService;
  const BrokerPortfolioScreen({super.key, required this.account, required this.registry, this.client, this.clock,
      this.orderService});
  @override
  State<BrokerPortfolioScreen> createState() => _BrokerPortfolioScreenState();
}

class _BrokerPortfolioScreenState extends State<BrokerPortfolioScreen> {
  BrokerPortfolio? portfolio;
  List<BrokerOrderRecord> orders = const [];
  late final BrokerOrderService service = widget.orderService ?? BrokerOrderService(widget.registry,
      client: widget.client, clock: widget.clock, directQuote: (c) => DirectAlpaca().quote(c),
      underlyingQuote: (u) async => UnderlyingQuote.fromDirect(await DirectAlpaca().stockQuote(u)));
  String? error;
  bool loading = false;
  Map<String, ProtectiveStatus> protective = const {};
  ProtectivePolicy protectivePolicy = const ProtectivePolicy();
  late final BrokerProtectiveTracker tracker = BrokerProtectiveTracker(widget.registry.storage, widget.account.id, clock: _now);
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
      final o = await service.journal(a).orders();
      var prot = protective, pol = protectivePolicy;
      try {
        prot = {for (final s in await tracker.observe(a.broker, p.positions)) s.contract: s};
        pol = await tracker.policy();
      } catch (_) {
        prot = const {}; // monitoring unavailable; never blocks viewing or manual closes
      }
      if (mounted) setState(() { portfolio = p; orders = o; protective = prot; protectivePolicy = pol; loading = false; });
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

  Future<void> _ticket({String? contract, TicketSide side = TicketSide.buyToOpen, int? quantity, String? conid}) async {
    final out = await showDialog<BrokerOrderOutcome>(context: context, builder: (_) => BrokerOrderTicketDialog(
        account: widget.account, service: service, initialContract: contract, initialSide: side,
        initialQuantity: quantity, initialConid: conid));
    if (out != null && mounted) {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(
          'أمر Paper ${out.clientOrderId}: ${stateLabel(out.state)}${out.code == null ? '' : ' (${out.code})'}')));
    }
    if (out != null) await _refresh();
  }

  String? reconcileSummary;

  Future<void> _reconcile() async {
    setState(() { loading = true; reconcileSummary = null; });
    try {
      final r = await service.reconcile(widget.account);
      final o = await service.journal(widget.account).orders();
      if (mounted) {
        setState(() { orders = o; loading = false;
          reconcileSummary = 'فُحص ${r.checked} • حُدّث ${r.updated} • تنفيذات ${r.fills}'
              '${r.stillUnresolved.isEmpty ? '' : ' • غير محسوم ${r.stillUnresolved.length}'}'
              '${r.discrepancies.isEmpty ? '' : '\nفروقات: ${r.discrepancies.join(', ')}'}'; });
      }
    } on BrokerException catch (e) {
      _fail(e.code);
    } catch (e) {
      _fail(RegExp(r'\(([A-Z0-9_]+)\)').firstMatch('$e')?.group(1) ?? 'UNKNOWN');
    }
  }

  Future<void> _resolve(BrokerOrderRecord o) async {
    final ok = await showDialog<bool>(context: context, builder: (c) => AlertDialog(
      title: const Text('حسم الأمر يدويًا كـ «لم يُرسل»؟'),
      content: Text('افعل ذلك فقط بعد التأكد من تطبيق الوسيط أن الأمر ${o.contract} غير موجود. يُسجل القرار ولا يُحذف أي سجل.'),
      actions: [
        TextButton(onPressed: () => Navigator.pop(c, false), child: const Text('إلغاء')),
        FilledButton(key: const ValueKey('confirm-resolve'), onPressed: () => Navigator.pop(c, true), child: const Text('تأكيد')),
      ]));
    if (ok != true) return;
    try {
      await service.resolveManually(widget.account, o.clientOrderId, 'checked broker app');
    } catch (e) {
      _fail(RegExp(r'\(([A-Z0-9_]+)\)').firstMatch('$e')?.group(1) ?? 'UNKNOWN');
      return;
    }
    final list = await service.journal(widget.account).orders();
    if (mounted) setState(() => orders = list);
  }

  static const _exitLabels = {'STOP_LOSS': 'وقف خسارة', 'TAKE_PROFIT': 'جني ربح', 'TRAILING_STOP': 'وقف متحرك'};
  String _exitText(ProtectiveStatus? s) => s?.exit == null ? '' : '\n⚠ اقتراح إغلاق: ${_exitLabels[s!.exit]} (اضغط مطولًا)';

  Future<void> _editPolicy() async {
    final c = [protectivePolicy.stopPercent, protectivePolicy.takePercent, protectivePolicy.trailPercent]
        .map((v) => TextEditingController(text: '$v')).toList();
    final ok = await showDialog<bool>(context: context, builder: (ctx) => AlertDialog(
      title: const Text('حدود الحماية'),
      content: Column(mainAxisSize: MainAxisSize.min, children: [
        for (final (i, label) in ['وقف الخسارة %', 'جني الربح %', 'وقف متحرك % (0 = إيقاف)'].indexed)
          TextField(key: ValueKey('protective-$i'), controller: c[i], keyboardType: TextInputType.number,
              decoration: InputDecoration(labelText: label)),
      ]),
      actions: [
        TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('إلغاء')),
        FilledButton(key: const ValueKey('save-protective'), onPressed: () => Navigator.pop(ctx, true), child: const Text('حفظ')),
      ]));
    if (ok != true) return;
    final v = c.map((x) => int.tryParse(x.text.trim()) ?? -1).toList();
    final p = ProtectivePolicy(stopPercent: v[0], takePercent: v[1], trailPercent: v[2]);
    if (!p.valid) { _fail('INVALID_POLICY'); return; }
    await tracker.setPolicy(p);
    if (mounted) setState(() => protectivePolicy = p);
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
            Row(children: [
              Expanded(child: Text('حماية: SL ${protectivePolicy.stopPercent}% • TP ${protectivePolicy.takePercent}% • '
                  'Trailing ${protectivePolicy.trailPercent}% (اقتراح فقط، الإرسال بتأكيدك)', key: const ValueKey('protective-policy'))),
              IconButton(key: const ValueKey('edit-protective'), tooltip: 'تعديل الحماية', onPressed: loading ? null : _editPolicy,
                  icon: const Icon(Icons.shield_outlined)),
            ]),
            Padding(padding: const EdgeInsets.only(top: 8, bottom: 4),
                child: Text('المراكز (${p.positions.length})', style: Theme.of(context).textTheme.titleMedium)),
            if (p.positions.isEmpty) const Text('لا توجد مراكز مفتوحة.'),
            for (final pos in p.positions)
              Card(child: ListTile(
                onLongPress: positionOcc(widget.account.broker, pos) == null ? null : () => _ticket(
                    contract: positionOcc(widget.account.broker, pos), side: TicketSide.sellToClose,
                    quantity: (decimalCents(pos.quantity) ?? 0) ~/ 100, conid: pos.contractId),
                title: Text(pos.symbol, textDirection: TextDirection.ltr),
                subtitle: Text('الكمية ${pos.quantity} • متوسط ${pos.averagePrice ?? '—'} • القيمة ${pos.marketValue ?? '—'}'
                    '${_exitText(protective[positionOcc(widget.account.broker, pos)])}'),
                trailing: Text(pos.unrealizedPl ?? '—', textDirection: TextDirection.ltr,
                    style: TextStyle(color: _plColor(context, pos.unrealizedPl))),
              )),
            Padding(padding: const EdgeInsets.only(top: 12, bottom: 4), child: Row(children: [
              Expanded(child: Text('أوامر Paper (${orders.length})', style: Theme.of(context).textTheme.titleMedium)),
              FilledButton.tonalIcon(key: const ValueKey('new-paper-order'), onPressed: loading ? null : () => _ticket(),
                  icon: const Icon(Icons.add_shopping_cart), label: const Text('أمر Paper')),
            ])),
            Row(children: [
              const Expanded(child: Text('اضغط مطولًا على مركز لفتح أمر إغلاق.')),
              TextButton.icon(key: const ValueKey('reconcile-orders'), onPressed: loading ? null : _reconcile,
                  icon: const Icon(Icons.sync), label: const Text('مطابقة الأوامر')),
            ]),
            if (reconcileSummary != null) Text(reconcileSummary!, key: const ValueKey('reconcile-summary')),
            for (final o in orders.reversed)
              Card(child: ListTile(
                title: Text('${o.side == 'BUY_TO_OPEN' ? 'شراء' : 'بيع'} ${o.quantity} × ${o.contract}', textDirection: TextDirection.ltr),
                subtitle: Text('${stateLabel(o.state)} • منفذ ${o.filledQuantity}/${o.quantity}'
                    '${o.brokerOrderId == null ? '' : ' • #${o.brokerOrderId}'}'),
                trailing: o.unresolved ? IconButton(tooltip: 'حسم يدوي', onPressed: () => _resolve(o),
                    icon: const Icon(Icons.rule)) : null,
              )),
          ],
        ]),
      ),
    );
  }
}
