import 'package:flutter_test/flutter_test.dart';
import 'package:options_ai_trader/option_pricing.dart';

PricingInput inp(double s, double k, double t, double r, double q, double v, OptionRight right) =>
    PricingInput(spot: s, strike: k, years: t, rate: r, dividendYield: q, volatility: v, right: right);

void near(double actual, double expected, double tol, [String? what]) =>
    expect((actual - expected).abs(), lessThanOrEqualTo(tol), reason: '${what ?? ''} $actual vs $expected');

void main() {
  test('normal CDF reference values', () {
    near(normCdf(0), 0.5, 1e-15);
    near(normCdf(1.96), 0.9750021048517795, 1e-13);
    near(normCdf(-1), 0.15865525393145707, 1e-13);
    near(normCdf(-8), 6.22096057427178e-16, 1e-20);
    near(normCdf(3) + normCdf(-3), 1, 1e-15);
  });

  // Hull, Options Futures & Other Derivatives, Example 15.6: S=42 K=40 r=10% sigma=20% T=0.5.
  test('Hull 15.6 European call 4.76 and put 0.81', () {
    near(europeanGreeks(inp(42, 40, 0.5, 0.1, 0, 0.2, OptionRight.call)).price, 4.7594, 1e-3);
    near(europeanGreeks(inp(42, 40, 0.5, 0.1, 0, 0.2, OptionRight.put)).price, 0.8086, 1e-3);
  });

  // Hull Greek letters chapter: S=49 K=50 r=5% sigma=20% T=20 weeks (0.3846).
  test('Hull Greek letters example (call)', () {
    final g = europeanGreeks(inp(49, 50, 0.3846, 0.05, 0, 0.2, OptionRight.call));
    near(g.price, 2.40, 0.005, 'price');
    near(g.delta, 0.522, 0.001, 'delta');
    near(g.gamma, 0.066, 0.001, 'gamma');
    near(g.theta, -4.31, 0.01, 'theta/yr');
    near(g.vega, 12.1, 0.05, 'vega');
    near(g.rho, 8.91, 0.01, 'rho');
  });

  // Haug, The Complete Guide to Option Pricing Formulas (2nd ed.), chapter 1/2 examples; q = r - b.
  test('Haug generalized BSM reference values', () {
    near(europeanGreeks(inp(100, 95, 0.5, 0.10, 0.05, 0.20, OptionRight.put)).price, 2.4648, 1e-4, 'Merton put');
    final dc = europeanGreeks(inp(105, 100, 0.5, 0.10, 0.10, 0.36, OptionRight.call));
    final dp = europeanGreeks(inp(105, 100, 0.5, 0.10, 0.10, 0.36, OptionRight.put));
    near(dc.delta, 0.5946, 1e-4, 'call delta');
    near(dp.delta, -0.3566, 1e-4, 'put delta');
    near(europeanGreeks(inp(55, 60, 0.75, 0.10, 0.0, 0.30, OptionRight.call)).gamma, 0.0278, 1e-4, 'gamma');
    near(europeanGreeks(inp(430, 405, 0.0833, 0.07, 0.05, 0.20, OptionRight.put)).theta, -31.1924, 2e-3, 'theta');
    near(europeanGreeks(inp(72, 75, 1, 0.09, 0, 0.19, OptionRight.call)).rho, 38.7325, 1e-3, 'rho');
  });

  test('analytic Greeks match finite differences and put-call parity', () {
    for (final right in OptionRight.values) {
      final p = inp(100, 105, 0.4, 0.04, 0.015, 0.27, right), g = europeanGreeks(p);
      double price(PricingInput x) => europeanGreeks(x).price;
      const h = 1e-3;
      near(g.delta, (price(p.copy(spot: 100 + h)) - price(p.copy(spot: 100 - h))) / (2 * h), 1e-6, 'delta');
      near(g.gamma, (price(p.copy(spot: 100 + h)) - 2 * g.price + price(p.copy(spot: 100 - h))) / (h * h), 1e-4, 'gamma');
      near(g.vega, (price(p.withVol(0.27 + h)) - price(p.withVol(0.27 - h))) / (2 * h), 1e-5, 'vega');
      near(g.rho, (price(p.copy(rate: 0.04 + h)) - price(p.copy(rate: 0.04 - h))) / (2 * h), 1e-4, 'rho');
      near(g.theta, -(price(p.copy(years: 0.4 + h)) - price(p.copy(years: 0.4 - h))) / (2 * h), 1e-4, 'theta');
    }
    final c = europeanGreeks(inp(100, 105, 0.4, 0.04, 0.015, 0.27, OptionRight.call)).price;
    final p = europeanGreeks(inp(100, 105, 0.4, 0.04, 0.015, 0.27, OptionRight.put)).price;
    near(c - p, 100 * 0.9940179640 - 105 * 0.9841273200, 1e-6, 'parity'); // e^{-qT}, e^{-rT}
  });

  // Hull American put example: S=50 K=50 r=10% sigma=40% T=5 months; 5-step tree 4.49, converged ~4.28.
  test('CRR American put reference values', () {
    final p = inp(50, 50, 5 / 12, 0.1, 0, 0.4, OptionRight.put);
    near(americanPrice(p, steps: 5), 4.49, 0.005, '5 steps');
    near(americanPrice(p, steps: 500), 4.28, 0.01, '500 steps');
    expect(americanPrice(p, steps: 500), greaterThan(europeanGreeks(p).price));
  });

  test('American call without dividends equals European; tree Greeks are close', () {
    final p = inp(49, 50, 0.3846, 0.05, 0, 0.2, OptionRight.call), e = europeanGreeks(p), a = americanGreeks(p, steps: 400);
    near(a.price, e.price, 0.01, 'price');
    near(a.delta, e.delta, 0.005, 'delta');
    near(a.gamma, e.gamma, 0.003, 'gamma');
    near(a.theta, e.theta, 0.05, 'theta');
    near(a.vega, e.vega, 0.1, 'vega');
    near(a.rho, e.rho, 0.1, 'rho');
  });

  test('implied volatility: Hull 21/20 call at 1.875 -> 23.5 %, and round trips', () {
    final r = impliedVolatility(1.875, inp(21, 20, 0.25, 0.1, 0, 0.2, OptionRight.call));
    expect(r.solved, isTrue);
    near(r.volatility!, 0.235, 0.0005);
    for (final right in OptionRight.values) {
      for (final v in [0.05, 0.2, 0.6, 1.5]) {
        final p = inp(100, 90, 0.3, 0.04, 0.01, v, right);
        final iv = impliedVolatility(europeanGreeks(p).price, p, minTimeValue: 0);
        expect(iv.solved, isTrue, reason: '$right $v ${iv.reason}');
        near(iv.volatility!, v, 1e-5, '$right $v');
      }
    }
  });

  test('American implied volatility round trip on the tree', () {
    final p = inp(50, 55, 0.5, 0.05, 0, 0.35, OptionRight.put);
    final iv = impliedVolatility(americanPrice(p, steps: 150), p, american: true, steps: 150);
    expect(iv.solved, isTrue);
    near(iv.volatility!, 0.35, 1e-4);
  });

  test('implied volatility fails closed with reasons', () {
    final call = inp(100, 90, 0.25, 0.05, 0, 0.2, OptionRight.call);
    expect(impliedVolatility(5, call).reason, 'PRICE_BELOW_INTRINSIC');
    expect(impliedVolatility(100, call).reason, 'PRICE_ABOVE_UPPER_BOUND');
    expect(impliedVolatility(0, call).reason, 'INVALID_INPUT');
    expect(impliedVolatility(double.nan, call).reason, 'INVALID_INPUT');
    expect(impliedVolatility(1, inp(100, 90, 0, 0.05, 0, 0.2, OptionRight.call)).reason, 'INVALID_INPUT');
    // Exactly the discounted intrinsic: no time value to imply a volatility from.
    expect(impliedVolatility(100 - 90 * 0.98757780049, call).reason, 'NO_TIME_VALUE');
    // Sub-half-cent time value is refused by default.
    expect(impliedVolatility(0.004, inp(100, 130, 0.05, 0.05, 0, 0.2, OptionRight.call)).reason, 'NO_TIME_VALUE');
    expect(() => europeanGreeks(inp(-1, 90, 0.25, 0.05, 0, 0.2, OptionRight.call)), throwsArgumentError);
  });

  test('years to expiry uses the last session close on the shared calendar', () {
    // 2026-11-20 is a Friday; close 16:00 New York = 21:00Z (EST).
    final t = yearsToExpiry('AAPL261120C00200000', DateTime.utc(2026, 11, 19, 21));
    near(t!, 1 / 365, 1e-9);
    expect(yearsToExpiry('AAPL261120C00200000', DateTime.utc(2026, 11, 20, 21, 1)), isNull);
    expect(yearsToExpiry('BAD', DateTime.utc(2026, 11, 19)), isNull);
    expect(yearsToExpiry('AAPL281120C00200000', DateTime.utc(2026, 11, 19)), isNull); // unsupported calendar year
  });
}
