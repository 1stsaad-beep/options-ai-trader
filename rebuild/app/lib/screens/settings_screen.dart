import 'package:flutter/material.dart';
import 'package:trader_core/trader_core.dart';

import '../services/app_controller.dart';
import 'settings_help.dart';

/// Per-account risk, entry, exit and engine settings.
class SettingsScreen extends StatefulWidget {
  final AppController controller;
  final String accountId;
  const SettingsScreen({super.key, required this.controller, required this.accountId});

  @override
  State<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends State<SettingsScreen> {
  late Map<String, Object?> _v; // working copy of AccountSettings.toJson()
  late Map<String, double> _weights;
  final Map<String, TextEditingController> _text = {};

  @override
  void initState() {
    super.initState();
    final s = widget.controller.account(widget.accountId)!.profile.settings;
    _v = Map<String, Object?>.from(s.toJson());
    _weights = {for (final e in s.engineWeights.entries) e.key.name: e.value};
  }

  @override
  void dispose() {
    for (final c in _text.values) {
      c.dispose();
    }
    super.dispose();
  }

  AccountSettings _build() =>
      AccountSettings.fromJson({..._v, 'engineWeights': _weights}.cast<String, dynamic>());

  Widget _num(String key, {bool integer = false}) {
    final h = settingsHelp[key]!;
    final c = _text.putIfAbsent(key, () => TextEditingController(text: '${_v[key]}'));
    final range = AccountSettings.allowedRanges[key];
    final rangeText = [
      if (range != null) 'المسموح: ${range.$1}–${range.$2}',
      if (h.suggested != null) 'المقترح: ${h.suggested}',
    ].join(' • ');
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 6),
      child: TextField(
        key: Key('setting-$key'),
        controller: c,
        keyboardType: const TextInputType.numberWithOptions(decimal: true),
        textDirection: TextDirection.ltr,
        decoration: InputDecoration(
          labelText: h.label,
          helperText: rangeText.isEmpty ? h.explain : '${h.explain}\n$rangeText',
          helperMaxLines: 5,
          suffixText: h.suffix,
        ),
        onChanged: (t) {
          final n = num.tryParse(t.trim());
          if (n != null) _v[key] = integer ? n.toInt() : n.toDouble();
        },
      ),
    );
  }

  void _applyElliottPreset() {
    final p = _build().withElliottDailyPreset();
    setState(() {
      _v = Map<String, Object?>.from(p.toJson());
      for (final e in _text.entries) {
        e.value.text = '${_v[e.key]}';
      }
    });
    ScaffoldMessenger.maybeOf(context)?.showSnackBar(const SnackBar(
        content: Text('طُبّقت الإعدادات المقترحة (عقود أسبوعية 2–9 أيام، احتفاظ حتى 7 أيام، خروج قبل الانتهاء بيوم، وقف طوارئ 90%). اضغط "حفظ".')));
  }

  Future<void> _resetDefaults() async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (c) => AlertDialog(
        title: const Text('استعادة الإعدادات الافتراضية؟'),
        content: const Text('ستعود كل قيم المخاطرة والدخول والخروج وأوزان المحركات إلى القيم الافتراضية المحافظة. '
            'قائمة الأسهم والمفاتيح لا تتغير. لن يُحفظ شيء حتى تضغط "حفظ".'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(c, false), child: const Text('إلغاء')),
          FilledButton(onPressed: () => Navigator.pop(c, true), child: const Text('استعادة')),
        ],
      ),
    );
    if (ok != true) return;
    const d = AccountSettings();
    setState(() {
      _v = Map<String, Object?>.from(d.toJson());
      _weights = {for (final e in d.engineWeights.entries) e.key.name: e.value};
      for (final e in _text.entries) {
        e.value.text = '${_v[e.key]}';
      }
    });
  }

  Widget _flag(String key, String label, {String? help}) => SwitchListTile(
        contentPadding: EdgeInsets.zero,
        title: Text(label),
        subtitle: help == null ? null : Text(help),
        value: _v[key] as bool,
        onChanged: (b) => setState(() => _v[key] = b),
      );

  Widget _section(String title, List<Widget> children) => Card(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(16, 8, 16, 12),
          child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            Padding(
                padding: const EdgeInsets.symmetric(vertical: 8),
                child: Text(title, style: Theme.of(context).textTheme.titleMedium)),
            ...children,
          ]),
        ),
      );

  Future<void> _save() async {
    final s = _build();
    final errors = s.validate();
    if (errors.isNotEmpty) {
      await showDialog<void>(
        context: context,
        builder: (c) => AlertDialog(
          title: const Text('إعدادات غير صالحة'),
          content: Text(errors.join('\n')),
          actions: [TextButton(onPressed: () => Navigator.pop(c), child: const Text('حسنًا'))],
        ),
      );
      return;
    }
    final rt = widget.controller.account(widget.accountId)!;
    await widget.controller.updateProfile(rt.profile.copyWith(settings: s));
    if (mounted) Navigator.pop(context);
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('إعدادات الحساب'),
        actions: [
          IconButton(
            key: const Key('reset-defaults'),
            tooltip: 'استعادة الافتراضي',
            icon: const Icon(Icons.restart_alt),
            onPressed: _resetDefaults,
          ),
          TextButton(onPressed: _save, child: const Text('حفظ')),
        ],
      ),
      body: ListView(
        padding: const EdgeInsets.all(12),
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(4, 0, 4, 8),
            child: Text('كل قيمة تُفحص عند الحفظ ضمن النطاق المسموح. القيم "المقترحة" محافظة وليست توصية استثمارية. '
                'التداول الحقيقي مقفل في هذه النسخة؛ الإعدادات تعمل على حساب Paper أو المحاكي.',
                style: Theme.of(context).textTheme.bodySmall),
          ),
          _section('الاستراتيجية', [
            DropdownButtonFormField<String>(
              key: const Key('setting-strategy'),
              initialValue: _v['strategy'] as String,
              decoration: const InputDecoration(labelText: 'استراتيجية الدخول', helperMaxLines: 4),
              items: const [
                DropdownMenuItem(value: 'composite', child: Text('المركّبة (المحركات الستة) — الافتراضية')),
                DropdownMenuItem(value: 'elliottDaily', child: Text('إليوت اليومي — تجريبية')),
              ],
              onChanged: (k) => setState(() => _v['strategy'] = k),
            ),
            if (_v['strategy'] == 'elliottDaily') ...[
              Card(
                color: Theme.of(context).colorScheme.errorContainer,
                child: const Padding(
                  padding: EdgeInsets.all(12),
                  child: Text('تجريبية — للحساب الورقي (Paper) فقط. القاعدة: نهاية الموجة 2 على الشموع اليومية (a-b-c) مع انحراف RSI '
                      'إيجابي ← شراء Call أسبوعي يُحتفظ به نحو 5 جلسات. نتائج البحث (أسعار عقود نموذجية وليست حقيقية) إيجابية في '
                      'فترات الاكتشاف والتحقق والاختبار النهائي، لكنها حساسة لإعداد حجم الموجات وعدد الصفقات قليل '
                      '(بضع إشارات لكل سهم في السنة). نسخة Put معاكسة كانت خاسرة. التفاصيل في ROUND5.md.'),
                ),
              ),
              _num('elliottZigZagAtr'),
              _num('elliottFineAtr'),
              _flag('elliottRequireWeeklyContext', 'اشتراط دافعة أسبوعية صاعدة',
                  help: 'فلتر إضافي من الدرجة الأعلى؛ قلّل الإشارات ولم يحسّن النتائج في البحث'),
              _flag('elliottAllowPuts', 'السماح بالنسخة المعاكسة (Put عند نهاية C)', help: 'كانت خاسرة في البحث — غير مُوصى بها'),
              OutlinedButton.icon(
                key: const Key('elliott-preset'),
                onPressed: _applyElliottPreset,
                icon: const Icon(Icons.auto_fix_high),
                label: const Text('تطبيق الإعدادات المقترحة لهذه الاستراتيجية'),
              ),
            ],
          ]),
          _section('حالة الحساب', [
            _flag('pauseNewEntries', 'إيقاف مؤقت للدخول الجديد',
                help: 'لا صفقات جديدة ولا تعزيز، مع استمرار إدارة الخروج ووقف الخسارة للمراكز المفتوحة'),
          ]),
          _section('المخاطرة وحجم الصفقة', [
            _num('riskPerTradePercent'),
            _num('maxPositionPercent'),
            _num('maxContractsPerTrade', integer: true),
            _num('maxTotalExposurePercent'),
            _num('dailyLossLimitPercent'),
          ]),
          _section('حدود الأمان', [
            _num('maxOpenPositions', integer: true),
            _num('maxOrdersPerDay', integer: true),
            _num('symbolCooldownMinutes', integer: true),
            const ListTile(
              contentPadding: EdgeInsets.zero,
              leading: Icon(Icons.lock_outline),
              title: Text('قفل الاتجاه (ثابت)'),
              subtitle: Text('لا يُفتح Call وPut على نفس السهم في نفس الوقت، ولا يُرسل أي أمر خارج ساعات السوق الرسمية.'),
            ),
          ]),
          _section('معايير الدخول', [
            DropdownButtonFormField<String>(
              initialValue: _v['timeframe'] as String,
              decoration: const InputDecoration(
                  labelText: 'الإطار الزمني للتحليل',
                  helperText: 'حجم الشمعة التي تحللها المحركات؛ الأطر الأكبر إشارات أقل وأبطأ وأكثر ثباتًا',
                  helperMaxLines: 3),
              items: const [
                DropdownMenuItem(value: 'm5', child: Text('5 دقائق')),
                DropdownMenuItem(value: 'm15', child: Text('15 دقيقة')),
                DropdownMenuItem(value: 'h1', child: Text('ساعة')),
                DropdownMenuItem(value: 'd1', child: Text('يومي')),
              ],
              onChanged: (t) => setState(() => _v['timeframe'] = t),
            ),
            _num('minScore'),
            _num('minAgreeingEngines', integer: true),
            _flag('requireTrendAlignment', 'اشتراط توافق الاتجاه العام', help: 'لا دخول عكس اتجاه محرك الاتجاه'),
            _flag('allowCalls', 'السماح بعقود Call', help: 'رهان على الصعود'),
            _flag('allowPuts', 'السماح بعقود Put', help: 'رهان على الهبوط'),
          ]),
          _section('أوزان المحركات (0 = تعطيل، 0–3)', [
            Text('الوزن يحدد تأثير كل محرك في النتيجة المركبة.', style: Theme.of(context).textTheme.bodySmall),
            for (final id in EngineId.values)
              Row(children: [
                SizedBox(width: 130, child: Text(id.arabic)),
                Expanded(
                  child: Slider(
                    value: (_weights[id.name] ?? 1).clamp(0, 3).toDouble(),
                    max: 3,
                    divisions: 12,
                    label: (_weights[id.name] ?? 1).toStringAsFixed(2),
                    onChanged: (x) => setState(() => _weights[id.name] = x),
                  ),
                ),
                SizedBox(width: 40, child: Text((_weights[id.name] ?? 1).toStringAsFixed(2), textDirection: TextDirection.ltr)),
              ]),
          ]),
          _section('اختيار العقد', [
            _num('minDaysToExpiry', integer: true),
            _num('maxDaysToExpiry', integer: true),
            _num('targetDelta'),
            _num('maxSpreadPercent'),
            _num('minOpenInterest', integer: true),
            _num('entryAggressiveness'),
            _num('orderTimeoutCycles', integer: true),
          ]),
          _section('فلتر التقلب IV/RV (اختياري)', [
            Text('القياس يُسجَّل دائمًا في سجل القرارات لكل دخول (IV وRV والنسبة والعرض/الطلب وفرقهما). '
                'المنع لا يحدث إلا إذا فعّلت الفلتر هنا. بحث الجولة الرابعة: الفلتر لم يفصل الرابح عن الخاسر بثبات، فجرّبه على Paper أولًا.',
                style: Theme.of(context).textTheme.bodySmall),
            _flag('ivRvFilterEnabled', 'تفعيل فلتر التقلب',
                help: 'منع شراء العقود الغالية مقارنة بالتقلب الفعلي للسهم؛ ويمنع الدخول إذا تعذر القياس'),
            _num('maxIvRvRatio'),
            _num('rvLookbackDays', integer: true),
            _flag('rvUseIntraday', 'حساب RV من شموع إطار التحليل',
                help: 'بدل الشموع اليومية؛ أكثر حساسية للتقلب الحالي (يتطلب إطارًا أصغر من اليومي)'),
            _num('maxBreakevenToExpectedMove'),
          ]),
          _section('الخروج', [
            _num('stopLossPercent'),
            _num('partialTakeProfitPercent'),
            _num('partialTakeProfitFraction'),
            _num('takeProfitPercent'),
            _num('trailingActivationPercent'),
            _num('trailingStopPercent'),
            _flag('exitOnUnderlyingInvalidation', 'الخروج عند كسر مستوى إبطال النمط',
                help: 'إذا كسر سعر السهم المستوى الذي يلغي فكرة الصفقة'),
            _flag('exitOnOppositeSignal', 'الخروج عند إشارة معاكسة', help: 'إذا انقلبت النتيجة المركبة بقوة في الاتجاه الآخر'),
            _num('maxHoldingDays', integer: true),
            _num('exitDaysBeforeExpiry', integer: true),
          ]),
          _section('التعزيز', [
            _flag('scaleInEnabled', 'تفعيل التعزيز للصفقات الرابحة', help: 'يُحسب ضمن أقصى أوامر الفتح اليومية'),
            _num('maxScaleIns', integer: true),
            _num('scaleInMinProfitPercent'),
            _num('scaleInMinScore'),
            _num('scaleInFraction'),
          ]),
          OutlinedButton.icon(
            onPressed: _resetDefaults,
            icon: const Icon(Icons.restart_alt),
            label: const Text('استعادة الإعدادات الافتراضية'),
          ),
          const SizedBox(height: 24),
          FilledButton(onPressed: _save, child: const Text('حفظ الإعدادات')),
          const SizedBox(height: 24),
        ],
      ),
    );
  }
}
