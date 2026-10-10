import 'dart:convert';
import 'dart:math' as math;
import 'package:flutter/material.dart';
import 'chart_analysis.dart';
import 'engine.dart';
import 'wave_analysis.dart';

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
  ChartWaveJournal waveJournal=ChartWaveJournal();
  @override
  void initState() {super.initState();end=widget.initialEnd ?? widget.engine.tick;}
  @override
  void didUpdateWidget(covariant DemoChartLab oldWidget) {
    super.didUpdateWidget(oldWidget);
    if(oldWidget.engine!=widget.engine || oldWidget.symbol!=widget.symbol) {
      waveJournal=ChartWaveJournal();
      end=widget.initialEnd ?? widget.engine.tick;
    }
  }
  @override
  Widget build(BuildContext context) {
    end=math.max(24,math.min(end,widget.engine.tick));
    final bars=DemoChartAnalysis.bars(widget.engine,widget.symbol,end);
    final summary=DemoChartAnalysis.summary(bars), pivots=DemoChartAnalysis.pivots(bars);
    if(waveJournal.latestTick==null || end>=waveJournal.latestTick!) waveJournal.append(bars);
    final waves=waveJournal.view(end);
    final frames=ChartWaveAnalysis.timeframes(bars);
    final patterns=lab==0?<ChartPattern>[
      if(waves.primary!=null) waves.primary!.drawing(),
      if(showAlternate && waves.alternate!=null) waves.alternate!.drawing(alternate:true),
    ]:lab==2?DemoChartAnalysis.harmonics(pivots):<ChartPattern>[];
    final divergences=DemoChartAnalysis.divergences(bars);
    final color=Theme.of(context).colorScheme;
    String n(dynamic v)=>v is num?v.toStringAsFixed(2):'$v';
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch,children:[
      Text('${widget.symbol} • مختبر بيانات اصطناعية • Shadow',style:Theme.of(context).textTheme.titleMedium),
      const Text('الرسومات مرشحات بحثية وليست أوامر. العرض يستخدم الملاحظات حتى مؤشر إعادة التشغيل فقط.'),
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
      SizedBox(height:330,child:LayoutBuilder(builder:(context,constraints) {
        final visible=bars.skip(math.max(0,bars.length-180)).toList();
        final width=math.max(constraints.maxWidth,visible.length*9.0);
        return ClipRect(child:InteractiveViewer(key:const Key('chart-pan-zoom'),constrained:false,
          minScale:1,maxScale:4,boundaryMargin:const EdgeInsets.all(8),
          child:CustomPaint(size:Size(width,330),painter:DemoCandlePainter(visible,
            summary,patterns,widget.markers.where((m)=>(m['tick'] as int)<=end).toList(),
            color,lab,overlays,indicators,
            DemoChartAnalysis.rsi(bars.map((b)=>b.close).toList())
              .skip(math.max(0,bars.length-180)).toList()))));
      })),
      Text('Chart Replay / Wave Replay • الملاحظة $end من ${widget.engine.tick}',key:const Key('chart-cursor')),
      Slider(key:const Key('chart-replay-slider'),value:end.toDouble(),min:24,
        max:math.max(25,widget.engine.tick).toDouble(),divisions:math.max(1,widget.engine.tick-24),
        onChanged:widget.engine.tick==24?null:(v)=>setState(()=>end=v.round())),
      Wrap(spacing:8,children:[
        OutlinedButton(onPressed:end>24?()=>setState(()=>end--):null,child:const Text('ملاحظة سابقة')),
        OutlinedButton(onPressed:end<widget.engine.tick?()=>setState(()=>end++):null,child:const Text('ملاحظة تالية')),
      ]),
      if(lab==0) ...[
        Text('قمم مؤكدة داخلية: ${pivots.length} • سيناريوهات نشطة: ${waves.active.length}. '
          'درجة رئيسية بتأكيد 4 ملاحظات وداخلية بتأكيد ملاحظتين. '
          '1–5 وABC والخامسة و3 of 3 مرشحات هندسية؛ لا جزم بالترقيم ولا أمر تداول.'),
        if(waves.primary==null) const Text('لا سيناريو موجي صالح عند هذا المؤشر؛ لا يُختلق ترقيم.'),
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
      if(lab==2) Text('نماذج XABCD المطابقة: ${patterns.length} • Gartley / Bat / Butterfly / Crab / Cypher. المنطقة المظللة حول D تمثل نطاق إلغاء محلي؛ ليست توقعًا مؤكدًا.'),
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

class DemoCandlePainter extends CustomPainter {
  final List<DemoCandle> bars;
  final DemoRow summary;
  final List<ChartPattern> patterns;
  final List<DemoRow> markers;
  final ColorScheme colors;
  final int lab;
  final bool overlays, indicators;
  final List<double?> rsiValues;
  DemoCandlePainter(this.bars,this.summary,this.patterns,this.markers,this.colors,this.lab,this.overlays,this.indicators,this.rsiValues);
  @override
  void paint(Canvas canvas,Size size) {
    if(bars.isEmpty)return;
    final low=bars.map((b)=>b.low).reduce(math.min)-.5,high=bars.map((b)=>b.high).reduce(math.max)+.5;
    final dx=size.width/bars.length,plotHeight=indicators?230.0:290.0;
    double y(double price)=>12+(high-price)/(high-low)*plotHeight;
    double x(int tick)=>(tick-bars.first.tick+.5)*dx;
    void text(String value,Offset at,Color color) {
      final p=TextPainter(text:TextSpan(text:value,style:TextStyle(color:color,fontSize:10)),textDirection:TextDirection.ltr)..layout();
      p.paint(canvas,at);
    }
    canvas.drawRect(Offset.zero&size,Paint()..color=colors.surfaceContainerLow);
    for(var line=0;line<5;line++) {
      final price=low+(high-low)*line/4;
      canvas.drawLine(Offset(0,y(price)),Offset(size.width,y(price)),Paint()..color=colors.outlineVariant..strokeWidth=.5);
      text(price.toStringAsFixed(2),Offset(3,y(price)),colors.onSurfaceVariant);
    }
    for(final b in bars) {
      final color=b.close>=b.open?Colors.tealAccent.shade700:Colors.redAccent;
      final p=Paint()..color=color..strokeWidth=1;
      canvas.drawLine(Offset(x(b.tick),y(b.high)),Offset(x(b.tick),y(b.low)),p);
      canvas.drawRect(Rect.fromLTRB(x(b.tick)-dx*.3,math.min(y(b.open),y(b.close)),x(b.tick)+dx*.3,
        math.max(y(b.open),y(b.close))+1),p);
    }
    if(overlays) {
      for(final field in ['support','resistance']) {
        final price=(summary[field] as num).toDouble();
        canvas.drawLine(Offset(0,y(price)),Offset(size.width,y(price)),Paint()..color=colors.primary..strokeWidth=.8);
      }
      if(lab==1) {
        for(final ratio in [.382,.618]) {
          final price=summary['resistance']-(summary['resistance']-summary['support'])*ratio;
          canvas.drawLine(Offset(0,y(price)),Offset(size.width,y(price)),Paint()..color=Colors.amber..strokeWidth=1);
          text('Fib $ratio',Offset(size.width-70,y(price)),colors.onSurface);
        }
      }
      for(final pattern in patterns) {
        final path=Path();
        final patternColor=pattern.alternate?Colors.lightBlueAccent:Colors.amber;
        for(var i=0;i<pattern.points.length;i++) {
          final point=pattern.points[i];
          if(i==0) {path.moveTo(x(point.index),y(point.price));} else {path.lineTo(x(point.index),y(point.price));}
          final label=pattern.labels.isNotEmpty?pattern.labels[i]:lab==2?'XABCD'[i]:'$i';
          text(label,Offset(x(point.index),y(point.price)-(pattern.alternate?26:14)),patternColor);
        }
        canvas.drawPath(path,Paint()..color=patternColor..style=PaintingStyle.stroke..strokeWidth=pattern.alternate?1:2);
        final last=pattern.points.last;
        canvas.drawRect(Rect.fromLTRB(x(last.index)-dx,y(math.max(last.price,pattern.invalidation)),
          x(last.index)+dx,y(math.min(last.price,pattern.invalidation))),Paint()..color=patternColor.withValues(alpha:.15));
      }
    }
    for(final marker in markers) {
      final tick=marker['tick'] as int;
      if(tick<bars.first.tick || tick>bars.last.tick)continue;
      final b=bars[tick-bars.first.tick];
      canvas.drawCircle(Offset(x(tick),y(b.close)),5,Paint()..color=Colors.purpleAccent);
      text('${marker['label']}',Offset(x(tick),y(b.close)+6),colors.onSurface);
    }
    if(indicators) {
      final values=rsiValues;
      final path=Path();var started=false;
      for(var i=0;i<values.length;i++) {
        if(values[i]==null)continue;
        final at=Offset((i+.5)*dx,310-values[i]!*.6);
        if(!started){path.moveTo(at.dx,at.dy);started=true;}else{path.lineTo(at.dx,at.dy);}
      }
      canvas.drawPath(path,Paint()..color=colors.tertiary..style=PaintingStyle.stroke..strokeWidth=1.5);
      text('RSI 14 • 0–100',const Offset(4,312),colors.onSurfaceVariant);
    }
  }
  @override
  bool shouldRepaint(covariant DemoCandlePainter oldDelegate)=>true;
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
