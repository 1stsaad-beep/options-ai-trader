/// Position sizing and contract selection — pure functions.
library;

import 'dart:math' as math;

import '../models.dart';
import '../options_math.dart';
import 'account.dart';

class SizingResult {
  final int quantity;
  final String reasonAr;
  const SizingResult(this.quantity, this.reasonAr);
}

/// How many contracts to buy at [premiumCents] (per share).
///
/// quantity = min(
///   riskBudget / (premium × multiplier × stopLoss%),   // risk per trade
///   positionBudget / (premium × multiplier),           // max position size
///   exposureLeft / (premium × multiplier),             // total exposure cap
///   buyingPower / (premium × multiplier + fee),        // cash
///   maxContractsPerTrade)
SizingResult sizePosition({
  required AccountSettings s,
  required int equityCents,
  required int buyingPowerCents,
  required int openExposureCents,
  required int premiumCents,
  int multiplier = 100,
  int feePerContractCents = 65,
}) {
  if (premiumCents <= 0 || equityCents <= 0) return const SizingResult(0, 'سعر أو رصيد غير صالح');
  final perContract = premiumCents * multiplier;
  final atRisk = perContract * s.stopLossPercent / 100;
  final byRisk = (equityCents * s.riskPerTradePercent / 100 / atRisk).floor();
  final byPosition = (equityCents * s.maxPositionPercent / 100 / perContract).floor();
  final exposureLeft = equityCents * s.maxTotalExposurePercent / 100 - openExposureCents;
  final byExposure = exposureLeft <= 0 ? 0 : (exposureLeft / perContract).floor();
  final byCash = (buyingPowerCents / (perContract + feePerContractCents)).floor();
  final q = [byRisk, byPosition, byExposure, byCash, s.maxContractsPerTrade].reduce(math.min);
  final limiter = q == byRisk
      ? 'نسبة المخاطرة'
      : q == byPosition
          ? 'حجم المركز الأقصى'
          : q == byExposure
              ? 'التعرض الكلي'
              : q == byCash
                  ? 'القوة الشرائية'
                  : 'الحد الأقصى للعقود';
  return SizingResult(math.max(0, q), q <= 0 ? 'الحجم صفر بسبب $limiter' : '$q عقد (المحدِّد: $limiter)');
}

class ContractChoice {
  final OptionQuote quote;
  final double delta;
  final String reasonAr;
  const ContractChoice(this.quote, this.delta, this.reasonAr);
}

/// Picks the contract closest to the target delta among liquid contracts
/// within the DTE window. Prefers the nearest expiry that meets the minimum
/// DTE (cheaper theta-wise than very short ones, cheaper premium than far ones).
/// Delta comes from the broker when provided, else from Black–Scholes.
ContractChoice? selectContract({
  required AccountSettings s,
  required List<OptionQuote> chain,
  required OptionRight right,
  required double spot,
  required DateTime now,
}) {
  ContractChoice? best;
  double bestScore = double.infinity;
  for (final q in chain) {
    final c = q.contract;
    if (c.right != right) continue;
    final dte = c.daysToExpiry(now);
    if (dte < s.minDaysToExpiry || dte > s.maxDaysToExpiry) continue;
    if (!q.isTwoSided || q.spreadFraction * 100 > s.maxSpreadPercent) continue;
    if (q.openInterest > 0 && q.openInterest < s.minOpenInterest) continue;
    final delta = (q.delta ??
            blackScholes(
              isCall: right == OptionRight.call,
              spot: spot,
              strike: c.strike,
              years: math.max(dte, 1) / 365,
              vol: q.impliedVolatility ?? 0.35,
            ).delta)
        .abs();
    if (delta < 0.15 || delta > 0.85) continue;
    // Score: delta distance dominates, then shorter DTE, then tighter spread.
    final score = (delta - s.targetDelta).abs() * 10 + dte / 365 + q.spreadFraction;
    if (score < bestScore) {
      bestScore = score;
      best = ContractChoice(
        q,
        delta,
        'العقد ${c.occSymbol}: دلتا ${delta.toStringAsFixed(2)}، $dte يوم للانتهاء، '
        'فرق السعر ${(q.spreadFraction * 100).toStringAsFixed(1)}%',
      );
    }
  }
  return best;
}

/// Buy limit between bid (aggressiveness 0) and ask (1).
int limitPrice(OptionQuote q, double aggressiveness) {
  final a = aggressiveness.clamp(0.0, 1.0);
  return math.max(1, (q.bidCents + (q.askCents - q.bidCents) * a).round());
}

/// Sell limit between ask (aggressiveness 0) and bid (1) — mirror of [limitPrice].
int sellLimitPrice(OptionQuote q, double aggressiveness) {
  final a = aggressiveness.clamp(0.0, 1.0);
  return math.max(1, (q.askCents - (q.askCents - q.bidCents) * a).round());
}
