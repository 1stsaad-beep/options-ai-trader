import 'dart:convert';
import 'dart:math' as math;
import 'package:flutter/material.dart';
import 'chart_analysis.dart';
import 'engine.dart';
import 'wave_analysis.dart';
import 'chart_fixtures.dart';
import 'chart_painter.dart';
export 'chart_painter.dart' show DemoCandlePainter;

class DemoChartLab extends StatefulWidget {
  final DemoEngine engine;
  final String symbol;
  final int? initialEnd;
  final List<DemoRow> markers;
  const DemoChartLab({super.key, required this.engine, required this.symbol,
    this.initialEnd, this.markers = const []});
  @override
  State<DemoChartLab> createState() => _DemoChartLabState();
}

class _DemoChartLabState extends State<DemoChartLab> {
  static const names = ['Wave Lab','Classic Chart Lab','Harmonic Lab','Indicator Lab','AI Confluence Lab'];
  int lab=0;
  late int end;
  bool overlays=true, indicators=true;
  bool showAlternate=true;
  String fixture='demo';
  int factor=1;
  late bool follow;
  final transform=TransformationController();
  @override
  void dispose() {transform.dispose();super.dispose();}
  void seek(int tick) {setState(() {end=tick;follow=false;});}
  void source(String value) {setState(() {
    fixture=value;factor=1;waveJournal=ChartWaveJournal();
    follow=value=='demo' && widget.initialEnd==null;
    end=value=='demo'?(widget.initialEnd??widget.engine.tick):ChartFixtures.bars(value).last.tick;
    transform.value=Matrix4.identity();
  });}
  ChartWaveJournal waveJournal=ChartWaveJournal();
  @override
  void initState() {super.initState();end=widget.initialEnd ?? widget.engine.tick;follow=widget.initialEnd==null;}
  @override
  void didUpdateWidget(covariant DemoChartLab oldWidget) {
    super.didUpdateWidget(oldWidget);
    if(oldWidget.engine!=widget.engine || oldWidget.symbol!=widget.symbol) {
      waveJournal=ChartWaveJournal();
      if(fixture=='demo') {end=widget.initialEnd ?? widget.engine.tick;follow=widget.initialEnd==null;}
    }
  }
  @override
  Widget build(BuildContext context) {
    final maximum=fixture=='demo'?widget.engine.tick:ChartFixtures.bars(fixture).last.tick;
    if(follow && fixture=='demo')end=maximum;
    end=math.max(24,math.min(end,maximum));
    final sourceBars=fixture=='demo'?DemoChartAnalysis.bars(widget.engine,widget.symbol,end):
      ChartFixtures.bars(fixture).where((b)=>b.tick<=end).toList();
    final bars=ChartWaveAnalysis.aggregate(sourceBars,factor);
    final summary=DemoChartAnalysis.summary(bars), pivots=DemoChartAnalysis.pivots(bars);
    if(waveJournal.latestTick==null || bars.last.tick>=waveJournal.latestTick!) waveJournal.append(bars);
    final waves=waveJournal.view(bars.last.tick);
    final frames=ChartWaveAnalysis.timeframes(bars);
    final patterns=lab==0?<ChartPattern>[
      if(waves.primary!=null) waves.primary!.drawing(),
      if(showAlternate && waves.alternate!=null) waves.alternate!.drawing(alternate:true),
    ]:lab==2?DemoChartAnalysis.harmonics(pivots):<ChartPattern>[];
    final divergenceSegments=DemoChartAnalysis.divergenceSegments(bars);
    final divergences=divergenceSegments.map((d)=>d.label).toList();
    final color=Theme.of(context).colorScheme;
    String n(dynamic v)=>v is num?v.toStringAsFixed(2):'$v';
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch,children:[
      Text('${widget.symbol} • مختبر بيانات اصطناعية • Shadow',style:Theme.of(context).textTheme.titleMedium),
      const Text('الرسومات مرشحات بحثية وليست أوامر. العرض يستخدم الملاحظات حتى مؤشر إعادة التشغيل فقط.'),
      if(widget.initialEnd==null) DropdownButtonFormField<String>(
        key:const Key('chart-fixture-selector'),initialValue:fixture,isExpanded:true,
        decoration:const InputDecoration(labelText:'مصدر الرسم فقط — لا يغيّر الحساب'),
        items:ChartFixtures.labels.entries.map((e)=>DropdownMenuItem(value:e.key,child:Text(e.value))).toList(),
        onChanged:(v){if(v!=null)source(v);}),
      if(fixture!='demo') const Text('عينة اصطناعية مضبوطة للرسم فقط؛ ليست إشارة سوق أو صفقة.',key:Key('chart-fixture-warning')),
      SingleChildScrollView(scrollDirection:Axis.horizontal,child:Row(children:[
        for(var i=0;i<names.length;i++) Padding(padding:const EdgeInsets.all(4),child:ChoiceChip(
          key:Key('chart-lab-$i'),label:Text(names[i]),selected:lab==i,onSelected:(_)=>setState(()=>lab=i)))
      ])),
      Wrap(spacing:12,children:[
        FilterChip(label:const Text('الرسومات'),selected:overlays,onSelected:(v)=>setState(()=>overlays=v)),
        FilterChip(label:const Text('المؤشرات'),selected:indicators,onSelected:(v)=>setState(()=>indicators=v)),
        if(lab==0) FilterChip(key:const Key('wave-alternate-toggle'),
          label:const Text('الترقيم البديل'),selected:showAlternate,
          onSelected:(v)=>setState(()=>showAlternate=v)),
      ]),
      Text(lab==0?(waves.primary==null?'لا سيناريو موجي صالح عند هذا المؤشر؛ لا يُختلق ترقيم.':
        'الأساسي: ${waves.primary!.labels.join(" → ")} • مرشح بحثي مؤكد القمم\n'
        '${waves.alternate==null?"لا بديل صالح":showAlternate?"البديل: ${waves.alternate!.labels.join(" → ")}":"البديل مخفي"}'):
        lab==2?(patterns.isEmpty?'لا نموذج XABCD / PRZ صالح عند هذا المؤشر.':
          '${patterns.length} نموذج مطابق للقواعد • PRZ نطاق نسب بحثي، وليس وقفًا.'):
        lab==3?(divergences.isEmpty?'لا دايفرجنس مؤكد عند هذا المؤشر.':divergences.join('، ')):
        'S = دعم • R = مقاومة • Fib = فيبوناتشي',key:const Key('chart-analysis-status')),
      Wrap(spacing:8,crossAxisAlignment:WrapCrossAlignment.center,children:[
        const Text('تجميع الملاحظات:'),
        for(final f in [1,5,15]) ChoiceChip(key:Key('chart-factor-$f'),label:Text('$f×'),selected:factor==f,
          onSelected:(_)=>setState((){factor=f;waveJournal=ChartWaveJournal();transform.value=Matrix4.identity();})),
        IconButton(key:const Key('chart-zoom-in'),tooltip:'تكبير',icon:const Icon(Icons.zoom_in),
          onPressed:(){final scale=math.min(4.0,transform.value.getMaxScaleOnAxis()*1.5);
            transform.value=Matrix4.diagonal3Values(scale,scale,1);}),
        TextButton(key:const Key('chart-fit'),onPressed:()=>transform.value=Matrix4.identity(),
          child:const Text('ملاءمة الرسم')),
      ]),
      SizedBox(height:440,child:LayoutBuilder(builder:(context,constraints) {
        final offset=math.max(0,bars.length-180),visible=bars.skip(offset).toList();
        final closes=bars.map((b)=>b.close).toList(),macd=DemoChartAnalysis.macdSeries(closes);
        final painter=DemoCandlePainter(visible,summary,patterns,
          widget.markers.where((m)=>(m['tick'] as int)<=end).toList(),color,lab,overlays,indicators,
          DemoChartAnalysis.rsi(closes).skip(offset).toList(),
          macdValues:ChartMacd(macd.line.skip(offset).toList(),macd.signal.skip(offset).toList(),
            macd.histogram.skip(offset).toList()),divergences:divergenceSegments);
        return Semantics(label:painter.layerLabels.join('; '),child:ClipRect(child:
          InteractiveViewer(key:const Key('chart-pan-zoom'),transformationController:transform,
            minScale:1,maxScale:4,child:RepaintBoundary(key:const Key('chart-canvas'),
              child:CustomPaint(size:Size(constraints.maxWidth,440),painter:painter)))));
      })),
      Text('Chart Replay / Wave Replay • الملاحظة $end من $maximum',key:const Key('chart-cursor')),
      Text('المحور # = رقم الملاحظة الاصطناعية، وليس وقت سوق • $factor× • '
        '${follow?"متابعة السوق":"إعادة مثبتة"} • أصفر/برتقالي أساسي، أزرق بديل، وردي دايفرجنس'),
      Slider(key:const Key('chart-replay-slider'),value:end.toDouble(),min:24,
        max:math.max(25,maximum).toDouble(),divisions:math.max(1,maximum-24),
        onChanged:maximum==24?null:(v)=>seek(v.round())),
      Wrap(spacing:8,children:[
        OutlinedButton(onPressed:end>24?()=>seek(end-1):null,child:const Text('ملاحظة سابقة')),
        OutlinedButton(onPressed:end<maximum?()=>seek(end+1):null,child:const Text('ملاحظة تالية')),
        if(fixture=='demo' && widget.initialEnd==null) OutlinedButton(key:const Key('chart-follow'),
          onPressed:()=>setState(()=>follow=true),child:const Text('متابعة السوق')),
      ]),
      if(lab==0) ...[
        Text('قمم مؤكدة داخلية: ${pivots.length} • سيناريوهات نشطة: ${waves.active.length}. '
          'درجة رئيسية بتأكيد 4 ملاحظات وداخلية بتأكيد ملاحظتين. '
          '1–5 وABC والخامسة و3 of 3 مرشحات هندسية؛ لا جزم بالترقيم ولا أمر تداول.'),
        if(waves.primary!=null) _scenarioCard(context,'الأساسي',waves.primary!,n),
        if(waves.alternate!=null) _scenarioCard(context,'البديل',waves.alternate!,n),
        Text('Wave Scenario Tracker • أحداث معروفة حتى المؤشر: ${waves.events.length}',
          key:const Key('wave-journal-summary')),
        const Text('الإلغاء عند إغلاق شمعة يتجاوز المستوى البنيوي. الأحداث لا تُعاد كتابتها عند تحريك المؤشر؛ '
          'يُعاد بناء سجل المختبر من تاريخ Demo الاصطناعي عند فتحه. لا سجل مُوقّع أو وعد تنفيذ.'),
        for(final event in waves.events.skip(math.max(0,waves.events.length-5)))
          Text('#${event.sequence} • ${event.event=="DETECTED"?"رصد مرشح":"إلغاء مرشح"} '
            'عند الملاحظة ${event.observedAt} • إغلاق ${n(event.close)}'),
      ],
      if(lab==1) Text('دعم ${n(summary['support'])} • مقاومة ${n(summary['resistance'])}\nنطاق 20 ملاحظة وفيبوناتشي 38.2% و61.8% • ${summary['candle']}\nالكشف الكامل عن النماذج الكلاسيكية غير معتمد في هذا المختبر المحلي.'),
      if(lab==2) Text('نماذج XABCD المطابقة: ${patterns.length} • Gartley / Bat / Butterfly / Crab / Cypher. PRZ تقاطع نطاقات النسب المحلية (ولـ Cypher نطاق XC)؛ ليست ضمان انعكاس.'),
      if(lab==3) Text('SMA20 ${n(summary['sma20'])} • EMA20 ${n(summary['ema20'])}\nRSI14 ${n(summary['rsi14'])} • MACD ${n(summary['macd'])}\nVWAP ${n(summary['vwap'])} • ATR14 ${n(summary['atr14'])}\nBollinger ${n(summary['bollinger_low'])} – ${n(summary['bollinger_high'])}\n${divergences.isEmpty?'لا دايفرجنس مؤكد':divergences.join('، ')}'),
      if(lab==4) Text('ملخص قواعد محلي، دون استدعاء AI: ${bars.last.close>summary['sma20']?'فوق المتوسط':'تحت المتوسط'}. ${divergences.isEmpty?'لا تعارض دايفرجنس مؤكد.':divergences.join('، ')}\nالدرجة لا تتجاوز أي شرط أمان. لا نموذج لغوي ولا اتصال خارجي.'),
      if(lab==0 || lab==4) ...[
        const SizedBox(height:8),
        const Text('توافق الفواصل الاصطناعية — شموع مكتملة فقط',key:Key('wave-mtf-heading')),
        for(final frame in frames) Text('${frame.factor}× ملاحظة • ${frame.bars.length} شمعة مكتملة '
          '• آخر إغلاق ${frame.lastTick??"—"} • ${frame.bias} • مرشحات ${frame.waves.length}'),
        const Text('هذه تجميعات ملاحظات Demo وليست دقائق سوق. نقص الإحماء يُعرض صراحةً؛ التوافق لا يتجاوز المخاطر.'),
      ],
      for(final p in patterns) Text('${p.name} • إلغاء ${n(p.invalidation)} • هدف بحثي ${n(p.target)}'),
      const SizedBox(height:12),
      const Text('كبّر بإصبعين وحرك الرسم أفقيًا. لا بيانات سوق حقيقية أو تحقق لدى IBKR.'),
    ]);
  }

  Widget _scenarioCard(BuildContext context,String role,ChartWaveScenario scenario,
      String Function(dynamic) number) => Card(child:Padding(
    padding:const EdgeInsets.all(10),child:Text('$role • ${scenario.name} '
      '• ${scenario.bullish?"صاعد":"هابط"} • ${scenario.degree=="main"?"رئيسي":"داخلي"}\n'
      'معروف منذ الملاحظة ${scenario.observedAt} • ${scenario.labels.join(" → ")}\n'
      'تفعيل هندسي ${number(scenario.activation)} • إلغاء ${number(scenario.invalidation)}\n'
      'أهداف فيبوناتشي بحثية ${scenario.targets.map<String>(number).join("، ")}'
      '${scenario.parentId==null?"":"\nمرتبط بموجة ثالثة رئيسية مؤكدة؛ لا ترقيم بأثر رجعي."}')));
}

