/// Alpaca adapter (reference implementation for new brokers).
///
/// * Paper:  https://paper-api.alpaca.markets   (fake money, real market data)
/// * Live:   https://api.alpaca.markets         (blocked by LiveTradingGuard)
/// * Data:   https://data.alpaca.markets        (stocks v2, options v1beta1)
///
/// Auth headers: `APCA-API-KEY-ID`, `APCA-API-SECRET-KEY`.
/// Options trading must be enabled on the Alpaca account (level 2 for buying
/// calls/puts). Option data feed defaults to `indicative` (free); set
/// `optionFeed: 'opra'` when the account has an OPRA subscription.
///
/// Verified against the public Alpaca docs; responses are parsed defensively
/// and any unexpected shape raises BrokerErrorCode.invalidResponse.
library;

import 'dart:convert';

import '../models.dart';
import 'broker_adapter.dart';
import 'json_util.dart';
import 'live_guard.dart';
import '../market/market_calendar.dart';

class AlpacaAdapter implements BrokerAdapter, MarketClockSource {
  final String accountId; // application account id (for the live guard)
  final BrokerCredentials credentials;
  final HttpTransport http;
  @override
  final TradingMode mode;
  final LiveApproval? liveApproval;
  final String stockFeed;
  final String optionFeed;
  final DateTime Function() clock;

  AlpacaAdapter({
    required this.accountId,
    required this.credentials,
    required this.http,
    this.mode = TradingMode.paper,
    this.liveApproval,
    this.stockFeed = 'iex',
    this.optionFeed = 'indicative',
    DateTime Function()? clock,
  }) : clock = clock ?? (() => DateTime.now().toUtc());

  @override
  BrokerKind get kind => BrokerKind.alpaca;

  Uri get _trading => Uri.parse(mode == TradingMode.paper ? 'https://paper-api.alpaca.markets' : 'https://api.alpaca.markets');
  static final Uri _data = Uri.parse('https://data.alpaca.markets');

  Map<String, String> get _headers => {
        'APCA-API-KEY-ID': credentials.require('keyId'),
        'APCA-API-SECRET-KEY': credentials.require('secretKey'),
        'Accept': 'application/json',
      };

  Future<dynamic> _get(Uri base, String path, [Map<String, String>? query]) async {
    final url = base.replace(path: path, queryParameters: query);
    final r = await http.send('GET', url, headers: _headers);
    if (!r.ok) throwForStatus(r, 'GET $path');
    return jDecode(r.body);
  }

  @override
  Future<void> connect() async {
    final a = await _get(_trading, '/v2/account');
    if (a is! Map || a['status'] != 'ACTIVE') {
      throw BrokerException(BrokerErrorCode.auth, 'Alpaca account not active: ${a is Map ? a['status'] : a}');
    }
  }

  /// Exchange clock (`GET /v2/clock`), used to confirm the offline calendar.
  @override
  Future<BrokerMarketClock> marketClock() async {
    final j = jMap(await _get(_trading, '/v2/clock'));
    DateTime t(String k) {
      final v = DateTime.tryParse('${j[k]}');
      if (v == null) throw BrokerException(BrokerErrorCode.invalidResponse, 'Alpaca clock: bad $k');
      return v.toUtc();
    }

    final open = j['is_open'];
    if (open is! bool) throw const BrokerException(BrokerErrorCode.invalidResponse, 'Alpaca clock: is_open missing');
    return BrokerMarketClock(timestamp: t('timestamp'), isOpen: open, nextOpen: t('next_open'), nextClose: t('next_close'));
  }

  @override
  Future<AccountSnapshot> account() async {
    final a = jMap(await _get(_trading, '/v2/account'));
    return AccountSnapshot(
      cashCents: jCents(a['cash']),
      equityCents: jCents(a['equity']),
      buyingPowerCents: jCents(a['options_buying_power'] ?? a['buying_power']),
      time: clock(),
    );
  }

