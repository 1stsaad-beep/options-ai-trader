/// Internal paper broker: fake money, no network, no keys.
///
/// Fill model (conservative, documented so tests can rely on it):
/// * Buy-to-open fills only when `limit >= ask`, at the ask.
/// * Sell-to-close fills only when `limit <= bid`, at the bid.
/// * Otherwise the order stays pending and is retried on every call to
///   [openOrders], [positions] or [account] (the "sweep").
/// * A per-contract fee is charged on every fill.
/// * Contracts past expiry are settled at intrinsic value (cash) by the sweep.
///
/// State is fully serialisable ([toJson]/[fromJson]) so the app can persist
/// each account independently.
library;

import 'dart:math' as math;

import '../models.dart';
import 'broker_adapter.dart';
import 'synthetic_market.dart';

class SimulatorBroker implements BrokerAdapter {
  final SyntheticMarket market;
  final DateTime Function() clock;
  final int feePerContractCents;

  int _cashCents;
  final Map<String, _Lot> _positions = {};
  final Map<String, _SimOrder> _orders = {};
  int _sequence = 0;

  SimulatorBroker({
    required this.market,
    required int startingCashCents,
    this.feePerContractCents = 65,
    DateTime Function()? clock,
  })  : clock = clock ?? market.clock,
        _cashCents = startingCashCents;

  @override
  BrokerKind get kind => BrokerKind.simulator;

  @override
  TradingMode get mode => TradingMode.paper;

  int get cashCents => _cashCents;

  @override
  Future<void> connect() async {}

  @override
  Future<AccountSnapshot> account() async {
    await _sweep();
    var value = 0;
    for (final lot in _positions.values) {
      final q = await market.optionQuote(lot.contract);
      final mark = q == null ? lot.averageCostCents : q.bidCents;
      value += mark * lot.quantity * lot.contract.multiplier;
    }
    final reserved = _reservedForOpenBuys();
    return AccountSnapshot(
      cashCents: _cashCents,
      equityCents: _cashCents + value,
      buyingPowerCents: math.max(0, _cashCents - reserved),
      time: clock(),
    );
  }

  @override
  Future<List<Position>> positions() async {
    await _sweep();
    return _positions.values
        .map((l) => Position(
            contract: l.contract, quantity: l.quantity, averageCostCents: l.averageCostCents, openedAt: l.openedAt))
        .toList();
  }

  @override
  Future<List<BrokerOrder>> openOrders() async {
    await _sweep();
    return _orders.values.where((o) => o.status.isOpen).map((o) => o.view()).toList();
  }

  @override
  Future<BrokerOrder?> order(String orderId) async {
    await _sweep();
    return _orders[orderId]?.view();
  }

  @override
  Future<BrokerOrder> placeOrder(OrderRequest r) async {
    await _sweep();
    // Idempotency: the same client order id never creates a second order.
    for (final o in _orders.values) {
      if (o.clientOrderId == r.clientOrderId) return o.view();
    }
    final id = 'SIM-${++_sequence}';
    final o = _SimOrder(id, r, clock());
    if (r.side == OrderSide.buyToOpen) {
      final need = r.limitPriceCents * r.quantity * r.contract.multiplier + feePerContractCents * r.quantity;
      if (need > _cashCents - _reservedForOpenBuys()) {
        o.reject('رصيد غير كافٍ');
      }
    } else {
      final held = _positions[r.contract.occSymbol]?.quantity ?? 0;
      final pendingSells = _orders.values
          .where((x) => x.status.isOpen && x.side == OrderSide.sellToClose && x.contract == r.contract)
          .fold<int>(0, (s, x) => s + x.remaining);
      if (r.quantity > held - pendingSells) o.reject('الكمية أكبر من المركز المملوك');
    }
    _orders[id] = o;
    if (o.status.isOpen) await _tryFill(o);
    return o.view();
  }

