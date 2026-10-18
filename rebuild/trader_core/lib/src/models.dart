/// Domain models shared by every layer.
///
/// Conventions (read before editing):
/// * Money is always integer **cents** (`int`). Option premiums are cents
///   *per share*; the cash value of one contract is `premiumCents * multiplier`.
/// * Analysis prices (candles, indicators) are `double` dollars. They never
///   touch the ledger directly.
/// * All timestamps are UTC.
library;

/// The two option types this app is allowed to trade. Nothing else.
enum OptionRight {
  call,
  put;

  /// The opposite right, used by the opposite-direction lock.
  OptionRight get opposite => this == call ? put : call;

  String get arabic => this == call ? 'شراء (Call)' : 'بيع (Put)';

  /// OCC single-letter code.
  String get occ => this == call ? 'C' : 'P';

  static OptionRight parse(String v) => switch (v.toLowerCase()) {
        'call' || 'c' => OptionRight.call,
        'put' || 'p' => OptionRight.put,
        _ => throw FormatException('Unknown option right: $v'),
      };
}

/// Paper uses fake money; live is locked behind [LiveTradingGuard].
enum TradingMode { paper, live }

/// Supported brokers. Add a value here and register an adapter factory in
/// `BrokerRegistry` to support a new broker.
enum BrokerKind {
  /// Internal simulator: no network, no keys, fake money.
  simulator,
  alpaca,
  ibkr,
  tradestation;

  String get arabic => switch (this) {
        BrokerKind.simulator => 'محاكي داخلي',
        BrokerKind.alpaca => 'Alpaca',
        BrokerKind.ibkr => 'Interactive Brokers',
        BrokerKind.tradestation => 'TradeStation',
      };

  static BrokerKind parse(String v) =>
      BrokerKind.values.firstWhere((k) => k.name == v,
          orElse: () => throw FormatException('Unknown broker: $v'));
}

/// One OHLCV bar.
class Candle {
  final DateTime time;
  final double open;
  final double high;
  final double low;
  final double close;
  final double volume;

  Candle({
    required this.time,
    required this.open,
    required this.high,
    required this.low,
    required this.close,
    this.volume = 0,
  }) {
    if (!(high >= low && high >= open && high >= close && low <= open && low <= close && low > 0)) {
      throw ArgumentError('Inconsistent OHLC at $time');
    }
  }

  Map<String, dynamic> toJson() => {
        't': time.toIso8601String(),
        'o': open,
        'h': high,
        'l': low,
        'c': close,
        'v': volume,
      };

  factory Candle.fromJson(Map<String, dynamic> j) => Candle(
        time: DateTime.parse(j['t'] as String).toUtc(),
        open: (j['o'] as num).toDouble(),
        high: (j['h'] as num).toDouble(),
        low: (j['l'] as num).toDouble(),
        close: (j['c'] as num).toDouble(),
        volume: (j['v'] as num? ?? 0).toDouble(),
      );
}

/// A single listed option contract.
class OptionContract {
  final String underlying;
  final OptionRight right;

  /// Expiration date (time-of-day ignored, stored as UTC midnight).
  final DateTime expiry;
  final int strikeCents;
  final int multiplier;

  OptionContract({
    required this.underlying,
    required this.right,
    required DateTime expiry,
    required this.strikeCents,
    this.multiplier = 100,
  }) : expiry = DateTime.utc(expiry.year, expiry.month, expiry.day) {
    if (strikeCents <= 0 || multiplier <= 0) {
      throw ArgumentError('Invalid strike/multiplier');
    }
  }

  /// OCC/OSI symbol, e.g. `AAPL261120C00150000`. Used by Alpaca directly.
  String get occSymbol {
    final y = (expiry.year % 100).toString().padLeft(2, '0');
    final m = expiry.month.toString().padLeft(2, '0');
    final d = expiry.day.toString().padLeft(2, '0');
    final strike = (strikeCents * 10).toString().padLeft(8, '0'); // strike * 1000
    return '$underlying$y$m$d${right.occ}$strike';
  }

