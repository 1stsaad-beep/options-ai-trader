/// Model Greeks and implied volatility (B8).
///
/// European options: generalized Black-Scholes-Merton with a continuous dividend
/// yield q (analytic price and Greeks). American options: Cox-Ross-Rubinstein
/// binomial tree (price, tree delta/gamma/theta, bumped vega/rho). Discrete cash
/// dividends, early-exercise on dividend dates and adjusted deliverables are NOT
/// modeled. Model values are labeled as such and never qualify an entry by themselves.
library;

import 'dart:math' as math;

import 'direct_alpaca.dart';
import 'market_paper_policy.dart';

const pricingModelVersion = 'oat-bsm-crr-v1';

enum OptionRight { call, put }

class PricingInput {
  final double spot, strike, years, rate, dividendYield, volatility;
  final OptionRight right;
  const PricingInput({required this.spot, required this.strike, required this.years, required this.rate,
      this.dividendYield = 0, required this.volatility, required this.right});
  PricingInput withVol(double v) => PricingInput(spot: spot, strike: strike, years: years, rate: rate,
      dividendYield: dividendYield, volatility: v, right: right);
  PricingInput copy({double? spot, double? years, double? rate}) => PricingInput(spot: spot ?? this.spot,
      strike: strike, years: years ?? this.years, rate: rate ?? this.rate, dividendYield: dividendYield,
      volatility: volatility, right: right);
  bool get valid => [spot, strike, years, rate, dividendYield, volatility].every((x) => x.isFinite) &&
      spot > 0 && strike > 0 && years > 0 && volatility > 0 && rate.abs() < 1 && dividendYield.abs() < 1;
}

/// Theta is per calendar year (divide by 365 for per-day); vega and rho per 1.00 (= 100 %) change.
class Greeks {
  final double price, delta, gamma, theta, vega, rho;
  const Greeks(this.price, this.delta, this.gamma, this.theta, this.vega, this.rho);
  double get thetaPerDay => theta / 365;
  double get vegaPerPoint => vega / 100;
  double get rhoPerPoint => rho / 100;
  Map<String, double> toJson() => {'price': price, 'delta': delta, 'gamma': gamma, 'theta': theta,
        'thetaPerDay': thetaPerDay, 'vega': vega, 'vegaPerPoint': vegaPerPoint, 'rho': rho};
}

/// Standard normal CDF (W. J. Cody / Hart double-precision rational approximation, |err| < 1e-14).
double normCdf(double x) {
  final z = x.abs();
  double c;
  if (z > 37) {
    c = 0;
  } else {
    final e = math.exp(-z * z / 2);
    if (z < 7.07106781186547) {
      var n = 3.52624965998911e-02 * z + 0.700383064443688;
      n = n * z + 6.37396220353165;
      n = n * z + 33.912866078383;
      n = n * z + 112.079291497871;
      n = n * z + 221.213596169931;
      n = n * z + 220.206867912376;
      var d = 8.83883476483184e-02 * z + 1.75566716318264;
      d = d * z + 16.064177579207;
      d = d * z + 86.7807322029461;
      d = d * z + 296.564248779674;
      d = d * z + 637.333633378831;
      d = d * z + 793.826512519948;
      d = d * z + 440.413735824752;
      c = e * n / d;
    } else {
      var d = z + 0.65;
      d = z + 4 / d;
      d = z + 3 / d;
      d = z + 2 / d;
      d = z + 1 / d;
      c = e / d / 2.506628274631;
    }
  }
  return x > 0 ? 1 - c : c;
}

double normPdf(double x) => math.exp(-x * x / 2) / math.sqrt(2 * math.pi);

