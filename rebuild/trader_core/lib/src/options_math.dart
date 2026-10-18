/// Black–Scholes helpers used by the simulator to price synthetic options and
/// by contract selection to estimate delta when a broker does not supply it.
/// European approximation; fine for selection/simulation, not for exercise.
library;

import 'dart:math' as math;

/// Standard normal CDF (Abramowitz–Stegun 7.1.26, |error| < 7.5e-8).
double normCdf(double x) {
  const a1 = 0.254829592, a2 = -0.284496736, a3 = 1.421413741, a4 = -1.453152027, a5 = 1.061405429;
  const p = 0.3275911;
  final sign = x < 0 ? -1.0 : 1.0;
  final z = x.abs() / math.sqrt2;
  final t = 1.0 / (1.0 + p * z);
  final y = 1.0 - (((((a5 * t + a4) * t) + a3) * t + a2) * t + a1) * t * math.exp(-z * z);
  return 0.5 * (1.0 + sign * y);
}

class BsResult {
  final double price;
  final double delta;
  const BsResult(this.price, this.delta);
}

/// [years] is time to expiry in years; [vol] annualised volatility; [rate] risk-free.
BsResult blackScholes({
  required bool isCall,
  required double spot,
  required double strike,
  required double years,
  required double vol,
  double rate = 0.04,
}) {
  if (spot <= 0 || strike <= 0) throw ArgumentError('spot/strike must be positive');
  final intrinsic = isCall ? math.max(0.0, spot - strike) : math.max(0.0, strike - spot);
  if (years <= 0 || vol <= 0) {
    final delta = isCall ? (spot > strike ? 1.0 : 0.0) : (spot < strike ? -1.0 : 0.0);
    return BsResult(intrinsic, delta);
  }
  final sq = vol * math.sqrt(years);
  final d1 = (math.log(spot / strike) + (rate + vol * vol / 2) * years) / sq;
  final d2 = d1 - sq;
  final df = math.exp(-rate * years);
  if (isCall) {
    return BsResult(spot * normCdf(d1) - strike * df * normCdf(d2), normCdf(d1));
  }
  return BsResult(strike * df * normCdf(-d2) - spot * normCdf(-d1), normCdf(d1) - 1);
}
