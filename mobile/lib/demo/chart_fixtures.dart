// Explicit display-only fixtures. Never fed to DemoEngine, accounts or orders.
import 'dart:math' as math;
import 'chart_analysis.dart';

class ChartFixtures {
  static const labels = <String,String>{
    'demo':'سوق Demo المحفوظ',
    'impulse':'عينة رسم: موجات 1–5',
    'abc':'عينة رسم: الأساسي / ABC البديل',
    'bat':'عينة رسم: Bat / XABCD / PRZ',
    'divergence':'عينة رسم: دايفرجنس RSI / MACD',
  };

  static List<DemoCandle> bars(String name) {
    final anchors = switch(name) {
      'impulse' => <int,double>{0:110,6:100,18:110,30:105,42:125,54:115,66:130,72:127},
      'abc' => <int,double>{0:110,6:100,18:110,30:105,42:125,48:122},
      // Interior Bat ratios allow the .1 OHLC wick on each confirmed pivot.
      'bat' => <int,double>{0:120,6:100,18:200,30:151,42:176,54:111.4,60:120},
      // First deep trough after a long decline; lower second trough after a
      // recovery. Both indicator values are calculated, never hard-coded.
      'divergence' => <int,double>{0:150,32:100,42:125,52:96,60:115},
      _ => throw ArgumentError.value(name,'fixture'),
    };
    final ticks=anchors.keys.toList();
    double value(int tick) {
      final left=ticks.lastWhere((t)=>t<=tick),right=ticks.firstWhere((t)=>t>=tick);
      return left==right?anchors[left]!:anchors[left]!+
        (anchors[right]!-anchors[left]!)*(tick-left)/(right-left);
    }
    return List.generate(ticks.last+1,(i) {
      final close=value(i),open=value(math.max(0,i-1));
      // Continuous OHLC deliberately exercises equal-extremum confirmation.
      return DemoCandle(i,open,math.max(open,close)+.1,
        math.min(open,close)-.1,close,1000);
    });
  }
}