Greeks europeanGreeks(PricingInput p) {
  if (!p.valid) throw ArgumentError('INVALID_PRICING_INPUT');
  final s = p.spot, k = p.strike, t = p.years, r = p.rate, q = p.dividendYield, v = p.volatility;
  final sq = math.sqrt(t), d1 = (math.log(s / k) + (r - q + v * v / 2) * t) / (v * sq), d2 = d1 - v * sq;
  final dq = math.exp(-q * t), dr = math.exp(-r * t), pdf = normPdf(d1);
  final gamma = dq * pdf / (s * v * sq), vega = s * dq * pdf * sq;
  if (p.right == OptionRight.call) {
    final nd1 = normCdf(d1), nd2 = normCdf(d2);
    return Greeks(s * dq * nd1 - k * dr * nd2, dq * nd1, gamma,
        -s * dq * pdf * v / (2 * sq) - r * k * dr * nd2 + q * s * dq * nd1, vega, k * t * dr * nd2);
  }
  final nd1 = normCdf(-d1), nd2 = normCdf(-d2);
  return Greeks(k * dr * nd2 - s * dq * nd1, -dq * nd1, gamma,
      -s * dq * pdf * v / (2 * sq) + r * k * dr * nd2 - q * s * dq * nd1, vega, -k * t * dr * nd2);
}

double _payoff(OptionRight right, double s, double k) => math.max(0, right == OptionRight.call ? s - k : k - s);

/// CRR American price; returns (price, nodes at step 1, nodes at step 2) for tree Greeks.
(double, List<double>, List<double>) _crr(PricingInput p, int steps) {
  final dt = p.years / steps, u = math.exp(p.volatility * math.sqrt(dt)), d = 1 / u;
  final a = math.exp((p.rate - p.dividendYield) * dt), pu = (a - d) / (u - d), disc = math.exp(-p.rate * dt);
  if (!(pu > 0 && pu < 1)) throw ArgumentError('TREE_PROBABILITY_OUT_OF_RANGE');
  final values = List<double>.generate(steps + 1, (i) => _payoff(p.right, p.spot * math.pow(u, steps - 2 * i), p.strike));
  var l1 = <double>[], l2 = <double>[];
  for (var n = steps - 1; n >= 0; n--) {
    for (var i = 0; i <= n; i++) {
      final cont = disc * (pu * values[i] + (1 - pu) * values[i + 1]);
      values[i] = math.max(cont, _payoff(p.right, p.spot * math.pow(u, n - 2 * i), p.strike));
    }
    if (n == 2) l2 = values.sublist(0, 3);
    if (n == 1) l1 = values.sublist(0, 2);
  }
  return (values[0], l1, l2);
}

double americanPrice(PricingInput p, {int steps = 200}) {
  if (!p.valid || steps < 3) throw ArgumentError('INVALID_PRICING_INPUT');
  return _crr(p, steps).$1;
}

Greeks americanGreeks(PricingInput p, {int steps = 200}) {
  if (!p.valid || steps < 3) throw ArgumentError('INVALID_PRICING_INPUT');
  final (price, l1, l2) = _crr(p, steps);
  final dt = p.years / steps, u = math.exp(p.volatility * math.sqrt(dt)), s = p.spot;
  final delta = (l1[0] - l1[1]) / (s * u - s / u);
  final su = s * u * u, sd = s / (u * u);
  final gamma = ((l2[0] - l2[1]) / (su - s) - (l2[1] - l2[2]) / (s - sd)) / ((su - sd) / 2);
  final theta = (l2[1] - price) / (2 * dt);
  final hv = 0.01 * p.volatility, hr = 0.0001;
  final vega = (americanPrice(p.withVol(p.volatility + hv), steps: steps) -
          americanPrice(p.withVol(p.volatility - hv), steps: steps)) / (2 * hv);
  final rho = (americanPrice(p.copy(rate: p.rate + hr), steps: steps) -
          americanPrice(p.copy(rate: p.rate - hr), steps: steps)) / (2 * hr);
  return Greeks(price, delta, gamma, theta, vega, rho);
}

class ImpliedVolResult {
  final double? volatility;
  final String? reason; // null when solved
  final int iterations;
  const ImpliedVolResult(this.volatility, this.reason, this.iterations);
  bool get solved => volatility != null;
}

const ivMin = 0.001, ivMax = 5.0;