  /// Parses an OCC symbol produced by [occSymbol].
  factory OptionContract.fromOcc(String occ) {
    final m = RegExp(r'^([A-Z.]{1,6})(\d{2})(\d{2})(\d{2})([CP])(\d{8})$').firstMatch(occ);
    if (m == null) throw FormatException('Bad OCC symbol: $occ');
    return OptionContract(
      underlying: m.group(1)!,
      right: OptionRight.parse(m.group(5)!),
      expiry: DateTime.utc(2000 + int.parse(m.group(2)!), int.parse(m.group(3)!), int.parse(m.group(4)!)),
      strikeCents: int.parse(m.group(6)!) ~/ 10,
    );
  }

  double get strike => strikeCents / 100.0;

  int daysToExpiry(DateTime now) {
    final today = DateTime.utc(now.year, now.month, now.day);
    return expiry.difference(today).inDays;
  }

  @override
  bool operator ==(Object other) => other is OptionContract && other.occSymbol == occSymbol;

  @override
  int get hashCode => occSymbol.hashCode;

  @override
  String toString() => occSymbol;
}

/// A quote for one option contract.
class OptionQuote {
  final OptionContract contract;
  final int bidCents;
  final int askCents;
  final int volume;
  final int openInterest;
  final double? delta;
  final double? impliedVolatility;
  final DateTime time;

  OptionQuote({
    required this.contract,
    required this.bidCents,
    required this.askCents,
    required this.time,
    this.volume = 0,
    this.openInterest = 0,
    this.delta,
    this.impliedVolatility,
  });

  bool get isTwoSided => bidCents > 0 && askCents >= bidCents;
  int get midCents => ((bidCents + askCents) / 2).round();

  /// Spread as a fraction of mid (0.05 = 5%). Infinite when not two-sided.
  double get spreadFraction => isTwoSided && midCents > 0 ? (askCents - bidCents) / midCents : double.infinity;
}

enum OrderSide { buyToOpen, sellToClose }

enum OrderStatus {
  pending,
  partiallyFilled,
  filled,
  cancelled,
  rejected;

  bool get isOpen => this == pending || this == partiallyFilled;
}

/// What the engine asks a broker to do. Always a limit order.
class OrderRequest {
  final String clientOrderId;
  final OptionContract contract;
  final OrderSide side;
  final int quantity;
  final int limitPriceCents;

  OrderRequest({
    required this.clientOrderId,
    required this.contract,
    required this.side,
    required this.quantity,
    required this.limitPriceCents,
  }) {
    if (quantity <= 0 || limitPriceCents <= 0) throw ArgumentError('Invalid order');
  }
}

/// A broker's view of an order.
class BrokerOrder {
  final String id;
  final String clientOrderId;
  final OptionContract contract;
  final OrderSide side;
  final int quantity;
  final int filledQuantity;
  final int limitPriceCents;
  final int? averageFillCents;
  final OrderStatus status;
  final DateTime createdAt;
  final String? rejectReason;

  const BrokerOrder({
    required this.id,
    required this.clientOrderId,
    required this.contract,
    required this.side,
    required this.quantity,
    required this.filledQuantity,
    required this.limitPriceCents,
    required this.status,
    required this.createdAt,
    this.averageFillCents,
    this.rejectReason,
  });
}

/// A held long option position (this app only buys to open).
class Position {
  final OptionContract contract;
  final int quantity;

  /// Average premium paid per share, in cents.
  final int averageCostCents;
  final DateTime openedAt;

  const Position({
    required this.contract,
    required this.quantity,
    required this.averageCostCents,
    required this.openedAt,
  });

  int get costBasisCents => averageCostCents * quantity * contract.multiplier;

  int marketValueCents(int markCents) => markCents * quantity * contract.multiplier;
}

/// Balances reported by a broker.
class AccountSnapshot {
  final int cashCents;
  final int equityCents;
  final int buyingPowerCents;
  final DateTime time;

  const AccountSnapshot({
    required this.cashCents,
    required this.equityCents,
    required this.buyingPowerCents,
    required this.time,
  });
}
