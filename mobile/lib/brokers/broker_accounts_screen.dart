/// Settings screen: add multiple Paper accounts per broker, test connections.
library;

import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;

import 'broker_adapter.dart';
import 'broker_models.dart';
import 'broker_portfolio_screen.dart';
import 'broker_store.dart';
import 'live_gate.dart';

String brokerMessage(String code) => const {
      'INVALID_KEYS': 'الحقول المطلوبة ناقصة أو بصيغة غير صحيحة (بدون مسافات).',
      'INVALID_SETTINGS': 'إعدادات الحساب غير صحيحة.',
      'INVALID_GATEWAY': 'عنوان Gateway يجب أن يبدأ بـ https:// دون مسار أو استعلام.',
      'NOT_PAPER_ACCOUNT': 'رقم حساب IBKR يجب أن يكون حساب Paper يبدأ بـ DU.',
      'IBKR_NOT_AUTHENTICATED': 'جلسة Client Portal غير مسجلة الدخول. سجّل الدخول بحساب Paper في Gateway ثم أعد الفحص.',
      'ACCOUNT_NOT_FOUND': 'الحساب المحدد غير موجود ضمن حسابات الوسيط.',
      'ACCOUNT_ARCHIVED': 'الحساب مؤرشف ولا يتصل.',
      'HTTP_401': 'HTTP 401: رفض الوسيط المصادقة. تحقق من المفاتيح.',
      'HTTP_403': 'HTTP 403: الصلاحيات لا تسمح بهذا الطلب.',
      'HTTP_404': 'HTTP 404: المسار أو الحساب غير موجود.',
      'HTTP_422': 'HTTP 422: رفض الوسيط الطلب لعدم صحته.',
      'HTTP_429': 'HTTP 429: تم بلوغ حد الطلبات؛ انتظر قبل المحاولة.',
      'TIMEOUT': 'انتهت مهلة الاتصال بالوسيط.',
      'NETWORK_ERROR': 'تعذر الوصول إلى الوسيط. تحقق من الإنترنت.',
      'TLS_ERROR': 'تعذر التحقق من شهادة HTTPS؛ لن نتجاوز التحقق.',
      'REDIRECT_REJECTED': 'رفضنا إعادة التوجيه حتى لا تُرسل المفاتيح إلى عنوان آخر.',
      'HOST_NOT_ALLOWED': 'العنوان خارج بيئة Paper المسموحة.',
      'INVALID_DATA': 'رد غير صالح من الوسيط.',
      'KEY_SAVE_FAILED': 'لم يتأكد الحفظ في المخزن المشفر؛ أعد المحاولة.',
      'KEYSTORE_UNAVAILABLE': 'تعذرت قراءة المخزن المشفر (Android Keystore).',
      'STORE_CORRUPT': 'بيانات الحسابات المحفوظة غير صالحة؛ لم تُحذف.',
      'TOO_MANY_ACCOUNTS': 'بلغت الحد الأقصى لحسابات هذا الوسيط.',
      'LIVE_NOT_APPROVED': 'التداول الحقيقي (Live) معطل ولا يمكن تفعيله من التطبيق.',
      'LIVE_NOT_IMPLEMENTED': 'التداول الحقيقي (Live) غير متاح في هذا الإصدار.',
    }[code] ??
    'تعذر تنفيذ العملية ($code).';

class BrokerAccountsScreen extends StatefulWidget {
  final BrokerAccountRegistry? registry;
  final http.Client? client;
  const BrokerAccountsScreen({super.key, this.registry, this.client});
  @override
  State<BrokerAccountsScreen> createState() => _BrokerAccountsScreenState();
}

