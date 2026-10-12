import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';

import 'api.dart';
import 'analysis_contract.dart';
import 'market_data.dart';
import 'demo/screen.dart';
import 'demo/store.dart';

void main() => runApp(const TraderApp());

class TraderApp extends StatefulWidget {
  final TraderApi? api;
  final DemoStore? demoStore;
  const TraderApp({super.key, this.api, this.demoStore});
  @override
  State<TraderApp> createState() => _TraderAppState();
}

class _TraderAppState extends State<TraderApp> {
  ThemeMode mode = ThemeMode.dark;
  @override
  Widget build(BuildContext context) => MaterialApp(
    title: 'Options AI Trader',
    locale: const Locale('ar'),
    supportedLocales: const [Locale('ar'), Locale('en')],
    localizationsDelegates: GlobalMaterialLocalizations.delegates,
    theme: ThemeData(useMaterial3: true, colorSchemeSeed: Colors.teal),
    darkTheme: ThemeData(
      useMaterial3: true,
      brightness: Brightness.dark,
      colorSchemeSeed: Colors.teal,
    ),
    themeMode: mode,
    home: Builder(
      builder: (context) => widget.api != null
          ? Dashboard(
              api: widget.api,
              themeMode: mode,
              onTheme: (value) => setState(() => mode = value),
            )
          : DemoScreen(
              store: widget.demoStore,
              onTheme: (value) {
                if (mode != value) setState(() => mode = value);
              },
              onBackend: () => Navigator.of(context).push(
                MaterialPageRoute<void>(
                  builder: (_) => Dashboard(
                    themeMode: mode,
                    onTheme: (value) => setState(() => mode = value),
                  ),
                ),
              ),
            ),
    ),
  );
}

class Dashboard extends StatefulWidget {
  final TraderApi? api;
  final ValueChanged<ThemeMode> onTheme;
  final ThemeMode themeMode;
  const Dashboard({
    super.key,
    this.api,
    required this.onTheme,
    required this.themeMode,
  });
  @override
  State<Dashboard> createState() => _DashboardState();
}

class _DashboardState extends State<Dashboard> {
  late final TraderApi api;
  final pages = const [
    'الرئيسية',
    'الحسابات وربط الوسطاء',
    'الفرص والتحليلات',
    'الصفقات والأوامر',
    'إعدادات المخاطر',
    'قائمة المراقبة',
    'التقارير والإحصاءات',
    'سجل القرارات',
    'الإشعارات والإيقاف الطارئ',
    'إعدادات الاستراتيجيات',
    'مختبر الأبحاث في الخادم',
  ];
  final icons = const [
    Icons.home_outlined,
    Icons.account_balance_outlined,
    Icons.radar,
    Icons.receipt_long,
    Icons.tune,
    Icons.visibility_outlined,
    Icons.bar_chart,
    Icons.history,
    Icons.stop_circle_outlined,
    Icons.auto_graph,
    Icons.science_outlined,
  ];
  List<Map<String, dynamic>> accounts = [];
  List<Map<String, dynamic>> rows = [];
  Map<String, dynamic> detail = {};
  String? accountId;
  String? error;
  int page = 0;
  bool loading = false;
  bool showPositions = false;
  final pendingOrderKeys = <String, String>{};
  List<Map<String, dynamic>> portfolio = [];
  final pendingFillKeys = <String, String>{};
  final automationResults = <String, Map<String, dynamic>>{};
  int generation = 0;
  String researchSymbol = 'NVDA';
  ResearchSnapshotList? researchSnapshots;
  ResearchReplay? researchReplay;
  String? selectedResearchSnapshot;
  String? researchNotice;

  @override
  void initState() {
    super.initState();
    api = widget.api ?? TraderApi();
    reloadAccounts();
  }

  @override
  void dispose() {
    if (widget.api == null) api.close();
    super.dispose();
  }

  String pathFor(String id) => '/api/accounts/${Uri.encodeComponent(id)}';
  String get accountPath => pathFor(accountId!);
  bool stillSelected(String id) {
    if (!mounted) return false;
    if (accountId == id) return true;
    setState(() => error = 'تغير الحساب؛ أعد فتح الإجراء للحساب المطلوب');
    return false;
  }

  String idOf(Map<String, dynamic> row) => '${row['id'] ?? row['account_id']}';

  Future<void> reloadAccounts() async {
    final requestId = ++generation;
    setState(() {
      loading = true;
      error = null;
    });
    try {
      final result = await api.list('/api/accounts');
      final ids = result.map((a) => a['id'] ?? a['account_id']).toList();
      if (ids.any((id) => id is! String || id.isEmpty) ||
          ids.toSet().length != ids.length) {
        throw const ApiException(
          'استجابة الحسابات تتضمن معرّفات غير صالحة أو مكررة',
        );
      }
      if (!mounted || requestId != generation) return;
      setState(() {
        accounts = result;
        if (!accounts.any((a) => idOf(a) == accountId)) {
          accountId = accounts.isEmpty ? null : idOf(accounts.first);
        }
      });
      await reload();
    } catch (e) {
      if (mounted && requestId == generation) {
        setState(() {
          error = '$e';
          loading = false;
        });
      }
    }
  }

  Future<void> reload() async {
    final requestId = ++generation;
    setState(() {
      loading = true;
      error = null;
      rows = [];
      detail = {};
      researchSnapshots = null;
      researchReplay = null;
      selectedResearchSnapshot = null;
      researchNotice = null;
    });
    try {
      List<Map<String, dynamic>> newRows = [];
      Map<String, dynamic> newDetail = {};
      if (page == 0) {
        final targets = List<Map<String, dynamic>>.from(accounts);
        final snapshots = await Future.wait(
          targets.map((a) async {
            final value = await api.request(
              'GET',
              '${pathFor(idOf(a))}/performance',
            );
            if (value is! Map ||
                value['realized_pnl_cents'] is! num ||
                value['source'] != 'synthetic_mock') {
              throw const ApiException(
                'بيانات الأداء غير مكتملة أو مصدرها غير مدعوم؛ الإجمالي غير متاح',
              );
            }
            return Map<String, dynamic>.from(value);
          }),
        );
        if (!mounted || requestId != generation) return;
        portfolio = snapshots;
      } else if (page == 1) {
        newRows = accounts;
      } else if (accountId != null) {
        final route = switch (page) {
          2 => '$accountPath/opportunities',
          3 => '$accountPath/${showPositions ? 'positions' : 'orders'}',
          5 => '$accountPath/watchlist',
          7 => '$accountPath/audit',
          _ => '$accountPath/performance',
        };
        if ([2, 3, 5, 7].contains(page)) {
          newRows = await api.list(route);
          if (page == 2) {
            newRows.sort(
              (a, b) => ((b['score'] as num?) ?? 0).compareTo(
                (a['score'] as num?) ?? 0,
              ),
            );
          }
        } else if (page == 4 || page == 9) {
          final value = await api.request('GET', '$accountPath/risk');
          newDetail = Map<String, dynamic>.from(value as Map);
        } else if (page == 10) {
          final selectedAccount = accountId!;
          final selectedSymbol = researchSymbol;
          final saved = await api.listResearchSnapshots(selectedAccount, selectedSymbol);
          if (!mounted || requestId != generation || accountId != selectedAccount ||
              researchSymbol != selectedSymbol) { return; }
          researchSnapshots = saved;
          final value = await api.inspectResearch(selectedAccount, selectedSymbol);
          if (!mounted || requestId != generation || accountId != selectedAccount ||
              researchSymbol != selectedSymbol) { return; }
          newDetail = value.data;
        } else if (page == 8) {
          newDetail = Map<String, dynamic>.from(
            await api.request('GET', '$accountPath/status') as Map,
          );
        } else {
          final value = await api.request('GET', route);
          newDetail = Map<String, dynamic>.from(value as Map);
        }
      }
      if (!mounted || requestId != generation) return;
      setState(() {
        rows = newRows;
        detail = newDetail;
        loading = false;
      });
    } catch (e) {
      if (mounted && requestId == generation) {
        setState(() {
          error = '$e';
          loading = false;
        });
      }
    }
  }

