/// Paper order ticket: enter -> review (admission) -> explicit confirm -> send.
library;

import 'package:flutter/material.dart';

import 'broker_accounts_screen.dart' show brokerMessage;
import 'broker_models.dart';
import 'broker_options.dart';
import 'broker_order_admission.dart';
import 'option_eligibility.dart';
import 'broker_order_journal.dart';
import 'broker_order_service.dart';

String _fixed(Object? v, int digits) => v is num ? v.toStringAsFixed(digits) : '—';

/// Compact eligibility summary; Greeks are labeled as model values.
String eligibilityText(OptionEligibility e) {
  final f = e.facts, g = f['greeks'] is Map ? f['greeks'] as Map : const {};
  return [
    'Eligibility: ${e.eligible ? 'PASS' : 'FAIL'}',
    'OI ${f['openInterest'] ?? '—'} • spread ${f['spreadBps'] ?? '—'} bps',
    'model IV ${f['impliedVol'] is num ? '${((f['impliedVol'] as num) * 100).toStringAsFixed(1)}%' : '—'}'
        ' • Δ ${_fixed(g['delta'], 3)} • Γ ${_fixed(g['gamma'], 4)} • Θ/day ${_fixed(g['thetaPerDay'], 3)} • V/pt ${_fixed(g['vegaPerPoint'], 3)}',
    if (e.reasons.isNotEmpty) 'reasons: ${e.reasons.join(', ')}',
  ].join('\n');
}

String orderMessage(String code) => const {
      'PORTFOLIO_STALE': 'بيانات الحساب قديمة؛ أعد المراجعة.',
      'OPTION_NOT_ELIGIBLE': 'العقد غير مؤهل للدخول (شروط العقد/السيولة/اليونانيات). راجع الأسباب.',
      'UNRESOLVED_ORDER_RECONCILE_REQUIRED': 'يوجد أمر غير محسوم (لم يتأكد وصوله). طابق الأوامر أولًا.',
      'INVALID_CONTRACT': 'رمز العقد غير صالح (صيغة OCC مثل AAPL261120C00200000).',
      'INVALID_ORDER': 'الكمية أو السعر غير صالح.',
      'IBKR_CONID_REQUIRED': 'IBKR يتطلب رقم العقد conid.',
      'QUOTE_UNAVAILABLE': 'لا يوجد سعر مؤهل للعقد. لـ Alpaca شغّل جلسة Direct (OPRA) أولًا.',
      'QUOTE_MISMATCH': 'السعر المستلم لعقد مختلف.',
      'QUOTE_STALE': 'السعر أقدم من 30 ثانية.',
      'QUOTE_INVALID': 'السعر غير صالح.',
      'QUOTE_SPREAD_TOO_WIDE': 'الفارق بين العرض والطلب واسع (>20%).',
      'QUOTE_SIZE_INSUFFICIENT': 'الكمية المعروضة أقل من الكمية المطلوبة.',
      'LIMIT_OUTSIDE_QUOTE': 'سعر الحد خارج نطاق العرض/الطلب الحالي.',
      'CLOSE_EXCEEDS_POSITION': 'كمية الإغلاق أكبر من المركز المملوك.',
      'SHORT_OPTION_REVIEW_REQUIRED': 'يوجد مركز خيارات مكشوف؛ المراجعة مطلوبة ولا يُسمح بأوامر جديدة.',
      'OPPOSITE_DIRECTION_LOCK': 'قفل الاتجاه المعاكس: يوجد Call/Put معاكس على نفس السهم.',
      'BALANCE_UNAVAILABLE': 'الرصيد غير متاح من الوسيط.',
      'RISK_LIMIT': 'تجاوز حد مخاطر الصفقة أو النقد المتاح.',
      'ALLOCATION_RISK_LIMIT': 'تجاوز حد التخصيص الكلي.',
      'CONTRACT_COUNT_RISK_LIMIT': 'تجاوز الحد الأقصى لعدد العقود.',
      'POSITION_COUNT_RISK_LIMIT': 'تجاوز الحد الأقصى لعدد المراكز.',
      'DAILY_LOSS_RISK_LIMIT': 'بلغت الخسائر المفتوحة حد الخسارة اليومي.',
      'RISK_UNAVAILABLE_POSITION_MARK': 'قيمة أحد المراكز غير متاحة؛ لا يمكن حساب المخاطر.',
      'POSITION_UNREADABLE': 'تعذر قراءة كمية أحد المراكز.',
      'REVIEW_EXPIRED': 'انتهت صلاحية المراجعة؛ راجع الأمر من جديد.',
      'NOT_ADMITTED': 'الأمر غير مقبول.',
      'JOURNAL_FULL': 'سجل الأوامر ممتلئ؛ لا نحذف السجلات. لا أوامر جديدة.',
      'JOURNAL_CORRUPT': 'سجل الأوامر غير صالح؛ لم يُحذف ولم يُرسل أي أمر.',
      'JOURNAL_UNAVAILABLE': 'تعذرت قراءة سجل الأوامر.',
      'JOURNAL_WRITE_UNCONFIRMED': 'لم يتأكد حفظ سجل الأمر؛ راجع الأوامر قبل أي إرسال جديد.',
    }[code] ??
    (code.startsWith('SESSION_') ? 'خارج نافذة التداول المسموحة ($code).'
        : code.startsWith('EXPIRY_') ? 'حالة انتهاء العقد لا تسمح بهذا الأمر ($code).' : brokerMessage(code));

