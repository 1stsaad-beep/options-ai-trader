import 'dart:math' as math;
import 'package:flutter/material.dart';
import 'chart_analysis.dart';
import 'engine.dart';

/// Price, RSI and MACD use distinct scales but the same observation x axis.
/// Inputs have already been cut at the replay cursor; this painter cannot read
/// the engine or generate a wave, price, order or interpretation.
class DemoCandlePainter extends CustomPainter {
  final List<DemoCandle> bars;
  final DemoRow summary;
  final List<ChartPattern> patterns;
  final List<DemoRow> markers;
  final ColorScheme colors;
  final int lab;
  final bool overlays, indicators;
  final List<double?> rsiValues;
  final ChartMacd? macdValues;
  final List<ChartDivergence> divergences;
  DemoCandlePainter(this.bars,this.summary,this.patterns,this.markers,this.colors,
    this.lab,this.overlays,this.indicators,this.rsiValues,
    {this.macdValues,this.divergences=const []});

  List<String> get layerLabels => [
    'Candles ${bars.length}', 'Observation axis',
    if(overlays) ...['Support','Resistance',
      if(lab==1) ...['Fib 0.382','Fib 0.618'],
      for(final p in patterns) ...[
        '${p.alternate?"Alternate":"Primary"}: ${p.name}',
        ...(p.labels.isNotEmpty?p.labels:lab==2?['X','A','B','C','D']:[]),
        if(p.przLow!=null && p.przHigh!=null) 'PRZ'],
      if(lab==3 || lab==4) for(final d in divergences) d.label],
    if(indicators) ...['RSI 14 (rolling)','MACD 12/26','Signal 9','Histogram'],
  ];

