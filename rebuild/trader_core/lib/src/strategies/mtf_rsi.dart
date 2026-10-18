/// Strategy B — multi-timeframe RSI re-entry (round 5, experimental).
///
/// PUT : slow RSI (e.g. hourly) >= overbought; fast RSI (e.g. 15 min) drops out
///       of overbought and comes back into it within [MtfRsiParams.window] fast
///       bars while the slow RSI is still overbought → buy a weekly Put.
/// CALL: mirror — slow RSI <= oversold; fast RSI rises out of oversold and
///       returns into it within the window while slow is still oversold → Call.
///
/// Signals are raised at the close of the fast bar that re-enters the zone; the
/// slow RSI is read from the last slow bar *completed* at that instant. Rules in
/// `rebuild/docs/STRATEGY_MTF_RSI.md`.
library;

import 'dart:math' as math;

import '../analysis/indicators.dart';
import 'common.dart';

class MtfRsiParams {
  /// Overbought threshold of the slow timeframe; oversold = 100 - this.
  final double slowOverbought;

  /// Overbought threshold of the fast timeframe (default = slow threshold).
  final double? fastOverbought;
  final int slowLength;
  final int fastLength;

  /// Max fast bars between leaving the zone and coming back.
  final int window;

  /// Also require the slow RSI to be in the zone when the fast RSI left it.
  final bool slowAtExit;
  final bool puts;
  final bool calls;

  const MtfRsiParams({
    this.slowOverbought = 70,
    this.fastOverbought,
    this.slowLength = 14,
    this.fastLength = 14,
    this.window = 8,
    this.slowAtExit = true,
    this.puts = true,
    this.calls = true,
  });

  double get fastOb => fastOverbought ?? slowOverbought;

  String get id => 'ob${slowOverbought.toStringAsFixed(0)}'
      '${fastOverbought == null ? '' : '/f${fastOverbought!.toStringAsFixed(0)}'}'
      '-L$slowLength/$fastLength-W$window${slowAtExit ? '' : '-noExitChk'}';
}

/// All signals over [fast] (entry timeframe) using [slow] for the zone filter.
List<StrategySignal> mtfRsiSignals(TfSeries fast, TfSeries slow, MtfRsiParams p) {
  final rf = rsi([for (final b in fast.bars) b.close], period: p.fastLength);
  final rs = rsi([for (final b in slow.bars) b.close], period: p.slowLength);
  final hi = p.fastOb, lo = 100 - p.fastOb, sHi = p.slowOverbought, sLo = 100 - p.slowOverbought;
  double? slowAt(DateTime t) {
    final n = slow.completedAt(t);
    return n == 0 ? null : rs[n - 1];
  }

  final out = <StrategySignal>[];
  int? exitOb, exitOs;
  for (var i = 1; i < fast.bars.length; i++) {
    final a = rf[i - 1], b = rf[i];
    if (a == null || b == null) continue;
    final t = fast.ends[i];
    // leaving the zones
    if (a >= hi && b < hi) {
      final s = slowAt(t);
      exitOb = (!p.slowAtExit || (s != null && s >= sHi)) ? i : null;
    }
    if (a <= lo && b > lo) {
      final s = slowAt(t);
      exitOs = (!p.slowAtExit || (s != null && s <= sLo)) ? i : null;
    }
    // coming back
    if (p.puts && a < hi && b >= hi && exitOb != null) {
      final gap = i - exitOb;
      final s = slowAt(t);
      if (gap <= p.window && s != null && s >= sHi) {
        var top = fast.bars[i].high;
        for (var k = math.max(0, exitOb - 1); k <= i; k++) {
          top = math.max(top, fast.bars[k].high);
        }
        out.add(StrategySignal(
          index: i,
          time: t,
          bullish: false,
          reasonAr: 'RSI البطيء ${s.toStringAsFixed(1)} في التشبع الشرائي، والسريع خرج ثم عاد فوق ${hi.toStringAsFixed(0)} بعد $gap شمعة → Put',
          invalidation: top,
          features: {'slowRsi': s, 'fastRsi': b, 'gap': gap},
        ));
      }
      exitOb = null;
    }
    if (p.calls && a > lo && b <= lo && exitOs != null) {
      final gap = i - exitOs;
      final s = slowAt(t);
      if (gap <= p.window && s != null && s <= sLo) {
        var bottom = fast.bars[i].low;
        for (var k = math.max(0, exitOs - 1); k <= i; k++) {
          bottom = math.min(bottom, fast.bars[k].low);
        }
        out.add(StrategySignal(
          index: i,
          time: t,
          bullish: true,
          reasonAr: 'RSI البطيء ${s.toStringAsFixed(1)} في التشبع البيعي، والسريع خرج ثم عاد تحت ${lo.toStringAsFixed(0)} بعد $gap شمعة → Call',
          invalidation: bottom,
          features: {'slowRsi': s, 'fastRsi': b, 'gap': gap},
        ));
      }
      exitOs = null;
    }
    if (exitOb != null && i - exitOb > p.window) exitOb = null;
    if (exitOs != null && i - exitOs > p.window) exitOs = null;
  }
  return out;
}