String stateLabel(String state) => const {
      OrderState.intent: 'محفوظ قبل الإرسال (غير محسوم)',
      OrderState.unknown: 'غير معروف — يلزم المطابقة',
      OrderState.rejected: 'مرفوض من الوسيط',
      OrderState.notPlaced: 'لم يُرسل',
      OrderState.confirmationRequired: 'لم يُنفذ — IBKR يطلب تأكيدًا (لا تأكيد آلي)',
      OrderState.open: 'مفتوح لدى الوسيط',
      OrderState.partiallyFilled: 'منفذ جزئيًا',
      OrderState.filled: 'منفذ',
      OrderState.canceled: 'ملغى',
      OrderState.expired: 'منتهي',
      OrderState.userResolvedNotPlaced: 'حُسم يدويًا: لم يُرسل (بعد مراجعة المستخدم)',
    }[state] ??
    state;

class BrokerOrderTicketDialog extends StatefulWidget {
  final BrokerAccount account;
  final BrokerOrderService service;
  final String? initialContract;
  final TicketSide initialSide;
  final int? initialQuantity;
  final String? initialConid;
  const BrokerOrderTicketDialog({super.key, required this.account, required this.service, this.initialContract,
      this.initialSide = TicketSide.buyToOpen, this.initialQuantity, this.initialConid});
  @override
  State<BrokerOrderTicketDialog> createState() => _BrokerOrderTicketDialogState();
}

class _BrokerOrderTicketDialogState extends State<BrokerOrderTicketDialog> {
  late final contract = TextEditingController(text: widget.initialContract ?? '');
  late final quantity = TextEditingController(text: '${widget.initialQuantity ?? 1}');
  final limit = TextEditingController();
  late final conid = TextEditingController(text: widget.initialConid ?? '');
  late TicketSide side = widget.initialSide;
  BrokerOrderReview? review;
  String? message;
  bool busy = false;

  @override
  void dispose() {
    for (final c in [contract, quantity, limit, conid]) { c.dispose(); }
    super.dispose();
  }

  BrokerOrderTicket? _ticket() {
    final q = int.tryParse(quantity.text.trim()), cents = decimalCents(limit.text.trim());
    if (q == null || cents == null) return null;
    return BrokerOrderTicket(contract: contract.text.trim().toUpperCase(), side: side, quantity: q, limitCents: cents,
        ibkrConid: widget.account.broker == BrokerKind.ibkr ? conid.text.trim() : null);
  }

  Future<void> _review() async {
    final t = _ticket();
    if (t == null) { setState(() => message = orderMessage('INVALID_ORDER')); return; }
    setState(() { busy = true; message = null; review = null; });
    try {
      final r = await widget.service.review(widget.account, t);
      if (mounted) {
        setState(() { review = r; busy = false;
          message = r.admission.admitted ? 'مقبول بعد الفحوص. يلزم تأكيدك للإرسال.' : orderMessage(r.admission.reason!); });
      }
    } on BrokerException catch (e) {
      if (mounted) setState(() { busy = false; message = orderMessage(e.code); });
    } catch (e) {
      if (mounted) setState(() { busy = false; message = orderMessage(_code(e)); });
    }
  }

  String _code(Object e) {
    final text = e.toString();
    final m = RegExp(r'\(([A-Z0-9_]+)\)').firstMatch(text);
    return m?.group(1) ?? 'UNKNOWN';
  }