  @override
  void paint(Canvas canvas,Size size) {
    if(bars.isEmpty)return;
    canvas.drawRect(Offset.zero&size,Paint()..color=colors.surfaceContainerLow);
    final plot=Rect.fromLTRB(48,30,size.width-10,indicators?size.height*.53:size.height-35);
    final lows=bars.map((b)=>b.low).toList(), highs=bars.map((b)=>b.high).toList();
    if(overlays) {
      for(final p in patterns) {
        final visible=p.points.where((p)=>bars.any((b)=>b.tick==p.index));
        lows.addAll(visible.map((p)=>p.price));highs.addAll(visible.map((p)=>p.price));
        if(p.przLow!=null) lows.add(p.przLow!);
        if(p.przHigh!=null) highs.add(p.przHigh!);
      }
    }
    final minimum=lows.reduce(math.min),maximum=highs.reduce(math.max);
    final margin=math.max(.25,(maximum-minimum)*.12);
    final low=minimum-margin,high=maximum+margin,dx=plot.width/bars.length;
    final indices={for(var i=0;i<bars.length;i++) bars[i].tick:i};
    double x(int tick)=>plot.left+(indices[tick]!+.5)*dx;
    double y(double price)=>plot.top+(high-price)/(high-low)*plot.height;
    void text(String value,Offset at,Color color,{double fontSize=10}) {
      final p=TextPainter(text:TextSpan(text:value,style:TextStyle(color:color,fontSize:fontSize)),
        textDirection:TextDirection.ltr)..layout(maxWidth:math.max(1,size.width-6));
      p.paint(canvas,Offset(at.dx.clamp(2,math.max(2,size.width-p.width-2)).toDouble(),
        at.dy.clamp(1,math.max(1,size.height-p.height-1)).toDouble()));
    }
    void line(Offset a,Offset b,Color color,[double width=1]) =>
      canvas.drawLine(a,b,Paint()..color=color..strokeWidth=width);
    text('PRICE • synthetic',const Offset(50,7),colors.onSurface);
    for(var i=0;i<5;i++) {
      final price=low+(high-low)*i/4;
      line(Offset(plot.left,y(price)),Offset(plot.right,y(price)),colors.outlineVariant,.5);
      text(price.toStringAsFixed(1),Offset(2,y(price)-5),colors.onSurfaceVariant);
    }
    for(final b in bars) {
      final color=b.close>=b.open?Colors.teal:Colors.redAccent;
      line(Offset(x(b.tick),y(b.high)),Offset(x(b.tick),y(b.low)),color);
      final top=math.min(y(b.open),y(b.close));
      canvas.drawRect(Rect.fromLTWH(x(b.tick)-dx*.3,top,math.max(1,dx*.6),
        math.max(1,(y(b.open)-y(b.close)).abs())),Paint()..color=color);
    }
    for(final i in {0,bars.length~/2,bars.length-1}) {
      text('#${bars[i].tick}',Offset(x(bars[i].tick)-10,plot.bottom+4),colors.onSurfaceVariant);
    }
    if(overlays) {
      void level(double price,String label,Color color) {
        if(price<low || price>high)return;
        line(Offset(plot.left,y(price)),Offset(plot.right,y(price)),color,.8);
        text('$label ${price.toStringAsFixed(2)}',Offset(plot.left+2,y(price)-12),color);
      }
      level((summary['support'] as num).toDouble(),'S',colors.primary);
      level((summary['resistance'] as num).toDouble(),'R',colors.primary);
      if(lab==1) { for(final ratio in [.382,.618]) {
        level(summary['resistance']-(summary['resistance']-summary['support'])*ratio,
          'Fib $ratio',colors.tertiary);
      } }
      for(final p in patterns) {
        final color=p.alternate?Colors.lightBlue:Colors.orange;
        final path=Path();var started=false;
        for(var i=0;i<p.points.length;i++) {
          final point=p.points[i];if(!indices.containsKey(point.index)){started=false;continue;}
          final at=Offset(x(point.index),y(point.price));
          if(!started){path.moveTo(at.dx,at.dy);started=true;}else{path.lineTo(at.dx,at.dy);}
          canvas.drawCircle(at,2.5,Paint()..color=color);
          final label=p.labels.isNotEmpty?p.labels[i]:lab==2?'XABCD'[i]:'$i';
          text(label,at+Offset(-3,p.alternate?16:-18),color,fontSize:12);
        }
        canvas.drawPath(path,Paint()..color=color..style=PaintingStyle.stroke..strokeWidth=p.alternate?1:2);
        if(p.przLow!=null && p.przHigh!=null && indices.containsKey(p.points.last.index)) {
          final left=math.max(plot.left,x(p.points.last.index)-12);
          canvas.drawRect(Rect.fromLTRB(left,y(p.przHigh!),plot.right,y(p.przLow!)),
            Paint()..color=color.withValues(alpha:.22));
          text('PRZ',Offset(left,y(p.przHigh!)-14),color);
        }
      }
    }
    for(final m in markers) {
      final index=indices[m['tick']];if(index==null)continue;
      final at=Offset(x(bars[index].tick),y(bars[index].close));
      canvas.drawCircle(at,4,Paint()..color=Colors.purpleAccent);
      text('${m['label']}',at+const Offset(0,7),colors.onSurface);
    }
    final rsiRect=Rect.fromLTRB(plot.left,size.height*.64,plot.right,size.height*.77);
    final macdRect=Rect.fromLTRB(plot.left,size.height*.85,plot.right,size.height-.02*size.height);
    double ry(double v)=>rsiRect.bottom-v/100*rsiRect.height;
    final macd=macdValues;
    final mv=<double>[0,if(macd!=null)...[
      ...macd.line.whereType<double>(),...macd.signal.whereType<double>(),...macd.histogram.whereType<double>()]];
    final extent=math.max(.01,mv.map((v)=>v.abs()).reduce(math.max))*1.15;
    double my(double v)=>macdRect.center.dy-v/extent*macdRect.height/2;
    void series(List<double?> values,double Function(double) sy,Color color) {
      final path=Path();var started=false;
      for(var i=0;i<math.min(values.length,bars.length);i++) {
        final value=values[i];if(value==null){started=false;continue;}
        final at=Offset(x(bars[i].tick),sy(value));
        if(!started){path.moveTo(at.dx,at.dy);started=true;}else{path.lineTo(at.dx,at.dy);}
      }
      canvas.drawPath(path,Paint()..color=color..style=PaintingStyle.stroke..strokeWidth=1.5);
    }
    if(indicators) {
      text('RSI 14 rolling • 0–100',Offset(plot.left,rsiRect.top-21),colors.tertiary);
      for(final v in [0.0,30.0,70.0,100.0]) {
        line(Offset(plot.left,ry(v)),Offset(plot.right,ry(v)),colors.outlineVariant,.5);
        text('${v.toInt()}',Offset(12,ry(v)-5),colors.onSurfaceVariant);
      }
      series(rsiValues,ry,colors.tertiary);
      if(rsiValues.every((v)=>v==null))text('RSI warmup: 15 closes',rsiRect.topLeft,colors.onSurface);
      text('MACD 12/26 • Signal 9 • Hist',Offset(plot.left,macdRect.top-22),colors.onSurface);
      line(Offset(plot.left,my(0)),Offset(plot.right,my(0)),colors.outlineVariant,.5);
      text('0',Offset(25,my(0)-5),colors.onSurfaceVariant);
      if(macd!=null) {
        for(var i=0;i<math.min(macd.histogram.length,bars.length);i++) {
          final v=macd.histogram[i];if(v==null)continue;
          line(Offset(x(bars[i].tick),my(0)),Offset(x(bars[i].tick),my(v)),
            v>=0?Colors.teal:Colors.redAccent,math.max(1,dx*.45));
        }
        series(macd.line,my,colors.primary);series(macd.signal,my,colors.tertiary);
        if(macd.signal.every((v)=>v==null))text('Signal warmup: 34 closes',macdRect.topLeft,colors.onSurface);
      }
    }
    if(overlays && (lab==3 || lab==4)) { for(final d in divergences) {
      if(!indices.containsKey(d.first.index)||!indices.containsKey(d.second.index))continue;
      final a=Offset(x(d.first.index),y(d.first.price)),b=Offset(x(d.second.index),y(d.second.price));
      line(a,b,Colors.pinkAccent,2);text('${d.indicator} DIV',b+const Offset(-40,-14),Colors.pinkAccent);
      if(indicators) {
        final sy=d.indicator=='RSI'?ry:my;
        line(Offset(a.dx,sy(d.firstValue)),Offset(b.dx,sy(d.secondValue)),Colors.pinkAccent,2);
      }
    } }
  }

  @override
  bool shouldRepaint(covariant DemoCandlePainter oldDelegate)=>true;
}
