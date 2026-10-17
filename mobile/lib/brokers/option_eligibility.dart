/// On-phone option entry eligibility (B9).
///
/// An entry (BUY_TO_OPEN) is eligible only if every check passes, using data fetched
/// now on the phone: Alpaca contract terms (standard deliverable, active/tradable,
/// open interest), the executable option quote (spread), a fresh underlying quote, and
/// model Greeks/IV computed from the quote mid (B8). Closing orders are never vetoed here.
/// Policy defaults are conservative placeholders that need user review.
library;

import '../option_pricing.dart';
import 'broker_options.dart';

class EligibilityPolicy {
  final int minOpenInterest, maxOpenInterestAgeDays, maxSpreadBps, maxUnderlyingAgeSeconds;
  final double minAbsDelta, maxAbsDelta, maxImpliedVol, rate, dividendYield;
  const EligibilityPolicy({this.minOpenInterest = 100, this.maxOpenInterestAgeDays = 5, this.maxSpreadBps = 1500,
      this.maxUnderlyingAgeSeconds = 30, this.minAbsDelta = 0.15, this.maxAbsDelta = 0.85, this.maxImpliedVol = 3.0,
      this.rate = 0.04, this.dividendYield = 0});
  Map<String, Object> toJson() => {'version': 'oat-eligibility-v1', 'minOpenInterest': minOpenInterest,
        'maxOpenInterestAgeDays': maxOpenInterestAgeDays, 'maxSpreadBps': maxSpreadBps,
        'maxUnderlyingAgeSeconds': maxUnderlyingAgeSeconds, 'minAbsDelta': minAbsDelta, 'maxAbsDelta': maxAbsDelta,
        'maxImpliedVol': maxImpliedVol, 'rate': rate, 'dividendYield': dividendYield, 'model': pricingModelVersion};
}

class UnderlyingQuote {
  final String symbol;
  final int bidCents, askCents;
  final DateTime time;
  const UnderlyingQuote(this.symbol, this.bidCents, this.askCents, this.time);
  /// Parses the existing native `paper-delivery-valuation-v1` stock quote.
  static UnderlyingQuote? fromDirect(Map<String, dynamic>? j) {
    if (j == null || j['version'] != 'paper-delivery-valuation-v1') return null;
    final at = DateTime.tryParse('${j['at']}'), b = j['bidCents'], a = j['askCents'];
    if (at == null || b is! int || a is! int || j['symbol'] is! String) return null;
    return UnderlyingQuote(j['symbol'] as String, b, a, at);
  }
}

class OptionEligibility {
  final bool eligible;
  final List<String> reasons, passed;
  final Map<String, Object?> facts; // model values are labeled MODEL_FROM_QUOTE_MID
  const OptionEligibility(this.eligible, this.reasons, this.passed, this.facts);
  Map<String, Object?> toJson() => {'contract': 'oat-option-eligibility-v1', 'eligible': eligible,
        'reasons': reasons, 'passed': passed, 'facts': facts};
}

int? _hundredths(Object? v) {
  // Decimal string/number -> value * 100 (exact for up to two decimals), else null.
  final text = v is num ? v.toString() : v is String ? v : null;
  if (text == null || !RegExp(r'^\d{1,12}(\.\d{1,8})?$').hasMatch(text)) return null;
  final parts = text.split('.');
  final frac = parts.length == 1 ? '' : parts[1].replaceAll(RegExp(r'0+$'), '');
  if (frac.length > 2) return null;
  return int.parse(parts[0]) * 100 + int.parse(frac.padRight(2, '0'));
}

/// Same "standard contract" rule as the server's option-eligibility-v1: American,
/// multiplier 100, size 100, root == underlying, a single equity deliverable of 100
/// shares of the underlying (100 % allocation, T+1, not delayed).
List<String> termsReasons(Map<String, dynamic> t, OccContract c, DateTime now, EligibilityPolicy policy) {
  final r = <String>[];
  final expiry = '20${c.yymmdd.substring(0, 2)}-${c.yymmdd.substring(2, 4)}-${c.yymmdd.substring(4, 6)}';
  final strike = _hundredths(t['strike_price']);
  if (t['symbol'] != c.occ || t['root_symbol'] != c.root || t['expiration_date'] != expiry ||
      t['type'] != (c.right == 'C' ? 'call' : 'put') || strike == null || strike * 10 != c.strikeMilli) {
    return ['CONTRACT_TERMS_IDENTITY_MISMATCH'];
  }
  if (t['status'] != 'active' || t['tradable'] != true) r.add('CONTRACT_NOT_TRADABLE');
  final d = t['deliverables'];
  final one = d is List && d.length == 1 && d.first is Map ? d.first as Map : null;
  final standard = t['style'] == 'american' && _hundredths(t['multiplier']) == 10000 && _hundredths(t['size']) == 10000 &&
      t['underlying_symbol'] == c.root && one != null && one['type'] == 'equity' && one['symbol'] == c.root &&
      (t['underlying_asset_id'] == null || one['asset_id'] == t['underlying_asset_id']) &&
      _hundredths(one['amount']) == 10000 && _hundredths(one['allocation_percentage']) == 10000 &&
      one['delayed_settlement'] == false && one['settlement_type'] == 'T+1';
  if (!standard) r.add('ADJUSTED_OR_UNSUPPORTED_CONTRACT');
  final oi = t['open_interest'] == null ? null : int.tryParse('${t['open_interest']}');
  final oiDate = DateTime.tryParse('${t['open_interest_date']}');
  if (oi == null || oiDate == null) {
    r.add('OPEN_INTEREST_UNAVAILABLE');
  } else if (now.toUtc().difference(DateTime.utc(oiDate.year, oiDate.month, oiDate.day)).inDays > policy.maxOpenInterestAgeDays) {
    r.add('OPEN_INTEREST_STALE');
  } else if (oi < policy.minOpenInterest) {
    r.add('OPEN_INTEREST_TOO_LOW');
  }
  return r;
}

