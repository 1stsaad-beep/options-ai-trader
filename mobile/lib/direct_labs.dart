import 'dart:math' as math;
import 'package:flutter/material.dart';
import 'direct_alpaca.dart';
import 'demo/chart_analysis.dart';
import 'demo/chart_painter.dart';
import 'demo/wave_analysis.dart';

class MarketSignal {
  final String direction;
  final bool confirmedReverse;
  const MarketSignal(this.direction,this.confirmedReverse);
  static MarketSignal analyze(List<MarketBar> rows) {
    if(rows.length<35)return const MarketSignal('WAIT',false);
    final bars=[for(var i=0;i<rows.length;i++)rows[i].candle(i)];
    final div=DemoChartAnalysis.divergenceSegments(bars).where((d)=>d.confirmedAt==bars.last.tick).toList();
    final bull=div.any((d)=>d.kind=='صاعد عادي'),bear=div.any((d)=>d.kind=='هابط عادي');
    if(bull!=bear)return MarketSignal(bull?'CALL':'PUT',true);
    final s=DemoChartAnalysis.summary(bars),rsi=s['rsi14'] as double?;
    if(rsi==null||!rsi.isFinite)return const MarketSignal('WAIT',false);
    if(bars.last.close>s['sma20']&&s['macd']>0&&rsi>=50&&rsi<=70)return const MarketSignal('CALL',false);
    if(bars.last.close<s['sma20']&&s['macd']<0&&rsi>=30&&rsi<=50)return const MarketSignal('PUT',false);
    return const MarketSignal('WAIT',false);
  }
}

class DirectLabs extends StatefulWidget {
  final List<MarketBar> rows;
  final String symbol,source;
  const DirectLabs({super.key,required this.rows,required this.symbol,required this.source});
  @override State<DirectLabs> createState()=>_DirectLabsState();
}
class _DirectLabsState extends State<DirectLabs> {
  int lab=0;
  static const names=['Wave Lab','Classic Chart Lab','Harmonic Lab','Indicator Lab','AI Confluence Lab'];
  String number(dynamic v)=>v is num&&v.isFinite?v.toStringAsFixed(2):'غير متاح';
  @override Widget build(BuildContext context) {
    final rows=widget.rows;
    if(rows.length<35)return Text('${widget.source} • ${widget.symbol}\n${rows.length} شمعة OHLCV؛ يلزم 35 شمعة مكتملة لإحماء المؤشرات. لا تُولد بيانات بديلة.');
    final bars=[for(var i=0;i<rows.length;i++)rows[i].candle(i)];
    final pivots=DemoChartAnalysis.pivots(bars),summary=DemoChartAnalysis.summary(bars);
    final wave=ChartWaveAnalysis.candidates(pivots,degree:'internal');
    final patterns=lab==0?wave.map((s)=>s.drawing()).toList():lab==2?DemoChartAnalysis.harmonics(pivots):<ChartPattern>[];
    final div=DemoChartAnalysis.divergenceSegments(bars),closes=bars.map((b)=>b.close).toList();
    final macd=DemoChartAnalysis.macdSeries(closes),offset=math.max(0,bars.length-180);
    final signal=MarketSignal.analyze(rows);
    return Column(crossAxisAlignment:CrossAxisAlignment.stretch,children:[
      Text('${widget.symbol} • ${widget.source}',key:const Key('direct-series-source')),
      Text('OHLCV أسهم • 1 دقيقة • توقيت UTC • آخر فترة ${rows.last.time.toIso8601String()}'),
      const Text('فجوات السوق لا تُملأ بشموع اصطناعية. الأشكال والمؤشرات بحثية؛ ليست أسعار عقود خيارات.'),
      SingleChildScrollView(scrollDirection:Axis.horizontal,child:Row(children:[for(var i=0;i<names.length;i++)
        Padding(padding:const EdgeInsets.all(4),child:ChoiceChip(label:Text(names[i]),selected:lab==i,onSelected:(_)=>setState(()=>lab=i)))])),
      SizedBox(height:440,child:LayoutBuilder(builder:(context,c)=>InteractiveViewer(minScale:1,maxScale:4,
        child:CustomPaint(size:Size(c.maxWidth,440),painter:DemoCandlePainter(bars.skip(offset).toList(),summary,patterns,[],
          Theme.of(context).colorScheme,lab,true,true,DemoChartAnalysis.rsi(closes).skip(offset).toList(),
          macdValues:ChartMacd(macd.line.skip(offset).toList(),macd.signal.skip(offset).toList(),macd.histogram.skip(offset).toList()),
          divergences:div,priceLabel:'STOCK • ${widget.source}',
          timeLabels:{for(var i=0;i<rows.length;i++)i:rows[i].time.toIso8601String().substring(11,16)}))))),
      if(lab==0) Text(wave.isEmpty?'لا ترقيم موجي مستوفٍ للقواعد.':'مرشحات موجية مؤكدة: ${wave.length} • ${wave.last.labels.join(' → ')}'),
      if(lab==1) Text('الدعم ${number(summary['support'])} • المقاومة ${number(summary['resistance'])}\nFib 38.2% / 61.8% • ${summary['candle']}\nالكشف الكامل للنماذج الكلاسيكية ما زال تجريبيًا.'),
      if(lab==2) Text(patterns.isEmpty?'لا نموذج Harmonic مؤكد.':patterns.map((p)=>'${p.name} • PRZ ${number(p.przLow)}–${number(p.przHigh)}').join('\n')),
      if(lab==3) Text('SMA20 ${number(summary['sma20'])} • EMA20 ${number(summary['ema20'])}\nRSI14 rolling ${number(summary['rsi14'])}\nMACD 12/26/9 ${number(summary['macd'])}\nATR14 ${number(summary['atr14'])} • VWAP للعينة ${number(summary['vwap'])}'),
      if(lab==4) Text('توافق قواعد محلية: ${signal.direction} • ${signal.confirmedReverse?'دايفرجنس جديد مؤكد':'لا عكس مؤكد جديد'}\nAI Confluence اسم المختبر؛ لا نموذج لغوي أو توقع ربحية. إشارة السهم لا تُسعّر الخيار.'),
      for(final d in div) Text('${d.label} • تأكد عند ${rows[d.confirmedAt].time.toIso8601String()}'),
    ]);
  }
}
