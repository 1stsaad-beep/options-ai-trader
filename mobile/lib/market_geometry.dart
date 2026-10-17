import 'dart:math' as math;
import 'direct_alpaca.dart';
import 'demo/chart_analysis.dart';

/// The server research facade's strict three-bar pivot and harmonic geometry.
/// Demo/wave journals retain their original versioned plateau convention.
const marketGeometryContract='confirmed-geometry-v1';
class MarketGeometry {
  static List<ChartPivot> confirmedPivots(List<MarketBar> bars,{int radius=3}) {
    if(radius<1)throw ArgumentError('Positive confirmation radius required');
    for(var i=0;i<bars.length;i++) {
      final b=bars[i];
      MarketBar.parse({'t':b.time.millisecondsSinceEpoch,'o':b.open,'h':b.high,'l':b.low,'c':b.close,'v':b.volume});
      if(i>0&&!b.time.isAfter(bars[i-1].time))throw const FormatException('Ordered observations required');
    }
    final result=<ChartPivot>[];
    for(var i=radius;i+radius<bars.length;i++) {
      final neighbours=[...bars.sublist(i-radius,i),...bars.sublist(i+1,i+radius+1)];
      final high=neighbours.every((b)=>bars[i].high>b.high),low=neighbours.every((b)=>bars[i].low<b.low);
      if(high!=low)result.add(ChartPivot(i,i+radius,high?bars[i].high:bars[i].low,high));
    }
    return result;
  }
  /// Same strict rule on synthetic/Demo candles (index = tick, confirmed at tick of the
  /// last bar of the right window). Used so Demo labs match Direct/server geometry.
  static List<ChartPivot> candlePivots(List<DemoCandle> bars,{int radius=3}) {
    if(radius<1)throw ArgumentError('Positive confirmation radius required');
    final result=<ChartPivot>[];
    for(var i=radius;i+radius<bars.length;i++) {
      final neighbours=[...bars.sublist(i-radius,i),...bars.sublist(i+1,i+radius+1)];
      final high=neighbours.every((b)=>bars[i].high>b.high),low=neighbours.every((b)=>bars[i].low<b.low);
      if(high!=low)result.add(ChartPivot(bars[i].tick,bars[i+radius].tick,high?bars[i].high:bars[i].low,high));
    }
    return result;
  }
  static void _validate(List<ChartPivot> points) {
    for(var i=0;i<points.length;i++) {
      final p=points[i];
      if(!p.price.isFinite||p.price<=0||p.index<0||p.confirmedAt<=p.index||
          (i>0&&(p.index<=points[i-1].index||p.confirmedAt<=points[i-1].confirmedAt))) {
        throw const FormatException('Invalid confirmed pivots');
      }
    }
  }
  static bool _alternating(List<ChartPivot> p)=>List.generate(p.length-1,(i)=>p[i].high!=p[i+1].high).every((v)=>v);
  static List<dynamic> _points(List<ChartPivot> p)=>[for(final v in p)[v.index,v.confirmedAt,v.price,v.high]];
  static List<Map<String,dynamic>> harmonics(List<ChartPivot> points,{double tolerance=.03}) {
    _validate(points);
    if(!tolerance.isFinite||tolerance<0||tolerance>.05)throw ArgumentError('Ratio tolerance must be 0..0.05');
    bool between(double v,double lo,double hi)=>lo-tolerance<=v&&v<=hi+tolerance;
    final result=<Map<String,dynamic>>[];
    for(var start=math.max(0,points.length-64);start+4<points.length;start++) {
      final p=points.sublist(start,start+5);if(!_alternating(p))continue;
      final sign=p.first.high?-1:1,v=p.map((q)=>q.price*sign).toList();
      final x=v[0],a=v[1],b=v[2],c=v[3],d=v[4],xa=a-x,ab=a-b,bc=c-b,cd=c-d;
      if([xa,ab,bc,cd].any((leg)=>leg<=0)||!(x<b&&b<a)||d>=b)continue;
      final ratios={'AB_XA':ab/xa,'BC_AB':bc/ab,'CD_BC':cd/bc,'AD_XA':(a-d)/xa,
        'XC_XA':(c-x)/xa,'CD_XC':c>x?cd/(c-x):0.0};
      void add(String kind,double low,double high) {
        final zone=[low*sign,high*sign]..sort();
        result.add({'kind':kind,'direction':sign==1?'BULLISH':'BEARISH','mode':'SHADOW','executable':false,
          'points':_points(p),'ratios':ratios,'przLow':zone[0],'przHigh':zone[1],
          'activation':p.last.price+sign*cd*.236,'invalidation':p.last.price-sign*xa*.05,
          'targets':[p.last.price+sign*cd*.382,p.last.price+sign*cd*.618],
          'observedAt':p.map((v)=>v.confirmedAt).reduce(math.max)});
      }
      const definitions={
        'GARTLEY':[.618,.618,1.272,1.618,.786,.786],
        'BAT':[.382,.5,1.618,2.618,.886,.886],
        'BUTTERFLY':[.786,.786,1.618,2.618,1.272,1.618],
        'CRAB':[.382,.618,2.24,3.618,1.618,1.618],
      };
      for(final entry in definitions.entries) {
        final r=entry.value,inside=['GARTLEY','BAT'].contains(entry.key);
        if(!(b<c&&c<a&&(inside?d>x:d<x)))continue;
        if(!(between(ratios['AB_XA']!,r[0],r[1])&&between(ratios['BC_AB']!,.382,.886)&&
            between(ratios['CD_BC']!,r[2],r[3])&&between(ratios['AD_XA']!,r[4],r[5]))){continue;}
        final low=math.max(a-(r[5]+tolerance)*xa,c-(r[3]+tolerance)*bc);
        final high=math.min(a-(r[4]-tolerance)*xa,c-(r[2]-tolerance)*bc);
        if(low<=d&&d<=high)add(entry.key,low,high);
      }
      if(c>a&&x<d&&d<b&&between(ratios['AB_XA']!,.382,.618)&&
          between(ratios['XC_XA']!,1.272,1.414)&&between(ratios['CD_XC']!,.786,.786)) {
        add('CYPHER',c-(.786+tolerance)*(c-x),c-(.786-tolerance)*(c-x));
      }
    }
    return result;
  }
  static ChartPattern drawing(Map<String,dynamic> h) {
    const names={'GARTLEY':'Gartley','BAT':'Bat','BUTTERFLY':'Butterfly','CRAB':'Crab','CYPHER':'Cypher'};
    return ChartPattern(names[h['kind']]!,[for(final p in h['points'] as List)
      ChartPivot(p[0] as int,p[1] as int,(p[2] as num).toDouble(),p[3] as bool)],
      h['invalidation'] as double,(h['targets'] as List).first as double,
      labels:const ['X','A','B','C','D'],przLow:h['przLow'] as double,przHigh:h['przHigh'] as double);
  }
  static List<Map<String,dynamic>> classicPatterns(List<ChartPivot> points,double close) {
    _validate(points);if(!close.isFinite||close<=0)throw ArgumentError('Positive observed close required');
    final result=<Map<String,dynamic>>[];
    for(final length in [3,5]) {
      if(points.length<length)continue;
      final p=points.sublist(points.length-length);if(!_alternating(p))continue;
      final direction=p.first.high?-1:1,prices=p.map((v)=>v.price*-direction).toList();
      if(length==3&&(prices[0]-prices[2]).abs()/prices[0].abs()<=.02) {
        final neckline=p[1].price;
        result.add({'kind':direction==-1?'DOUBLE_TOP':'DOUBLE_BOTTOM','points':_points(p),
          'neckline':neckline,'confirmed':(close-neckline)*direction>0});
      }
      if(length==5&&prices[2]>math.max(prices[0],prices[4])&&(prices[0]-prices[4]).abs()/prices[0].abs()<=.03) {
        final neckline=direction==-1?math.min(p[1].price,p[3].price):math.max(p[1].price,p[3].price);
        result.add({'kind':direction==-1?'HEAD_AND_SHOULDERS':'INVERSE_HEAD_AND_SHOULDERS','points':_points(p),
          'neckline':neckline,'confirmed':(close-neckline)*direction>0});
      }
    }
    if(points.length>=6&&_alternating(points.sublist(points.length-6))) {
      final p=points.sublist(points.length-6),highs=p.where((v)=>v.high).map((v)=>v.price).toList(),lows=p.where((v)=>!v.high).map((v)=>v.price).toList();
      if(highs.length==3&&lows.length==3&&highs[0]>highs[1]&&highs[1]>highs[2]&&highs[2]>lows[2]&&lows[2]>lows[1]&&lows[1]>lows[0]) {
        result.add({'kind':'CONVERGING_TRIANGLE','upper':highs.last,'lower':lows.last,'confirmed':close>highs.last||close<lows.last});
      }
    }
    return result;
  }
  static List<ChartClassic> classicDrawings(List<ChartPivot> points,double close) {
    return [for(final p in classicPatterns(points,close))(() {
      final triangle=p['kind']=='CONVERGING_TRIANGLE';
      final vertices=triangle?points.sublist(points.length-6):[for(final v in p['points'] as List)
        ChartPivot(v[0] as int,v[1] as int,(v[2] as num).toDouble(),v[3] as bool)];
      final labels=triangle?[for(var i=0;i<vertices.length;i++)'${vertices[i].high?"H":"L"}${i~/2+1}']:
        vertices.length==5?['LS','N1','H','N2','RS']:['P1','N','P2'];
      return ChartClassic(p['kind'] as String,List.unmodifiable(vertices),List.unmodifiable(labels),p['confirmed'] as bool,
        neckline:(p['neckline'] as num?)?.toDouble());
    })()];
  }
}
