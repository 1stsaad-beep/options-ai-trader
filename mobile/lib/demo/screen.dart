import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'engine.dart';
import 'store.dart';
import 'backup.dart';
import 'chart_lab.dart';
import 'research_lab.dart';

class DemoScreen extends StatefulWidget {
  final DemoStore? store;
  final ValueChanged<ThemeMode> onTheme;
  final VoidCallback onBackend;
  const DemoScreen({
    super.key,
    this.store,
    required this.onTheme,
    required this.onBackend,
  });
  @override
  State<DemoScreen> createState() => _DemoScreenState();
}

class _DemoScreenState extends State<DemoScreen> with WidgetsBindingObserver {
  late final DemoController controller;
  String? selected;
  int page = 0;
  DemoRow? replay;
  bool positionsTab = false;
  String chartSymbol = 'NVDA';
  static const pages = [
    'الرئيسية',
    'الحسابات المحلية',
    'الفرص والتحليلات',
    'الصفقات والأوامر',
    'إعدادات المخاطر',
    'قوائم المراقبة',
    'التقارير والاختبار التاريخي',
    'سجل القرارات',
    'الطوارئ واختبار الأعطال',
    'الاستراتيجيات والإعدادات',
    'مختبر الرسوم المتقدم',
    'إعادة قرارات الصفقات',
    'مختبر الأبحاث المحلي',
  ];
  static const icons = [
    Icons.home_outlined,
    Icons.account_balance_wallet_outlined,
    Icons.radar,
    Icons.receipt_long_outlined,
    Icons.shield_outlined,
    Icons.visibility_outlined,
    Icons.insights,
    Icons.history,
    Icons.emergency_outlined,
    Icons.tune,
    Icons.candlestick_chart,
    Icons.replay_circle_filled,
    Icons.science_outlined,
  ];
  DemoEngine get engine => controller.engine;
  DemoRow? get account => selected == null ? null : engine.account(selected!);
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    controller = DemoController(widget.store ?? PreferencesDemoStore())
      ..addListener(changed);
    controller.load();
  }

  void changed() {
    if (!mounted) return;
    if (controller.ready && !engine.accounts.any((a) => a['id'] == selected)) {
      selected = engine.accounts.isEmpty ? null : engine.accounts.first['id'];
    }
    setState(() {});
    if (controller.ready) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted) {
          widget.onTheme(switch (engine.theme) {
            'light' => ThemeMode.light,
            'system' => ThemeMode.system,
            _ => ThemeMode.dark,
          });
        }
      });
    }
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state != AppLifecycleState.resumed) controller.pause();
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    controller.removeListener(changed);
    controller.dispose();
    super.dispose();
  }

  String money(num value) => '${(value / 100).toStringAsFixed(2)} USD';
  String label(dynamic value) => switch (value) {
    'BUY' => 'شراء',
    'SELL_TO_CLOSE' => 'إغلاق المملوك',
    'OPEN' => 'معلّق',
    'PARTIAL' => 'منفّذ جزئيًا',
    'FILLED' => 'منفّذ',
    'CANCELLED' => 'ملغى',
    'breakout' => 'اختراق',
    'pullback' => 'تراجع',
    _ => '$value',
  };
  Future<void> act(void Function(DemoEngine) op) => controller.change(op);

  void backupMessage(String message) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(message)));
  }

  Future<void> exportBackup() async {
    try {
      final text = controller.exportBackup();
      await Clipboard.setData(ClipboardData(text: text));
      backupMessage('نُسخت بيانات Demo إلى الحافظة. الصق JSON في مكان تحفظه بنفسك؛ لم يُنشأ ملف تلقائيًا.');
    } catch (e) { backupMessage('تعذر تصدير النسخة: $e'); }
  }

  Future<void> importBackup() async {
    if (!controller.ready || controller.busy || controller.storageUncertain) return;
    controller.pause();
    final expectedCurrent = engine.encode();
    final text = await showDialog<String>(context: context,
      builder: (_) => const _DemoBackupInputDialog());
    if (text == null || !mounted) return;
    try {
      final preview = DemoBackup.inspect(text);
      final confirmed = await showDialog<bool>(context: context, builder: (dialog) => AlertDialog(
        title: const Text('معاينة استبدال بيانات Demo'),
        content: SingleChildScrollView(child: Column(mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text('الحسابات: ${preview.accountCount} • الأوامر: ${preview.orderCount}\n'
              'المراكز: ${preview.positionCount} • الصفقات المغلقة: ${preview.tradeCount}',
              key: const Key('demo-backup-preview-counts')),
            Text(preview.accountNames.take(10).join('، ')),
            const SizedBox(height: 12),
            const Text('سيُستبدل جميع حسابات Demo على الجهاز؛ لا دمج. '
              'تبقى القرارات والتعبئات الأصلية محفوظة، وتتوقف الأتمتة والتعزيز والانعكاس. '
              'راجع الأوامر المعلقة ثم صالح كل حساب واستأنفه صراحة قبل أي دخول جديد. '
              'أوامر الإغلاق المملوك قد تستكمل بعد المصالحة عند تشغيل المحاكاة. '
              'التحقق من البنية والدفتر لا يثبت أصالة مصدر النسخة.'),
          ])),
        actions: [
          TextButton(key: const Key('demo-backup-cancel'),
            onPressed: () => Navigator.pop(dialog, false), child: const Text('احتفظ بالبيانات الحالية')),
          FilledButton(key: const Key('demo-backup-confirm'),
            onPressed: () => Navigator.pop(dialog, true), child: const Text('استبدال كل حسابات Demo')),
        ],
      ));
      if (confirmed != true || !mounted) return;
      final imported = await controller.importBackup(preview, expectedCurrent: expectedCurrent);
      if (!mounted) return;
      if (imported) {
        setState(() {
          selected = engine.accounts.isEmpty ? null : engine.accounts.first['id'];
          replay = null;
          page = 0;
        });
        backupMessage('استُعيدت بيانات Demo والأتمتة معطلة. راجع الأوامر قبل المصالحة، واستأنف الحساب صراحة لأي دخول جديد.');
      }
    } catch (e) { backupMessage('رُفضت النسخة؛ لم تتغير بياناتك. $e'); }
  }

  Future<Map<String, String>?> form(
    String title,
    Map<String, String> fields,
  ) async {
    final controls = {
      for (final e in fields.entries)
        e.key: TextEditingController(text: e.value),
    };
    final result = await showDialog<Map<String, String>>(
      context: context,
      builder: (c) => AlertDialog(
        title: Text(title),
        content: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              for (final e in controls.entries)
                Padding(
                  padding: const EdgeInsets.only(bottom: 12),
                  child: TextField(
                    controller: e.value,
                    decoration: InputDecoration(labelText: e.key),
                  ),
                ),
            ],
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(c),
            child: const Text('إلغاء'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(c, {
              for (final e in controls.entries) e.key: e.value.text.trim(),
            }),
            child: const Text('حفظ'),
          ),
        ],
      ),
    );
    await Future<void>.delayed(const Duration(milliseconds: 350));
    for (final c in controls.values) {
      c.dispose();
    }
    return result;
  }

  Future<void> newAccount() async {
    final values = await form('حساب محلي — رصيد اصطناعي', {
      'اسم الحساب': '',
      'الرصيد بالدولار': '10000',
    });
    if (values == null || !mounted) return;
    await act((e) {
      final amount = double.tryParse(values['الرصيد بالدولار']!);
      if (amount == null || !amount.isFinite) {
        throw const DemoRejected('الرصيد غير صالح');
      }
      selected = e.createAccount(
        values['اسم الحساب']!,
        (amount * 100).round(),
      )['id'];
    });
  }

  Future<void> editRisk() async {
    final id = selected!, r = engine.risk(account!);
    const fields = {
      'مخاطرة الصفقة % (0–100)': 'trade_pct',
      'الخسارة اليومية % (0–100)': 'daily_pct',
      'تخصيص رأس المال % (0–100)': 'allocation_pct',
      'التعرض المفتوح % (0–100)': 'exposure_pct',
      'حد العقود (1–100)': 'max_contracts',
      'مجموعة مخاطر مترابطة (اختياري)': 'group',
      'تعرض المجموعة % (0–100)': 'group_allocation_pct',
      'خسارة المجموعة % (0–100)': 'group_daily_pct',
    };
    final result = await form('مخاطر الحساب المحلي', {
      for (final e in fields.entries) e.key: '${r[e.value]}',
    });
    if (result == null || !mounted || selected != id) return;
    final changes = <String,dynamic>{for(final f in fields.entries)
      f.value:f.value=='group'?result[f.key]:int.tryParse(result[f.key]!)};
    if(changes.values.any((v)=>v==null)) {
      await act((_)=>throw const DemoRejected('أدخل نسبًا وأعدادًا صحيحة')); return;
    }
    final elevated=DemoEngine.elevated({...r,...changes});
    if(elevated) {
      final confirmed=await showDialog<bool>(context:context,builder:(c)=>AlertDialog(
        title:const Text('تأكيد مخاطر مرتفعة'),
        content:const Text('قد تستنفد هذه الحدود كامل رأس المال الاصطناعي. تخصيص رأس المال يختلف عن خسارة الصفقة والخسارة اليومية. هل تقرّ بهذه المخاطر لحساب Demo المحدد؟'),
        actions:[TextButton(onPressed:()=>Navigator.pop(c,false),child:const Text('إلغاء')),
          FilledButton(onPressed:()=>Navigator.pop(c,true),child:const Text('أقرّ بالمخاطر وأحفظ'))]));
      if(confirmed!=true || !mounted) return;
    }
    changes['elevated_risk_ack']=elevated;
    await act((e)=>e.configure(id,changes));
  }

  Future<void> editExecution() async {
    final id = selected!, r = engine.risk(account!);
    const fields = {
      'وقف الخسارة %': 'stop_pct',
      'جني الربح %': 'take_pct',
      'الوقف المتحرك % (0 لتعطيله)': 'trailing_pct',
      'جني مرحلي % (0 لتعطيله)': 'partial_take_pct',
      'حد احتفاظ Swing بالملاحظات': 'swing_max_ticks',
      'حماية الانتهاء بالأيام (0 لتعطيلها)': 'expiry_guard_days',
      'أقصى عدد تعزيزات': 'scaling_max',
      'عقود كل إضافة': 'scaling_quantity',
      'تهدئة التعزيز بالملاحظات': 'scaling_cooldown',
      'كمية الدخول': 'quantity',
      'عقود التنفيذ لكل خطوة': 'fill_chunk',
      'العمولة لكل عقد بالسنت': 'commission',
      'الانزلاق لكل سهم خيار بالسنت': 'slippage',
    };
    final result = await form('التنفيذ والخروج المحلي', {
      for (final f in fields.entries) f.key: '${r[f.value]}',
    });
    if (result == null || !mounted || selected != id) return;
    await act(
      (e) => e.configure(id, {
        for (final f in fields.entries) f.value: int.tryParse(result[f.key]!),
      }),
    );
  }

  Future<void> manualOrder({DemoRow? position}) async {
    final id = selected!;
    final values =
        await form(position == null ? 'شراء عقد اصطناعي' : 'إغلاق مركز مملوك', {
          if (position == null) 'الرمز': 'NVDA',
          if (position == null) 'النوع CALL أو PUT': 'CALL',
          'عدد العقود': '${position?['quantity'] ?? 1}',
        });
    if (values == null || !mounted || id != selected) return;
    await act((e) {
      final qty = int.tryParse(values['عدد العقود']!);
      if (qty == null) throw const DemoRejected('عدد العقود غير صالح');
      final c =
          position ??
          e.contract(
            values['الرمز']!.toUpperCase(),
            values['النوع CALL أو PUT']!.toUpperCase(),
          );
      e.submit(
        id,
        c,
        position == null ? 'BUY' : 'SELL_TO_CLOSE',
        qty,
        'manual-$id-${e.sequence + 1}-${e.tick}',
      );
    });
  }

  Widget card(String title, String detail, {IconData? icon, Widget? action}) =>
      Card(
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  if (icon != null) ...[Icon(icon), const SizedBox(width: 8)],
                  Expanded(
                    child: Text(
                      title,
                      style: Theme.of(context).textTheme.titleMedium,
                    ),
                  ),
                  if (action != null) action,
                ],
              ),
              const SizedBox(height: 8),
              Text(detail),
            ],
          ),
        ),
      );
  Widget button(
    String text,
    VoidCallback action, {
    IconData icon = Icons.play_arrow,
  }) => Padding(
    padding: const EdgeInsets.symmetric(vertical: 6),
    child: FilledButton.icon(
      onPressed: controller.busy ? null : action,
      icon: Icon(icon),
      label: Text(text),
    ),
  );
  Widget metric(String title, String value) =>
      SizedBox(width: 190, child: card(title, value));

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(
      title: Text(pages[page]),
      actions: [
        PopupMenuButton<String>(
          key: const Key('demo-backup-menu'),
          tooltip: 'نسخة Demo يدوية',
          enabled: controller.ready && !controller.busy,
          icon: const Icon(Icons.import_export),
          onSelected: (action) {
            if (action == 'export') { exportBackup(); }
            if (action == 'import') { importBackup(); }
          },
          itemBuilder: (_) => [
            const PopupMenuItem(value: 'export', child: Text('نسخ نسخة Demo إلى الحافظة')),
            PopupMenuItem(value: 'import', enabled: !controller.storageUncertain,
              child: const Text('استيراد نسخة Demo من JSON')),
          ],
        ),
        PopupMenuButton<String>(
          tooltip: 'مظهر التطبيق',
          icon: const Icon(Icons.brightness_6_outlined),
          onSelected: (s) => act((e) => e.theme = s),
          itemBuilder: (_) => const [
            PopupMenuItem(value: 'dark', child: Text('الوضع الداكن')),
            PopupMenuItem(value: 'light', child: Text('الوضع الفاتح')),
            PopupMenuItem(value: 'system', child: Text('اتباع مظهر النظام')),
          ],
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
                    style: TextStyle(fontSize: 23, fontWeight: FontWeight.bold),
                  ),
                  SizedBox(height: 12),
                  Text('V1.0 • Demo محلي بلا إنترنت'),
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
                },
              ),
            const Divider(),
            ListTile(
              leading: const Icon(Icons.dns_outlined),
              title: const Text('خادم Mock اختياري'),
              subtitle: const Text('وضع منفصل؛ لا ينقل حسابات Demo'),
              onTap: () {
                Navigator.pop(context);
                controller.pause();
                widget.onBackend();
              },
            ),
          ],
        ),
      ),
    ),
    body: SafeArea(
      child: Column(
        children: [
          Container(
            width: double.infinity,
            color: Theme.of(context).colorScheme.secondaryContainer,
            padding: const EdgeInsets.all(12),
            child: const Text(
              'Demo محلي • بيانات وأموال اصطناعية • بلا وسيط أو إنترنت • Live مقفل',
              key: Key('local-demo-banner'),
            ),
          ),
          if (controller.ready && engine.accounts.isNotEmpty)
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 16),
              child: DropdownButtonFormField<String>(
                key: ValueKey(selected),
                initialValue: selected,
                isExpanded: true,
                decoration: const InputDecoration(
                  labelText: 'الحساب المحلي النشط',
                ),
                items: engine.accounts
                    .map(
                      (a) => DropdownMenuItem<String>(
                        value: a['id'],
                        child: Text(a['name']),
                      ),
                    )
                    .toList(),
                onChanged: controller.busy
                    ? null
                    : (v) => setState(() {
                        selected = v;
                        replay = null;
                      }),
              ),
            ),
          if (controller.busy) const LinearProgressIndicator(),
          if (controller.error != null)
            Padding(
              padding: const EdgeInsets.all(12),
              child: Semantics(
                liveRegion: true,
                child: Text(
                  controller.error!,
                  style: TextStyle(color: Theme.of(context).colorScheme.error),
                ),
              ),
            ),
          if (controller.storageUncertain)
            TextButton(key: const Key('demo-backup-reload-storage'),
              onPressed: controller.busy ? null : controller.load,
              child: const Text('إعادة قراءة التخزين بعد تصدير النسخة الحالية')),
          Expanded(
            child: ListView(
              padding: const EdgeInsets.all(16),
              children: !controller.ready
                  ? [
                      const Text(
                        'جارٍ فتح الحفظ المحلي. لا يُطلب اتصال بالشبكة.',
                      ),
                      if (!controller.busy)
                        button('إعادة محاولة تحميل البيانات', controller.load),
                    ]
                  : content(),
            ),
          ),
          if (controller.ready)
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 0, 16, 8),
              child: Row(
                children: [
                  Expanded(
                    child: OutlinedButton.icon(
                      onPressed: controller.busy
                          ? null
                          : () => act((e) => e.step()),
                      icon: const Icon(Icons.skip_next),
                      label: const Text('خطوة سوق محلية'),
                    ),
                  ),
                  const SizedBox(width: 8),
                  IconButton.filled(
                    tooltip: controller.playing
                        ? 'إيقاف الوقت'
                        : 'تشغيل الوقت المحلي',
                    onPressed: controller.playing
                        ? controller.pause
                        : controller.play,
                    icon: Icon(
                      controller.playing ? Icons.pause : Icons.play_arrow,
                    ),
                  ),
                ],
              ),
            ),
        ],
      ),
    ),
  );

  List<Widget> content() {
    final a = account, id = selected;
    if (page == 0) {
      final metrics = engine.accounts
          .map((a) => engine.performance(a['id']))
          .toList();
      return [
        card(
          'تجربة محلية جاهزة',
          'الحسابات والإعدادات محفوظة على هذا الجهاز. يتوقف الوقت عند إغلاق التطبيق. لا ترسل الأزرار أي أوامر خارجية.',
          icon: Icons.offline_bolt_outlined,
        ),
        Wrap(
          spacing: 8,
          children: [
            metric('الحسابات', '${engine.accounts.length}'),
            metric(
              'حقوق الحسابات الاصطناعية',
              money(metrics.fold<int>(0, (n, p) => n + (p['equity'] as int))),
            ),
            metric(
              'الربح والخسارة المحققة',
              money(metrics.fold<int>(0, (n, p) => n + (p['realized'] as int))),
            ),
            metric('الملاحظات المحلية', '${engine.tick}'),
          ],
        ),
        Text('وقت اصطناعي: ${engine.now.toIso8601String()}'),
        if (metrics.any((p) => p['stale'] == true))
          const Text('تحذير: التقييم يعرض آخر سعر معروف، وليس سعرًا حديثًا.'),
        button('إضافة حساب محلي', newAccount, icon: Icons.add),
        if (a != null)
          card(
            'ابدأ دورة التداول الوهمي',
            'فعّل الأتمتة من الاستراتيجيات، ثم شغّل الوقت أو تقدم خطوة. تُنفَّذ الإشارة في ملاحظة لاحقة مع فحص المخاطر والرسوم.',
            action: IconButton(
              onPressed: () => setState(() => page = 9),
              icon: const Icon(Icons.arrow_forward),
            ),
          ),
      ];
    }
    if (page == 1) {
      return [
        button('إضافة حساب محلي', newAccount, icon: Icons.add),
        const Text('الأرصدة اصطناعية. لا توجد كلمات مرور أو حسابات وسيط.'),
        ...engine.accounts.map(
          (item) => card(
            item['name'],
            'رصيد البداية: ${money(item['initial'])}\nالرصيد النقدي: ${money(item['cash'])}\n${item['known'] == true ? 'حالة محلية موثوقة' : 'تحتاج مصالحة'}',
            action: IconButton(
              tooltip: 'تغيير الاسم',
              icon: const Icon(Icons.edit_outlined),
              onPressed: () async {
                final values = await form('اسم الحساب المحلي', {
                  'الاسم': item['name'],
                });
                if (values != null && mounted) {
                  await act((e) => e.rename(item['id'], values['الاسم']!));
                }
              },
            ),
          ),
        ),
      ];
    }
    if (a == null || id == null) {
      return [const Text('أضف حسابًا محليًا للبدء.')];
    }
    final r = engine.risk(a), p = engine.performance(id);
    if (page == 2) {
      return [
        const Text(
          'إشارات كمية من 21 ملاحظة اصطناعية مكتملة. لا نموذج لغوي يملك سلطة التنفيذ.',
        ),
        ...engine
            .opportunities(id)
            .map(
              (o) => card(
                '${o['symbol']} • ${o['right']} • ${o['score']}/100',
                '${o['regime']}\n${o['reason']}\n${o['strategy'] == null ? 'فرصة مستبعدة' : label(o['strategy'])}',
              ),
            ),
        if (!engine.marketAvailable)
          const Text('السوق الاصطناعي منقطع؛ اكتشاف الفرص متوقف.'),
      ];
    }
    if (page == 3) {
      return [
        Wrap(
          spacing: 8,
          children: [
            button('شراء تجريبي', () => manualOrder(), icon: Icons.add),
            OutlinedButton(
              onPressed: () => setState(() => positionsTab = !positionsTab),
              child: Text(positionsTab ? 'عرض الأوامر' : 'عرض المراكز'),
            ),
          ],
        ),
        const Text(
          'أوامر Limit محلية. التنفيذ في خطوة لاحقة، وفق السيولة الجزئية المحددة، دون بيع مكشوف.',
        ),
        if (positionsTab)
          ...engine
              .rows(a, 'positions')
              .map(
                (pos) => card(
                  '${pos['symbol']} ${pos['right']} × ${pos['quantity']}',
                  'التكلفة مع عمولة الدخول: ${money(pos['cost'])}\nانتهاء: ${pos['expiry']}',
                  action: PopupMenuButton<String>(tooltip:'إدارة المركز',
                    onSelected:(v) {
                      if(v=='close') {manualOrder(position:pos);}
                      if(v=='scale') {act((e)=>e.scale(id,pos));}
                      if(v=='reverse') {act((e)=>e.requestReversal(id,pos['symbol'],
                        pos['right']=='CALL'?'PUT':'CALL','ui-$id-${e.sequence}-${e.tick}'));}
                    },
                    itemBuilder:(_)=>const [PopupMenuItem(value:'close',child:Text('إغلاق المملوك')),
                      PopupMenuItem(value:'scale',child:Text('تعزيز وفق المخاطر')),
                      PopupMenuItem(value:'reverse',child:Text('انعكاس بعد إغلاق ومصالحة'))]),
                ),
              )
        else
          ...engine
              .rows(a, 'orders')
              .reversed
              .map(
                (o) => card(
                  '${o['symbol']} • ${label(o['side'])} • ${label(o['status'])}',
                  'التنفيذ: ${o['filled']}/${o['quantity']} • الحد: ${money(o['limit'])}\nالرسوم: ${money(o['fees_paid'])}\nالسبب: ${label(o['reason'])}\n${o['id']}',
                  action: DemoEngine.active.contains(o['status'])
                      ? TextButton(
                          onPressed: () => act((e) => e.cancel(id, o['id'])),
                          child: const Text('إلغاء'),
                        )
                      : null,
                ),
              ),
        if (engine.rows(a, positionsTab ? 'positions' : 'orders').isEmpty)
          const Text('لا توجد سجلات بعد.'),
      ];
    }
    if (page == 4) {
      return [
        button('تعديل مخاطر الحساب', editRisk, icon: Icons.shield_outlined),
        card(
          'حدود الدخول',
          'مخاطرة الصفقة: ${r['trade_pct']}%\nالخسارة اليومية: ${r['daily_pct']}%\nتخصيص رأس المال: ${r['allocation_pct']}%\nالتعرض المفتوح: ${r['exposure_pct']}%\nحد العقود: ${r['max_contracts']}',
        ),
        card(
          'المشرف العام',
          '${(r['group'] as String).isEmpty ? 'لا مجموعة مرتبطة' : r['group']}\nحد التعرض: ${r['group_allocation_pct']}%\nحد الخسارة: ${r['group_daily_pct']}%',
        ),
        card(
          'قياس المخاطر الآن',
          'التعرض شامل حجوزات الشراء: ${money(p['exposure'])}\nالربح والخسارة غير المحققة: ${money(p['unrealized'])}',
        ),
        const Text(
          'الحدود مستقلة لكل حساب. المجموعة المرتبطة تستخدم أشد الحدود بين أعضائها. بيانات غير موثوقة تمنع التنفيذ.',
        ),
      ];
    }
    if (page == 5) {
      return [
        button('إضافة سهم', () async {
          final result = await form('كتالوج Demo فقط', {'رمز السهم': ''});
          if (result != null && mounted && selected == id) {
            await act((e) => e.watch(id, result['رمز السهم']!));
          }
        }, icon: Icons.add),
        Text(
          'الرموز المحلية المتاحة: ${DemoEngine.symbols.join('، ')}. التحقق محلي ولا يمثل صلاحيات بيانات وسيط.',
        ),
        ...((a['watch'] as Map).entries).map(
          (w) => Card(
            child: ListTile(
              title: Text(w.key),
              subtitle: Text(
                w.value == true ? 'فعال في المحاكاة المحلية' : 'متوقف',
              ),
              leading: Switch(
                value: w.value,
                onChanged: (v) => act((e) => e.watch(id, w.key, enabled: v)),
              ),
              trailing: IconButton(
                tooltip: 'حذف السهم',
                icon: const Icon(Icons.delete_outline),
                onPressed: () => act((e) => e.watch(id, w.key, remove: true)),
              ),
            ),
          ),
        ),
      ];
    }
    if (page == 6) {
      return [
        Wrap(
          spacing: 8,
          children: [
            metric('النقد', money(p['cash'])),
            metric('حقوق الحساب', money(p['equity'])),
            metric('محقق', money(p['realized'])),
            metric('غير محقق', money(p['unrealized'])),
            metric('العمولات', money(p['fees'])),
          ],
        ),
        const Text(
          'اختبار تاريخي اصطناعي من 120 ملاحظة، بمعلمات الحساب. دفتر مستقل؛ لا يغير الرصيد أو المراكز الحالية. يتضمن السبريد والانزلاق والعمولات، وتنفيذًا بعد الإشارة.',
        ),
        button('تشغيل الاختبار التاريخي المحلي', () {
          controller.pause();
          setState(() => replay = engine.backtest(id));
        }, icon: Icons.replay),
        if (replay != null) ...[
          card(
            'نتيجة إعادة التشغيل — ليست دليل ربحية',
            'صفقات مغلقة: ${replay!['trades']}\nربح وخسارة محققة: ${money(replay!['realized'])}\nعمولات: ${money(replay!['fees'])}\nأقصى تراجع: ${money(replay!['max_drawdown'])}\nمراكز مفتوحة: ${replay!['open_positions']}',
          ),
          SizedBox(
            height: 120,
            child: CustomPaint(
              painter: EquityPainter(
                (replay!['curve'] as List).cast<int>(),
                Theme.of(context).colorScheme.primary,
              ),
              child: const SizedBox.expand(),
            ),
          ),
        ],
        const Text(
          'التقييم الاصطناعي عند bid؛ لا يقيس سوق الخيارات أو ربحية استراتيجية حقيقية.',
        ),
      ];
    }
    if (page == 7) {
      return [
        const Text(
          'سجل محلي للقرارات والرفض والفرص الضائعة. يُحتفظ بآخر 2000 حدث تشخيصي لكل حساب؛ سجل الأوامر والصفقات مستقل.',
        ),
        ...engine
            .rows(a, 'audit')
            .reversed
            .take(100)
            .map((log) => card(log['event'], '${log['reason']}\n${log['at']}')),
      ];
    }
    if (page == 8) {
      return [
        card(
          'حالة الحساب',
          '${a['connected'] == true ? 'متصل اصطناعيًا' : 'انقطاع اصطناعي'} • ${a['known'] == true ? 'موثوق' : 'غير موثوق'}\n${a['stopped'] == true ? 'الدخول متوقف' : 'الدخول متاح وفق المخاطر'}',
        ),
        button(
          'إيقاف الحساب المحدد',
          () => act((e) => e.stop(id: id)),
          icon: Icons.stop_circle,
        ),
        button(
          'إيقاف جميع الحسابات',
          () => act((e) => e.stop()),
          icon: Icons.emergency,
        ),
        OutlinedButton(
          onPressed: () => act((e) => e.resume(id)),
          child: const Text('استئناف هذا الحساب بعد المصالحة'),
        ),
        if (engine.globalStop)
          OutlinedButton(
            onPressed: () => act((e) => e.globalStop = false),
            child: const Text('رفع الإيقاف العام — الحسابات تبقى متوقفة'),
          ),
        const Divider(),
        const Text('مختبر أعطال محلي — لا يقطع اتصالًا حقيقيًا'),
        button(
          'محاكاة انقطاع الحساب',
          () => act((e) => e.disconnect(id)),
          icon: Icons.link_off,
        ),
        button(
          'مصالحة وإعادة اتصال محلي',
          () => act((e) => e.reconcile(id)),
          icon: Icons.sync,
        ),
        SwitchListTile(
          title: const Text('توفر السوق الاصطناعي'),
          value: engine.marketAvailable,
          onChanged: (v) => act((e) => e.marketAvailable = v),
        ),
        button(
          'اختبار فقد استجابة أمر',
          () => act(
            (e) => e.submit(
              id,
              e.contract('NVDA', 'CALL'),
              'BUY',
              1,
              'fault-$id-${e.sequence + 1}',
              loseResponse: true,
            ),
          ),
          icon: Icons.science_outlined,
        ),
        const Text(
          'بعد فقد الاستجابة، تحقق من الأمر ثم صالح الحساب. لن يعاد إرساله تلقائيًا. الإيقاف يمنع الشراء ويتيح إغلاق المملوك فقط في حالة موثوقة.',
        ),
      ];
    }
    if (page == 12) {
      return [DemoResearchLab(key: ValueKey('research-$id'), engine: engine, accountId: id)];
    }
    if (page == 10) {
      return [
        DropdownButtonFormField<String>(initialValue:chartSymbol,
          decoration:const InputDecoration(labelText:'رمز مختبر الرسم'),
          items:DemoEngine.symbols.map((s)=>DropdownMenuItem(value:s,child:Text(s))).toList(),
          onChanged:(s)=>setState(()=>chartSymbol=s!)),
        DemoChartLab(key:ValueKey('$id-$chartSymbol'),engine:engine,symbol:chartSymbol),
      ];
    }
    if (page == 11) {
      return [
        const Text('لقطات القرار محفوظة وقت إرسال الأمر. افتح الصفقة لرؤية الدخول والإضافات والخروج دون تفسير لاحق مختلق.'),
        for(final trade in engine.rows(a,'trades').reversed) card(
          '${trade['symbol']} • ${money(trade['pnl'])}',
          '${trade['reason']} • الملاحظة ${trade['tick']}',
          action:TextButton(onPressed:()=>Navigator.push(context,MaterialPageRoute<void>(
            builder:(_)=>DemoDecisionReplay(engine:engine,trade:trade))),child:const Text('إعادة القرار'))),
        if(engine.rows(a,'trades').isEmpty) const Text('لا صفقات مغلقة بعد. نفّذ دورة تجريبية لعرض قراراتها.'),
        for(final v in engine.rows(a,'reversals')) card('انعكاس ${v['symbol']}',
          '${v['state']} • ${v['right']} • مفتاح ${v['request_key']}'),
      ];
    }
    return [
      SwitchListTile(
        key: const Key('demo-automation'),
        title: const Text('تداول وهمي آلي لهذا الحساب'),
        subtitle: const Text(
          'من الفرصة الكمية إلى المخاطر والأمر ثم الخروج المحلي',
        ),
        value: r['automation'],
        onChanged: (v) => act((e) => e.configure(id, {'automation': v})),
      ),
      SwitchListTile(title:const Text('انعكاس آلي بعد إغلاق ومصالحة'),
        subtitle:const Text('إشارة كمية معاكسة صالحة؛ التنفيذ الجديد ينتظر الإغلاق الكامل'),
        value:r['reversal_enabled'],onChanged:(v)=>act((e)=>e.configure(id,{'reversal_enabled':v}))),
      SwitchListTile(title:const Text('تعزيز المراكز الرابحة'),
        subtitle:const Text('معطل افتراضيًا؛ يشمل المخاطر والحجوزات والتهدئة'),
        value:r['scaling_enabled'],onChanged:(v)=>act((e)=>e.configure(id,{'scaling_enabled':v}))),
      SwitchListTile(title:const Text('إضافات متناقصة'),value:r['scaling_decreasing'],
        onChanged:(v)=>act((e)=>e.configure(id,{'scaling_decreasing':v}))),
      DropdownButtonFormField<String>(initialValue:r['entry_profile'],
        decoration:const InputDecoration(labelText:'ملف الدخول — لا يغير حجم المخاطرة'),
        items:const [DropdownMenuItem(value:'conservative',child:Text('محافظ — اختراق فقط')),
          DropdownMenuItem(value:'balanced',child:Text('متوازن')),
          DropdownMenuItem(value:'opportunistic',child:Text('انتهازي — قواعد كمية'))],
        onChanged:(v)=>act((e)=>e.configure(id,{'entry_profile':v}))),
      DropdownButtonFormField<String>(initialValue:r['entry_method'],
        decoration:const InputDecoration(labelText:'توقيت الدخول'),
        items:const [DropdownMenuItem(value:'early',child:Text('مبكر')),
          DropdownMenuItem(value:'confirmed',child:Text('مؤكد بملاحظتين')),
          DropdownMenuItem(value:'pullback',child:Text('تراجع'))],
        onChanged:(v)=>act((e)=>e.configure(id,{'entry_method':v}))),
      for (final s in ['breakout', 'pullback'])
        CheckboxListTile(
          title: Text(label(s)),
          value: (r['strategies'] as List).contains(s),
          onChanged: (v) => act((e) {
            final list = List<String>.from(r['strategies']);
            if (v == true) {
              list.add(s);
            } else {
              list.remove(s);
            }
            e.configure(id, {'strategies': list});
          }),
        ),
      DropdownButtonFormField<String>(
        isExpanded: true,
        initialValue: r['holding'],
        decoration: const InputDecoration(labelText: 'سياسة الاحتفاظ'),
        items: const [
          DropdownMenuItem(
            value: 'intraday',
            child: Text('داخل الجلسة الاصطناعية'),
          ),
          DropdownMenuItem(value: 'swing', child: Text('عدة جلسات اصطناعية')),
        ],
        onChanged: (v) => act((e) => e.configure(id, {'holding': v})),
      ),
      DropdownButtonFormField<String>(
        isExpanded: true,
        initialValue: r['mode'],
        decoration: const InputDecoration(labelText: 'وضع الحساب المحلي'),
        items: const [
          DropdownMenuItem(value: 'demo', child: Text('Demo — تنفيذ وهمي')),
          DropdownMenuItem(
            value: 'observe',
            child: Text('مراقبة دون دخول جديد'),
          ),
        ],
        onChanged: (v) => act((e) => e.configure(id, {'mode': v})),
      ),
      button(
        'قواعد التنفيذ والخروج والتكاليف',
        editExecution,
        icon: Icons.tune,
      ),
      card(
        'الإعدادات الحالية',
        'وقف الخسارة: ${r['stop_pct']}% • جني الربح: ${r['take_pct']}%\nالكمية: ${r['quantity']} • التنفيذ الجزئي: ${r['fill_chunk']}\nالعمولة: ${money(r['commission'])} • الانزلاق: ${money(r['slippage'])}',
      ),
      DropdownButtonFormField<String>(
        isExpanded: true,
        initialValue: engine.scenario,
        decoration: const InputDecoration(
          labelText: 'سيناريو أسعار الخيارات الاصطناعي — لجميع الحسابات',
        ),
        items: const [
          DropdownMenuItem(value: 'flat', child: Text('مستقر')),
          DropdownMenuItem(value: 'wave', child: Text('متذبذب')),
          DropdownMenuItem(value: 'rally', child: Text('ارتفاع قيمة العقود')),
          DropdownMenuItem(value: 'drop', child: Text('انخفاض قيمة العقود')),
        ],
        onChanged: (v) => act((e) => e.scenario = v!),
      ),
      const SizedBox(height: 12),
      const Text(
        'الجلسة ثابتة ومصطنعة، وليست تقويم بورصة. الأسعار لا تستخدم نموذج تسعير خيارات حقيقيًا. لا IBKR ولا Paper ولا Live داخل Demo.',
      ),
    ];
  }
}