  @override
  Future<List<Position>> positions() async {
    final list = jList(await _get(_trading, '/v2/positions'));
    final out = <Position>[];
    for (final raw in list) {
      final p = jMap(raw);
      if (p['asset_class'] != 'us_option') continue; // stocks are not managed by this app
      final qty = jNum(p['qty']).round();
      if (qty <= 0) continue; // this app only holds long options
      out.add(Position(
        contract: OptionContract.fromOcc(p['symbol'] as String),
        quantity: qty,
        averageCostCents: jCents(p['avg_entry_price']),
        openedAt: clock(), // Alpaca does not report an open time on positions
      ));
    }
    return out;
  }

  @override
  Future<List<BrokerOrder>> openOrders() async {
    final list = jList(await _get(_trading, '/v2/orders', {'status': 'open', 'limit': '500', 'nested': 'false'}));
    return list.map((o) => _order(jMap(o))).whereType<BrokerOrder>().toList();
  }

  @override
  Future<BrokerOrder?> order(String orderId) async {
    try {
      return _order(jMap(await _get(_trading, '/v2/orders/$orderId')));
    } on BrokerException catch (e) {
      if (e.code == BrokerErrorCode.notFound) return null;
      rethrow;
    }
  }

  @override
  Future<BrokerOrder> placeOrder(OrderRequest r) async {
    LiveTradingGuard.ensureAllowed(mode: mode, accountId: accountId, approval: liveApproval);
    final body = jsonEncode({
      'symbol': r.contract.occSymbol,
      'qty': '${r.quantity}',
      'side': r.side == OrderSide.buyToOpen ? 'buy' : 'sell',
      'position_intent': r.side == OrderSide.buyToOpen ? 'buy_to_open' : 'sell_to_close',
      'type': 'limit',
      'time_in_force': 'day',
      'limit_price': (r.limitPriceCents / 100).toStringAsFixed(2),
      'client_order_id': r.clientOrderId,
    });
    final res = await http.send('POST', _trading.replace(path: '/v2/orders'),
        headers: {..._headers, 'Content-Type': 'application/json'}, body: body);
    if (!res.ok) throwForStatus(res, 'POST /v2/orders');
    final o = _order(jMap(jDecode(res.body)));
    if (o == null) throw const BrokerException(BrokerErrorCode.invalidResponse, 'Order response is not an option order');
    return o;
  }

  @override
  Future<void> cancelOrder(String orderId) async {
    final r = await http.send('DELETE', _trading.replace(path: '/v2/orders/$orderId'), headers: _headers);
    if (!r.ok && r.status != 404) throwForStatus(r, 'DELETE order');
  }

  static String _tf(BarTimeframe t) => switch (t) {
        BarTimeframe.m5 => '5Min',
        BarTimeframe.m15 => '15Min',
        BarTimeframe.h1 => '1Hour',
        BarTimeframe.d1 => '1Day',
      };

  @override
  Future<List<Candle>> bars(String symbol, BarTimeframe timeframe, {int limit = 300}) async {
    // Markets are open ~27% of wall time; look back far enough for [limit] bars.
    final lookback = timeframe == BarTimeframe.d1 ? timeframe.duration * (limit * 1.6) : timeframe.duration * (limit * 5);
    final j = jMap(await _get(_data, '/v2/stocks/$symbol/bars', {
      'timeframe': _tf(timeframe),
      'start': clock().subtract(lookback).toIso8601String(),
      'limit': '$limit',
      'sort': 'desc',
      'adjustment': 'split',
      'feed': stockFeed,
    }));
    final raw = (j['bars'] as List?) ?? const [];
    final out = raw.map((b) {
      final m = jMap(b);
      return Candle(
        time: DateTime.parse(m['t'] as String).toUtc(),
        open: jNum(m['o']),
        high: jNum(m['h']),
        low: jNum(m['l']),
        close: jNum(m['c']),
        volume: jNum(m['v']),
      );
    }).toList();
    return out.reversed.toList(); // oldest first
  }