class _BrokerAccountsScreenState extends State<BrokerAccountsScreen> {
  late final BrokerAccountRegistry registry =
      widget.registry ?? BrokerAccountRegistry(PlatformSecureKeyValue());
  List<BrokerAccount> accounts = const [];
  final Map<String, String> status = {};
  final Set<String> busy = {};
  String? error;
  bool loading = true;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final list = await registry.list();
      if (mounted) setState(() { accounts = list; error = null; loading = false; });
    } on BrokerStoreException catch (e) {
      if (mounted) setState(() { error = brokerMessage(e.code); loading = false; });
    }
  }

  Future<void> _test(BrokerAccount a) async {
    setState(() { busy.add(a.id); status[a.id] = 'جارٍ الفحص…'; });
    String result;
    try {
      final creds = await registry.credentials(a.id);
      final adapter = createPaperAdapter(a, creds, client: widget.client,
          onRefreshTokenRotated: (t) => registry.updateSecret(a.id, 'refreshToken', t));
      final s = await adapter.connect();
      result = 'متصل (Paper) • ${s.brokerAccountId} • نقد ${s.cash ?? '—'} • قيمة ${s.equity ?? '—'} ${s.currency}';
    } on BrokerException catch (e) {
      result = brokerMessage(e.code);
    } on BrokerStoreException catch (e) {
      result = brokerMessage(e.code);
    } on LiveTradingDisabled catch (e) {
      result = brokerMessage(e.message);
    } catch (_) {
      result = brokerMessage('UNKNOWN');
    }
    if (mounted) setState(() { busy.remove(a.id); status[a.id] = result; });
  }

  Future<void> _add() async {
    final added = await showDialog<bool>(context: context, builder: (_) => _AddBrokerDialog(registry: registry));
    if (added == true) await _load();
  }

  Future<void> _archive(BrokerAccount a) async {
    final ok = await showDialog<bool>(context: context, builder: (c) => AlertDialog(
      title: const Text('أرشفة الحساب ونسيان المفاتيح؟'),
      content: const Text('يبقى سجل الحساب محفوظًا (مؤرشفًا) وتُحذف مفاتيحه فقط من المخزن المشفر.'),
      actions: [
        TextButton(onPressed: () => Navigator.pop(c, false), child: const Text('إلغاء')),
        FilledButton(onPressed: () => Navigator.pop(c, true), child: const Text('أرشفة')),
      ]));
    if (ok != true) return;
    try {
      await registry.forgetKeys(a.id);
    } on BrokerStoreException catch (e) {
      if (mounted) setState(() => status[a.id] = brokerMessage(e.code));
    }
    await _load();
  }

  @override
  Widget build(BuildContext context) {
    final active = accounts.where((a) => !a.archived).toList();
    final archived = accounts.length - active.length;
    return Scaffold(
      appBar: AppBar(title: const Text('حسابات الوسطاء (Paper)')),
      floatingActionButton: FloatingActionButton.extended(
          onPressed: loading ? null : _add, icon: const Icon(Icons.add), label: const Text('إضافة حساب')),
      body: loading
          ? const Center(child: CircularProgressIndicator())
          : ListView(padding: const EdgeInsets.fromLTRB(12, 12, 12, 96), children: [
              const Card(child: ListTile(
                leading: Icon(Icons.lock_outline),
                title: Text('وضع Paper فقط'),
                subtitle: Text('Live Trading معطل بشكل ثابت. المفاتيح محفوظة مشفرة على الهاتف (Android Keystore) ولا تُعرض أو تُرسل لغير الوسيط.'),
              )),
              SwitchListTile(value: LiveTradingGate.liveAvailable, onChanged: null,
                  title: const Text('Live Trading'), subtitle: const Text('معطل — يتطلب موافقة صريحة لاحقًا')),
              if (error != null) Padding(padding: const EdgeInsets.all(8), child: Text(error!,
                  style: TextStyle(color: Theme.of(context).colorScheme.error))),
              for (final kind in BrokerKind.values) ...[
                Padding(padding: const EdgeInsets.only(top: 12, bottom: 4),
                    child: Text(kind.paperTitle, style: Theme.of(context).textTheme.titleMedium)),
                if (!active.any((a) => a.broker == kind)) const Text('لا توجد حسابات.'),
                for (final a in active.where((a) => a.broker == kind))
                  Card(child: ListTile(
                    title: Text(a.label),
                    subtitle: Text([
                      for (final e in a.settings.entries) '${e.key}: ${e.value}',
                      status[a.id] ?? 'لم يُفحص الاتصال',
                    ].join('\n')),
                    isThreeLine: true,
                    onTap: () => Navigator.of(context).push(MaterialPageRoute<void>(builder: (_) =>
                        BrokerPortfolioScreen(account: a, registry: registry, client: widget.client))),
                    trailing: Wrap(spacing: 4, children: [
                      IconButton(tooltip: 'فحص الاتصال', onPressed: busy.contains(a.id) ? null : () => _test(a),
                          icon: const Icon(Icons.wifi_tethering)),
                      IconButton(tooltip: 'أرشفة', onPressed: () => _archive(a), icon: const Icon(Icons.archive_outlined)),
                    ]),
                  )),
              ],
              if (archived > 0) Padding(padding: const EdgeInsets.only(top: 12), child: Text('حسابات مؤرشفة محفوظة: $archived')),
            ]),
    );
  }
}

