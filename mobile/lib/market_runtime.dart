import 'dart:async';
import 'dart:convert';
import 'package:flutter/material.dart';
import 'api.dart';
import 'market_monitor.dart';

Map<String, dynamic> runtimeObject(dynamic raw) {
  if (raw is! Map || raw.keys.any((k) => k is! String)) {
    throw const FormatException('Invalid runtime object');
  }
  return Map<String, dynamic>.from(raw);
}

DateTime runtimeTime(dynamic raw) {
  if (raw is! String || !RegExp(r'(Z|[+-]\d\d:\d\d)$').hasMatch(raw)) {
    throw const FormatException('Timezone required');
  }
  return DateTime.parse(raw).toUtc();
}

void runtimeAuthority(Map<String, dynamic> value, {String? account, bool envelope = true}) {
  if ((envelope && value['schema_version'] != 1) ||
      (account != null && value['account_id'] != account) ||
      value['mode'] != 'real_market_virtual' || value['external_orders_enabled'] != false ||
      value['virtual_fills_enabled'] != false || value['new_risk_allowed'] != false ||
      value['stop_loss_execution_assumed'] != false) {
    throw const FormatException('Untrusted runtime authority/account');
  }
}

class RuntimeConfig {
  final int version;
  final bool enabled;
  final Map<String, bool> strategies;
  RuntimeConfig(this.version, this.enabled, this.strategies);
  factory RuntimeConfig.parse(dynamic raw) {
    final value = runtimeObject(raw), strategies = runtimeObject(runtimeObject(raw)['strategies']);
    if (value['version'] is! int || (value['version'] as int) < 0 || value['enabled'] is! bool ||
        strategies.length != 2 || !strategies.containsKey('breakout') || !strategies.containsKey('pullback') ||
        strategies.values.any((v) => v is! bool)) {
      throw const FormatException('Invalid runtime config');
    }
    return RuntimeConfig(value['version'] as int, value['enabled'] as bool, Map<String, bool>.from(strategies));
  }
}

class RuntimeStatus {
  final Map<String, dynamic> value;
  final RuntimeConfig config;
  final DateTime serverTime;
  final List<Map<String, dynamic>> latest;
  RuntimeStatus(this.value, this.config, this.serverTime, this.latest);
  factory RuntimeStatus.parse(dynamic raw, String account) {
    final value = runtimeObject(raw);
    runtimeAuthority(value, account: account);
    final at = runtimeTime(value['server_time']);
    if (value['state'] is! String || value['heartbeat_fresh'] is! bool || value['latest'] is! List) {
      throw const FormatException('Invalid runtime status');
    }
    if (value['collector'] != null) {
      final collector = runtimeObject(value['collector']);
      runtimeAuthority(collector, envelope: false);
      runtimeTime(collector['heartbeat_at']);
    }
    final archive = runtimeObject(value['archive']);
    for (final key in ['records', 'bytes', 'segments']) {
      if (archive[key] is! int || (archive[key] as int) < 0) throw const FormatException('Invalid archive counters');
    }
    final latest = <Map<String, dynamic>>[];
    final identities = <String>{};
    for (final raw in value['latest'] as List) {
      final row = runtimeObject(raw);
      if (row['symbol'] is! String || !RegExp(r'^[A-Z][A-Z0-9.]{0,9}$').hasMatch(row['symbol'] as String) ||
          !['stock_snapshot', 'stock_bars', 'option_chain'].contains(row['kind']) ||
          row['state_now'] is! String || row['observation_id'] is! String ||
          row['sha256'] is! String || !RegExp(r'^[a-f0-9]{64}$').hasMatch(row['sha256'] as String) ||
          row['feed'] != (row['kind'] == 'option_chain' ? 'indicative' : 'iex') ||
          !identities.add('${row['symbol']}:${row['kind']}')) {
        throw const FormatException('Invalid cached observation');
      }
      runtimeTime(row['recorded_at']); runtimeTime(row['captured_at']);
      if (row['price'] != null && (row['price'] is! num || !(row['price'] as num).isFinite ||
          (row['price'] as num) < 0 || row['kind'] != 'stock_snapshot' || row['market_time'] == null)) {
        throw const FormatException('Invalid market price');
      }
      if (row['market_time'] != null && runtimeTime(row['market_time']).isAfter(at)) {
        throw const FormatException('Future market price');
      }
      latest.add(row);
    }
    return RuntimeStatus(value, RuntimeConfig.parse(value['config']), at, latest);
  }
}