/// Implied volatility for a premium [price] (per share). Fails closed with a reason
/// instead of returning a misleading number (below intrinsic, above the no-arbitrage
/// upper bound, no time value, or no convergence).
ImpliedVolResult impliedVolatility(double price, PricingInput p,
    {bool american = false, int steps = 200, double tolerance = 1e-6, double minTimeValue = 0.005}) {
  if (!price.isFinite || price <= 0 || !p.withVol(0.2).valid) return const ImpliedVolResult(null, 'INVALID_INPUT', 0);
  final t = p.years, dq = math.exp(-p.dividendYield * t), dr = math.exp(-p.rate * t);
  final lower = american
      ? math.max(_payoff(p.right, p.spot, p.strike),
          math.max(0.0, p.right == OptionRight.call ? p.spot * dq - p.strike * dr : p.strike * dr - p.spot * dq))
      : math.max(0.0, p.right == OptionRight.call ? p.spot * dq - p.strike * dr : p.strike * dr - p.spot * dq);
  final upper = p.right == OptionRight.call ? p.spot * (american ? 1 : dq) : p.strike * (american ? 1 : dr);
  if (price < lower - 1e-9) return const ImpliedVolResult(null, 'PRICE_BELOW_INTRINSIC', 0);
  if (price >= upper) return const ImpliedVolResult(null, 'PRICE_ABOVE_UPPER_BOUND', 0);
  // Less than half a cent of time value cannot identify a volatility.
  if (price - lower <= math.max(minTimeValue, 1e-9)) return const ImpliedVolResult(null, 'NO_TIME_VALUE', 0);
  double f(double v) => (american ? americanPrice(p.withVol(v), steps: steps) : europeanGreeks(p.withVol(v)).price) - price;
  // The CRR tree needs sigma * sqrt(dt) > |r - q| * dt for valid probabilities.
  var lo = american ? math.max(ivMin, 1.01 * (p.rate - p.dividendYield).abs() * math.sqrt(t / steps) + 1e-6) : ivMin;
  var hi = ivMax, flo = f(lo), fhi = f(hi);
  if (flo > 0) return const ImpliedVolResult(null, 'NO_TIME_VALUE', 0);
  if (fhi < 0) return const ImpliedVolResult(null, 'VOLATILITY_ABOVE_RANGE', 0);
  var v = 0.3.clamp(lo, hi).toDouble();
  for (var i = 1; i <= 200; i++) {
    final fv = f(v);
    if (fv.abs() < tolerance * 1e-2 || (hi - lo) < tolerance) return ImpliedVolResult(v, null, i);
    if (fv > 0) {
      hi = v;
    } else {
      lo = v;
    }
    // Newton step (analytic vega for European); fall back to bisection when it leaves the bracket.
    double next = (lo + hi) / 2;
    if (!american) {
      final vega = europeanGreeks(p.withVol(v)).vega;
      if (vega > 1e-12) {
        final n = v - fv / vega;
        if (n > lo && n < hi) next = n;
      }
    }
    if ((next - v).abs() < tolerance) return ImpliedVolResult(next, null, i);
    v = next;
  }
  return const ImpliedVolResult(null, 'NOT_CONVERGED', 200);
}

/// Year fraction (ACT/365) from [now] to the close of the contract's last trading
/// session, using the shared versioned calendar. Null when the calendar cannot say.
double? yearsToExpiry(String contract, DateTime now) {
  final e = paperExpiry(contract, now);
  if (!e.close) return null;
  final m = OptionQuote.pattern.firstMatch(contract);
  if (m == null) return null;
  final nominal = DateTime.utc(2000 + int.parse(m[2]!), int.parse(m[3]!), int.parse(m[4]!), 12);
  for (var back = 0; back < 8; back++) {
    final s = paperSession(nominal.subtract(Duration(days: back)));
    if (s.status == 'NO_SESSION') continue;
    final close = s.closes;
    if (close == null) return null;
    final ms = close.difference(now.toUtc()).inMilliseconds;
    return ms > 0 ? ms / (365 * 24 * 3600 * 1000) : null;
  }
  return null;
}
