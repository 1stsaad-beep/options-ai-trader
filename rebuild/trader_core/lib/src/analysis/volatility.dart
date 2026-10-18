/// Realised volatility, implied volatility and the IV/RV entry filter.
///
/// Background (research round 4, `rebuild/research/report4/10_main.md`): the
/// weekly contracts the signals buy were priced with real implied volatility
/// well above the underlying's realised volatility (A: 31% vs 24%, C: 49% vs
/// 24%), so the premium swallowed the predicted move. The report recommends
/// logging the real IV and bid/ask of every order and an *optional* IV/RV cap
/// "to be tuned later" — it also found that IV/RV buckets did not separate
/// winners from losers consistently between periods. Hence: always measured and
/// logged, blocking only when the user enables it.
library;

import 'dart:math' as math;

import '../market/market_calendar.dart';
import '../models.dart';
import '../options_math.dart';

/// Annualised close-to-close volatility of the last [lookback] log returns
/// (sample stdev × sqrt(barsPerYear)). Null when there is not enough data.
double? realizedVol(List<double> closes, {int lookback = 20, double barsPerYear = 252}) {
  if (closes.length < lookback + 1 || lookback < 2) return null;
  final r = <double>[];
  for (var i = closes.length - lookback; i < closes.length; i++) {
    final a = closes[i - 1], b = closes[i];
    if (a <= 0 || b <= 0) return null;
    r.add(math.log(b / a));
  }
  final mean = r.reduce((x, y) => x + y) / r.length;
  var ss = 0.0;
  for (final x in r) {
    ss += (x - mean) * (x - mean);
  }
  return math.sqrt(ss / (r.length - 1)) * math.sqrt(barsPerYear);
}

/// Implied volatility solved from an option price (bisection on Black-Scholes).
/// Null when the price is outside the no-arbitrage range.
double? impliedVolFromPrice({
  required bool isCall,
  required double spot,
  required double strike,
  required double years,
  required double price,
  double rate = 0.04,
}) {
  if (spot <= 0 || strike <= 0 || years <= 0 || price <= 0) return null;
  double f(double v) => blackScholes(isCall: isCall, spot: spot, strike: strike, years: years, vol: v, rate: rate).price;
  var lo = 0.005, hi = 6.0;
  if (price < f(lo) - 1e-9 || price > f(hi)) return null;
  for (var i = 0; i < 80; i++) {
    final mid = (lo + hi) / 2;
    if (f(mid) > price) {
      hi = mid;
    } else {
      lo = mid;
    }
  }
  return (lo + hi) / 2;
}

/// Years from [now] to the 16:00 New York close of the contract's expiry date
/// (at least one hour).
double yearsToExpiry(OptionContract c, DateTime now) {
  final close = NewYorkTime.toUtc(c.expiry.year, c.expiry.month, c.expiry.day, 16);
  final minutes = math.max(60, close.difference(now.toUtc()).inMinutes);
  return minutes / (365 * 24 * 60);
}

/// Settings of the filter (a view over AccountSettings so the core stays testable).
class VolFilterSettings {
  final bool enabled;
  final double maxIvRvRatio;
  final int rvLookbackDays;
  final bool useIntradayRv;

  /// Block when the move needed to break even at expiry exceeds this multiple of
  /// the expected move (spot × RV × sqrt(T)); 0 = off.
  final double maxBreakevenToExpectedMove;
  const VolFilterSettings({
    this.enabled = false,
    this.maxIvRvRatio = 1.5,
    this.rvLookbackDays = 20,
    this.useIntradayRv = false,
    this.maxBreakevenToExpectedMove = 1.0,
  });
}

class VolCheck {
  final double? iv;

  /// `broker` (snapshot greeks) or `solved` (from the mid price) or `none`.
  final String ivSource;
  final double? rvDaily;
  final double? rvIntraday;

  /// RV used for the ratio (daily, or intraday when chosen and available).
  final double? rv;
  final double? ivRv;
  final double breakevenMovePct;
  final double? expectedMovePct;
  final double? breakevenToExpected;
  final double years;

  /// Arabic reason when the filter blocks the entry (only if enabled).
  final String? blockReasonAr;

  const VolCheck({
    required this.iv,
    required this.ivSource,
    required this.rvDaily,
    required this.rvIntraday,
    required this.rv,
    required this.ivRv,
    required this.breakevenMovePct,
    required this.expectedMovePct,
    required this.breakevenToExpected,
    required this.years,
    required this.blockReasonAr,
  });

  bool get blocked => blockReasonAr != null;

  static String _p(double? v) => v == null ? '—' : '${(v * 100).toStringAsFixed(1)}%';