  @override
  Future<void> cancelOrder(String orderId) async {
    final o = _orders[orderId];
    if (o == null) throw const BrokerException(BrokerErrorCode.notFound, 'Unknown order');
    if (o.status.isOpen) o.status = OrderStatus.cancelled;
  }

  int _reservedForOpenBuys() => _orders.values
      .where((o) => o.status.isOpen && o.side == OrderSide.buyToOpen)
      .fold<int>(0, (s, o) => s + o.limitPriceCents * o.remaining * o.contract.multiplier + feePerContractCents * o.remaining);

  Future<void> _sweep() async {
    final now = clock();
    // 1) settle expired positions at intrinsic value
    for (final key in _positions.keys.toList()) {
      final lot = _positions[key]!;
      final expiryMoment = lot.contract.expiry.add(const Duration(hours: 20));
      if (now.isBefore(expiryMoment)) continue;
      final spot = await market.lastPrice(lot.contract.underlying);
      final intrinsic = lot.contract.right == OptionRight.call
          ? math.max(0.0, spot - lot.contract.strike)
          : math.max(0.0, lot.contract.strike - spot);
      _cashCents += (intrinsic * 100).round() * lot.quantity * lot.contract.multiplier;
      _positions.remove(key);
      for (final o in _orders.values) {
        if (o.status.isOpen && o.contract == lot.contract) o.status = OrderStatus.cancelled;
      }
    }
    // 2) retry pending orders
    for (final o in _orders.values.where((o) => o.status.isOpen).toList()) {
      await _tryFill(o);
    }
  }

  Future<void> _tryFill(_SimOrder o) async {
    final q = await market.optionQuote(o.contract);
    if (q == null || !q.isTwoSided) return;
    final qty = o.remaining;
    if (o.side == OrderSide.buyToOpen) {
      if (o.limitPriceCents < q.askCents) return;
      final cost = q.askCents * qty * o.contract.multiplier + feePerContractCents * qty;
      if (cost > _cashCents) {
        o.reject('رصيد غير كافٍ عند التنفيذ');
        return;
      }
      _cashCents -= cost;
      final lot = _positions[o.contract.occSymbol];
      if (lot == null) {
        _positions[o.contract.occSymbol] = _Lot(o.contract, qty, q.askCents, clock());
      } else {
        final total = lot.quantity + qty;
        lot.averageCostCents = ((lot.averageCostCents * lot.quantity + q.askCents * qty) / total).round();
        lot.quantity = total;
      }
      o.fill(qty, q.askCents);
    } else {
      if (o.limitPriceCents > q.bidCents) return;
      final lot = _positions[o.contract.occSymbol];
      if (lot == null || lot.quantity < qty) {
        o.reject('لا يوجد مركز كافٍ');
        return;
      }
      _cashCents += q.bidCents * qty * o.contract.multiplier - feePerContractCents * qty;
      lot.quantity -= qty;
      if (lot.quantity == 0) _positions.remove(o.contract.occSymbol);
      o.fill(qty, q.bidCents);
    }
  }

  // ---- MarketDataSource: delegate to the synthetic market ----
  @override
  Future<List<Candle>> bars(String symbol, BarTimeframe timeframe, {int limit = 300}) =>
      market.bars(symbol, timeframe, limit: limit);

  @override
  Future<double> lastPrice(String symbol) => market.lastPrice(symbol);

  @override
  Future<List<OptionQuote>> optionChain(String underlying,
          {required DateTime minExpiry, required DateTime maxExpiry, OptionRight? right}) =>
      market.optionChain(underlying, minExpiry: minExpiry, maxExpiry: maxExpiry, right: right);

  @override
  Future<OptionQuote?> optionQuote(OptionContract contract) => market.optionQuote(contract);

