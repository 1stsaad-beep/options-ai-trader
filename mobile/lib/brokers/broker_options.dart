/// OCC option identity, broker symbol mapping, exact cents and quote qualification.
library;

import '../direct_alpaca.dart' show OptionQuote;
import 'broker_models.dart';

class OccContract {
  final String root, yymmdd, right; // right: C or P
  final int strikeMilli;
  const OccContract._(this.root, this.yymmdd, this.right, this.strikeMilli);

  /// Same identity rule as the existing Direct/Market Paper code ([OptionQuote.pattern]).
  static OccContract? parse(String text) {
    final m = OptionQuote.pattern.firstMatch(text.trim().toUpperCase());
    if (m == null) return null;
    final strike = int.parse(m[6]!);
    if (strike <= 0) return null;
    return OccContract._(m[1]!, '${m[2]}${m[3]}${m[4]}', m[5]!, strike);
  }

  String get occ => '$root$yymmdd$right${strikeMilli.toString().padLeft(8, '0')}';
  String get direction => right == 'C' ? 'CALL' : 'PUT';

  String get _strikeText {
    final whole = strikeMilli ~/ 1000, frac = strikeMilli % 1000;
    if (frac == 0) return '$whole';
    return '$whole.${frac.toString().padLeft(3, '0').replaceAll(RegExp(r'0+$'), '')}';
  }

  /// TradeStation option symbol, e.g. `AAPL 261120C200` / `SPY 261120P502.5`.
  String get tradeStationSymbol => '$root $yymmdd$right$_strikeText';

  static final _ts = RegExp(r'^([A-Z]{1,6}) (\d{6})([CP])(\d{1,5}(?:\.\d{1,3})?)$');
  static OccContract? fromTradeStation(String symbol) {
    final m = _ts.firstMatch(symbol.trim());
    if (m == null) return null;
    final parts = m[4]!.split('.');
    final milli = int.parse(parts[0]) * 1000 + (parts.length > 1 ? int.parse(parts[1].padRight(3, '0')) : 0);
    return parse('${m[1]}${m[2]}${m[3]}${milli.toString().padLeft(8, '0')}');
  }

  /// Broker order symbol for this contract.
  String symbolFor(BrokerKind broker) => broker == BrokerKind.tradestation ? tradeStationSymbol : occ;
}

/// Normalizes a broker position symbol to OCC, or null for non-option / unknown rows.
String? positionOcc(BrokerKind broker, BrokerPosition p) {
  if (broker == BrokerKind.tradestation) return OccContract.fromTradeStation(p.symbol)?.occ;
  return OccContract.parse(p.symbol.replaceAll(' ', ''))?.occ;
}

/// Exact decimal string -> cents. Extra precision is rounded in the conservative
/// direction requested ([up] = toward +infinity). Returns null for invalid input.
int? decimalCents(String? text, {bool up = false}) {
  if (text == null) return null;
  final m = RegExp(r'^(-?)(\d{1,13})(?:\.(\d{1,12}))?$').firstMatch(text.trim());
  if (m == null) return null;
  final negative = m[1] == '-';
  final frac = m[3] ?? '';
  var cents = int.parse(m[2]!) * 100 + int.parse(frac.padRight(2, '0').substring(0, 2));
  final remainder = frac.length > 2 && RegExp(r'[1-9]').hasMatch(frac.substring(2));
  if (remainder && (up != negative)) cents += 1;
  return negative ? -cents : cents;
}

String centsText(int cents) {
  final sign = cents < 0 ? '-' : '';
  final a = cents.abs();
  return '$sign${a ~/ 100}.${(a % 100).toString().padLeft(2, '0')}';
}

class BrokerQuote {
  final String contract; // OCC
  final int bid, ask, bidSize, askSize; // cents / contracts
  final DateTime time;
  final String source, timeSource; // timeSource: QUOTE (provider timestamp) or RECEIVED (local receipt)
  const BrokerQuote({required this.contract, required this.bid, required this.ask, required this.bidSize,
      required this.askSize, required this.time, required this.source, required this.timeSource});

  factory BrokerQuote.fromDirect(OptionQuote q) => BrokerQuote(contract: q.contract, bid: q.bid, ask: q.ask,
      bidSize: q.bidSize, askSize: q.askSize, time: q.time, source: 'alpaca-direct-${q.feed}', timeSource: 'QUOTE');

  Map<String, Object> toJson() => {'contract': contract, 'bid': bid, 'ask': ask, 'bidSize': bidSize,
        'askSize': askSize, 'at': time.toUtc().toIso8601String(), 'source': source, 'timeSource': timeSource};
}

/// Thresholds mirror [OptionQuote.valid]: age 0..30 s, bid > 0, ask >= bid,
/// spread <= 20% of ask, displayed size on both sides >= quantity.
String? quoteReason(BrokerQuote? q, String contract, int quantity, DateTime now) {
  if (q == null) return 'QUOTE_UNAVAILABLE';
  if (q.contract != contract) return 'QUOTE_MISMATCH';
  final age = now.toUtc().difference(q.time.toUtc()).inMicroseconds;
  if (age < 0 || age > 30000000) return 'QUOTE_STALE';
  if (q.bid <= 0 || q.ask < q.bid || q.ask > 100000000) return 'QUOTE_INVALID';
  if ((q.ask - q.bid) * 5 > q.ask) return 'QUOTE_SPREAD_TOO_WIDE';
  if (q.bidSize < quantity || q.askSize < quantity) return 'QUOTE_SIZE_INSUFFICIENT';
  return null;
}