  @override
  Future<double> lastPrice(String symbol) async {
    final j = jMap(await _get(_data, '/v2/stocks/$symbol/trades/latest', {'feed': stockFeed}));
    return jNum(jMap(j['trade'])['p']);
  }

  @override
  Future<List<OptionQuote>> optionChain(String underlying,
      {required DateTime minExpiry, required DateTime maxExpiry, OptionRight? right}) async {
    final out = <OptionQuote>[];
    String? page;
    var guard = 0;
    do {
      final q = {
        'feed': optionFeed,
        'expiration_date_gte': isoDate(minExpiry),
        'expiration_date_lte': isoDate(maxExpiry),
        'limit': '1000',
        if (right != null) 'type': right.name,
        if (page != null) 'page_token': page,
      };
      final j = jMap(await _get(_data, '/v1beta1/options/snapshots/$underlying', q));
      final snaps = jMap(j['snapshots'] ?? <String, dynamic>{});
      snaps.forEach((occ, v) {
        final quote = _snapshot(occ, jMap(v));
        if (quote != null) out.add(quote);
      });
      page = j['next_page_token'] as String?;
    } while (page != null && ++guard < 10);
    return out;
  }

  @override
  Future<OptionQuote?> optionQuote(OptionContract contract) async {
    final j = jMap(await _get(_data, '/v1beta1/options/snapshots', {'symbols': contract.occSymbol, 'feed': optionFeed}));
    final snaps = jMap(j['snapshots'] ?? <String, dynamic>{});
    final v = snaps[contract.occSymbol];
    return v == null ? null : _snapshot(contract.occSymbol, jMap(v));
  }

  OptionQuote? _snapshot(String occ, Map<String, dynamic> s) {
    final lq = s['latestQuote'];
    if (lq is! Map) return null;
    final greeks = s['greeks'];
    final bar = s['dailyBar'];
    return OptionQuote(
      contract: OptionContract.fromOcc(occ),
      bidCents: jCents(lq['bp']),
      askCents: jCents(lq['ap']),
      time: DateTime.tryParse('${lq['t']}')?.toUtc() ?? clock(),
      volume: bar is Map ? jNum(bar['v']).round() : 0,
      delta: greeks is Map && greeks['delta'] != null ? jNum(greeks['delta']) : null,
      gamma: greeks is Map && greeks['gamma'] != null ? jNum(greeks['gamma']) : null,
      theta: greeks is Map && greeks['theta'] != null ? jNum(greeks['theta']) : null,
      vega: greeks is Map && greeks['vega'] != null ? jNum(greeks['vega']) : null,
      impliedVolatility: s['impliedVolatility'] == null ? null : jNum(s['impliedVolatility']),
    );
  }

  BrokerOrder? _order(Map<String, dynamic> o) {
    final symbol = o['symbol'];
    if (symbol is! String || o['asset_class'] != 'us_option') return null;
    final status = switch (o['status']) {
      'filled' => OrderStatus.filled,
      'partially_filled' => OrderStatus.partiallyFilled,
      'canceled' || 'expired' || 'done_for_day' || 'replaced' => OrderStatus.cancelled,
      'rejected' || 'suspended' => OrderStatus.rejected,
      _ => OrderStatus.pending, // new, accepted, pending_new, held, ...
    };
    return BrokerOrder(
      id: o['id'] as String,
      clientOrderId: (o['client_order_id'] as String?) ?? '',
      contract: OptionContract.fromOcc(symbol),
      side: o['side'] == 'buy' ? OrderSide.buyToOpen : OrderSide.sellToClose,
      quantity: jNum(o['qty']).round(),
      filledQuantity: jNum(o['filled_qty'] ?? 0).round(),
      limitPriceCents: jCents(o['limit_price'] ?? 0),
      averageFillCents: o['filled_avg_price'] == null ? null : jCents(o['filled_avg_price']),
      status: status,
      createdAt: DateTime.tryParse('${o['created_at']}')?.toUtc() ?? clock(),
    );
  }
}
