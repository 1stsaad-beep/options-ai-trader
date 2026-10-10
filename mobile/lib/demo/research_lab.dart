import 'package:flutter/material.dart';
import 'engine.dart';
import 'research_analysis.dart';

class DemoResearchLab extends StatefulWidget {
  final DemoEngine engine;
  final String accountId;
  const DemoResearchLab({super.key, required this.engine, required this.accountId});
  @override
  State<DemoResearchLab> createState() => _DemoResearchLabState();
}

class _DemoResearchLabState extends State<DemoResearchLab> {
  String symbol = 'NVDA', right = 'CALL';
  double spotChange = 0, ivChange = 0;
  int elapsedDays = 1;

  String number(dynamic value) => value is num ? value.toStringAsFixed(2) : 'غير متاح';
  String method(String name) => switch (name) {
    'early' => 'دخول مبكر', 'confirmed' => 'دخول مؤكد', _ => 'دخول بعد تراجع',
  };
  Widget section(String title, List<Widget> body, {bool expanded = false}) => Card(
    child: ExpansionTile(title: Text(title), initiallyExpanded: expanded,
      childrenPadding: const EdgeInsets.all(12),
      children: body.map((w) => Padding(padding: const EdgeInsets.only(bottom: 10), child: w)).toList()),
  );