class RuntimeEvents {
  final List<Map<String, dynamic>> items;
  final String? nextBefore;
  RuntimeEvents(this.items, this.nextBefore);
  factory RuntimeEvents.parse(dynamic raw, String account) {
    final value = runtimeObject(raw);
    runtimeAuthority(value, account: account);
    runtimeTime(value['as_of']);
    if (value['items'] is! List || (value['next_before'] != null && value['next_before'] is! String) ||
        value['delivery'] != 'DURABLE_API_INBOX_ONLY') {
      throw const FormatException('Invalid event page');
    }
    final items = <Map<String, dynamic>>[];
    final ids = <String>{};
    for (final raw in value['items'] as List) {
      final item = runtimeObject(raw);
      runtimeAuthority(item, account: account, envelope: false);
      runtimeTime(item['created']);
      if (item['id'] is! String || !ids.add(item['id'] as String) || item['kind'] is! String ||
          item['sha256'] is! String || !RegExp(r'^[a-f0-9]{64}$').hasMatch(item['sha256'] as String)) {
        throw const FormatException('Invalid original event');
      }
      runtimeObject(item['detail']);
      if (item['acknowledged_at'] != null) {
        runtimeTime(item['acknowledged_at']);
      }
      items.add(item);
    }
    return RuntimeEvents(items, value['next_before'] as String?);
  }
}

String runtimeLabel(String state) => const {
  'DISABLED': 'مصدر البيانات غير مفعّل — يحتاج موافقة منفصلة على الخادم',
  'WORKER_UNAVAILABLE': 'العامل غير متاح أو نبضه قديم',
  'COLLECTING_ANALYSIS_ONLY': 'جمع وتحليل فقط — التنفيذ مقفل',
  'WAITING': 'العامل ينتظر موعد القراءة التالية',
  'NO_ACTIVE_DEMAND': 'لا حسابات مفعّلة للتحليل أو لا رموز مراقبة',
  'SESSION_CLOSED': 'جلسة السوق مغلقة أو التقويم غير متاح',
  'AUTH_BLOCKED': 'رفض مصادقة أو صلاحيات البيانات — مراجعة الخادم مطلوبة',
  'BACKOFF': 'تهدئة الاتصال قبل إعادة المحاولة',
  'DATA_UNAVAILABLE': 'انقطاع البيانات أو التخزين — لا تنفيذ مفترض',
  'DEMAND_LIMIT_REACHED': 'عدد الرموز يتجاوز حد الجامع الحالي',
  'FRESH_IEX_TRADE': 'صفقة IEX حديثة وقت قراءة الخادم',
  'FRESH_COMPLETED_BARS': 'شموع مكتملة حديثة وقت قراءة الخادم',
  'STALE_OR_FUTURE_DATA': 'بيانات غير صالحة للاعتماد الحالي',
  'INDICATIVE_OPTIONS_NOT_EXECUTABLE': 'خيارات إرشادية — غير صالحة للتنفيذ',
  'NO_VALID_TRADE': 'لا يوجد سعر صفقة صالح',
  'NO_COMPLETED_BARS': 'لا شموع مكتملة',
  'INCOMPLETE_OBSERVATION': 'نتيجة جزئية',
  'COLLECTOR_STATE': 'تغير حالة جامع البيانات',
  'CONFIG_CHANGED': 'تعديل إعدادات تحليل الحساب',
  'OBSERVATION_ANALYZED': 'مشاهدة وقرار تحليل محفوظان',
  'ACCOUNT_COLLECTION_BLOCKED': 'تعطل جمع بيانات الحساب',
}[state] ?? 'حالة الخادم: $state';