  Future<void> _confirmAndSend() async {
    final r = review!;
    final t = r.ticket;
    final ok = await showDialog<bool>(context: context, builder: (c) => AlertDialog(
      title: const Text('تأكيد إرسال أمر Paper'),
      content: Text([
        '${widget.account.broker.paperTitle} • ${widget.account.label}',
        '${t.side == TicketSide.buyToOpen ? 'شراء لفتح' : 'بيع لإغلاق'} ${t.quantity} × ${t.contract}',
        'سعر حد ${centsText(t.limitCents)} • التكلفة التقديرية ${centsText(r.admission.costCents)} (رسوم ${centsText(r.admission.feeCents)})',
        'Paper فقط — لا أموال حقيقية. سيُعاد الفحص قبل الإرسال.',
      ].join('\n')),
      actions: [
        TextButton(onPressed: () => Navigator.pop(c, false), child: const Text('إلغاء')),
        FilledButton(key: const ValueKey('confirm-send'), onPressed: () => Navigator.pop(c, true), child: const Text('تأكيد وإرسال')),
      ]));
    if (ok != true || !mounted) return;
    setState(() { busy = true; message = 'جارٍ إعادة الفحص والإرسال…'; });
    try {
      final out = await widget.service.submit(r);
      if (mounted) Navigator.pop(context, out);
    } on BrokerException catch (e) {
      if (mounted) setState(() { busy = false; review = null; message = orderMessage(e.code); });
    } catch (e) {
      if (mounted) setState(() { busy = false; review = null; message = orderMessage(_code(e)); });
    }
  }

  @override
  Widget build(BuildContext context) {
    final r = review;
    return AlertDialog(
      title: Text('أمر Paper • ${widget.account.broker.title}'),
      content: SingleChildScrollView(child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
        SegmentedButton<TicketSide>(
          segments: const [
            ButtonSegment(value: TicketSide.buyToOpen, label: Text('شراء لفتح')),
            ButtonSegment(value: TicketSide.sellToClose, label: Text('بيع لإغلاق')),
          ],
          selected: {side},
          onSelectionChanged: busy ? null : (s) => setState(() { side = s.first; review = null; }),
        ),
        TextField(key: const ValueKey('ticket-contract'), controller: contract, textDirection: TextDirection.ltr,
            decoration: const InputDecoration(labelText: 'العقد (OCC)', hintText: 'AAPL261120C00200000'),
            onChanged: (_) => setState(() => review = null)),
        TextField(key: const ValueKey('ticket-quantity'), controller: quantity, keyboardType: TextInputType.number,
            decoration: const InputDecoration(labelText: 'الكمية (عقود)'), onChanged: (_) => setState(() => review = null)),
        TextField(key: const ValueKey('ticket-limit'), controller: limit, keyboardType: const TextInputType.numberWithOptions(decimal: true),
            decoration: const InputDecoration(labelText: 'سعر الحد (للعقد الواحد)'), onChanged: (_) => setState(() => review = null)),
        if (widget.account.broker == BrokerKind.ibkr)
          TextField(key: const ValueKey('ticket-conid'), controller: conid, keyboardType: TextInputType.number,
              decoration: const InputDecoration(labelText: 'IBKR conid'), onChanged: (_) => setState(() => review = null)),
        if (busy) const Padding(padding: EdgeInsets.only(top: 8), child: LinearProgressIndicator()),
        if (r?.quote != null) Padding(padding: const EdgeInsets.only(top: 8), child: Text(
            'السعر: عرض ${centsText(r!.quote!.bid)} / طلب ${centsText(r.quote!.ask)} • ${r.quote!.source} (${r.quote!.timeSource})',
            textDirection: TextDirection.ltr)),
        if (r?.eligibility != null) Padding(padding: const EdgeInsets.only(top: 8), child: Text(
            eligibilityText(r!.eligibility!), key: const ValueKey('ticket-eligibility'), textDirection: TextDirection.ltr)),
        if (r != null && r.admission.admitted)
          Text('التكلفة التقديرية ${centsText(r.admission.costCents)} • فحوص ناجحة: ${r.admission.passed.length}'),
        if (message != null) Padding(padding: const EdgeInsets.only(top: 8), child: Text(message!,
            key: const ValueKey('ticket-message'),
            style: TextStyle(color: r != null && r.admission.admitted ? null : Theme.of(context).colorScheme.error))),
      ])),
      actions: [
        TextButton(onPressed: busy ? null : () => Navigator.pop(context), child: const Text('إغلاق')),
        OutlinedButton(onPressed: busy ? null : _review, child: const Text('مراجعة')),
        FilledButton(onPressed: busy || r == null || !r.admission.admitted ? null : _confirmAndSend,
            child: const Text('إرسال…')),
      ],
    );
  }
}
