import 'dart:math' as math;
import 'dart:convert';
import 'direct_replay.dart';
import 'market_indicators.dart';
import 'package:flutter/material.dart';
import 'direct_alpaca.dart';
import 'demo/chart_analysis.dart';
import 'demo/chart_painter.dart';
import 'demo/wave_analysis.dart';

class MarketSignal {
  final String direction;
  final bool confirmedReverse;
  final String reason;
  const MarketSignal(this.direction,this.confirmedReverse,{this.reason='QUANTITATIVE_RULE'});
  static MarketSignal analyze(List<MarketBar> rows,{String strategy='confluence'}) {
    if(rows.length<35)return const MarketSignal('WAIT',false);
    if(!['confluence','trend','breakout','pullback','divergence'].contains(strategy))return const MarketSignal('WAIT',false,reason:'UNSUPPORTED_STRATEGY');
    final bars=[for(var i=0;i<rows.length;i++)rows[i].candle(i)];
    final div=MarketIndicators.divergences(rows).where((d)=>d.confirmedAt==bars.last.tick).toList();
    bool structured(ChartDivergence d) {
      final between=bars.sublist(d.first.index+1,d.second.index);
      if(between.isEmpty)return false;
      return d.kind=='صاعد عادي'?bars.last.close>between.map((b)=>b.high).reduce(math.max):
        d.kind=='هابط عادي'&&bars.last.close<between.map((b)=>b.low).reduce(math.min);
    }
    final bull=div.any((d)=>d.kind=='صاعد عادي'&&structured(d)),bear=div.any((d)=>d.kind=='هابط عادي'&&structured(d));
    if(['confluence','divergence'].contains(strategy)&&bull!=bear)return MarketSignal(bull?'CALL':'PUT',true,reason:'DIVERGENCE_AND_STRUCTURE_BREAK');
    if(strategy=='divergence')return const MarketSignal('WAIT',false,reason:'NO_CONFIRMED_DIVERGENCE_STRUCTURE');
    final s=MarketIndicators.summary(rows),rsi=s['rsi14'] as double?;
    if(rsi==null||!rsi.isFinite)return const MarketSignal('WAIT',false);
    if(strategy=='breakout') {
      final previous=bars.sublist(bars.length-21,bars.length-1),last=bars.last;
      final volume=previous.map((b)=>b.volume).reduce((a,b)=>a+b)/previous.length;
      if(volume<=0||last.volume<volume*1.2)return const MarketSignal('WAIT',false,reason:'BREAKOUT_VOLUME_NOT_CONFIRMED');
      if(last.close>previous.map((b)=>b.high).reduce(math.max))return const MarketSignal('CALL',false,reason:'UPPER_RANGE_VOLUME_BREAK');
      if(last.close<previous.map((b)=>b.low).reduce(math.min))return const MarketSignal('PUT',false,reason:'LOWER_RANGE_VOLUME_BREAK');
      return const MarketSignal('WAIT',false,reason:'NO_RANGE_BREAK');
    }
    if(strategy=='pullback') {
      final last=bars.last,previous=bars[bars.length-2],mean=s['sma20'] as double;
      if(s['macd']>0&&last.low<=mean&&last.close>mean&&last.close>previous.high&&rsi>=50&&rsi<=70)return const MarketSignal('CALL',false,reason:'BULLISH_MEAN_RETEST_AND_STRUCTURE');
      if(s['macd']<0&&last.high>=mean&&last.close<mean&&last.close<previous.low&&rsi>=30&&rsi<=50)return const MarketSignal('PUT',false,reason:'BEARISH_MEAN_RETEST_AND_STRUCTURE');
      return const MarketSignal('WAIT',false,reason:'NO_CONFIRMED_MEAN_RETEST');
    }
    if(bars.last.close>s['sma20']&&s['macd']>0&&rsi>=50&&rsi<=70)return const MarketSignal('CALL',false);
    if(bars.last.close<s['sma20']&&s['macd']<0&&rsi>=30&&rsi<=50)return const MarketSignal('PUT',false);
    return const MarketSignal('WAIT',false);
  }
}