/// Own-backend cache/control only. No DemoStore/engine, provider endpoint or
/// financial order API is imported or called by this screen.
class MarketRuntimeScreen extends StatefulWidget {
  final TraderApi api;
  final List<Map<String, dynamic>> accounts;
  final String initialAccount;
  final Duration refreshInterval;
  const MarketRuntimeScreen({super.key, required this.api, required this.accounts,
    required this.initialAccount, this.refreshInterval = const Duration(seconds: 15)});
  @override
  State<MarketRuntimeScreen> createState() => _MarketRuntimeScreenState();
}

class _MarketRuntimeScreenState extends State<MarketRuntimeScreen> with WidgetsBindingObserver {
  late String account;
  RuntimeStatus? status;
  RuntimeEvents? events;
  String? error;
  String? notice;
  bool busy = false, active = true;
  int generation = 0;
  Timer? timer;
  DateTime? received;

  @override
  void initState() {
    super.initState(); account = widget.initialAccount;
    WidgetsBinding.instance.addObserver(this);
    if (widget.refreshInterval > Duration.zero) {
      timer = Timer.periodic(widget.refreshInterval, (_) { if (active && !busy) load(); });
    }
    load();
  }
  @override
  void dispose() { timer?.cancel(); WidgetsBinding.instance.removeObserver(this); super.dispose(); }
  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    active = state == AppLifecycleState.resumed;
    if (!active) {
      generation++;
      if (mounted) setState(() { status = null; events = null; busy = false; });
    } else { load(); }
  }

  String path(String id) => '/api/accounts/${Uri.encodeComponent(id)}/market-runtime';
  bool current(int request, String id) => mounted && generation == request && account == id;
  String message(Object e, {bool mutation = false}) {
    if (mutation) return 'لم تتأكد نتيجة الحفظ؛ لن يُعاد الطلب تلقائيًا. حدّث الحالة للتحقق قبل محاولة أخرى.';
    if (e is FormatException) return 'رفض استجابة لا تطابق الحساب أو عقد الخادم؛ لا بديل من Demo.';
    if (e is ApiException && e.status == 401) return 'تعذر توثيق اتصال الخادم؛ راجع رمز وصول API في إعدادات الاتصال.';
    return 'تعذر الاتصال بخادم السوق؛ الأسعار السابقة غير معتمدة. جرّب تحديث الحالة.';
  }

  Future<void> load({bool more = false}) async {
    final id = account, request = ++generation;
    final priorEvents = events;
    final cursor = more ? priorEvents?.nextBefore : null;
    setState(() { busy = true; error = null; if (!more) { status = null; events = null; } });
    try {
      final query = cursor == null ? '' : '?${Uri(queryParameters: {'before': cursor}).query}';
      final results = await Future.wait([
        widget.api.request('GET', '${path(id)}/status'),
        widget.api.request('GET', '${path(id)}/events$query'),
      ]);
      final nextStatus = RuntimeStatus.parse(results[0], id);
      var nextEvents = RuntimeEvents.parse(results[1], id);
      if (more && priorEvents != null) {
        final seen = priorEvents.items.map((i) => i['id']).toSet();
        nextEvents = RuntimeEvents([...priorEvents.items, ...nextEvents.items.where((e) => !seen.contains(e['id']))], nextEvents.nextBefore);
      }
      if (!current(request, id)) return;
      setState(() { status = nextStatus; events = nextEvents; received = DateTime.now().toUtc(); });
    } catch (e) {
      if (current(request, id)) setState(() { status = null; events = null; error = message(e); });
    } finally {
      if (current(request, id)) setState(() => busy = false);
    }
  }

  Future<void> configure({bool? enabled, String? strategy, bool? selected}) async {
    final config = status?.config;
    if (config == null || busy) return;
    final id = account, request = ++generation;
    final strategies = Map<String, bool>.from(config.strategies);
    if (strategy != null) strategies[strategy] = selected!;
    setState(() { busy = true; error = null; notice = null; });
    try {
      final raw = runtimeObject(await widget.api.request('PUT', '${path(id)}/config', {
        'expected_version': config.version, 'enabled': enabled ?? config.enabled, 'strategies': strategies,
      }));
      runtimeAuthority(raw, account: id);
      RuntimeConfig.parse(raw);
      if (!current(request, id)) return;
      setState(() => notice = 'حُفظ إعداد التحليل لهذا الحساب فقط. موافقة اتصال Alpaca والتنفيذ لم تتغير.');
      await load();
    } catch (e) {
      if (current(request, id)) setState(() { status = null; events = null; error = message(e, mutation: true); });
    } finally {
      if (current(request, id)) setState(() => busy = false);
    }
  }

  Future<void> acknowledge(String eventId) async {
    if (busy) return;
    final id = account, request = ++generation;
    setState(() { busy = true; error = null; });
    try {
      final result = runtimeObject(await widget.api.request('POST', '${path(id)}/events/${Uri.encodeComponent(eventId)}/ack'));
      runtimeAuthority(result, account: id);
      if (result['acknowledged'] != true) throw const FormatException('Ack not confirmed');
      if (current(request, id)) await load();
    } catch (e) {
      if (current(request, id)) setState(() { status = null; error = message(e, mutation: true); });
    } finally {
      if (current(request, id)) setState(() => busy = false);
    }
  }

  Widget timestampLine(String label, dynamic at) => Text('$label: ${at == null ? 'غير متاح' : runtimeTime(at).toIso8601String()} (UTC)', textDirection: TextDirection.ltr);

  @override
  Widget build(BuildContext context) {
    final data = status;
    return Scaffold(
      appBar: AppBar(title: const Text('خادم السوق'), actions: [
        if (MarketMonitor.supported) IconButton(tooltip: 'مراقبة Android التجريبية',
          onPressed: () => Navigator.push(context, MaterialPageRoute<void>(builder: (_) => MarketMonitorScreen(api: widget.api, account: account))),
          icon: const Icon(Icons.notifications_active_outlined)),
        IconButton(
        tooltip: 'تحديث حالة الخادم', onPressed: busy ? null : () => load(), icon: const Icon(Icons.refresh))]),
      body: SafeArea(child: ListView(padding: const EdgeInsets.all(12), children: [
        const Text('مراقبة وتحليل مستقلان عن Demo • تنفيذ الخيارات مقفل', style: TextStyle(fontWeight: FontWeight.bold)),
        const Text('استمرار المحرك مسؤولية الخادم. إغلاق الهاتف لا يوقفه. لا مفاتيح Alpaca داخل التطبيق.'),
        const SizedBox(height: 12),
        DropdownButtonFormField<String>(key: ValueKey('runtime-account-$account'), initialValue: account,
          isExpanded: true, decoration: const InputDecoration(labelText: 'حساب الخادم'),
          items: widget.accounts.map((a) => DropdownMenuItem<String>(value: '${a['id'] ?? a['account_id']}',
            child: Text('${a['name']}', overflow: TextOverflow.ellipsis))).toList(),
          onChanged: (id) async {
            if (id == null || id == account) return;
            try { await MarketMonitor.stopIfSupported(); }
            catch (_) { if (mounted) setState(() => notice = 'لم يتأكد إيقاف المراقبة الخلفية؛ أوقفها قبل تغيير الحساب.'); return; }
            if (!mounted) return;
            setState(() { account = id; notice = null; }); load();
          }),
        if (busy) const LinearProgressIndicator(),
        if (error != null) Semantics(liveRegion: true, child: Padding(padding: const EdgeInsets.all(12),
          child: Text(error!, key: const Key('runtime-error'), style: TextStyle(color: Theme.of(context).colorScheme.error)))),
        if (notice != null) Text(notice!),
        if (data != null) ...[
          Card(child: Padding(padding: const EdgeInsets.all(12), child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            const Text('اتصال API ناجح'),
            Text(runtimeLabel(data.value['state'] as String), key: const Key('runtime-worker-state')),
            Text(data.value['heartbeat_fresh'] == true ? 'نبض العامل حديث وقت الاستعلام' : 'نبض العامل مفقود أو متأخر'),
            timestampLine('وقت الخادم', data.value['server_time']),
            timestampLine('آخر قراءة للهاتف', received?.toIso8601String()),
            const Text('حداثة القراءة لا تعني صلاحية تنفيذ الخيارات. لا نفترض وقف خسارة عند غياب أسعار صالحة.'),
          ]))),
          SwitchListTile(key: const Key('runtime-enabled'), title: const Text('تحليل هذا الحساب على الخادم'),
            subtitle: const Text('لا يغيّر Demo أو المخاطر، ولا يمنح موافقة اتصال المزود'),
            value: data.config.enabled, onChanged: busy ? null : (v) => configure(enabled: v)),
          for (final name in ['breakout', 'pullback']) SwitchListTile(key: ValueKey('runtime-$name'),
            title: Text(name == 'breakout' ? 'استراتيجية الاختراق' : 'استراتيجية الارتداد'),
            value: data.config.strategies[name]!, onChanged: busy ? null : (v) => configure(strategy: name, selected: v)),
          Text('الأرشيف: ${data.value['archive']['records']} مشاهدة • ${data.value['archive']['segments']} مقطع • ${((data.value['archive']['bytes'] as int)/1048576).toStringAsFixed(2)} MiB'),
          const Text('السجلات محفوظة؛ مساحة القرص والنسخ الخارجية مسؤولية الخادم.'),
          const Divider(), const Text('الأسعار والمشاهدات المحفوظة', style: TextStyle(fontSize: 18)),
          if (data.latest.isEmpty) const Text('لا مشاهدات محفوظة لهذا الحساب. لم تُنشأ أسعار بديلة.'),
          for (final row in data.latest) Card(child: Padding(padding: const EdgeInsets.all(12),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text('${row['symbol']} • ${row['feed']}', textDirection: TextDirection.ltr),
              if (row['kind'] == 'stock_snapshot') Text('آخر صفقة IEX: ${row['price'] == null ? 'غير متاحة' : (row['price'] as num).toStringAsFixed(2)}', key: ValueKey('runtime-price-${row['symbol']}')),
              Text(runtimeLabel(row['state_now'] as String)),
              if (row['kind'] == 'stock_snapshot') timestampLine('وقت السعر', row['market_time']),
              timestampLine('وقت الالتقاط', row['captured_at']),
              timestampLine('وقت الحفظ', row['recorded_at']),
              const Text('IEX لا يمثل السوق الموحّد كله؛ خيارات indicative للمراقبة فقط.'),
            ]))),
        ],
        const Divider(), const Text('الأحداث والتنبيهات', style: TextStyle(fontSize: 18)),
        const Text('صندوق الخادم؛ ليس إشعار Push عند إغلاق الهاتف.'),
        if (events?.items.isEmpty == true) const Text('لا أحداث محفوظة.'),
        for (final event in events?.items ?? <Map<String, dynamic>>[]) Card(child: Padding(
          padding: const EdgeInsets.all(8), child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(runtimeLabel(event['kind'] as String)), timestampLine('وقت الحدث', event['created']),
            ExpansionTile(title: const Text('تفاصيل السجل الأصلي'), children: [
              SelectableText(const JsonEncoder.withIndent('  ').convert(event['detail']), textDirection: TextDirection.ltr),
              SelectableText('SHA-256: ${event['sha256']}', textDirection: TextDirection.ltr),
            ]),
            if (event['acknowledged_at'] == null) TextButton(onPressed: busy ? null : () => acknowledge(event['id'] as String),
              child: const Text('تمت القراءة')) else const Text('مقروء'),
          ]))),
        if (events?.nextBefore != null) OutlinedButton(onPressed: busy ? null : () => load(more: true), child: const Text('أحداث أقدم')),
      ])),
    );
  }
}
