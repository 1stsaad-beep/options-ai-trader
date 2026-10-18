import 'package:flutter/material.dart';
import 'package:trader_core/trader_core.dart';

import '../services/app_controller.dart';

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

  Widget _num(String key, String label, {String? help, bool integer = false, String suffix = ''}) {
    final c = _text.putIfAbsent(key, () => TextEditingController(text: '${_v[key]}'));
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 6),
      child: TextField(
        controller: c,
        keyboardType: const TextInputType.numberWithOptions(decimal: true),
        textDirection: TextDirection.ltr,
        decoration: InputDecoration(labelText: label, helperText: help, helperMaxLines: 3, suffixText: suffix),
        onChanged: (t) {
          final n = num.tryParse(t.trim());
          if (n != null) _v[key] = integer ? n.toInt() : n.toDouble();
        },
      ),
    );
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
        actions: [TextButton(onPressed: _save, child: const Text('حفظ'))],
      ),
      body: ListView(
        padding: const EdgeInsets.all(12),
        children: [
          _section('المخاطرة وحجم الصفقة', [
            _num('riskPerTradePercent', 'نسبة المخاطرة لكل صفقة', suffix: '%',
                help: 'أقصى خسارة مقبولة للصفقة من قيمة الحساب (العلاوة × نسبة وقف الخسارة)'),
            _num('maxPositionPercent', 'أقصى حجم للمركز الواحد', suffix: '%'),
            _num('maxContractsPerTrade', 'أقصى عدد عقود للصفقة', integer: true),
            _num('maxOpenPositions', 'أقصى عدد صفقات مفتوحة', integer: true),
            _num('maxTotalExposurePercent', 'أقصى تعرض كلي', suffix: '%'),
            _num('dailyLossLimitPercent', 'حد الخسارة اليومي', suffix: '%', help: 'يوقف الدخول الجديد لبقية اليوم'),
          ]),
          _section('معايير الدخول', [
            DropdownButtonFormField<String>(
              initialValue: _v['timeframe'] as String,
              decoration: const InputDecoration(labelText: 'الإطار الزمني للتحليل'),
              items: const [
                DropdownMenuItem(value: 'm5', child: Text('5 دقائق')),
                DropdownMenuItem(value: 'm15', child: Text('15 دقيقة')),
                DropdownMenuItem(value: 'h1', child: Text('ساعة')),
                DropdownMenuItem(value: 'd1', child: Text('يومي')),
              ],
              onChanged: (t) => setState(() => _v['timeframe'] = t),
            ),
            _num('minScore', 'الحد الأدنى للنتيجة المركبة (0-100)'),
            _num('minAgreeingEngines', 'أقل عدد محركات متوافقة', integer: true),
            _flag('requireTrendAlignment', 'اشتراط توافق الاتجاه العام'),
            _flag('allowCalls', 'السماح بعقود Call'),
            _flag('allowPuts', 'السماح بعقود Put'),
          ]),
          _section('أوزان المحركات (0 = تعطيل)', [
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
            _num('minDaysToExpiry', 'أقل أيام حتى الانتهاء', integer: true),
            _num('maxDaysToExpiry', 'أقصى أيام حتى الانتهاء', integer: true),
            _num('targetDelta', 'الدلتا المستهدفة', help: '0.5 تقريبًا عند سعر التنفيذ (ATM)'),
            _num('maxSpreadPercent', 'أقصى فرق بين العرض والطلب', suffix: '%'),
            _num('minOpenInterest', 'أقل عدد عقود مفتوحة (OI)', integer: true),
            _num('entryAggressiveness', 'جرأة التسعير (0 = العرض، 1 = الطلب)'),
            _num('orderTimeoutCycles', 'إلغاء الأمر غير المنفذ بعد (دورات)', integer: true),
          ]),
          _section('الخروج', [
            _num('stopLossPercent', 'وقف الخسارة', suffix: '%', help: 'من سعر شراء العقد'),
            _num('partialTakeProfitPercent', 'جني ربح جزئي عند', suffix: '%'),
            _num('partialTakeProfitFraction', 'نسبة الكمية المباعة جزئيًا (0-0.9)'),
            _num('takeProfitPercent', 'هدف الربح الكامل', suffix: '%'),
            _num('trailingActivationPercent', 'تفعيل الوقف المتحرك عند ربح', suffix: '%'),
            _num('trailingStopPercent', 'الوقف المتحرك: تراجع من القمة', suffix: '%'),
            _flag('exitOnUnderlyingInvalidation', 'الخروج عند كسر مستوى إبطال النمط'),
            _flag('exitOnOppositeSignal', 'الخروج عند إشارة معاكسة'),
            _num('maxHoldingDays', 'أقصى مدة احتفاظ (أيام)', integer: true),
            _num('exitDaysBeforeExpiry', 'الإغلاق قبل الانتهاء بـ (أيام)', integer: true),
          ]),
          _section('التعزيز', [
            _flag('scaleInEnabled', 'تفعيل التعزيز للصفقات الرابحة'),
            _num('maxScaleIns', 'أقصى عدد تعزيزات', integer: true),
            _num('scaleInMinProfitPercent', 'أقل ربح للتعزيز', suffix: '%'),
            _num('scaleInMinScore', 'أقل نتيجة للتعزيز'),
            _num('scaleInFraction', 'حجم التعزيز نسبة للكمية الأولى'),
          ]),
          const SizedBox(height: 24),
          FilledButton(onPressed: _save, child: const Text('حفظ الإعدادات')),
          const SizedBox(height: 24),
        ],
      ),
    );
  }
}