  bool researchRequestIsCurrent(int requestId, String account, String symbol) =>
      mounted && requestId == generation && page == 10 &&
      accountId == account && researchSymbol == symbol;

  Future<void> saveResearchSnapshot() async {
    if (loading || accountId == null) return;
    final account = accountId!, symbol = researchSymbol;
    final requestId = ++generation;
    setState(() { loading = true; error = null; researchNotice = null; });
    try {
      final saved = await api.saveResearchSnapshot(account, symbol);
      if (!researchRequestIsCurrent(requestId, account, symbol)) return;
      setState(() {
        detail = saved.workbench.data;
        researchReplay = null;
        selectedResearchSnapshot = saved.snapshotId;
        researchNotice = 'حُفظت لقطة البحث في الخادم: ${saved.snapshotId}';
      });
      try {
        final listing = await api.listResearchSnapshots(account, symbol);
        if (!researchRequestIsCurrent(requestId, account, symbol)) return;
        setState(() {
          researchSnapshots = listing;
          if (!listing.items.any((item) => item.snapshotId == saved.snapshotId)) {
            selectedResearchSnapshot = null;
          }
        });
      } catch (e) {
        if (!researchRequestIsCurrent(requestId, account, symbol)) return;
        setState(() {
          selectedResearchSnapshot = null;
          researchSnapshots = null;
          error = 'حُفظت اللقطة، لكن تعذر تحديث القائمة. $e';
        });
      }
    } catch (e) {
      if (!researchRequestIsCurrent(requestId, account, symbol)) return;
      setState(() => error = '$e — لم تُعد المحاولة تلقائيًا. حدّث القائمة للتحقق من الحفظ قبل إعادة الطلب.');
    } finally {
      if (researchRequestIsCurrent(requestId, account, symbol)) {
        setState(() => loading = false);
      }
    }
  }

  Future<void> replayResearchSnapshot() async {
    if (loading || accountId == null || selectedResearchSnapshot == null) return;
    final account = accountId!, symbol = researchSymbol;
    final snapshotId = selectedResearchSnapshot!;
    final requestId = ++generation;
    setState(() {
      loading = true; error = null; researchReplay = null;
      detail = {}; researchNotice = null;
    });
    try {
      final replay = await api.replayResearchSnapshot(account, symbol, snapshotId);
      if (!researchRequestIsCurrent(requestId, account, symbol) ||
          selectedResearchSnapshot != snapshotId) { return; }
      setState(() {
        researchReplay = replay;
        detail = replay.original.data;
        researchNotice = 'تُعرض بيانات القرار الأصلية المحفوظة؛ لم تُعَد صياغة الأسباب بعد القرار.';
      });
    } catch (e) {
      if (researchRequestIsCurrent(requestId, account, symbol)) {
        setState(() => error = '$e');
      }
    } finally {
      if (researchRequestIsCurrent(requestId, account, symbol)) {
        setState(() => loading = false);
      }
    }
  }

  Future<void> captureResearchObservation() async {
    if (loading || accountId == null || selectedResearchSnapshot == null) return;
    final account = accountId!, symbol = researchSymbol;
    final snapshotId = selectedResearchSnapshot!;
    final requestId = ++generation;
    setState(() {
      loading = true; error = null; researchNotice = null;
    });
    try {
      final observation = await api.captureResearchObservation(account, symbol, snapshotId);
      if (!researchRequestIsCurrent(requestId, account, symbol) ||
          selectedResearchSnapshot != snapshotId) { return; }
      setState(() {
        researchReplay = null;
        researchNotice = 'حُفظت ملاحظة اصطناعية عند ${observation.observedAt.toIso8601String()}. '
          'احفظ ملاحظة أخرى في دقيقة لاحقة ثم أعد عرض اللقطة. القرار الأصلي لم يتغير.';
      });
    } catch (e) {
      if (researchRequestIsCurrent(requestId, account, symbol)) {
        setState(() => error = '$e — لم تُعد المحاولة تلقائيًا. أعد عرض اللقطة للتحقق من النتيجة قبل أي طلب جديد.');
      }
    } finally {
      if (researchRequestIsCurrent(requestId, account, symbol)) {
        setState(() => loading = false);
      }
    }
  }

  Future<bool> mutate(String method, String path, [Object? body]) async {
    setState(() {
      loading = true;
      error = null;
    });
    try {
      await api.request(method, path, body);
      if (!mounted) return true;
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(const SnackBar(content: Text('تم حفظ التغيير في الخادم')));
      await reloadAccounts();
      return true;
    } catch (e) {
      if (mounted) {
        setState(() {
          error = '$e';
          loading = false;
        });
      }
      return false;
    }
  }