  @override
  Widget build(BuildContext context) {
    final engine = widget.engine;
    final account = engine.account(widget.accountId), risk = engine.risk(account);
    final data = DemoResearchAnalysis.build(engine, widget.accountId, symbol);
    final analysis = Map<String, dynamic>.from(data['analysis'] as Map);
    final tournament = Map<String, dynamic>.from(data['tournament'] as Map);
    final pairs = (data['correlation_pairs'] as List).cast<DemoRow>();
    final failures = List<String>.from(data['hard_failures'] as List);
    final quote = engine.marketAvailable ? engine.quote(engine.contract(symbol, right)) : null;
    final twin = quote == null ? null : DemoResearchAnalysis.optionTwin(
      spot: engine.underlying(symbol, engine.tick) / 100,
      premium: ((quote['bid'] as int) + (quote['ask'] as int)) / 200,
      right: right, spotChangePct: spotChange, elapsedDays: elapsedDays,
      ivChangePoints: ivChange, commissionCents: risk['commission'] as int,
      slippageCents: risk['slippage'] as int,
      spread: ((quote['ask'] as int) - (quote['bid'] as int)) / 100,
    );
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      const Text('مختبر أبحاث محلي • Shadow', key: Key('research-shadow-banner'),
        style: TextStyle(fontWeight: FontWeight.bold)),
      const Text('اصطناعي، بلا شبكة، للقراءة فقط. هذه الشاشة لا تنفّذ صفقات ولا تمنح إذن تداول.'),
      Text('الحساب: ${account['name']} • الملاحظة: ${data['as_of_tick']}'),
      DropdownButtonFormField<String>(key: const Key('research-symbol'), initialValue: symbol,
        decoration: const InputDecoration(labelText: 'رمز الكتالوج الاصطناعي'),
        items: DemoEngine.symbols.map((s) => DropdownMenuItem(value: s, child: Text(s))).toList(),
        onChanged: (s) { if (s != null) setState(() => symbol = s); }),
      section('مشرف السلامة ودرجة الثقة', [
        Text('درجة صحة البوابات التشخيصية: ${data['trust_score']}/100'),
        Text(failures.isEmpty ? 'لا عطل في البوابات المعروضة؛ يلزم فحص المخاطر الكامل عند أي أمر.'
            : failures.join('\n'), key: const Key('research-hard-gates')),
        const Text('أي فشل إلزامي يخفض الدرجة إلى صفر. قوة الإشارة لا تعوّض فشل الأمان.'),
      ], expanded: true),
      section('مقارنة السيناريوهات وتوقيت الدخول', [
        for (final row in (analysis['scenario_battle'] as List).cast<DemoRow>())
          Text('${row['scenario']}: ${number(row['score'])} — درجة قواعد، ليست احتمالًا'),
        Text(analysis['directional_conflict'] == true ? 'تعارض اتجاهي: نعم' : 'تعارض اتجاهي: لا'),
        for (final row in (data['entry_methods'] as List).cast<DemoRow>())
          Text('${method(row['method'] as String)}: ${row['candidate'] == true ? 'مرشح كمي' : 'لا مرشح'}\n'
              'التفعيل بالسنت: ${row['activation'] ?? '—'} • الإلغاء: ${row['invalidation'] ?? '—'}\n'
              'صالح حتى الملاحظة: ${row['expires_tick'] ?? '—'} • ملف: ${row['profile']}'),
        const Text('الترتيب والمقارنة لا يعدّلان مخاطر الحساب أو استراتيجية الأتمتة.'),
      ]),
      section('Option Twin — سيناريو عقد واحد', [
        const Text('Greeks افتراضية معلنة: |Delta| 0.5، Gamma 0.01، Theta −0.04/يوم، Vega 0.08/نقطة IV.'),
        DropdownButtonFormField<String>(key: const Key('twin-right'), initialValue: right,
          decoration: const InputDecoration(labelText: 'نوع الخيار الافتراضي'),
          items: const [DropdownMenuItem(value: 'CALL', child: Text('CALL')),
            DropdownMenuItem(value: 'PUT', child: Text('PUT'))],
          onChanged: (v) { if (v != null) setState(() => right = v); }),
        Text('تغير سعر السهم: ${number(spotChange)}%'),
        Slider(key: const Key('twin-spot-change'), value: spotChange, min: -10, max: 10, divisions: 40,
          label: '${number(spotChange)}%', onChanged: (v) => setState(() => spotChange = v)),
        Text('الأيام المنقضية: $elapsedDays'),
        Slider(value: elapsedDays.toDouble(), min: 0, max: 7, divisions: 7,
          onChanged: (v) => setState(() => elapsedDays = v.round())),
        Text('تغير التقلب الضمني: ${number(ivChange)} نقطة مئوية'),
        Slider(value: ivChange, min: -15, max: 15, divisions: 30,
          onChanged: (v) => setState(() => ivChange = v)),
        if (twin == null) const Text('بيانات السوق منقطعة؛ سيناريو التسعير غير متاح.')
        else ...[
          Text('القيمة التقريبية للقسط: ${number(twin['estimated_mid'])} USD'),
          Text('صافي السيناريو بعد السبريد والانزلاق والعمولتين: ${number(twin['scenario_pnl_usd'])} USD',
            key: const Key('twin-pnl')),
          Text('إجمالي العمولات: ${number(twin['commissions_usd'])} USD • المضاعف 100'),
        ],
        const Text('لا يحاكي الممارسة أو تغير Greeks أو الانتهاء. حركات كبيرة تقلل صلاحية التقريب؛ لا توقع ربحية.'),
      ]),
      section('فخ السيولة وحارس الارتباط', [
        Text('الحجم النسبي: ${number(analysis['relative_volume'])}'),
        if ((analysis['liquidity_flags'] as List).isEmpty) const Text('لا علامة OHLCV وفق هذه القواعد المحدودة.'),
        for (final flag in List<String>.from(analysis['liquidity_flags'] as List)) Text(flag),
        Text(analysis['liquidity_scope'] as String),
        const Text('تعرض هذا الحساب يشمل تكلفة المملوك وحجز أوامر الشراء. لا تُصفّر Call وPut بعضها.'),
        for (final e in (data['exposure_cents'] as Map).entries)
          Text('${e.key}: ${number((e.value as int) / 100)} USD'),
        if (pairs.isEmpty) const Text('يلزم تعرض في رمزين على الأقل للمقارنة؛ لا نتيجة ارتباط مصطنعة.'),
        for (final pair in pairs) Text('${pair['first']} / ${pair['second']}: ${number(pair['correlation'])}'
          ' • ${pair['flagged'] == true ? 'تحذير تركّز أو بيانات غير كافية' : 'لم يتجاوز |0.8|'}'),
      ]),
      section('بطولة الاستراتيجيات — Walk Forward', [
        const Text('مقارنة متابعة الزخم وعكسه على عائد السهم الاصطناعي فقط. تدريب 20 ملاحظة، فصل ملاحظة، اختبار 8 ملاحظات متتابعة.'),
        const Text('تُخصم 10 نقاط أساس لكل فترة كتقدير تكلفة؛ هذا ليس اختبار عقود خيارات.'),
        Text('فترات اختبار مكتملة: ${(tournament['folds'] as List).length}'),
        if ((tournament['folds'] as List).isEmpty) const Text('تقدم بالوقت المحلي لجمع بيانات كافية؛ لا يتم توليد مستقبل للتقييم.')
        else Text('مجموع خارج العينة: ${number(tournament['out_of_sample_bps'])} نقطة أساس'),
        for (final fold in (tournament['folds'] as List).cast<DemoRow>().reversed.take(8))
          Text('${fold['selected']} • اختبار ${fold['test_start_tick']}–${fold['test_end_tick']}\n'
              'نهاية التدريب: ${fold['train_end_tick']} • النتيجة: ${number(fold['test_score_bps'])} نقطة أساس'),
      ]),
      section('ذاكرة القرار وإعادة السيناريو البديل', [
        const Text('تُعرض اللقطة الأصلية. لا تُعاد صياغة سبب التداول بعد النتيجة.'),
        if ((data['decision_memory'] as List).isEmpty) const Text('لا قرار محفوظ لهذا الرمز في الحساب المحدد.'),
        for (final memory in (data['decision_memory'] as List).cast<DemoRow>().reversed.take(10))
          OutlinedButton(onPressed: () {
            final saved = DemoResearchAnalysis.replaySavedDecision(engine, widget.accountId, memory['order_id'] as String);
            final original = Map<String, dynamic>.from(saved['original_decision'] as Map);
            showDialog<void>(context: context, builder: (c) => AlertDialog(
              title: const Text('قرار أصلي محفوظ'),
              content: SingleChildScrollView(child: Text('الحساب: ${original['account_id']}\n'
                'الملاحظة: ${original['tick']}\nالسبب الأصلي: ${original['reason']}\n'
                'الاتجاه: ${original['side']}\nحالة الأمر: ${saved['status']}\n'
                'عمليات التنفيذ: ${(saved['fills'] as List).length}\n\n${saved['reason']}')),
              actions: [TextButton(onPressed: () => Navigator.pop(c), child: const Text('إغلاق'))]));
          }, child: Text('فتح ${memory['order_id']}')),
        const Text('Counterfactual المحلي غير محسوب: سلسلة أسعار الخيارات التاريخية الكاملة غير محفوظة. نتيجة بديلة رقمية هنا ستكون غير موثقة.'),
      ]),
      section('حدود المختبر', [for (final text in DemoResearchAnalysis.limitations) Text(text)]),
    ]);
  }
}
