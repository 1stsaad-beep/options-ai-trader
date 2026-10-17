/// Single protective-exit rule shared by Market Paper, Demo and Broker Paper (B10).
///
/// All amounts are whole-position values in the same valuation basis (raw bid or
/// costed liquidation), as exact integers:
/// - STOP_LOSS:     value * 100 <= basis * (100 - stop)
/// - TAKE_PROFIT:   value * 100 >= basis * (100 + take)
/// - TRAILING_STOP: trail > 0, the peak exceeded the basis (armed only after a gain),
///                  and value * 100 <= peak * (100 - trail)
/// Priority is STOP_LOSS > TAKE_PROFIT > TRAILING_STOP. The peak must include every
/// observed value up to and including the current one (including it never fires early).
library;

const protectiveExitVersion = 'oat-protective-exit-v1';
const stopLossExit = 'STOP_LOSS', takeProfitExit = 'TAKE_PROFIT', trailingStopExit = 'TRAILING_STOP';

String? protectiveExit({required BigInt basis, required BigInt value, required BigInt peak,
    required int stopPercent, required int takePercent, required int trailPercent}) {
  final h = BigInt.from(100);
  if (value * h <= basis * BigInt.from(100 - stopPercent)) return stopLossExit;
  if (value * h >= basis * BigInt.from(100 + takePercent)) return takeProfitExit;
  if (trailingArmedAndHit(basis: basis, value: value, peak: peak, trailPercent: trailPercent)) return trailingStopExit;
  return null;
}

bool trailingArmedAndHit({required BigInt basis, required BigInt value, required BigInt peak, required int trailPercent}) =>
    trailPercent > 0 && peak > basis && value * BigInt.from(100) <= peak * BigInt.from(100 - trailPercent);

/// Convenience for int cents.
String? protectiveExitCents({required int basis, required int value, required int peak,
        required int stopPercent, required int takePercent, required int trailPercent}) =>
    protectiveExit(basis: BigInt.from(basis), value: BigInt.from(value), peak: BigInt.from(peak < value ? value : peak),
        stopPercent: stopPercent, takePercent: takePercent, trailPercent: trailPercent);