  Future<Map<String, String>?> form(
    String title,
    Map<String, String> fields, {
    Set<String> secret = const {},
  }) async {
    final controllers = {
      for (final key in fields.keys)
        key: TextEditingController(text: fields[key]),
    };
    final result = await showDialog<Map<String, String>>(
      context: context,
      builder: (context) => AlertDialog(
        title: Text(title),
        content: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              for (final e in controllers.entries)
                Padding(
                  padding: const EdgeInsets.only(bottom: 12),
                  child: TextField(
                    controller: e.value,
                    obscureText: secret.contains(e.key),
                    autocorrect: !secret.contains(e.key),
                    enableSuggestions: !secret.contains(e.key),
                    decoration: InputDecoration(labelText: e.key),
                  ),
                ),
            ],
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('إلغاء'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, {
              for (final e in controllers.entries) e.key: e.value.text.trim(),
            }),
            child: const Text('حفظ'),
          ),
        ],
      ),
    );
    // Dispose after the closing route has finished animating.
    await Future<void>.delayed(const Duration(milliseconds: 350));
    for (final c in controllers.values) {
      c.dispose();
    }
    return result;
  }

  Future<void> settings() async {
    final values = await form(
      'اتصال الخادم المحلي أو HTTPS',
      {'عنوان الخادم': api.baseUrl, 'رمز الوصول': api.token},
      secret: {'رمز الوصول'},
    );
    if (values == null || !mounted) return;
    api.baseUrl = values['عنوان الخادم']!;
    api.token = values['رمز الوصول']!;
    await reloadAccounts();
  }

  Future<void> createAccount() async {
    final values = await form('حساب محاكاة جديد — MockBroker', {
      'اسم الحساب': '',
    });
    if (values == null || !mounted) return;
    await mutate('POST', '/api/accounts', {
      'name': values['اسم الحساب'],
      'equity_cents': 1000000,
    });
  }

  Future<void> addSymbol() async {
    final target = accountId;
    if (target == null) return;
    final values = await form('إضافة رمز للمراقبة', {'رمز السهم': ''});
    if (values == null || !mounted) return;
    if (!stillSelected(target)) return;
    await mutate('POST', '${pathFor(target)}/watchlist', {
      'symbol': values['رمز السهم']!.toUpperCase(),
    });
  }

  Future<void> editRisk() async {
    final target = accountId;
    if (target == null) return;
    final dynamic r = detail['risk'] ?? detail;
    final values = await form('حدود الحساب (%)', {
      'مخاطرة الصفقة': '${r['trade_risk_pct'] ?? 1}',
      'الخسارة اليومية': '${r['daily_loss_pct'] ?? 3}',
      'إجمالي التخصيص': '${r['allocation_pct'] ?? 20}',
      'عدد العقود الأقصى': '${r['max_contracts'] ?? 5}',
      'مجموعة مخاطر مترابطة (اختياري)': '${r['risk_group'] ?? ''}',
      'حد تخصيص المجموعة %': '${r['group_allocation_pct'] ?? 30}',
      'حد خسارة المجموعة اليومية %': '${r['group_daily_loss_pct'] ?? 3}',
    });
    if (values == null || !mounted) return;
    final trade = int.tryParse(values['مخاطرة الصفقة']!);
    final loss = int.tryParse(values['الخسارة اليومية']!);
    final allocation = int.tryParse(values['إجمالي التخصيص']!);
    if (trade == null ||
        trade < 0 ||
        trade > 100 ||
        loss == null ||
        loss < 0 ||
        loss > 100 ||
        allocation == null ||
        allocation < 0 ||
        allocation > 100) {
      setState(
        () => error =
            'أدخل نسبًا صحيحة بين 0 و100؛ الصفر يقفل ميزانية الدخول ذات الصلة',
      );
      return;
    }
    if (!stillSelected(target)) return;
    final contracts = int.tryParse(values['عدد العقود الأقصى']!);
    if (contracts == null || contracts < 1) {
      setState(() => error = 'عدد العقود يجب أن يكون عددًا صحيحًا موجبًا');
      return;
    }
    final groupAllocation=int.tryParse(values['حد تخصيص المجموعة %']!),
      groupLoss=int.tryParse(values['حد خسارة المجموعة اليومية %']!);
    if(groupAllocation==null || groupLoss==null || groupAllocation<0 || groupAllocation>100 || groupLoss<0 || groupLoss>100) {
      setState(()=>error='حدود المجموعة بين 0 و100');return;
    }
    final elevated=trade>2 || loss>3 || allocation>30 || groupAllocation>30 || groupLoss>3 ||
      ((r['global_allocation_pct'] as int?)??30)>30 || ((r['global_daily_loss_pct'] as int?)??3)>3;
    if(elevated) {
      final approved=await showDialog<bool>(context:context,builder:(c)=>AlertDialog(
        title:const Text('تأكيد مخاطر مرتفعة'),content:const Text('قد تستنفد هذه الحدود رأس المال الاصطناعي. هل تقر بهذه النسب المحددة لهذا الحساب؟'),
        actions:[TextButton(onPressed:()=>Navigator.pop(c,false),child:const Text('إلغاء')),
          FilledButton(onPressed:()=>Navigator.pop(c,true),child:const Text('أقرّ بالمخاطر وأحفظ'))]));
      if(approved!=true || !stillSelected(target)) return;
    }
    await mutate('PUT', '${pathFor(target)}/risk', {
      if(elevated) 'elevated_risk_ack':true,
      'trade_risk_pct': trade,
      'daily_loss_pct': loss,
      'allocation_pct': allocation,
      'max_contracts': contracts,
      'risk_group': values['مجموعة مخاطر مترابطة (اختياري)']!.isEmpty
          ? null
          : values['مجموعة مخاطر مترابطة (اختياري)'],
      'group_allocation_pct': int.tryParse(values['حد تخصيص المجموعة %']!),
      'group_daily_loss_pct': int.tryParse(
        values['حد خسارة المجموعة اليومية %']!,
      ),
    });
  }

  Future<void> editStrategies() async {
    final target = accountId;
    if (target == null) return;
    final values = await form('استراتيجيات الحساب — محاكاة فقط', {
      'الاستراتيجيات (breakout,pullback)':
          (detail['strategies'] as List? ?? ['breakout', 'pullback']).join(','),
      'مدة الاحتفاظ (intraday/swing)': '${detail['holding'] ?? 'intraday'}',
      'وضع التشغيل (paper/shadow/analysis)': '${detail['mode'] ?? 'paper'}',
    });
    if (values == null || !stillSelected(target)) return;
    final strategies = values['الاستراتيجيات (breakout,pullback)']!
        .split(',')
        .map((s) => s.trim())
        .where((s) => s.isNotEmpty)
        .toList();
    final holding = values['مدة الاحتفاظ (intraday/swing)'];
    final mode = values['وضع التشغيل (paper/shadow/analysis)'];
    if (strategies.any((s) => !['breakout', 'pullback'].contains(s)) ||
        !['intraday', 'swing'].contains(holding) ||
        !['paper', 'shadow', 'analysis'].contains(mode)) {
      setState(() => error = 'اختر القيم المدعومة فقط؛ Live مقفل');
      return;
    }
    await mutate('PUT', '${pathFor(target)}/risk', {
      'strategies': strategies,
      'holding': holding,
      'mode': mode,
    });
  }

  Future<void> editAutomation() async {
    final target = accountId;
    if (target == null) return;
    final maxContracts = detail['max_contracts'] is int
        ? detail['max_contracts'] as int
        : 5;
    final values = await form('قواعد التنفيذ والخروج — MockBroker', {
      'وقف الخسارة %': '${detail['stop_loss_pct'] ?? 20}',
      'جني الربح %': '${detail['take_profit_pct'] ?? 30}',
      'عقود الدخول الآلي': '${detail['auto_quantity'] ?? 1}',
      'عقود التنفيذ الجزئي لكل ملاحظة': '${detail['auto_fill_chunk'] ?? 1}',
      'أقصى فرق بين العرض والطلب %': '${detail['max_spread_pct'] ?? 10}',
    });
    if (values == null || !stillSelected(target)) return;
    final stopLoss = int.tryParse(values['وقف الخسارة %']!);
    final takeProfit = int.tryParse(values['جني الربح %']!);
    final quantity = int.tryParse(values['عقود الدخول الآلي']!);
    final fillChunk = int.tryParse(values['عقود التنفيذ الجزئي لكل ملاحظة']!);
    final maxSpread = int.tryParse(values['أقصى فرق بين العرض والطلب %']!);
    if (stopLoss == null ||
        stopLoss < 1 ||
        stopLoss > 95 ||
        takeProfit == null ||
        takeProfit < 1 ||
        takeProfit > 500 ||
        quantity == null ||
        quantity < 1 ||
        quantity > 100 ||
        quantity > maxContracts ||
        fillChunk == null ||
        fillChunk < 1 ||
        fillChunk > 100 ||
        maxSpread == null ||
        maxSpread < 1 ||
        maxSpread > 50) {
      setState(
        () => error =
            'تحقق من الحدود: وقف الخسارة 1–95%، جني الربح 1–500%، '
            'العقود 1–100 وبحد الحساب ($maxContracts)، '
            'التنفيذ الجزئي 1–100، فرق العرض والطلب 1–50%.',
      );
      return;
    }
    await mutate('PUT', '${pathFor(target)}/risk', {
      'stop_loss_pct': stopLoss,
      'take_profit_pct': takeProfit,
      'auto_quantity': quantity,
      'auto_fill_chunk': fillChunk,
      'max_spread_pct': maxSpread,
    });
  }

  Future<void> runAutomation() async {
    final target = accountId;
    if (target == null || loading) return;
    final requestId = ++generation;
    setState(() {
      loading = true;
      error = null;
      automationResults.remove(target);
    });
    try {
      final result = await api.runMockCycle(target);
      if (!mounted || requestId != generation || accountId != target) return;
      setState(() => automationResults[target] = result);
      await reloadAccounts();
    } catch (e) {
      if (!mounted || requestId != generation || accountId != target) return;
      setState(() {
        loading = false;
        error = '$e';
      });
    }
  }

  Future<void> createOrder() async {
    final selectedAccount = accountId;
    if (selectedAccount == null) return;
    final values = await form('أمر MockBroker فقط — لا تنفيذ حقيقي', {
      'مفتاح منع التكرار':
          pendingOrderKeys[selectedAccount] ??
          'mobile-$selectedAccount-${DateTime.now().microsecondsSinceEpoch}',
      'السهم': 'NVDA',
      'نوع الخيار (CALL/PUT)': 'CALL',
      'انتهاء العقد YYYY-MM-DD': '',
      'سعر التنفيذ بالسنت': '',
      'الإجراء (BUY/SELL_TO_CLOSE)': 'BUY',
      'عدد العقود': '1',
      'سعر الحد بالسنت': '',
    });
    if (values == null || !mounted) return;
    if (accountId != selectedAccount) {
      setState(() => error = 'تغير الحساب؛ افتح نموذج الأمر مجددًا');
      return;
    }
    final strike = int.tryParse(values['سعر التنفيذ بالسنت']!);
    final qty = int.tryParse(values['عدد العقود']!);
    final limit = int.tryParse(values['سعر الحد بالسنت']!);
    if ([strike, qty, limit].any((n) => n == null || n <= 0) ||
        DateTime.tryParse(values['انتهاء العقد YYYY-MM-DD']!) == null) {
      setState(
        () => error = 'تحقق من الأعداد الصحيحة الموجبة وتاريخ انتهاء العقد',
      );
      return;
    }
    pendingOrderKeys[selectedAccount] = values['مفتاح منع التكرار']!;
    final success = await mutate(
      'POST',
      '/api/accounts/${Uri.encodeComponent(selectedAccount)}/orders',
      {
        'request_key': values['مفتاح منع التكرار'],
        'symbol': values['السهم']!.toUpperCase(),
        'right': values['نوع الخيار (CALL/PUT)']!.toUpperCase(),
        'expiry': values['انتهاء العقد YYYY-MM-DD'],
        'strike_cents': strike,
        'side': values['الإجراء (BUY/SELL_TO_CLOSE)']!.toUpperCase(),
        'quantity': qty,
        'limit_cents': limit,
      },
    );
    if (success) {
      pendingOrderKeys.remove(selectedAccount);
    } else if (mounted) {
      setState(
        () => error =
            '$error\nاحتفظ بمفتاح منع التكرار ${pendingOrderKeys[selectedAccount]} عند إعادة إرسال نفس الأمر، وراجع الأوامر أولًا.',
      );
    }
  }

  Future<void> stop({required bool global}) async {
    final target = accountId;
    if (!global && target == null) return;
    final yes = await showDialog<bool>(
      context: context,
      builder: (c) => AlertDialog(
        title: Text(global ? 'إيقاف جميع الحسابات؟' : 'إيقاف الحساب المحدد؟'),
        content: const Text(
          'سيمنع الخادم فتح مراكز جديدة. يسمح بإغلاق المملوك فقط بعد مصالحة موثوقة؛ لا يغلق المراكز تلقائيًا.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(c, false),
            child: const Text('إلغاء'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(c, true),
            child: const Text('تأكيد الإيقاف'),
          ),
        ],
      ),
    );
    if (yes != true || !mounted) return;
    if (!global && !stillSelected(target!)) return;
    await mutate('POST', '/api/emergency-stop', {
      if (!global) 'account_id': target,
    });
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(
      title: Text(pages[page]),
      actions: [
        PopupMenuButton<ThemeMode>(
          tooltip: 'مظهر التطبيق',
          initialValue: widget.themeMode,
          onSelected: widget.onTheme,
          icon: const Icon(Icons.brightness_6_outlined),
          itemBuilder: (_) => const [
            PopupMenuItem(value: ThemeMode.dark, child: Text('الوضع الداكن')),
            PopupMenuItem(value: ThemeMode.light, child: Text('الوضع الفاتح')),
            PopupMenuItem(
              value: ThemeMode.system,
              child: Text('اتباع مظهر النظام'),
            ),
          ],
        ),
        IconButton(
          tooltip: 'اتصال الخادم',
          onPressed: loading ? null : settings,
          icon: const Icon(Icons.settings_ethernet),
        ),
        IconButton(
          tooltip: 'تحديث',
          onPressed: loading ? null : reloadAccounts,
          icon: const Icon(Icons.refresh),
        ),
      ],
    ),
    drawer: Drawer(
      child: SafeArea(
        child: ListView(
          children: [
            const DrawerHeader(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    'Options AI Trader',
                    style: TextStyle(fontSize: 22, fontWeight: FontWeight.bold),
                  ),
                  SizedBox(height: 12),
                  Text('منصة مستقلة • محاكاة فقط'),
                ],
              ),
            ),
            for (var i = 0; i < pages.length; i++)
              ListTile(
                selected: page == i,
                leading: Icon(icons[i]),
                title: Text(pages[i]),
                onTap: () {
                  Navigator.pop(context);
                  setState(() => page = i);
                  reload();
                },
              ),
            ListTile(
              leading: const Icon(Icons.public),
              title: const Text('بيانات السوق الحقيقية'),
              enabled: accountId != null,
              onTap: accountId == null ? null : () {
                Navigator.pop(context);
                Navigator.of(context).push(MaterialPageRoute<void>(
                  builder: (_) => MarketDataScreen(api: api,
                    accounts: List<Map<String, dynamic>>.from(accounts),
                    initialAccount: accountId!),
                ));
              },
            ),
          ],
        ),
      ),
    ),
    body: SafeArea(
      child: Column(
        children: [
          Material(
            color: Theme.of(context).colorScheme.secondaryContainer,
            child: const Padding(
              padding: EdgeInsets.all(12),
              child: Row(
                children: [
                  Icon(Icons.shield_outlined),
                  SizedBox(width: 10),
                  Expanded(
                    child: Text(
                      'محاكاة فقط — Live مقفل. النتائج لا تثبت الربحية.',
                    ),
                  ),
                ],
              ),
            ),
          ),
          if (accounts.isNotEmpty)
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 16),
              child: DropdownButtonFormField<String>(
                key: ValueKey(accountId),
                initialValue: accountId,
                isExpanded: true,
                decoration: const InputDecoration(labelText: 'الحساب النشط'),
                items: accounts
                    .map(
                      (a) => DropdownMenuItem(
                        value: idOf(a),
                        child: Text(
                          '${a['name'] ?? idOf(a)} • ${a['broker'] == 'mock' ? 'محاكاة اصطناعية' : format(a['mode'], 'mode')}',
                        ),
                      ),
                    )
                    .toList(),
                onChanged: loading
                    ? null
                    : (value) {
                        setState(() => accountId = value);
                        reload();
                      },
              ),
            ),
          if (loading) const LinearProgressIndicator(),
          if (error != null)
            Padding(
              padding: const EdgeInsets.all(16),
              child: Semantics(
                liveRegion: true,
                child: Card(
                  color: Theme.of(context).colorScheme.errorContainer,
                  child: Padding(
                    padding: const EdgeInsets.all(12),
                    child: Text(error!),
                  ),
                ),
              ),
            ),
          Expanded(
            child: RefreshIndicator(
              onRefresh: reloadAccounts,
              child: ListView(
                physics: const AlwaysScrollableScrollPhysics(),
                padding: const EdgeInsets.all(16),
                children: content(),
              ),
            ),
          ),
        ],
      ),
    ),
  );

  List<Widget> content() {
    if (page == 0) {
      final realized = portfolio.fold<num>(
        0,
        (sum, a) => sum + (a['realized_pnl_cents'] as num),
      );
      final alerts = accounts
          .where(
            (a) =>
                a['state_known'] == false ||
                a['state_known'] == 0 ||
                a['stopped'] == true ||
                a['stopped'] == 1,
          )
          .length;
      return [
        Text(
          'الحسابات المحمّلة: ${accounts.length}',
          style: Theme.of(context).textTheme.headlineSmall,
        ),
        const Text('مصدر الأرقام: الخادم / MockBroker — محاكاة اصطناعية'),
        if (!loading &&
            error == null &&
            portfolio.isNotEmpty &&
            portfolio.every((a) => a['realized_pnl_cents'] is num))
          Text(
            'إجمالي الربح والخسارة المحققة: ${format(realized, 'realized_pnl_cents')}',
          ),
        Text('تنبيهات حالة الحساب: $alerts'),
        const SizedBox(height: 12),
        ...accounts.map(recordCard),
        if (accounts.isEmpty && !loading)
          const Text('لا توجد حسابات. أضف حساب محاكاة من صفحة الحسابات.'),
      ];
    }
    if (page == 9) {
      final enabled = detail['automation_enabled'] == true;
      final paperMode = detail['mode'] == 'paper';
      return [
        const Text(
          'اختراق وتراجع: قواعد كمية؛ الذكاء الاصطناعي يشرح ولا يرسل الأوامر.',
        ),
        FilledButton.icon(
          onPressed: loading || accountId == null || detail.isEmpty
              ? null
              : editStrategies,
          icon: const Icon(Icons.auto_graph),
          label: const Text('تعديل استراتيجيات الحساب'),
        ),
        if (detail.isNotEmpty)
          recordCard({
            for (final key in ['strategies', 'holding', 'mode'])
              key: detail[key],
          }),
        const SizedBox(height: 16),
        const Text('التنفيذ الآلي التجريبي — MockBroker فقط'),
        const Text(
          'عند التفعيل يدير الخادم مراكز الحساب المملوكة، بما فيها الصفقات '
          'اليدوية، وفق وقف الخسارة وجني الربح وانتهاء العقود. '
          'الأسعار اصطناعية والنتائج ليست أداءً حقيقيًا.',
        ),
        SwitchListTile(
          key: const Key('automation-enabled'),
          title: Text(
            enabled ? 'التنفيذ التجريبي مفعّل' : 'التنفيذ التجريبي معطّل',
          ),
          subtitle: const Text(
            'مستقل لهذا الحساب؛ متاح في وضع Paper / Mock فقط',
          ),
          value: enabled,
          onChanged:
              loading || accountId == null || detail.isEmpty || !paperMode
              ? null
              : (value) {
                  final target = accountId!;
                  mutate('PUT', '${pathFor(target)}/risk', {
                    'automation_enabled': value,
                  });
                },
        ),
        OutlinedButton.icon(
          key: const Key('automation-settings'),
          onPressed: loading || accountId == null || detail.isEmpty
              ? null
              : editAutomation,
          icon: const Icon(Icons.tune),
          label: const Text('تعديل قواعد التنفيذ والخروج'),
        ),
        if (detail.isNotEmpty)
          recordCard({
            for (final key in [
              'stop_loss_pct',
              'take_profit_pct',
              'auto_quantity',
              'auto_fill_chunk',
              'max_spread_pct',
            ])
              key: detail[key],
          }),
        const Text(
          'صالح الحساب وفعّل الرموز المطلوبة قبل التشغيل. كل دورة تتحقق من '
          'الحساب والأوامر والمخاطر. الدخول مرة واحدة لكل رمز في اليوم (UTC)، '
          'والتنفيذ الجزئي يتطلب ملاحظة سعر اصطناعية جديدة.',
        ),
        FilledButton.icon(
          key: const Key('automation-run'),
          onPressed: loading || accountId == null || !enabled || !paperMode
              ? null
              : runAutomation,
          icon: const Icon(Icons.play_arrow),
          label: const Text('تشغيل دورة محاكاة واحدة'),
        ),
        const Text(
          'الزر يطلب دورة واحدة من الخادم. الاستمرار عند إغلاق التطبيق يتطلب '
          'تشغيل عامل المحاكاة المستقل. الطلب لا يُعاد تلقائيًا عند الانقطاع.',
        ),
        if (automationResults[accountId] != null) ...[
          const SizedBox(height: 12),
          const Text('نتيجة آخر دورة من الخادم لهذا الحساب'),
          recordCard(automationResults[accountId]!),
        ],
      ];
    }
    if (page == 1) {
      return [
        FilledButton.icon(
          onPressed: loading ? null : createAccount,
          icon: const Icon(Icons.add),
          label: const Text('إضافة حساب محاكاة'),
        ),
        const Padding(
          padding: EdgeInsets.symmetric(vertical: 16),
          child: Text(
            'IBKR: محول مُجهّز في الخادم دون اتصال فعلي. لا تربط حسابًا حقيقيًا.',
          ),
        ),
        ...rows.map(
          (a) => Column(
            children: [
              recordCard(a),
              OutlinedButton(
                onPressed: loading
                    ? null
                    : () => mutate(
                        'POST',
                        '/api/accounts/${Uri.encodeComponent(idOf(a))}/reconcile',
                      ),
                child: const Text('مصالحة حالة المحاكاة'),
              ),
            ],
          ),
        ),
        if (rows.isEmpty)
          const Text('لا توجد حسابات؛ أضف حساب محاكاة بعد الاتصال بالخادم.'),
      ];
    }
    if (page == 8) {
      return [
        const Text(
          'تنبيهات داخل التطبيق عند التحديث؛ إشعارات Push غير مفعّلة.',
        ),
        if (detail.isNotEmpty) recordCard(detail),
        const Icon(Icons.stop_circle_outlined, size: 72, color: Colors.red),
        const Padding(
          padding: EdgeInsets.symmetric(vertical: 20),
          child: Text(
            'الإيقاف يمنع الأوامر الجديدة في الخادم المستقل حتى لو أُغلق التطبيق. راجع الأوامر والمراكز بعد انقطاع الاتصال.',
          ),
        ),
        FilledButton.icon(
          onPressed: loading || accountId == null
              ? null
              : () => stop(global: false),
          icon: const Icon(Icons.stop),
          label: const Text('إيقاف الحساب المحدد'),
        ),
        const SizedBox(height: 12),
        FilledButton.icon(
          onPressed: loading ? null : () => stop(global: true),
          icon: const Icon(Icons.stop_circle),
          label: const Text('إيقاف جميع الحسابات'),
        ),
      ];
    }
    if (accountId == null) {
      return [const Text('اتصل بالخادم ثم أضف حساب محاكاة من صفحة الحسابات.')];
    }
    if (page == 10) {
      const moduleLabels = {
        'scenario_battle': 'مقارنة السيناريوهات',
        'entry_timing': 'توقيت الدخول',
        'option_twin': 'Option Twin',
        'liquidity_trap': 'فخ السيولة',
        'correlation_guard': 'حارس الارتباط',
        'strategy_tournament': 'بطولة الاستراتيجيات',
        'safety_supervisor': 'مشرف السلامة والثقة',
      };
      return [
        const Text('بحث الخادم • Shadow • بيانات اصطناعية',
          key: Key('backend-research-banner')),
        const Text('بحث اصطناعي مع حفظ لقطاته في الخادم. لا ترسل هذه الصفحة أوامر أو تعدّل المخاطر. الحفظ يحلل البيانات المتاحة لحظة الطلب.'),
        OutlinedButton.icon(key: const Key('backend-research-symbol'),
          onPressed: loading ? null : () async {
            final selectedAccount = accountId;
            final values = await form('رمز البحث في كتالوج Mock', {'الرمز': researchSymbol});
            if (values == null || !mounted || accountId != selectedAccount) return;
            final symbol = values['الرمز']!.toUpperCase();
            if (!RegExp(r'^[A-Z][A-Z0-9.]{0,9}$').hasMatch(symbol)) {
              setState(() => error = 'رمز غير صالح');
              return;
            }
            setState(() => researchSymbol = symbol);
            await reload();
          }, icon: const Icon(Icons.search), label: Text('الرمز: $researchSymbol')),
        Wrap(spacing: 8, runSpacing: 8, children: [
          FilledButton.icon(key: const Key('backend-research-save'),
            onPressed: loading || detail.isEmpty ? null : saveResearchSnapshot,
            icon: const Icon(Icons.bookmark_add_outlined),
            label: const Text('حفظ لقطة بحث جديدة')),
          OutlinedButton.icon(key: const Key('backend-research-refresh'),
            onPressed: loading ? null : reload,
            icon: const Icon(Icons.refresh), label: const Text('تحديث البحث والقائمة')),
        ]),
        if (researchNotice != null) Padding(
          padding: const EdgeInsets.symmetric(vertical: 8),
          child: Text(researchNotice!, key: const Key('backend-research-notice'))),
        if (researchSnapshots != null) ...[
          if (researchSnapshots!.items.isEmpty) const Text('لا توجد لقطات محفوظة لهذا الحساب والرمز.'),
          if (researchSnapshots!.items.isNotEmpty) ...[
            DropdownButtonFormField<String>(
              key: ValueKey('backend-research-snapshots-${selectedResearchSnapshot ?? "none"}'),
              initialValue: researchSnapshots!.items.any((item) =>
                item.snapshotId == selectedResearchSnapshot) ? selectedResearchSnapshot : null,
              isExpanded: true,
              decoration: const InputDecoration(labelText: 'لقطة محفوظة في الخادم'),
              items: researchSnapshots!.items.map((item) => DropdownMenuItem(
                value: item.snapshotId,
                child: Text('${item.asOf.toIso8601String()} • ${item.snapshotId}',
                  maxLines: 1, overflow: TextOverflow.ellipsis),
              )).toList(),
              onChanged: loading ? null : (value) => setState(() {
                selectedResearchSnapshot = value;
                researchReplay = null;
                researchNotice = null;
                detail = {};
              }),
            ),
            OutlinedButton.icon(key: const Key('backend-research-replay'),
              onPressed: loading || selectedResearchSnapshot == null ? null : replayResearchSnapshot,
              icon: const Icon(Icons.history), label: const Text('إعادة عرض اللقطة الأصلية')),
            OutlinedButton.icon(key: const Key('backend-research-capture'),
              onPressed: loading || selectedResearchSnapshot == null ? null : captureResearchObservation,
              icon: const Icon(Icons.add_chart), label: const Text('حفظ ملاحظة اصطناعية لاحقة')),
            const Text('النتيجة البديلة تستخدم الملاحظات الاصطناعية المحفوظة فقط. '
              'احفظ ملاحظتين في دقيقتين مختلفتين بعد القرار؛ إعادة العرض لا تولّد أسعارًا تاريخية.'),
          ],
          if (researchSnapshots!.truncated) const Text('تُعرض أحدث اللقطات فقط؛ توجد لقطات أقدم في الخادم.'),
        ],
        if (researchReplay != null) Card(child: Padding(
          padding: const EdgeInsets.all(12),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text('اللقطة: ${researchReplay!.snapshotId}'),
            const Text('Counterfactual • نتيجة افتراضية بملاحظات اصطناعية محفوظة؛ ليست أسعار سوق أو تنفيذًا أو دليل ربحية.'),
            if (!researchReplay!.hasOutcome)
              const Text('النتيجة غير متاحة: لا توجد ملاحظات اصطناعية لاحقة محفوظة وكافية. لم تُختلق أسعار أو أرباح.',
                key: Key('backend-replay-unavailable')),
            if (researchReplay!.hasOutcome) ...[
              Text('صافي افتراضي بعد التكاليف: ${format(researchReplay!.counterfactual['pnl'])}',
                key: const Key('backend-replay-outcome')),
              Text('الدخول الافتراضي: ${researchReplay!.counterfactual['entry_at']}'),
              Text('الخروج الافتراضي: ${researchReplay!.counterfactual['exit_at']}'),
              Text('العمولات: ${format(researchReplay!.counterfactual['commissions'])}'),
            ],
          ]))),
        if (detail.isNotEmpty) ...[
          Text('الحساب: ${detail['account_id']} • وقت البيانات: ${detail['as_of']}'),
          for (final entry in (detail['modules'] as Map).entries)
            Card(child: ExpansionTile(
              key: ValueKey('backend-research-${entry.key}'),
              title: Text(moduleLabels[entry.key] ?? '${entry.key}'),
              children: [entry.value is Map
                ? recordCard(Map<String, dynamic>.from(entry.value as Map))
                : Padding(padding: const EdgeInsets.all(12), child: Text(format(entry.value)))])),
          if (detail['decision'] is Map) recordCard({
            for (final e in (detail['decision'] as Map).entries)
              if (['decision_id', 'decided_at', 'reasons'].contains(e.key)) '${e.key}': e.value,
          }),
          ...List<Object?>.from(detail['limitations'] as List).map((v) => Padding(
            padding: const EdgeInsets.symmetric(vertical: 6), child: Text('$v'))),
        ],
        if (detail.isEmpty && !loading) const Text('لا نتائج موثوقة متاحة. راجع الخطأ أو الاتصال بالخادم.'),
        const Text('اللقطات تخص الحساب والرمز المحددين وتبقى في قاعدة بيانات الخادم. عرض بحث Demo المحلي مستقل عن هذه البيانات.'),
      ];
    }
    if (page == 5) {
      return [
        FilledButton.icon(
          onPressed: loading ? null : addSymbol,
          icon: const Icon(Icons.add),
          label: const Text('إضافة سهم'),
        ),
        const Padding(
          padding: EdgeInsets.symmetric(vertical: 12),
          child: Text(
            'التحقق في MockBroker خاص بالمحاكاة. ملاحظة السوق صالحة 60 ثانية؛ حدّثها صراحة من زر تحديث الرمز، وصالح الحساب من صفحة الحسابات. لا توجد بيانات حقيقية.',
          ),
        ),
        ...rows.map(
          (r) => Card(
            child: ListTile(
              title: Text('${r['symbol']}'),
              subtitle: Text('${r['validation_status'] ?? r['status'] ?? ''}'),
              leading: Switch(
                value: r['enabled'] == true || r['enabled'] == 1,
                onChanged: loading
                    ? null
                    : (v) => mutate(
                        'PATCH',
                        '$accountPath/watchlist/${Uri.encodeComponent('${r['symbol']}')}',
                        {'enabled': v},
                      ),
              ),
              trailing: Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  IconButton(
                    tooltip: 'تحديث ملاحظة سوق اصطناعية',
                    icon: const Icon(Icons.sync),
                    onPressed: loading
                        ? null
                        : () => mutate(
                            'POST',
                            '$accountPath/mock-market-data',
                            {'symbol': r['symbol'], 'available': true},
                          ),
                  ),
                  IconButton(
                    tooltip: 'حذف السهم',
                    icon: const Icon(Icons.delete_outline),
                    onPressed: loading
                        ? null
                        : () => mutate(
                            'DELETE',
                            '$accountPath/watchlist/${Uri.encodeComponent('${r['symbol']}')}',
                          ),
                  ),
                ],
              ),
            ),
          ),
        ),
        if (rows.isEmpty && !loading) const Text('قائمة المراقبة فارغة.'),
      ];
    }
    if (page == 4) {
      return [
        FilledButton.icon(
          onPressed: loading || detail.isEmpty ? null : editRisk,
          icon: const Icon(Icons.tune),
          label: const Text('تعديل حدود المخاطر'),
        ),
        const Padding(
          padding: EdgeInsets.symmetric(vertical: 12),
          child: Text(
            'الإشارات كمية. الذكاء الاصطناعي لا يرسل أوامر ولا يتجاوز المخاطر. V1 يدعم شراء Call/Put وإغلاق المملوك فقط.',
          ),
        ),
        recordCard(detail),
      ];
    }
    if ([2, 3, 7].contains(page)) {
      return [
        if (page == 3)
          Row(
            children: [
              Expanded(
                child: FilledButton.icon(
                  onPressed: loading ? null : createOrder,
                  icon: const Icon(Icons.add),
                  label: const Text('أمر محاكاة'),
                ),
              ),
              const SizedBox(width: 8),
              Expanded(
                child: OutlinedButton(
                  onPressed: loading
                      ? null
                      : () {
                          setState(() => showPositions = !showPositions);
                          reload();
                        },
                  child: Text(showPositions ? 'عرض الأوامر' : 'عرض المراكز'),
                ),
              ),
            ],
          ),
        const SizedBox(height: 12),
        Text(
          page == 2
              ? 'الفرص تخضع لقواعد كمية وفحص المخاطر؛ لا تُرسل أوامر من هذه الشاشة.'
              : page == 3
              ? 'أوامر المحاكاة الخاصة بالحساب المحدد فقط.'
              : 'أسباب القرارات والرفض والفرص الضائعة.',
        ),
        const SizedBox(height: 12),
        ...rows.map(
          (r) => page == 3 && !showPositions ? orderCard(r) : recordCard(r),
        ),
        if (rows.isEmpty && !loading) const Text('لا توجد سجلات بعد.'),
      ];
    }
    return [
      const Text('تقارير الحساب المحدد — نتائج اصطناعية من MockBroker'),
      ...accounts.where((a) => idOf(a) == accountId).map(recordCard),
      const SizedBox(height: 12),
      if (detail.isNotEmpty) recordCard(detail),
      if (detail.isEmpty && !loading) const Text('لا تتوفر بيانات من الخادم.'),
      const Padding(
        padding: EdgeInsets.symmetric(vertical: 16),
        child: Text(
          'بيانات الأداء للمحاكاة فقط. Backtesting يحتاج بيانات تاريخية موثقة قبل تقييم أي استراتيجية.',
        ),
      ),
    ];
  }

  Future<void> manageOrder(
    Map<String, dynamic> order, {
    required bool fill,
  }) async {
    final selectedAccount = accountId;
    final orderId = '${order['id']}';
    if (selectedAccount == null ||
        '${order['account_id']}' != selectedAccount) {
      setState(() => error = 'الأمر لا ينتمي إلى الحساب المحدد');
      return;
    }
    final path =
        '/api/accounts/${Uri.encodeComponent(selectedAccount)}/orders/${Uri.encodeComponent(orderId)}';
    if (!fill) {
      final yes = await showDialog<bool>(
        context: context,
        builder: (c) => AlertDialog(
          title: const Text('إلغاء أمر المحاكاة؟'),
          content: Text('الأمر: $orderId'),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(c, false),
              child: const Text('رجوع'),
            ),
            FilledButton(
              onPressed: () => Navigator.pop(c, true),
              child: const Text('تأكيد الإلغاء'),
            ),
          ],
        ),
      );
      if (yes != true || !mounted) return;
      if (accountId != selectedAccount) {
        setState(() => error = 'تغير الحساب؛ أعد فتح الإجراء');
        return;
      }
      await mutate('POST', '$path/cancel');
      return;
    }
    final values = await form('محاكاة تنفيذ جزئي — MockBroker فقط', {
      'معرّف التنفيذ لمنع التكرار':
          pendingFillKeys[orderId] ??
          'fill-$orderId-${DateTime.now().microsecondsSinceEpoch}',
      'عدد العقود المنفذة': '1',
      'سعر التنفيذ بالسنت': '${order['limit_cents']}',
    });
    if (values == null || !mounted) return;
    if (accountId != selectedAccount) {
      setState(() => error = 'تغير الحساب؛ أعد فتح الإجراء');
      return;
    }
    final quantity = int.tryParse(values['عدد العقود المنفذة']!);
    final price = int.tryParse(values['سعر التنفيذ بالسنت']!);
    if (quantity == null || quantity <= 0 || price == null || price <= 0) {
      setState(() => error = 'أدخل أعدادًا صحيحة موجبة');
      return;
    }
    pendingFillKeys[orderId] = values['معرّف التنفيذ لمنع التكرار']!;
    final success = await mutate('POST', '$path/mock-fill', {
      'fill_id': pendingFillKeys[orderId],
      'quantity': quantity,
      'price_cents': price,
    });
    if (success) {
      pendingFillKeys.remove(orderId);
    } else if (mounted) {
      setState(
        () => error =
            '$error\nراجع الأمر قبل إعادة المحاكاة واحتفظ بمعرّف التنفيذ ${pendingFillKeys[orderId]}.',
      );
    }
  }

  Widget orderCard(Map<String, dynamic> order) => Column(
    children: [
      recordCard(order),
      if (['PENDING', 'PARTIAL', 'UNKNOWN'].contains(order['status']))
        Wrap(
          spacing: 8,
          children: [
            OutlinedButton.icon(
              onPressed: loading ? null : () => manageOrder(order, fill: true),
              icon: const Icon(Icons.science_outlined),
              label: const Text('محاكاة تنفيذ جزئي'),
            ),
            OutlinedButton.icon(
              onPressed: loading ? null : () => manageOrder(order, fill: false),
              icon: const Icon(Icons.cancel_outlined),
              label: const Text('إلغاء الأمر'),
            ),
          ],
        ),
    ],
  );

  static const hiddenFields = {'fingerprint', 'sequence'};
  static const booleanFields = {
    'enabled',
    'verified',
    'state_known',
    'stopped',
    'halted',
    'live_enabled',
    'emergency_stop',
    'snapshot_valid',
    'global_stopped',
    'new_entries_allowed',
  };
  static const centsFields = {
    'equity',
    'cash',
    'realized',
    'cost',
    'strike',
    'limit_cents',
    'price_cents',
    'strike_cents',
    'daily_pnl_cents',
    'open_cost_cents',
  };
  Widget recordCard(Map<String, dynamic> record) => Card(
    child: Padding(
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: record.entries
            .where((e) => !hiddenFields.contains(e.key))
            .map(
              (e) => Padding(
                padding: const EdgeInsets.symmetric(vertical: 4),
                child: Text(
                  '${labels[e.key] ?? e.key}: ${format(e.value, e.key)}',
                ),
              ),
            )
            .toList(),
      ),
    ),
  );
  String format(dynamic value, [String? key]) {
    if (value == null) return '—';
    if (key == 'detail' && value is String) {
      try {
        return format(jsonDecode(value));
      } on FormatException {
        return value;
      }
    }
    if (booleanFields.contains(key) &&
        (value == 0 || value == 1 || value is bool)) {
      return value == true || value == 1 ? 'نعم' : 'لا';
    }
    if (value is num &&
        (centsFields.contains(key) || (key?.endsWith('_cents') ?? false))) {
      return '${(value / 100).toStringAsFixed(2)} USD';
    }
    if (value is Map) {
      return value.entries
          .where((e) => !hiddenFields.contains('${e.key}'))
          .map(
            (e) =>
                '${labels['${e.key}'] ?? e.key}: ${format(e.value, '${e.key}')}',
          )
          .join('\n');
    }
    if (value is List) return value.map((v) => format(v)).join('، ');
    if (value == true) return 'نعم';
    if (value == false) return 'لا';
    return enumLabels[value.toString()] ?? value.toString();
  }

  static const enumLabels = {
    'paper': 'Paper (نوع البيئة؛ بيانات Mock اصطناعية)',
    'live': 'Live مقفل',
    'mock': 'وسيط محاكاة',
    'synthetic_mock': 'بيانات اصطناعية للمحاكاة',
    'CALL': 'خيار شراء Call',
    'PUT': 'خيار بيع Put',
    'BUY': 'شراء',
    'SELL_TO_CLOSE': 'بيع لإغلاق المملوك',
    'PENDING': 'معلّق',
    'PARTIAL': 'منفذ جزئيًا',
    'FILLED': 'منفذ بالكامل',
    'CANCELLED': 'ملغى',
    'shadow': 'Shadow — إشارات فقط',
    'analysis': 'تحليل فقط',
    'UNKNOWN': 'استجابة غير مؤكدة؛ المصالحة مطلوبة',
    'REJECTED': 'مرفوض',
    'EXPIRED': 'منتهي',
    'owned_closes_only_after_trusted_reconciliation':
        'إغلاق المملوك فقط بعد مصالحة موثوقة',
    'intraday': 'داخل اليوم',
    'swing': 'متعدد الأيام',
    'breakout': 'اختراق',
    'pullback': 'تراجع',
  };
  static const labels = {
    'id': 'المعرّف',
    'account_id': 'الحساب',
    'name': 'الاسم',
    'mode': 'الوضع',
    'broker': 'الوسيط',
    'status': 'الحالة',
    'symbol': 'السهم',
    'enabled': 'مفعّل',
    'equity': 'قيمة الحساب',
    'state_known': 'حالة الحساب معلومة',
    'emergency_stop': 'الإيقاف الطارئ',
    'config': 'الإعدادات',
    'equity_cents': 'قيمة الحساب',
    'realized_pnl_cents': 'الربح والخسارة المحققة',
    'open_premium_cents': 'قيمة المراكز',
    'open_positions': 'عدد المراكز',
    'live_enabled': 'التداول الحقيقي مفعّل',
    'source': 'مصدر البيانات',
    'cash': 'النقد',
    'risk': 'المخاطر',
    'halted': 'متوقف',
    'strategy': 'الاستراتيجية',
    'score': 'التقييم',
    'reason': 'السبب',
    'side': 'الاتجاه',
    'quantity': 'الكمية',
    'filled_quantity': 'الكمية المنفذة',
    'created_at': 'تاريخ الإنشاء',
    'timestamp': 'الوقت',
    'event': 'الحدث',
    'pnl': 'الربح والخسارة',
    'realized_pnl': 'الربح والخسارة المحققة',
    'trade_risk_pct': 'حد مخاطرة الصفقة %',
    'daily_loss_pct': 'حد الخسارة اليومية %',
    'allocation_pct': 'حد التخصيص %',
    'positions': 'المراكز',
    'orders': 'الأوامر',
    'filled': 'العقود المنفذة',
    'right_kind': 'نوع الخيار',
    'right': 'نوع الخيار',
    'expiry': 'انتهاء العقد',
    'strike': 'سعر التنفيذ',
    'strike_cents': 'سعر التنفيذ',
    'limit_cents': 'قسط الحد لكل سهم',
    'price_cents': 'قسط التنفيذ لكل سهم',
    'cost': 'تكلفة المركز',
    'realized': 'الربح والخسارة المحققة',
    'stopped': 'الإيقاف الطارئ مفعّل',
    'verified': 'تم التحقق للمحاكاة',
    'snapshot_at': 'وقت آخر حالة للحساب',
    'daily_pnl_cents': 'ربح وخسارة اليوم',
    'open_cost_cents': 'تكلفة المراكز المفتوحة',
    'unrealized_pnl_cents': 'الربح والخسارة غير المحققة',
    'detail': 'تفاصيل القرار',
    'created': 'وقت التسجيل',
    'order_id': 'معرّف الأمر',
    'request_key': 'مفتاح منع تكرار الأمر',
    'risk_group': 'مجموعة المخاطر',
    'group_allocation_pct': 'حد تخصيص المجموعة %',
    'group_daily_loss_pct': 'حد خسارة المجموعة اليومية %',
    'new_entries_allowed': 'فتح مراكز جديدة مسموح',
    'snapshot_valid': 'حالة الحساب موثوقة',
    'global_stopped': 'الإيقاف العام',
    'emergency_policy': 'سياسة الطوارئ',
    'max_contracts': 'عدد العقود الأقصى',
    'holding': 'مدة الاحتفاظ',
    'strategies': 'الاستراتيجيات',
    'automation_enabled': 'التنفيذ التجريبي الآلي مفعّل',
    'stop_loss_pct': 'وقف الخسارة %',
    'take_profit_pct': 'جني الربح %',
    'auto_quantity': 'عقود الدخول الآلي',
    'auto_fill_chunk': 'عقود التنفيذ الجزئي لكل ملاحظة',
    'max_spread_pct': 'أقصى فرق بين العرض والطلب %',
    'actions': 'الإجراءات',
    'blocked_reason': 'سبب منع التنفيذ',
    'blocked_reasons': 'أسباب منع التنفيذ',
    'orders_submitted': 'الأوامر التجريبية المرسلة',
    'fills_applied': 'عمليات التنفيذ التجريبي',
    'expired_positions': 'المراكز المنتهية',
  };
}