class _DemoBackupInputDialog extends StatefulWidget {
  const _DemoBackupInputDialog();
  @override
  State<_DemoBackupInputDialog> createState() => _DemoBackupInputDialogState();
}

class _DemoBackupInputDialogState extends State<_DemoBackupInputDialog> {
  final input = TextEditingController();
  String? error;
  bool reading = false;

  @override
  void dispose() { input.dispose(); super.dispose(); }

  Future<void> paste() async {
    setState(() { reading = true; error = null; });
    try {
      final data = await Clipboard.getData(Clipboard.kTextPlain);
      if (!mounted) return;
      final text = data?.text;
      if (text == null || text.isEmpty || text.length > DemoBackup.maxBytes) {
        setState(() => error = 'الحافظة فارغة أو النسخة أكبر من الحد المسموح');
      } else {
        input.text = text;
      }
    } catch (_) {
      if (mounted) setState(() => error = 'تعذر قراءة الحافظة؛ يمكنك لصق JSON يدويًا');
    } finally {
      if (mounted) setState(() => reading = false);
    }
  }

  @override
  Widget build(BuildContext context) => AlertDialog(
    title: const Text('استيراد نسخة Demo يدوية'),
    content: SingleChildScrollView(child: Column(mainAxisSize: MainAxisSize.min, children: [
      const Text('الصق JSON الذي صدّرته من Demo فقط، بحد أقصى 2 MiB. '
        'لا تدخل عنوان خادم أو كلمة مرور أو رمز وصول. لن تتغير البيانات قبل المعاينة والتأكيد.'),
      TextField(key: const Key('demo-backup-input'), controller: input,
        maxLines: 5, textDirection: TextDirection.ltr,
        decoration: const InputDecoration(labelText: 'JSON النسخة المحلية')),
      OutlinedButton(key: const Key('demo-backup-paste'), onPressed: reading ? null : paste,
        child: const Text('لصق من الحافظة')),
      if (error != null) Text(error!),
    ])),
    actions: [
      TextButton(onPressed: () => Navigator.pop(context), child: const Text('إلغاء')),
      FilledButton(key: const Key('demo-backup-preview'),
        onPressed: reading ? null : () => Navigator.pop(context, input.text),
        child: const Text('معاينة النسخة')),
    ],
  );
}

class EquityPainter extends CustomPainter {
  final List<int> values;
  final Color color;
  EquityPainter(this.values, this.color);
  @override
  void paint(Canvas canvas, Size size) {
    if (values.length < 2) return;
    final low = values.reduce((a, b) => a < b ? a : b),
        high = values.reduce((a, b) => a > b ? a : b);
    final span = high == low ? 1 : high - low;
    final path = Path();
    for (var i = 0; i < values.length; i++) {
      final x = i * size.width / (values.length - 1),
          y = size.height - 4 - (values[i] - low) / span * (size.height - 8);
      if (i == 0) {
        path.moveTo(x, y);
      } else {
        path.lineTo(x, y);
      }
    }
    canvas.drawPath(
      path,
      Paint()
        ..color = color
        ..style = PaintingStyle.stroke
        ..strokeWidth = 2,
    );
  }

  @override
  bool shouldRepaint(covariant EquityPainter old) =>
      old.values != values || old.color != color;
}
