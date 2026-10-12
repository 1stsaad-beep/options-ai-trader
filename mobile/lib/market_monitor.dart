import 'dart:async';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'api.dart';

/// Native monitoring can only GET our server status. It cannot enable analysis.
class MarketMonitor {
  static const channel = MethodChannel('oat/market_monitor');
  static bool get supported => !kIsWeb && defaultTargetPlatform == TargetPlatform.android;
  static Future<Map<String, dynamic>> state([String method = 'status', Map<String, dynamic>? arguments]) async {
    if (!supported) return {'active': false, 'state': 'UNSUPPORTED'};
    try {
      final raw = await channel.invokeMapMethod<String, dynamic>(method, arguments);
      if (raw == null || raw['active'] is! bool || raw['state'] is! String ||
          (raw['active'] == true && raw['account'] is! String)) {
        throw const FormatException('Invalid monitor state');
      }
      return Map<String, dynamic>.from(raw);
    } on MissingPluginException {
      return {'active': false, 'state': 'UNSUPPORTED'};
    }
  }
  static Future<void> stopIfSupported() async { await state('stop'); }
}

String monitorLabel(String state) => const {
  'STOPPED': 'المراقبة متوقفة',
  'STARTING': 'طُلب بدء الخدمة؛ انتظار تأكيد Android',
  'CONNECTING': 'الخدمة بدأت؛ الاتصال بالخادم لم يُتحقق بعد',
  'API_REACHABLE': 'API متاح ونبض العامل حديث وقت آخر قراءة — لا يعني صلاحية الأسعار',
  'WORKER_UNAVAILABLE': 'API متاح؛ نبض العامل مفقود أو متأخر',
  'UNAVAILABLE': 'تعذر التحقق من حالة الخادم',
  'AUTH_REQUIRED': 'توقفت المراقبة: راجع مصادقة API',
  'SESSION_ENDED': 'انتهت جلسة الثلاثين دقيقة؛ يلزم بدء يدوي جديد',
  'SYSTEM_TIMEOUT': 'أوقف Android الخدمة بسبب حد التشغيل',
  'TASK_REMOVED': 'توقفت المراقبة عند إغلاق مهمة التطبيق',
  'START_FAILED': 'لم يسمح Android ببدء المراقبة',
  'NOTIFICATIONS_REQUIRED': 'يلزم السماح بالإشعارات وقناة المراقبة من إعدادات Android',
  'UNSUPPORTED': 'الخيار التجريبي متاح في نسخة Android فقط',
}[state] ?? 'حالة المراقبة غير معروفة؛ افتح التطبيق للتحقق';

class MarketMonitorScreen extends StatefulWidget {
  final TraderApi api;
  final String account;
  const MarketMonitorScreen({super.key, required this.api, required this.account});
  @override
  State<MarketMonitorScreen> createState() => _MarketMonitorScreenState();
}