  String get summaryAr => 'التقلب الضمني ${_p(iv)}${ivSource == 'solved' ? ' (محسوب من السعر)' : ''} • '
      'المحقق ${_p(rv)} • IV/RV ${ivRv?.toStringAsFixed(2) ?? '—'} • '
      'حركة التعادل ${breakevenMovePct.toStringAsFixed(2)}% مقابل الحركة المتوقعة ${expectedMovePct?.toStringAsFixed(2) ?? '—'}%';

  Map<String, Object?> toJson() => {
        'iv': iv == null ? null : double.parse(iv!.toStringAsFixed(4)),
        'ivSource': ivSource,
        'rvDaily': rvDaily == null ? null : double.parse(rvDaily!.toStringAsFixed(4)),
        'rvIntraday': rvIntraday == null ? null : double.parse(rvIntraday!.toStringAsFixed(4)),
        'ivRv': ivRv == null ? null : double.parse(ivRv!.toStringAsFixed(3)),
        'breakevenMovePct': double.parse(breakevenMovePct.toStringAsFixed(3)),
        'expectedMovePct': expectedMovePct == null ? null : double.parse(expectedMovePct!.toStringAsFixed(3)),
        'blocked': blocked,
      };
}

/// Measures IV, RV, IV/RV and break-even vs expected move for buying [q] and,
/// when [f] is enabled, decides whether the entry is blocked.
///
/// [daily]: completed daily bars of the underlying; [intraday]: completed bars of
/// the analysis timeframe with [intradayBarsPerDay] bars per session.
VolCheck evaluateVolFilter({
  required VolFilterSettings f,
  required OptionQuote q,
  required double spot,
  required DateTime now,
  required List<Candle> daily,
  List<Candle>? intraday,
  int intradayBarsPerDay = 26,
}) {
  final c = q.contract;
  final isCall = c.right == OptionRight.call;
  final years = yearsToExpiry(c, now);
  final premium = (q.isTwoSided ? q.midCents : q.askCents) / 100.0;
  var iv = q.impliedVolatility;
  var source = 'broker';
  if (iv == null || iv <= 0) {
    iv = impliedVolFromPrice(isCall: isCall, spot: spot, strike: c.strike, years: years, price: premium);
    source = iv == null ? 'none' : 'solved';
  }
  final rvD = realizedVol([for (final b in daily) b.close], lookback: f.rvLookbackDays);
  double? rvI;
  if (intraday != null && intradayBarsPerDay > 0) {
    final n = math.min(intraday.length - 1, f.rvLookbackDays * intradayBarsPerDay);
    if (n >= 20) rvI = realizedVol([for (final b in intraday) b.close], lookback: n, barsPerYear: 252.0 * intradayBarsPerDay);
  }
  final rv = f.useIntradayRv && rvI != null ? rvI : rvD;
  final ratio = (iv != null && rv != null && rv > 0) ? iv / rv : null;
  final breakeven = isCall ? math.max(0.0, c.strike + premium - spot) : math.max(0.0, spot - (c.strike - premium));
  final expected = rv == null ? null : spot * rv * math.sqrt(years);
  final beToExp = (expected == null || expected <= 0) ? null : breakeven / expected;

  String? reason;
  if (f.enabled) {
    if (ratio != null && ratio > f.maxIvRvRatio) {
      reason = 'فلتر التقلب: IV/RV = ${ratio.toStringAsFixed(2)} أعلى من الحد ${f.maxIvRvRatio.toStringAsFixed(2)} — العقد غالٍ مقارنة بحركة السهم الفعلية';
    } else if (f.maxBreakevenToExpectedMove > 0 && beToExp != null && beToExp > f.maxBreakevenToExpectedMove) {
      reason = 'فلتر التقلب: حركة التعادل حتى الانتهاء (${(breakeven / spot * 100).toStringAsFixed(2)}%) تتجاوز '
          '${f.maxBreakevenToExpectedMove.toStringAsFixed(2)}× الحركة المتوقعة (${(expected! / spot * 100).toStringAsFixed(2)}%)';
    } else if (ratio == null) {
      reason = 'فلتر التقلب: تعذر حساب IV أو RV — لا دخول بدون قياس';
    }
  }
  return VolCheck(
    iv: iv,
    ivSource: source,
    rvDaily: rvD,
    rvIntraday: rvI,
    rv: rv,
    ivRv: ratio,
    breakevenMovePct: breakeven / spot * 100,
    expectedMovePct: expected == null ? null : expected / spot * 100,
    breakevenToExpected: beToExp,
    years: years,
    blockReasonAr: reason,
  );
}