OptionEligibility evaluateEligibility({required OccContract contract, required Map<String, dynamic>? terms,
    required BrokerQuote? quote, required UnderlyingQuote? underlying, required DateTime now,
    EligibilityPolicy policy = const EligibilityPolicy()}) {
  final reasons = <String>[], passed = <String>[];
  final facts = <String, Object?>{'policy': policy.toJson()};
  void check(String name, List<String> failed) => failed.isEmpty ? passed.add(name) : reasons.addAll(failed);

  if (terms == null) {
    reasons.add('CONTRACT_TERMS_UNAVAILABLE');
  } else {
    check('CONTRACT_TERMS', termsReasons(terms, contract, now, policy));
    facts['openInterest'] = terms['open_interest'];
    facts['openInterestDate'] = terms['open_interest_date'];
    facts['style'] = terms['style'];
  }

  final years = yearsToExpiry(contract.occ, now);
  if (years == null) reasons.add('EXPIRY_TIME_UNAVAILABLE');

  int? midCents2; // mid * 2 in cents to stay integral
  if (quote == null || quote.bid <= 0 || quote.ask < quote.bid) {
    reasons.add('OPTION_QUOTE_UNUSABLE');
  } else {
    midCents2 = quote.bid + quote.ask;
    final spreadBps = (quote.ask - quote.bid) * 20000 ~/ midCents2;
    facts['spreadBps'] = spreadBps;
    check('SPREAD', spreadBps > policy.maxSpreadBps ? ['SPREAD_TOO_WIDE'] : []);
  }

  double? spot;
  if (underlying == null || underlying.symbol != contract.root || underlying.bidCents <= 0 ||
      underlying.askCents < underlying.bidCents) {
    reasons.add('UNDERLYING_QUOTE_UNAVAILABLE');
  } else {
    final age = now.difference(underlying.time);
    if (age.isNegative || age.inSeconds > policy.maxUnderlyingAgeSeconds) {
      reasons.add('UNDERLYING_QUOTE_STALE');
    } else {
      spot = (underlying.bidCents + underlying.askCents) / 200;
      facts['underlyingMid'] = spot;
      passed.add('UNDERLYING_QUOTE');
    }
  }

  if (years != null && midCents2 != null && spot != null) {
    final input = PricingInput(spot: spot, strike: contract.strikeMilli / 1000, years: years, rate: policy.rate,
        dividendYield: policy.dividendYield, volatility: 0.2, right: contract.right == 'C' ? OptionRight.call : OptionRight.put);
    final american = terms?['style'] != 'european';
    final iv = impliedVolatility(midCents2 / 200, input, american: american, steps: 150);
    if (!iv.solved) {
      reasons.add('IMPLIED_VOL_${iv.reason}');
    } else {
      final g = american ? americanGreeks(input.withVol(iv.volatility!), steps: 150) : europeanGreeks(input.withVol(iv.volatility!));
      facts['greeksSource'] = 'MODEL_FROM_QUOTE_MID';
      facts['impliedVol'] = iv.volatility;
      facts['greeks'] = g.toJson();
      final f = <String>[
        if (iv.volatility! > policy.maxImpliedVol) 'IMPLIED_VOL_TOO_HIGH',
        if (g.delta.abs() < policy.minAbsDelta) 'DELTA_TOO_SMALL',
        if (g.delta.abs() > policy.maxAbsDelta) 'DELTA_TOO_LARGE',
      ];
      check('GREEKS', f);
    }
  }
  return OptionEligibility(reasons.isEmpty, List.unmodifiable(reasons), List.unmodifiable(passed), facts);
}
