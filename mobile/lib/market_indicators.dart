import 'dart:math' as math;
import 'direct_alpaca.dart';
import 'demo/chart_analysis.dart';
import 'market_geometry.dart';

/// Matches backend intelligence/indicators.py. No warm-up backfill, no future
/// input, SMA-seeded EMA, Wilder RSI/ATR and UTC-date VWAP resets.
const marketIndicatorContract='completed-bar-indicators-v1';
const marketDivergenceContract='confirmed-divergence-v1';
const marketDivergenceLabels={'REGULAR_BULLISH':'صاعد عادي','HIDDEN_BULLISH':'صاعد خفي',
  'REGULAR_BEARISH':'هابط عادي','HIDDEN_BEARISH':'هابط خفي'};
class MarketIndicators {
  static void values(List<double> values,int period) {
    if(period<1||values.any((v)=>!v.isFinite))throw const FormatException('Finite values and positive period required');
  }
  static List<double?> sma(List<double> data,int period) {
    values(data,period);
    return List.generate(data.length,(i)=>i+1<period?null:data.sublist(i+1-period,i+1).reduce((a,b)=>a+b)/period);
  }
  static List<double?> ema(List<double> data,int period) {
    values(data,period);final out=List<double?>.filled(data.length,null);
    if(data.length<period)return out;
    var value=data.take(period).reduce((a,b)=>a+b)/period;out[period-1]=value;
    final alpha=2/(period+1);
    for(var i=period;i<data.length;i++){value=data[i]*alpha+value*(1-alpha);out[i]=value;}
    return out;
  }
  static List<double?> rsi(List<double> data,{int period=14}) {
    values(data,period);final out=List<double?>.filled(data.length,null);
    if(data.length<=period)return out;
    var gain=0.0,loss=0.0;
    for(var i=1;i<=period;i++){final d=data[i]-data[i-1];gain+=math.max(d,0);loss+=math.max(-d,0);}
    gain/=period;loss/=period;
    double value()=>gain==0&&loss==0?50:loss==0?100:100-100/(1+gain/loss);
    out[period]=value();
    for(var i=period+1;i<data.length;i++) {
      final d=data[i]-data[i-1];gain=(gain*(period-1)+math.max(d,0))/period;
      loss=(loss*(period-1)+math.max(-d,0))/period;out[i]=value();
    }
    return out;
  }
  static ChartMacd macd(List<double> data,{int fast=12,int slow=26,int signal=9}) {
    values(data,signal);if(fast>=slow)throw const FormatException('MACD fast must be less than slow');
    final a=ema(data,fast),b=ema(data,slow);
    final line=List<double?>.generate(data.length,(i)=>a[i]==null||b[i]==null?null:a[i]!-b[i]!);
    final start=math.min(slow-1,data.length);
    final signals=<double?>[...List<double?>.filled(start,null),...ema(line.skip(start).whereType<double>().toList(),signal)];
    return ChartMacd(line,signals,List.generate(data.length,(i)=>line[i]==null||signals[i]==null?null:line[i]!-signals[i]!));
  }
  static Map<String,dynamic> series(List<MarketBar> rows) {
    if(rows.isEmpty)throw const FormatException('Completed bars required');
    for(var i=0;i<rows.length;i++) {
      final b=rows[i];
      if(![b.open,b.high,b.low,b.close,b.volume].every((v)=>v.isFinite)||b.low<=0||b.volume<0||
          b.low>math.min(b.open,b.close)||b.high<math.max(b.open,b.close)||
          (i>0&&!b.time.isAfter(rows[i-1].time))) {
        throw const FormatException('Ordered valid OHLCV required');
      }
    }
    final closes=rows.map((b)=>b.close).toList(),m=macd(closes),middle=sma(closes,20);
    final atr=List<double?>.filled(rows.length,null),vwap=<double?>[];
    final ranges=<double>[];var range=0.0,total=0.0,volume=0.0;String? day;
    for(var i=0;i<rows.length;i++) {
      final b=rows[i],current=b.time.toUtc().toIso8601String().substring(0,10);
      final tr=i==0?b.high-b.low:math.max(b.high-b.low,math.max((b.high-rows[i-1].close).abs(),(b.low-rows[i-1].close).abs()));
      ranges.add(tr);
      if(i==13){range=ranges.reduce((a,b)=>a+b)/14;atr[i]=range;}
      else if(i>13){range=(range*13+tr)/14;atr[i]=range;}
      if(current!=day){day=current;total=0;volume=0;}
      total+=(b.high+b.low+b.close)/3*b.volume;volume+=b.volume;vwap.add(volume==0?null:total/volume);
    }
    final spread=List<double?>.generate(rows.length,(i) {
      if(i<19)return null;
      final mean=middle[i]!;
      return 2*math.sqrt(closes.sublist(i-19,i+1).fold<double>(0,(sum,v)=>sum+(v-mean)*(v-mean))/20);
    });
    return {'sma20':middle,'ema20':ema(closes,20),'ema50':ema(closes,50),'rsi14':rsi(closes),
      'macd':{'line':m.line,'signal':m.signal,'histogram':m.histogram},'atr14':atr,'vwap_utc_day':vwap,
      'bollinger20':{'middle':middle,'upper':List<double?>.generate(rows.length,(i)=>middle[i]==null?null:middle[i]!+spread[i]!),
        'lower':List<double?>.generate(rows.length,(i)=>middle[i]==null?null:middle[i]!-spread[i]!)}};
  }
  static Map<String,dynamic> summary(List<MarketBar> rows) {
    final s=series(rows),tail=rows.skip(math.max(0,rows.length-20)),last=rows.last;
    final span=last.high-last.low;
    return {'indicator_contract':marketIndicatorContract,'sma20':s['sma20'].last,'ema20':s['ema20'].last,
      'ema50':s['ema50'].last,'rsi14':s['rsi14'].last,'macd':s['macd']['line'].last,
      'macd_signal':s['macd']['signal'].last,'macd_histogram':s['macd']['histogram'].last,
      'atr14':s['atr14'].last,'vwap':s['vwap_utc_day'].last,'vwap_policy':'UTC calendar date',
      'bollinger_low':s['bollinger20']['lower'].last,'bollinger_high':s['bollinger20']['upper'].last,
      'support':tail.map((b)=>b.low).reduce(math.min),'resistance':tail.map((b)=>b.high).reduce(math.max),
      'candle':span>0&&(last.open-last.close).abs()<=span*.1?'Doji مرشح':'لا نمط شمعة خاص',
      'as_of':last.time.toUtc().toIso8601String()};
  }
  static List<ChartDivergence> divergences(List<MarketBar> rows) {
    if(rows.isEmpty)return [];
    final s=series(rows),p=MarketGeometry.confirmedPivots(rows);
    return [...confirmedDivergences(p,s['rsi14'] as List<double?>),
      ...confirmedDivergences(p,s['macd']['line'] as List<double?>,name:'MACD')];
  }
  /// Same adjacent same-kind pairs, strict confirmation, distance and epsilon
  /// rules as the server. Old Demo and saved research versions stay unchanged.
  static List<ChartDivergence> confirmedDivergences(List<ChartPivot> points,List<double?> oscillator,
    {String name='RSI',int minDistance=3,int maxDistance=60,double minimumMomentumChange=1e-9}) {
    if(!['RSI','MACD'].contains(name)||minDistance<1||maxDistance<minDistance||
      !minimumMomentumChange.isFinite||minimumMomentumChange<0||oscillator.any((v)=>v!=null&&!v.isFinite)) {
      throw const FormatException('Invalid divergence configuration or oscillator');
    }
    for(var i=0;i<points.length;i++) {
      final p=points[i];
      if(!p.price.isFinite||p.price<=0||p.index<0||p.confirmedAt<=p.index||p.confirmedAt>=oscillator.length||
        (i>0&&(p.index<=points[i-1].index||p.confirmedAt<=points[i-1].confirmedAt))) {
        throw const FormatException('Invalid confirmed divergence pivots');
      }
    }
    final result=<ChartDivergence>[];
    for(final high in [false,true]) {
      final same=points.where((p)=>p.high==high).toList();
      for(var i=1;i<same.length;i++) {
        final a=same[i-1],b=same[i],old=oscillator[a.index],value=oscillator[b.index];
        if(old==null||value==null||b.index-a.index<minDistance||b.index-a.index>maxDistance)continue;
        final priceChange=b.price-a.price,momentumChange=value-old;
        if(momentumChange.abs()<=minimumMomentumChange||priceChange.abs()<=math.max(a.price,b.price)*1e-9)continue;
        final kind=!high&&priceChange<0&&momentumChange>0?'REGULAR_BULLISH':
          !high&&priceChange>0&&momentumChange<0?'HIDDEN_BULLISH':
          high&&priceChange>0&&momentumChange<0?'REGULAR_BEARISH':
          high&&priceChange<0&&momentumChange>0?'HIDDEN_BEARISH':null;
        if(kind!=null)result.add(ChartDivergence(name,marketDivergenceLabels[kind]!,a,b,old,value));
      }
    }
    return result;
  }
}
