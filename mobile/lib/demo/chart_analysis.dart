// Pure causal chart calculations for synthetic local observations only.
import 'dart:math' as math;
import 'engine.dart';

class DemoCandle {
  final int tick;
  final double open, high, low, close, volume;
  const DemoCandle(this.tick, this.open, this.high, this.low, this.close, this.volume);
}

class ChartPivot {
  final int index, confirmedAt;
  final double price;
  final bool high;
  const ChartPivot(this.index, this.confirmedAt, this.price, this.high);
}

class ChartPattern {
  final String name;
  final List<ChartPivot> points;
  final double invalidation, target;
  const ChartPattern(this.name, this.points, this.invalidation, this.target);
}

class DemoChartAnalysis {
  static List<DemoCandle> bars(DemoEngine e, String symbol, int end) {
    if (end < 24 || end > e.tick) throw const DemoRejected('حد إعادة التشغيل يتجاوز البيانات المتاحة');
    // A fixed left edge preserves indicator warmup and causal prefix stability.
    return List.generate(end + 1, (i) {
      final close = e.underlying(symbol, i) / 100;
      final open = e.underlying(symbol, math.max(0, i - 1)) / 100;
      return DemoCandle(i, open, math.max(open, close) + .15,
        math.min(open, close) - .15, close, i % 3 == 0 ? 1500 : 1000);
    });
  }

  static List<double?> sma(List<double> values, int period) => List.generate(values.length,
    (i) => i + 1 < period ? null : values.sublist(i + 1 - period, i + 1).reduce((a,b)=>a+b) / period);

  static List<double> ema(List<double> values, int period) {
    final out = <double>[];
    for (final value in values) {
      out.add(out.isEmpty ? value : value * (2 / (period + 1)) + out.last * (1 - 2 / (period + 1)));
    }
    return out;
  }

  static List<double?> rsi(List<double> values, {int period = 14}) {
    final result = List<double?>.filled(values.length, null);
    for (var i = period; i < values.length; i++) {
      var gain = 0.0, loss = 0.0;
      for (var j = i - period + 1; j <= i; j++) {
        final change = values[j] - values[j - 1];
        gain += math.max(change, 0); loss += math.max(-change, 0);
      }
      result[i] = gain + loss == 0 ? 50 : loss == 0 ? 100 : 100 - 100 / (1 + gain / loss);
    }
    return result;
  }

  static List<double> macd(List<double> values) {
    final fast = ema(values, 12), slow = ema(values, 26);
    return List.generate(values.length, (i) => fast[i] - slow[i]);
  }

  static List<ChartPivot> pivots(List<DemoCandle> bars, {int radius = 2}) {
    final result = <ChartPivot>[];
    for (var i = radius; i + radius < bars.length; i++) {
      final neighbors = bars.sublist(i - radius, i + radius + 1);
      final high = neighbors.where((b) => b.tick != bars[i].tick).every((b) => b.high < bars[i].high);
      final low = neighbors.where((b) => b.tick != bars[i].tick).every((b) => b.low > bars[i].low);
      if (high != low) result.add(ChartPivot(i, i + radius, high ? bars[i].high : bars[i].low, high));
    }
    return result;
  }

  static List<ChartPattern> waves(List<ChartPivot> pivots) {
    final out = <ChartPattern>[];
    for (var i = 0; i + 5 < pivots.length; i++) {
      final p = pivots.sublist(i, i + 6);
      if (!List.generate(5, (j) => p[j].high != p[j+1].high).every((v)=>v)) continue;
      final sign = p.first.high ? -1 : 1;
      final q = p.map((v) => v.price * sign).toList();
      final w1 = q[1]-q[0], w3 = q[3]-q[2], w5 = q[5]-q[4];
      if (q[2] <= q[0] || q[3] <= q[1] || q[4] <= q[1] || q[5] <= q[3] ||
          w1 <= 0 || w3 <= 0 || w5 <= 0 || w3 < math.min(w1,w5)) continue;
      out.add(ChartPattern('مرشح 1–5 مؤكد القمم', p, p[4].price, p[5].price));
    }
    return out;
  }

