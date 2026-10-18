import 'package:flutter/material.dart';
import 'package:trader_core/trader_core.dart';

import '../services/app_controller.dart';

/// Shown on every main screen while the kill switch is on.
class KillSwitchBanner extends StatelessWidget {
  final AppController controller;
  const KillSwitchBanner({super.key, required this.controller});

  @override
  Widget build(BuildContext context) {
    if (!controller.killSwitch) return const SizedBox.shrink();
    final scheme = Theme.of(context).colorScheme;
    return Card(
      key: const Key('kill-switch-banner'),
      color: scheme.errorContainer,
      child: ListTile(
        leading: Icon(Icons.pan_tool, color: scheme.onErrorContainer),
        title: Text('الإيقاف الطارئ مفعّل', style: TextStyle(color: scheme.onErrorContainer, fontWeight: FontWeight.bold)),
        subtitle: Text('كل التداول الآلي متوقف لجميع الحسابات. لن تُرسل أي أوامر (دخول أو خروج). المراكز المفتوحة تبقى كما هي.',
            style: TextStyle(color: scheme.onErrorContainer)),
        trailing: FilledButton(
          onPressed: () => confirmResume(context, controller),
          child: const Text('استئناف'),
        ),
      ),
    );
  }
}

/// AppBar action: one tap pauses everything; resuming asks for confirmation.
class KillSwitchButton extends StatelessWidget {
  final AppController controller;
  const KillSwitchButton({super.key, required this.controller});

  @override
  Widget build(BuildContext context) => controller.killSwitch
      ? IconButton(
          key: const Key('kill-switch-resume'),
          tooltip: 'استئناف التداول الآلي',
          icon: const Icon(Icons.play_arrow),
          onPressed: () => confirmResume(context, controller),
        )
      : IconButton(
          key: const Key('kill-switch'),
          tooltip: 'إيقاف طارئ لكل التداول الآلي',
          icon: Icon(Icons.pan_tool, color: Theme.of(context).colorScheme.error),
          onPressed: () async {
            await controller.setKillSwitch(true);
            if (context.mounted) {
              ScaffoldMessenger.of(context)
                  .showSnackBar(const SnackBar(content: Text('تم الإيقاف الطارئ: توقف التداول الآلي لكل الحسابات')));
            }
          },
        );
}

Future<void> confirmResume(BuildContext context, AppController controller) async {
  final ok = await showDialog<bool>(
    context: context,
    builder: (c) => AlertDialog(
      title: const Text('استئناف التداول الآلي؟'),
      content: const Text('ستعود الحسابات المفعّلة إلى إرسال الأوامر في ساعات السوق حسب إعداداتها.'),
      actions: [
        TextButton(onPressed: () => Navigator.pop(c, false), child: const Text('إلغاء')),
        FilledButton(onPressed: () => Navigator.pop(c, true), child: const Text('استئناف')),
      ],
    ),
  );
  if (ok == true) await controller.setKillSwitch(false);
}

/// Background (foreground-service) control with battery guidance and limits.
class BackgroundCard extends StatefulWidget {
  final AppController controller;
  const BackgroundCard({super.key, required this.controller});

  @override
  State<BackgroundCard> createState() => _BackgroundCardState();
}

class _BackgroundCardState extends State<BackgroundCard> {
  bool? _batteryOk;

  @override
  void initState() {
    super.initState();
    _checkBattery();
  }

  Future<void> _checkBattery() async {
    final ok = await widget.controller.background.isIgnoringBatteryOptimizations();
    if (mounted) setState(() => _batteryOk = ok);
  }

  @override
  Widget build(BuildContext context) {
    final c = widget.controller;
    final supported = c.background.supported;
    return Card(
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        SwitchListTile(
          key: const Key('background-switch'),
          secondary: const Icon(Icons.notifications_active_outlined),
          title: const Text('التشغيل في الخلفية'),
          subtitle: Text(!supported
              ? 'متاح على أندرويد فقط'
              : c.backgroundRunning
                  ? 'يعمل — إشعار دائم، والدورات تستمر مع إطفاء الشاشة'
                  : 'متوقف — الدورات تعمل فقط والتطبيق مفتوح'),
          value: c.backgroundRunning,
          onChanged: !supported
              ? null
              : (v) async {
                  if (v) {
                    final err = await c.startBackground();
                    if (err != null && context.mounted) {
                      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(err)));
                    }
                  } else {
                    await c.stopBackground();
                  }
                  await _checkBattery();
                },
        ),
        if (supported && _batteryOk == false)
          ListTile(
            leading: const Icon(Icons.battery_alert_outlined),
            title: const Text('تحسين البطارية مفعّل لهذا التطبيق'),
            subtitle: const Text('قد يؤخر النظام الدورات. اختر "غير مقيّد" أو "عدم التحسين" لـ Options AI v2 إن أردت دقة أعلى.'),
            trailing: TextButton(
              onPressed: () async {
                await c.background.openBatterySettings();
                await _checkBattery();
              },
              child: const Text('الإعدادات'),
            ),
          ),
        if (c.backgroundError != null)
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 0, 16, 8),
            child: Text(c.backgroundError!, style: TextStyle(color: Theme.of(context).colorScheme.error)),
          ),
        Align(
          alignment: AlignmentDirectional.centerStart,
          child: TextButton(
            onPressed: () => showDialog<void>(
              context: context,
              builder: (d) => AlertDialog(
                title: const Text('حدود التشغيل في الخلفية'),
                content: const SingleChildScrollView(child: Text(backgroundLimitsAr)),
                actions: [TextButton(onPressed: () => Navigator.pop(d), child: const Text('حسنًا'))],
              ),
            ),
            child: const Text('ما حدود التشغيل في الخلفية؟'),
          ),
        ),
      ]),
    );
  }
}