class DirectLabs extends StatefulWidget {
  final List<MarketBar> rows;
  final String symbol,source;
  final List<Map<String,dynamic>> decisions;
  final Map<String,dynamic>? waveEpoch;
  const DirectLabs({super.key,required this.rows,required this.symbol,required this.source,this.decisions=const [],this.waveEpoch});
  @override State<DirectLabs> createState()=>_DirectLabsState();
}
class _DirectLabsState extends State<DirectLabs> {
  int lab=0,minutes=1;
  bool levels=true,models=true,showAlternate=true;
  String? _archiveBytes;
  ChartWaveView? _archiveView;
  List<Widget> controls()=>[
    Wrap(spacing:6,children:[for(final frame in [1,5,15,60])ChoiceChip(label:Text('$frame دقيقة'),selected:minutes==frame,onSelected:(_)=>setState(()=>minutes=frame))]),
    Wrap(children:[FilterChip(label:const Text('المستويات'),selected:levels,onSelected:(v)=>setState(()=>levels=v)),
      FilterChip(label:const Text('النماذج'),selected:models,onSelected:(v)=>setState(()=>models=v)),
      if(lab==0)FilterChip(key:const Key('direct-wave-alternate'),label:const Text('الترقيم البديل'),
        selected:showAlternate,onSelected:(v)=>setState(()=>showAlternate=v))]),
  ];
  static const names=['Wave Lab','Classic Chart Lab','Harmonic Lab','Indicator Lab','AI Confluence Lab'];
  String number(dynamic v)=>v is num&&v.isFinite?v.toStringAsFixed(2):'غير متاح';
  @override Widget build(BuildContext context) {
    final rows=directTimeframe(widget.rows,minutes);
    if(rows.isEmpty)return Column(crossAxisAlignment:CrossAxisAlignment.stretch,children:[...controls(),Text('${widget.source} • ${widget.symbol}\nلا توجد شموع مكتملة لهذا الفاصل من Alpaca بعد. افتح إعدادات الاتصال وافحص النتيجة. لا تُولد بيانات Demo بديلة.',key:const Key('direct-empty-chart'))]);
    final bars=[for(var i=0;i<rows.length;i++)rows[i].candle(i)];
    final markers=directTradeMarkers(rows,minutes,widget.symbol,widget.decisions);
    if(rows.length<35){return Column(crossAxisAlignment:CrossAxisAlignment.stretch,children:[...controls(),
      Text('${widget.symbol} • ${widget.source}',key:const Key('direct-series-source')),
      Text('${rows.length} شمعة OHLCV فعلية • UTC ${rows.last.time.toIso8601String()}؛ يلزم 35 شمعة لإحماء المؤشرات. لا تُولد بيانات بديلة.'),
      SizedBox(height:320,child:LayoutBuilder(builder:(context,c)=>CustomPaint(key:const Key('direct-chart'),size:Size(c.maxWidth,320),
        painter:DemoCandlePainter(bars,{},[],markers,Theme.of(context).colorScheme,0,false,false,[],
          priceLabel:'STOCK • ${widget.source}',timeLabels:{for(var i=0;i<rows.length;i++)i:rows[i].time.toIso8601String().substring(11,16)})))),
    ]);}
    final pivots=DemoChartAnalysis.pivots(bars),summary=MarketIndicators.summary(rows);
    final epoch=widget.waveEpoch;
    final archived=minutes==1&&epoch!=null&&(epoch['times'] as List).last==rows.last.time.millisecondsSinceEpoch;
    if(archived) {
      final encoded=jsonEncode(epoch);
      if(encoded!=_archiveBytes) {
        final journal=ChartWaveJournal.restore(epoch['journal'] as Map<String,dynamic>);
        _archiveView=journal.view(journal.latestTick!);_archiveBytes=encoded;
      }
    }
    final wave=archived?_archiveView!:directWaveView(rows);
    ChartPattern drawing(ChartWaveScenario scenario,{bool alternate=false}) {
      final p=scenario.drawing(alternate:alternate);if(!archived)return p;
      final times=epoch['times'] as List,indices={for(var i=0;i<rows.length;i++)rows[i].time.millisecondsSinceEpoch:i};
      return ChartPattern(p.name,[for(final q in p.points)ChartPivot(indices[times[q.index]]??-1,
        indices[times[q.confirmedAt]]??-1,q.price,q.high)],p.invalidation,p.target,
        labels:p.labels,alternate:p.alternate,przLow:p.przLow,przHigh:p.przHigh);
    }
    final patterns=lab==0?<ChartPattern>[
      if(wave.primary!=null)drawing(wave.primary!),
      if(showAlternate&&wave.alternate!=null)drawing(wave.alternate!,alternate:true),
    ]:lab==2?DemoChartAnalysis.harmonics(pivots):<ChartPattern>[];
    final div=MarketIndicators.divergences(rows),closes=bars.map((b)=>b.close).toList();
    final macd=MarketIndicators.macd(closes),offset=math.max(0,bars.length-180);
    final signal=MarketSignal.analyze(rows);
    return Column(crossAxisAlignment:CrossAxisAlignment.stretch,children:[...controls(),
      Text('${widget.symbol} • ${widget.source}',key:const Key('direct-series-source')),
      Text('OHLCV أسهم • $minutes دقيقة • توقيت UTC • آخر فترة ${rows.last.time.toIso8601String()}'),
      const Text('فجوات السوق لا تُملأ بشموع اصطناعية. الأشكال والمؤشرات بحثية؛ ليست أسعار عقود خيارات.'),
      SingleChildScrollView(scrollDirection:Axis.horizontal,child:Row(children:[for(var i=0;i<names.length;i++)
        Padding(padding:const EdgeInsets.all(4),child:ChoiceChip(label:Text(names[i]),selected:lab==i,onSelected:(_)=>setState(()=>lab=i)))])),
      SizedBox(height:440,child:LayoutBuilder(builder:(context,c)=>InteractiveViewer(minScale:1,maxScale:4,
        child:CustomPaint(key:const Key('direct-chart'),size:Size(c.maxWidth,440),painter:DemoCandlePainter(bars.skip(offset).toList(),summary,patterns,markers,
          Theme.of(context).colorScheme,lab,levels,models,MarketIndicators.rsi(closes).skip(offset).toList(),
          macdValues:ChartMacd(macd.line.skip(offset).toList(),macd.signal.skip(offset).toList(),macd.histogram.skip(offset).toList()),
          divergences:div,wilderRsi:true,priceLabel:'STOCK • ${widget.source}',
          timeLabels:{for(var i=0;i<rows.length;i++)i:rows[i].time.toIso8601String().substring(11,16)}))))),
      if(lab==0)...[
        Text(wave.primary==null?'لا ترقيم موجي نشط مستوفٍ للقواعد.':'مرشحات موجية نشطة: ${wave.active.length}',key:const Key('direct-wave-status')),
        for(final entry in {'الأساسي':wave.primary,'البديل':showAlternate?wave.alternate:null}.entries)
          if(entry.value!=null)Text('${entry.key}: ${entry.value!.name} • ${entry.value!.degree}\n'
            '${entry.value!.labels.join(' → ')} • التفعيل ${number(entry.value!.activation)} • الإلغاء ${number(entry.value!.invalidation)}\n'
            'أهداف Fib: ${entry.value!.targets.map(number).join(' / ')}'),
        Text(archived?'موجات من أرشيف محفوظ عبر نوافذ المصدر • ${(epoch['times'] as List).length} شمعة • حد المصدر: ${epoch['boundary']}. قد تقع بعض نقاط النموذج قبل النافذة المعروضة.':
          'السجل سببي داخل هذه النافذة فقط؛ لا أرشيف متحقق مطابق لهذا الفاصل والمصدر.'),
        Text('أحداث الرصد والإلغاء: ${wave.events.length}',key:const Key('direct-wave-events')),
      ],
      if(lab==1) Text('الدعم ${number(summary['support'])} • المقاومة ${number(summary['resistance'])}\nFib 38.2% / 61.8% • ${summary['candle']}\nالكشف الكامل للنماذج الكلاسيكية ما زال تجريبيًا.'),
      if(lab==2) Text(patterns.isEmpty?'لا نموذج Harmonic مؤكد.':patterns.map((p)=>'${p.name} • PRZ ${number(p.przLow)}–${number(p.przHigh)}').join('\n')),
      if(lab==3) Text('SMA20 ${number(summary['sma20'])} • EMA20 ${number(summary['ema20'])}\nRSI14 Wilder ${number(summary['rsi14'])}\nMACD 12/26/9 ${number(summary['macd'])}\nATR14 ${number(summary['atr14'])} • VWAP يوم UTC ${number(summary['vwap'])}'),
      if(lab==4) Text('توافق قواعد محلية: ${signal.direction} • ${signal.confirmedReverse?'دايفرجنس جديد مؤكد':'لا عكس مؤكد جديد'}\nAI Confluence اسم المختبر؛ لا نموذج لغوي أو توقع ربحية. إشارة السهم لا تُسعّر الخيار.'),
      if(markers.isNotEmpty)const Text('علامات Market Paper مثبتة على شمعة الإشارة؛ المحور لسعر السهم. سعر العقد والرسوم في القرار الأصلي.'),
      for(final m in markers.reversed.take(20))ListTile(title:Text('${m['label']} • ${m['decision']}'),subtitle:Text('سعر الخيار ${(m['optionPriceCents']/100).toStringAsFixed(2)} USD'),
        onTap:()=>showDialog<void>(context:context,builder:(context)=>AlertDialog(title:const Text('القرار الأصلي وقت الحدث'),
          content:SizedBox(width:600,child:SingleChildScrollView(child:SelectableText(const JsonEncoder.withIndent('  ').convert(m['original'])))),
          actions:[TextButton(onPressed:()=>Navigator.pop(context),child:const Text('إغلاق'))]))),
      for(final d in div) Text('${d.label} • تأكد عند ${rows[d.confirmedAt].time.toIso8601String()}'),
    ]);
  }
}