  static List<ChartPattern> harmonics(List<ChartPivot> pivots) {
    final out = <ChartPattern>[];
    bool near(double value, double target) => (value-target).abs() <= .04;
    for (var i = 0; i + 4 < pivots.length; i++) {
      final p = pivots.sublist(i, i+5);
      if (!List.generate(4, (j) => p[j].high != p[j+1].high).every((v)=>v)) continue;
      final xa=(p[1].price-p[0].price).abs(), ab=(p[2].price-p[1].price).abs();
      final bc=(p[3].price-p[2].price).abs(), cd=(p[4].price-p[3].price).abs();
      if (xa == 0 || ab == 0 || bc == 0) continue;
      final b=ab/xa, c=bc/ab, d=(p[4].price-p[1].price).abs()/xa, extension=cd/bc;
      final sign = p[1].price > p[0].price ? 1 : -1;
      final q = p.map((v)=>v.price*sign).toList();
      if (!(q[0]<q[2] && q[2]<q[3] && q[3]<q[1] && q[4]<q[2])) continue;
      String? name;
      if (near(b,.618) && c>=.382 && c<=.886 && near(d,.786) && extension>=1.27 && extension<=1.618) name='Gartley';
      if (b>=.382 && b<=.5 && c>=.382 && c<=.886 && near(d,.886) && extension>=1.618 && extension<=2.618) name='Bat';
      if (near(b,.786) && c>=.382 && c<=.886 && near(d,1.27) && extension>=1.618 && extension<=2.618) name='Butterfly';
      if (b>=.382 && b<=.618 && c>=.382 && c<=.886 && near(d,1.618) && extension>=2.24 && extension<=3.618) name='Crab';
      if (name != null) {
        final target=p[4].price + sign * cd * .382;
        out.add(ChartPattern(name,p,p[4].price-sign*xa*.05,target));
      }
    }
    // Cypher geometry has C outside XA and uses XC for the D retracement.
    for (var i = 0; i + 4 < pivots.length; i++) {
      final p = pivots.sublist(i,i+5);
      if (!List.generate(4,(j)=>p[j].high!=p[j+1].high).every((v)=>v)) continue;
      final sign=p[1].price>p[0].price?1:-1;
      final q=p.map((v)=>v.price*sign).toList(), xa=(p[1].price-p[0].price).abs();
      if (xa==0 || q[2]<=q[0] || q[2]>=q[1] || q[3]<=q[1] || q[4]<=q[0] || q[4]>=q[2]) continue;
      final b=(q[1]-q[2])/xa, c=(q[3]-q[0])/xa, d=(q[3]-q[4])/(q[3]-q[0]);
      if (b>=.382 && b<=.618 && c>=1.272 && c<=1.414 && near(d,.786)) {
        out.add(ChartPattern('Cypher',p,p[0].price,p[4].price+sign*(q[3]-q[4])*.382));
      }
    }
    return out;
  }

  static DemoRow summary(List<DemoCandle> bars) {
    final closes=bars.map((b)=>b.close).toList(), tail=bars.skip(math.max(0,bars.length-20)).toList();
    final mean=tail.map((b)=>b.close).reduce((a,b)=>a+b)/tail.length;
    final std=math.sqrt(tail.map((b)=>math.pow(b.close-mean,2)).reduce((a,b)=>a+b)/tail.length);
    var tr=0.0;
    for(var i=math.max(1,bars.length-14);i<bars.length;i++) {
      tr+=math.max(bars[i].high-bars[i].low,math.max((bars[i].high-bars[i-1].close).abs(),(bars[i].low-bars[i-1].close).abs()));
    }
    final volume=bars.fold<double>(0,(n,b)=>n+b.volume);
    final last=bars.last;
    return {'sma20':mean,'ema20':ema(closes,20).last,'rsi14':rsi(closes).last,
      'macd':macd(closes).last,'atr14':tr/math.min(14,bars.length-1),
      'vwap':bars.fold<double>(0,(n,b)=>n+(b.high+b.low+b.close)/3*b.volume)/volume,
      'bollinger_low':mean-2*std,'bollinger_high':mean+2*std,
      'support':tail.map((b)=>b.low).reduce(math.min),'resistance':tail.map((b)=>b.high).reduce(math.max),
      'candle':(last.open-last.close).abs()/(last.high-last.low)<.1?'Doji مرشح':'لا نمط شمعة خاص',
      'confirmed_pivots':pivots(bars).length,'as_of':last.tick};
  }

  static List<String> divergences(List<DemoCandle> bars) {
    final p=pivots(bars), closes=bars.map((b)=>b.close).toList();
    final indicators={'RSI':rsi(closes),'MACD':macd(closes).cast<double?>()};
    final out=<String>[];
    for(final high in [false,true]) {
      final same=p.where((p)=>p.high==high).toList();
      if(same.length<2) continue;
      final a=same[same.length-2],b=same.last;
      if(b.index-a.index<3 || b.index-a.index>60) continue;
      for(final entry in indicators.entries) {
        final first=entry.value[a.index], second=entry.value[b.index];
        if(first==null || second==null) continue;
        if(!high && b.price<a.price && second>first) out.add('${entry.key}: صاعد عادي');
        if(high && b.price>a.price && second<first) out.add('${entry.key}: هابط عادي');
        if(!high && b.price>a.price && second<first) out.add('${entry.key}: صاعد خفي');
        if(high && b.price<a.price && second>first) out.add('${entry.key}: هابط خفي');
      }
    }
    return out;
  }
}