const backgroundLimitsAr = '''• التداول يعمل على هاتفك فقط، بدون أي خادم. إذا أُغلق التطبيق أو أُعيد تشغيل الهاتف تتوقف الدورات حتى تفتحه مجددًا.
• إغلاق التطبيق بسحبه من قائمة التطبيقات الأخيرة يوقف الخدمة والتداول.
• بعض الشركات المصنعة (Xiaomi وHuawei وSamsung وغيرها) توقف التطبيقات في الخلفية بقوة؛ قد تحتاج للسماح بالتشغيل التلقائي وإلغاء تحسين البطارية.
• في وضع توفير الطاقة العميق (Doze) قد تتأخر الدورات أو الشبكة دقائق.
• تعمل دورة كل دقيقة تقريبًا، ولا ترسل أوامر إلا في ساعات السوق الرسمية (حتى 13:00 بتوقيت نيويورك في أيام الإغلاق المبكر).
• زر "إيقاف طارئ" في الإشعار يوقف كل التداول الآلي فورًا، وزر "إيقاف الخدمة" يوقف التشغيل في الخلفية فقط.''';

/// Clear summary of an account's risk and safety settings.
class RiskSettingsCard extends StatelessWidget {
  final AccountRuntime rt;
  final bool killSwitch;
  final VoidCallback? onEdit;
  const RiskSettingsCard({super.key, required this.rt, required this.killSwitch, this.onEdit});

  @override
  Widget build(BuildContext context) {
    final s = rt.profile.settings;
    final st = rt.state;
    final today = NewYorkTime.dateKey(DateTime.now().toUtc());
    final ordersToday = st.ordersDayKey == today ? st.ordersToday : 0;
    final rights = [if (s.allowCalls) 'Call', if (s.allowPuts) 'Put'];
    final rows = <(String, String)>[
      ('الإيقاف الطارئ', killSwitch ? 'مفعّل — لا أوامر' : 'غير مفعّل'),
      ('المخاطرة لكل صفقة', '${s.riskPerTradePercent}% من قيمة الحساب'),
      ('أقصى حجم للمركز', '${s.maxPositionPercent}%'),
      ('أقصى صفقات مفتوحة', '${rt.positions.length} / ${s.maxOpenPositions}'),
      ('أوامر الفتح اليوم', '$ordersToday / ${s.maxOrdersPerDay}'),
      ('فترة التهدئة لكل سهم', s.symbolCooldownMinutes == 0 ? 'معطلة' : '${s.symbolCooldownMinutes} دقيقة بعد كل دخول/خروج'),
      ('حد الخسارة اليومي', '${s.dailyLossLimitPercent}%'),
      ('وقف الخسارة', '${s.stopLossPercent}% من سعر العقد'),
      ('الأنواع المسموحة', rights.isEmpty ? 'لا شيء' : rights.join(' و ')),
      ('قفل الاتجاه', 'لا يُفتح Call وPut على نفس السهم معًا'),
      ('التداول الحقيقي', LiveTradingGuard.buildAllowsLive ? 'متاح بشروط' : 'مقفل في هذه النسخة'),
    ];
    return Card(
      key: const Key('risk-card'),
      child: Padding(
        padding: const EdgeInsets.fromLTRB(16, 8, 8, 8),
        child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          Row(children: [
            Expanded(child: Text('إعدادات المخاطر والأمان', style: Theme.of(context).textTheme.titleMedium)),
            if (onEdit != null) TextButton(onPressed: onEdit, child: const Text('تعديل')),
          ]),
          for (final (k, v) in rows)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 2),
              child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                SizedBox(width: 150, child: Text(k, style: Theme.of(context).textTheme.bodySmall)),
                Expanded(child: Text(v)),
              ]),
            ),
        ]),
      ),
    );
  }
}