class DemoDecisionReplay extends StatelessWidget {
  final DemoEngine engine;
  final DemoRow trade;
  const DemoDecisionReplay({super.key,required this.engine,required this.trade});
  @override
  Widget build(BuildContext context) {
    final snapshots=(trade['entry_decisions'] as List? ?? []).cast<String>();
    final exit=trade['exit_decision'] is String?jsonDecode(trade['exit_decision']) as DemoRow:null;
    final entry=snapshots.map((s)=>jsonDecode(s) as DemoRow).toList();
    return Scaffold(appBar:AppBar(title:const Text('إعادة قرار الصفقة')),body:SafeArea(child:ListView(padding:const EdgeInsets.all(16),children:[
      Text('${trade['symbol']} ${trade['right']??''} × ${trade['quantity']} • بيانات اصطناعية'),
      Text('النتيجة المحققة: ${(trade['pnl']/100).toStringAsFixed(2)} USD • سبب الخروج: ${trade['reason']}'),
      if(entry.isEmpty) const Text('صفقة من إصدار سابق: لم تحفظ لقطة قرار؛ لا نُنشئ أسبابًا بأثر رجعي.'),
      for(var i=0;i<entry.length;i++) Card(child:Padding(padding:const EdgeInsets.all(12),child:Text(
        '${i==0?'قرار الدخول':'قرار إضافة'} • ملاحظة ${entry[i]['tick']}\n${entry[i]['reason']}\nعقد: ${entry[i]['contract']}\nالأدلة المحفوظة: ${entry[i]['evidence']??'طلب يدوي؛ لا إشارة آلية'}\nحد الأمر: ${entry[i]['limit']} سنت'))),
      if(exit!=null) Text('لقطة الخروج: ${exit['reason']} • ملاحظة ${exit['tick']}'),
      Text('سعر التنفيذ الختامي: ${trade['exit_price']??'غير محفوظ'} سنت • عمولة الخروج: ${trade['exit_fee']??'غير محفوظ'} سنت'),
      const Text('المقارنة تعرض القرار المسجل والنتيجة الفعلية الاصطناعية. لا يُختلق توقع سعري غير محفوظ.'),
      DemoChartLab(engine:engine,symbol:trade['symbol'],initialEnd:trade['tick'],markers:[
        if(trade['entry_tick'] is int) {'tick':trade['entry_tick'],'label':'IN'},
        for(final s in entry.skip(1)) {'tick':s['tick'],'label':'ADD'},
        {'tick':trade['tick'],'label':'OUT'},
      ]),
    ])));
  }
}