  // ---- persistence ----
  Map<String, dynamic> toJson() => {
        'v': 1,
        'cashCents': _cashCents,
        'sequence': _sequence,
        'positions': _positions.values.map((l) => l.toJson()).toList(),
        'orders': _orders.values.map((o) => o.toJson()).toList(),
      };

  void restore(Map<String, dynamic> j) {
    if (j['v'] != 1) throw const FormatException('Unknown simulator state version');
    _cashCents = j['cashCents'] as int;
    _sequence = j['sequence'] as int;
    _positions
      ..clear()
      ..addEntries((j['positions'] as List).map((e) {
        final l = _Lot.fromJson(e as Map<String, dynamic>);
        return MapEntry(l.contract.occSymbol, l);
      }));
    _orders
      ..clear()
      ..addEntries((j['orders'] as List).map((e) {
        final o = _SimOrder.fromJson(e as Map<String, dynamic>);
        return MapEntry(o.id, o);
      }));
  }
}

class _Lot {
  final OptionContract contract;
  int quantity;
  int averageCostCents;
  final DateTime openedAt;
  _Lot(this.contract, this.quantity, this.averageCostCents, this.openedAt);

  Map<String, dynamic> toJson() =>
      {'c': contract.occSymbol, 'q': quantity, 'a': averageCostCents, 't': openedAt.toIso8601String()};

  factory _Lot.fromJson(Map<String, dynamic> j) => _Lot(OptionContract.fromOcc(j['c'] as String), j['q'] as int,
      j['a'] as int, DateTime.parse(j['t'] as String));
}

class _SimOrder {
  final String id;
  final String clientOrderId;
  final OptionContract contract;
  final OrderSide side;
  final int quantity;
  final int limitPriceCents;
  final DateTime createdAt;
  int filled = 0;
  int? avgFill;
  OrderStatus status = OrderStatus.pending;
  String? rejectReason;

  _SimOrder(this.id, OrderRequest r, this.createdAt)
      : clientOrderId = r.clientOrderId,
        contract = r.contract,
        side = r.side,
        quantity = r.quantity,
        limitPriceCents = r.limitPriceCents;

  _SimOrder._raw(this.id, this.clientOrderId, this.contract, this.side, this.quantity, this.limitPriceCents,
      this.createdAt);

  int get remaining => quantity - filled;

  void reject(String reason) {
    status = OrderStatus.rejected;
    rejectReason = reason;
  }

  void fill(int qty, int price) {
    final prev = avgFill ?? 0;
    avgFill = ((prev * filled + price * qty) / (filled + qty)).round();
    filled += qty;
    status = filled >= quantity ? OrderStatus.filled : OrderStatus.partiallyFilled;
  }

  BrokerOrder view() => BrokerOrder(
        id: id,
        clientOrderId: clientOrderId,
        contract: contract,
        side: side,
        quantity: quantity,
        filledQuantity: filled,
        limitPriceCents: limitPriceCents,
        averageFillCents: avgFill,
        status: status,
        createdAt: createdAt,
        rejectReason: rejectReason,
      );

  Map<String, dynamic> toJson() => {
        'id': id,
        'cid': clientOrderId,
        'c': contract.occSymbol,
        's': side.name,
        'q': quantity,
        'l': limitPriceCents,
        't': createdAt.toIso8601String(),
        'f': filled,
        'af': avgFill,
        'st': status.name,
        'rr': rejectReason,
      };

  factory _SimOrder.fromJson(Map<String, dynamic> j) {
    final o = _SimOrder._raw(
      j['id'] as String,
      j['cid'] as String,
      OptionContract.fromOcc(j['c'] as String),
      OrderSide.values.byName(j['s'] as String),
      j['q'] as int,
      j['l'] as int,
      DateTime.parse(j['t'] as String),
    );
    o.filled = j['f'] as int;
    o.avgFill = j['af'] as int?;
    o.status = OrderStatus.values.byName(j['st'] as String);
    o.rejectReason = j['rr'] as String?;
    return o;
  }
}
