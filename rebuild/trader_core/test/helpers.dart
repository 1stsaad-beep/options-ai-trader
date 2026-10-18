import 'package:trader_core/trader_core.dart';

final DateTime t0 = DateTime.utc(2026, 3, 2, 14, 30);

/// Candles whose closes follow [closes]; high/low are close ± [wick] and open
/// equals close, so a local extreme of the closes is a strict pivot.
List<Candle> candlesFromCloses(List<double> closes, {double wick = 0.05}) => [
      for (var i = 0; i < closes.length; i++)
        Candle(
          time: t0.add(Duration(minutes: 15 * i)),
          open: closes[i],
          high: closes[i] + wick,
          low: closes[i] - wick,
          close: closes[i],
          volume: 1000,
        )
    ];

/// Piecewise-linear path through ([bars], price) waypoints. The first waypoint
/// is at bar 0; each next waypoint gives the number of bars of that leg.
List<double> path(double start, List<(int, double)> legs) {
  final out = <double>[start];
  var current = start;
  for (final (bars, target) in legs) {
    final step = (target - current) / bars;
    for (var i = 1; i <= bars; i++) {
      out.add(current + step * i);
    }
    current = target;
  }
  return out;
}
