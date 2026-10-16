import 'dart:math' as math;
import 'direct_alpaca.dart';
import 'market_indicators.dart';
import 'demo/chart_analysis.dart';

/// Versioned deterministic signals shared with the server. No fill authority.
const marketStrategyContract='observed-market-strategy-v1';
const marketStrategies=['confluence','trend','breakout','pullback','divergence'];

class MarketSignal {
  static bool greater(num a,num b)=>a-b>1e-9*math.max(1,math.max(a.abs(),b.abs()));
  Map<String,dynamic> toJson()=>{'contract':marketStrategyContract,'direction':direction,'confirmedReverse':confirmedReverse,'reason':reason};
  final String direction;
  final bool confirmedReverse;
  final String reason;
  const MarketSignal(this.direction,this.confirmedReverse,{this.reason='QUANTITATIVE_RULE'});
  static MarketSignal analyze(List<MarketBar> rows,{String strategy='confluence'}) {
    if(rows.length<35)return const MarketSignal('WAIT',false);
    if(!marketStrategies.contains(strategy))return const MarketSignal('WAIT',false,reason:'UNSUPPORTED_STRATEGY');
    final bars=[for(var i=0;i<rows.length;i++)rows[i].candle(i)];
    final div=MarketIndicators.divergences(rows).where((d)=>d.confirmedAt==bars.last.tick).toList();
    bool structured(ChartDivergence d) {
      final between=bars.sublist(d.first.index+1,d.second.index);
      if(between.isEmpty)return false;
      return d.kind=='صاعد عادي'?greater(bars.last.close,between.map((b)=>b.high).reduce(math.max)):
        d.kind=='هابط عادي'&&greater(between.map((b)=>b.low).reduce(math.min),bars.last.close);
    }
    final bull=div.any((d)=>d.kind=='صاعد عادي'&&structured(d)),bear=div.any((d)=>d.kind=='هابط عادي'&&structured(d));
    if(['confluence','divergence'].contains(strategy)&&bull!=bear)return MarketSignal(bull?'CALL':'PUT',true,reason:'DIVERGENCE_AND_STRUCTURE_BREAK');
    if(strategy=='divergence')return const MarketSignal('WAIT',false,reason:'NO_CONFIRMED_DIVERGENCE_STRUCTURE');
    final s=MarketIndicators.summary(rows),rsi=s['rsi14'] as double?;
    if(rsi==null||!rsi.isFinite)return const MarketSignal('WAIT',false);
    if(strategy=='breakout') {
      final previous=bars.sublist(bars.length-21,bars.length-1),last=bars.last;
      final volume=previous.map((b)=>b.volume).reduce((a,b)=>a+b)/previous.length;
      if(volume<=0||greater(volume*1.2,last.volume))return const MarketSignal('WAIT',false,reason:'BREAKOUT_VOLUME_NOT_CONFIRMED');
      if(greater(last.close,previous.map((b)=>b.high).reduce(math.max)))return const MarketSignal('CALL',false,reason:'UPPER_RANGE_VOLUME_BREAK');
      if(greater(previous.map((b)=>b.low).reduce(math.min),last.close))return const MarketSignal('PUT',false,reason:'LOWER_RANGE_VOLUME_BREAK');
      return const MarketSignal('WAIT',false,reason:'NO_RANGE_BREAK');
    }
    if(strategy=='pullback') {
      final last=bars.last,previous=bars[bars.length-2],mean=s['sma20'] as double;
      if(greater(s['macd'] as num,0)&&!greater(last.low,mean)&&greater(last.close,mean)&&greater(last.close,previous.high)&&!greater(50,rsi)&&!greater(rsi,70))return const MarketSignal('CALL',false,reason:'BULLISH_MEAN_RETEST_AND_STRUCTURE');
      if(greater(0,s['macd'] as num)&&!greater(mean,last.high)&&greater(mean,last.close)&&greater(previous.low,last.close)&&!greater(30,rsi)&&!greater(rsi,50))return const MarketSignal('PUT',false,reason:'BEARISH_MEAN_RETEST_AND_STRUCTURE');
      return const MarketSignal('WAIT',false,reason:'NO_CONFIRMED_MEAN_RETEST');
    }
    if(greater(bars.last.close,s['sma20'] as num)&&greater(s['macd'] as num,0)&&!greater(50,rsi)&&!greater(rsi,70))return const MarketSignal('CALL',false);
    if(greater(s['sma20'] as num,bars.last.close)&&greater(0,s['macd'] as num)&&!greater(30,rsi)&&!greater(rsi,50))return const MarketSignal('PUT',false);
    return const MarketSignal('WAIT',false);
  }
}