class _MarketMonitorScreenState extends State<MarketMonitorScreen> with WidgetsBindingObserver {
  Map<String, dynamic>? state;
  String? error;
  bool busy = false, visible = true;
  Timer? timer;
  int generation = 0;
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    refresh();
    timer = Timer.periodic(const Duration(seconds: 2), (_) { if (visible && !busy) refresh(); });
  }
  @override
  void dispose() {
    timer?.cancel();
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }
  @override
  void didChangeAppLifecycleState(AppLifecycleState value) {
    visible = value == AppLifecycleState.resumed;
    if (visible) refresh();
  }
  Future<void> refresh() async {
    if (busy) return;
    final request = ++generation;
    try {
      final value = await MarketMonitor.state();
      if (mounted && generation == request) setState(() { state = value; });
    } catch (_) {
      if (mounted && generation == request) setState(() { state = null; error = 'تعذر التحقق من الخدمة؛ لا يُفترض أنها تعمل. يمكن محاولة إيقافها.'; });
    }
  }
  Future<void> start() async {
    if (busy) return;
    final accepted = await showDialog<bool>(context: context, builder: (context) => AlertDialog(
      title: const Text('بدء مراقبة تجريبية؟'),
      content: const Text('قراءة حالة حساب الخادم كل دقيقة لمدة تصل إلى 30 دقيقة مع إشعار ظاهر. قد يوقفها Android أو توفير الطاقة. لا تعمل عند إطفاء الهاتف، ولا تشغّل محرك السوق داخل الهاتف أو تفعّل تداولًا.'),
      actions: [TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('إلغاء')),
        TextButton(onPressed: () => Navigator.pop(context, true), child: const Text('بدء الجلسة'))],
    ));
    if (accepted != true || !mounted) return;
    generation++;
    setState(() { busy = true; error = null; });
    try {
      final allowed = await MarketMonitor.channel.invokeMethod<bool>('permission');
      if (allowed != true) {
        if (mounted) setState(() => error = 'لم تُمنح صلاحية الإشعارات؛ لم تبدأ جلسة المراقبة. راجع إعدادات Android.');
        return;
      }
      if (!mounted) return;
      final value = await MarketMonitor.state('start', {
        'baseUrl': widget.api.baseUrl, 'token': widget.api.token, 'account': widget.account,
      });
      if (mounted) setState(() { state = value; });
    } catch (_) {
      if (mounted) setState(() { state = null; error = 'لم يتأكد بدء الخدمة؛ لا إعادة تلقائية. افتح التطبيق وتحقق من HTTPS ورمز API والإشعارات.'; });
    } finally { if (mounted) setState(() => busy = false); }
  }
  Future<void> stop() async {
    setState(() { busy = true; error = null; });
    generation++;
    try {
      final value = await MarketMonitor.state('stop');
      if (mounted) setState(() => state = value);
    } catch (_) {
      if (mounted) setState(() => error = 'لم يتأكد الإيقاف؛ استخدم زر الإيقاف في إشعار Android أو أوقف التطبيق من إعدادات النظام.');
    } finally { if (mounted) setState(() => busy = false); }
  }
  @override
  Widget build(BuildContext context) {
    final enabled = state?['active'] == true || state?['state'] == 'STARTING';
    return Scaffold(appBar: AppBar(title: const Text('مراقبة Android التجريبية')),
      body: SafeArea(child: ListView(padding: const EdgeInsets.all(16), children: [
        Text('حساب الخادم المحدد: ${widget.account}'),
        const Text('هذه جلسة مراقبة للخادم؛ محرك السوق يبقى مستقلًا على Linux. لا حاجة لشراء خادم الآن.'),
        const SizedBox(height: 12),
        const Text('حتى 30 دقيقة • قراءة كل دقيقة • HTTPS فقط • لا تشغيل تلقائي عند الإقلاع'),
        const Text('تستمر محاولة المراقبة عند الانتقال إلى الشاشة الرئيسية. إزالة التطبيق من المهام أو إيقافه أو انقطاع الطاقة يوقفها. قد يؤخر توفير الطاقة القراءات؛ ليست ضمانًا للتنبيهات أو للعمل 24/7.'),
        const Text('لا يُحفظ رمز API على القرص، ولا تُدخل مفاتيح Alpaca هنا. الإشعار يعرض حالة الاتصال فقط؛ تفاصيل الأحداث تبقى في صندوق الخادم.'),
        const SizedBox(height: 12),
        Text(state == null ? 'حالة الخدمة غير متحققة' : monitorLabel(state!['state'] as String), key: const Key('monitor-state')),
        if (state?['account'] != null) Text('حساب جلسة المراقبة: ${state!['account']}'),
        if (error != null) Text(error!, key: const Key('monitor-error')),
        FilledButton(key: const Key('monitor-start'), onPressed: busy || enabled || !MarketMonitor.supported || state == null || state?['state'] == 'UNSUPPORTED' ? null : start,
          child: const Text('بدء مراقبة لمدة 30 دقيقة')),
        OutlinedButton(key: const Key('monitor-stop'), onPressed: busy || !MarketMonitor.supported ? null : stop,
          child: const Text('إيقاف مراقبة Android فقط')),
        const Text('إيقاف هذه الجلسة لا يوقف تحليل الحساب على الخادم. تحكم التحليل مستقل في شاشة خادم السوق.'),
      ])));
  }
}