class _AddBrokerDialog extends StatefulWidget {
  final BrokerAccountRegistry registry;
  const _AddBrokerDialog({required this.registry});
  @override
  State<_AddBrokerDialog> createState() => _AddBrokerDialogState();
}

class _AddBrokerDialogState extends State<_AddBrokerDialog> {
  BrokerKind kind = BrokerKind.alpaca;
  final label = TextEditingController();
  final Map<String, TextEditingController> fields = {};
  String? error;
  bool saving = false;

  TextEditingController _field(String name) => fields.putIfAbsent(name, TextEditingController.new);

  @override
  void dispose() {
    label.dispose();
    for (final c in fields.values) { c.dispose(); }
    super.dispose();
  }

  Future<void> _save() async {
    setState(() { saving = true; error = null; });
    try {
      await widget.registry.add(broker: kind, label: label.text.trim().isEmpty ? kind.title : label.text,
          values: {for (final f in kind.fields) f.name: _field('${kind.name}.${f.name}').text});
      if (mounted) Navigator.pop(context, true);
    } on BrokerStoreException catch (e) {
      setState(() { error = brokerMessage(e.code); saving = false; });
    } on FormatException {
      setState(() { error = brokerMessage('INVALID_SETTINGS'); saving = false; });
    }
  }

  @override
  Widget build(BuildContext context) => AlertDialog(
        title: const Text('إضافة حساب Paper'),
        content: SingleChildScrollView(child: Column(mainAxisSize: MainAxisSize.min, children: [
          DropdownButtonFormField<BrokerKind>(
            initialValue: kind,
            decoration: const InputDecoration(labelText: 'الوسيط'),
            items: [for (final k in BrokerKind.values) DropdownMenuItem(value: k, child: Text(k.title))],
            onChanged: saving ? null : (k) => setState(() => kind = k!),
          ),
          TextField(controller: label, decoration: const InputDecoration(labelText: 'اسم الحساب')),
          for (final f in kind.fields)
            TextField(
              key: ValueKey('broker-field-${kind.name}-${f.name}'),
              controller: _field('${kind.name}.${f.name}'),
              obscureText: f.secret, autocorrect: false, enableSuggestions: false,
              decoration: InputDecoration(labelText: f.label, helperText: f.hint.isEmpty ? null : f.hint),
            ),
          if (error != null) Padding(padding: const EdgeInsets.only(top: 8),
              child: Text(error!, style: TextStyle(color: Theme.of(context).colorScheme.error))),
        ])),
        actions: [
          TextButton(onPressed: saving ? null : () => Navigator.pop(context, false), child: const Text('إلغاء')),
          FilledButton(onPressed: saving ? null : _save, child: const Text('حفظ مشفر')),
        ],
      );
}
