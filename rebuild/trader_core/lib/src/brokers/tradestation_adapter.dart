/// TradeStation adapter (API v3).
///
/// * Paper (SIM): https://sim-api.tradestation.com/v3
/// * Live:        https://api.tradestation.com/v3 (blocked by LiveTradingGuard)
/// * Auth: OAuth2 refresh-token grant at https://signin.tradestation.com/oauth/token.
///   The user creates an API key (client id/secret) and a refresh token once;
///   the adapter exchanges it for 20-minute access tokens automatically.
///
/// STATUS: written from the public v3 documentation; NOT yet exercised against
/// a real SIM account. The next developer must run the contract checklist in
/// HANDOFF.md ("TradeStation") before enabling it in the UI by default.
///
/// Option symbols use TradeStation's format: `AAPL 261120C150` / `SPY 261120P452.5`.
library;

import 'dart:convert';

import '../models.dart';
import 'broker_adapter.dart';
import 'json_util.dart';
import 'live_guard.dart';

class TradeStationAdapter implements BrokerAdapter {
  final String accountId;
  final BrokerCredentials credentials;
  final HttpTransport http;
  @override
  final TradingMode mode;
  final LiveApproval? liveApproval;
  final DateTime Function() clock;

  String? _token;
  DateTime _tokenExpiry = DateTime.fromMillisecondsSinceEpoch(0, isUtc: true);

  TradeStationAdapter({
    required this.accountId,
    required this.credentials,
    required this.http,
    this.mode = TradingMode.paper,
    this.liveApproval,
    DateTime Function()? clock,
  }) : clock = clock ?? (() => DateTime.now().toUtc());

  @override
  BrokerKind get kind => BrokerKind.tradestation;

  String get _base => mode == TradingMode.paper ? 'https://sim-api.tradestation.com/v3' : 'https://api.tradestation.com/v3';
  String get _brokerAccount => credentials.require('accountId');

  /// Converts to TradeStation's option symbol format.
  static String tsSymbol(OptionContract c) {
    final y = (c.expiry.year % 100).toString().padLeft(2, '0');
    final m = c.expiry.month.toString().padLeft(2, '0');
    final d = c.expiry.day.toString().padLeft(2, '0');
    final whole = c.strikeCents ~/ 100;
    final frac = c.strikeCents % 100;
    final strike = frac == 0 ? '$whole' : '$whole.${frac.toString().padLeft(2, '0').replaceAll(RegExp(r'0$'), '')}';
    return '${c.underlying} $y$m$d${c.right.occ}$strike';
  }

  static OptionContract fromTsSymbol(String s) {
    final m = RegExp(r'^([A-Z.]+) (\d{2})(\d{2})(\d{2})([CP])(\d+(?:\.\d+)?)$').firstMatch(s.trim());
    if (m == null) throw BrokerException(BrokerErrorCode.invalidResponse, 'Bad TradeStation option symbol: $s');
    return OptionContract(
      underlying: m.group(1)!,
      right: OptionRight.parse(m.group(5)!),
      expiry: DateTime.utc(2000 + int.parse(m.group(2)!), int.parse(m.group(3)!), int.parse(m.group(4)!)),
      strikeCents: (double.parse(m.group(6)!) * 100).round(),
    );
  }

  Future<String> _accessToken() async {
    if (_token != null && clock().isBefore(_tokenExpiry)) return _token!;
    final body = Uri(queryParameters: {
      'grant_type': 'refresh_token',
      'client_id': credentials.require('clientId'),
      'client_secret': credentials.require('clientSecret'),
      'refresh_token': credentials.require('refreshToken'),
    }).query;
    final r = await http.send('POST', Uri.parse('https://signin.tradestation.com/oauth/token'),
        headers: {'Content-Type': 'application/x-www-form-urlencoded'}, body: body);
    if (!r.ok) throwForStatus(r, 'TradeStation token');
    final j = jMap(jDecode(r.body));
    _token = j['access_token'] as String?;
    if (_token == null) throw const BrokerException(BrokerErrorCode.auth, 'No access_token in response');
    final ttl = (j['expires_in'] as num?)?.toInt() ?? 1200;
    _tokenExpiry = clock().add(Duration(seconds: ttl - 60));
    return _token!;
  }

  Future<dynamic> _call(String method, String path, {Map<String, String>? query, Object? json}) async {
    final token = await _accessToken();
    final url = Uri.parse('$_base$path').replace(queryParameters: query);
    final r = await http.send(method, url,
        headers: {
          'Authorization': 'Bearer $token',
          'Accept': 'application/json',
          if (json != null) 'Content-Type': 'application/json',
        },
        body: json == null ? null : jsonEncode(json));
    if (!r.ok) throwForStatus(r, '$method $path');
    return r.body.isEmpty ? null : jDecode(r.body);
  }

  @override
  Future<void> connect() async {
    await account();
  }

  @override
  Future<AccountSnapshot> account() async {
    final j = jMap(await _call('GET', '/brokerage/accounts/$_brokerAccount/balances'));
    final list = jList(j['Balances']);
    if (list.isEmpty) throw const BrokerException(BrokerErrorCode.notFound, 'No balances for account');
    final b = jMap(list.first);
    return AccountSnapshot(
      cashCents: jCents(b['CashBalance']),
      equityCents: jCents(b['Equity']),
      buyingPowerCents: jCents(b['BuyingPower']),
      time: clock(),
    );
  }

  @override
  Future<List<Position>> positions() async {
    final j = jMap(await _call('GET', '/brokerage/accounts/$_brokerAccount/positions'));
    final out = <Position>[];
    for (final raw in jList(j['Positions'] ?? const [])) {
      final p = jMap(raw);
      if (p['AssetType'] != 'STOCKOPTION' || p['LongShort'] != 'Long') continue;
      out.add(Position(
        contract: fromTsSymbol(p['Symbol'] as String),
        quantity: jNum(p['Quantity']).round(),
        averageCostCents: jCents(p['AveragePrice']),
        openedAt: DateTime.tryParse('${p['Timestamp']}')?.toUtc() ?? clock(),
      ));
    }
    return out;
  }

  @override
  Future<List<BrokerOrder>> openOrders() async {
    final j = jMap(await _call('GET', '/brokerage/accounts/$_brokerAccount/orders'));
    return jList(j['Orders'] ?? const [])
        .map((o) => _order(jMap(o)))
        .whereType<BrokerOrder>()
        .where((o) => o.status.isOpen)
        .toList();
  }

  @override
  Future<BrokerOrder?> order(String orderId) async {
    final j = jMap(await _call('GET', '/brokerage/accounts/$_brokerAccount/orders/$orderId'));
    final list = jList(j['Orders'] ?? const []);
    return list.isEmpty ? null : _order(jMap(list.first));
  }

  @override
  Future<BrokerOrder> placeOrder(OrderRequest r) async {
    LiveTradingGuard.ensureAllowed(mode: mode, accountId: accountId, approval: liveApproval);
    final j = jMap(await _call('POST', '/orderexecution/orders', json: {
      'AccountID': _brokerAccount,
      'Symbol': tsSymbol(r.contract),
      'Quantity': '${r.quantity}',
      'OrderType': 'Limit',
      'LimitPrice': (r.limitPriceCents / 100).toStringAsFixed(2),
      'TradeAction': r.side == OrderSide.buyToOpen ? 'BUYTOOPEN' : 'SELLTOCLOSE',
      'TimeInForce': {'Duration': 'DAY'},
      'Route': 'Intelligent',
    }));
    final list = jList(j['Orders'] ?? const []);
    if (list.isEmpty) {
      throw BrokerException(BrokerErrorCode.rejected, 'Order rejected: ${j['Errors'] ?? j}');
    }
    final id = '${jMap(list.first)['OrderID']}';
    return (await order(id)) ??
        BrokerOrder(
          id: id,
          clientOrderId: r.clientOrderId,
          contract: r.contract,
          side: r.side,
          quantity: r.quantity,
          filledQuantity: 0,
          limitPriceCents: r.limitPriceCents,
          status: OrderStatus.pending,
          createdAt: clock(),
        );
  }

  @override
  Future<void> cancelOrder(String orderId) async {
    await _call('DELETE', '/orderexecution/orders/$orderId');
  }

  BrokerOrder? _order(Map<String, dynamic> o) {
    final legs = o['Legs'];
    if (legs is! List || legs.isEmpty) return null;
    final leg = jMap(legs.first);
    if (leg['AssetType'] != null && leg['AssetType'] != 'STOCKOPTION') return null;
    OptionContract contract;
    try {
      contract = fromTsSymbol(leg['Symbol'] as String);
    } on BrokerException {
      return null;
    }
    final status = switch (o['Status']) {
      'FLL' || 'FLP' => OrderStatus.filled,
      'FPR' => OrderStatus.partiallyFilled,
      'CAN' || 'EXP' || 'OUT' || 'UCN' => OrderStatus.cancelled,
      'REJ' || 'BRO' => OrderStatus.rejected,
      _ => OrderStatus.pending, // ACK, OPN, DON, RCV, ...
    };
    final action = '${leg['BuyOrSell']}'.toLowerCase();
    return BrokerOrder(
      id: '${o['OrderID']}',
      clientOrderId: '${o['OrderID']}',
      contract: contract,
      side: action.startsWith('buy') ? OrderSide.buyToOpen : OrderSide.sellToClose,
      quantity: jNum(leg['QuantityOrdered'] ?? 0).round(),
      filledQuantity: jNum(leg['ExecQuantity'] ?? 0).round(),
      limitPriceCents: jCents(o['LimitPrice'] ?? 0),
      averageFillCents: leg['ExecutionPrice'] == null ? null : jCents(leg['ExecutionPrice']),
      status: status,
      createdAt: DateTime.tryParse('${o['OpenedDateTime']}')?.toUtc() ?? clock(),
      rejectReason: o['RejectReason'] as String?,
    );
  }

  @override
  Future<List<Candle>> bars(String symbol, BarTimeframe timeframe, {int limit = 300}) async {
    final (interval, unit) = switch (timeframe) {
      BarTimeframe.m5 => ('5', 'Minute'),
      BarTimeframe.m15 => ('15', 'Minute'),
      BarTimeframe.h1 => ('60', 'Minute'),
      BarTimeframe.d1 => ('1', 'Daily'),
    };
    final j = jMap(await _call('GET', '/marketdata/barcharts/$symbol',
        query: {'interval': interval, 'unit': unit, 'barsback': '$limit'}));
    return jList(j['Bars'] ?? const []).map((b) {
      final m = jMap(b);
      return Candle(
        time: DateTime.parse(m['TimeStamp'] as String).toUtc(),
        open: jNum(m['Open']),
        high: jNum(m['High']),
        low: jNum(m['Low']),
        close: jNum(m['Close']),
        volume: jNum(m['TotalVolume'] ?? 0),
      );
    }).toList();
  }

  Future<List<Map<String, dynamic>>> _quotes(List<String> symbols) async {
    final out = <Map<String, dynamic>>[];
    for (var i = 0; i < symbols.length; i += 50) {
      final batch = symbols.sublist(i, i + 50 > symbols.length ? symbols.length : i + 50);
      final j = jMap(await _call('GET', '/marketdata/quotes/${batch.map(Uri.encodeComponent).join(',')}'));
      out.addAll(jList(j['Quotes'] ?? const []).map(jMap));
    }
    return out;
  }

  @override
  Future<double> lastPrice(String symbol) async {
    final q = await _quotes([symbol]);
    if (q.isEmpty) throw BrokerException(BrokerErrorCode.notFound, 'No quote for $symbol');
    return jNum(q.first['Last']);
  }

  @override
  Future<List<OptionQuote>> optionChain(String underlying,
      {required DateTime minExpiry, required DateTime maxExpiry, OptionRight? right}) async {
    final spot = await lastPrice(underlying);
    final ej = jMap(await _call('GET', '/marketdata/options/expirations/$underlying'));
    final expiries = jList(ej['Expirations'] ?? const [])
        .map((e) => DateTime.parse(jMap(e)['Date'] as String).toUtc())
        .map((d) => DateTime.utc(d.year, d.month, d.day))
        .where((d) => !d.isBefore(minExpiry) && !d.isAfter(maxExpiry))
        .toList();
    final symbols = <String>[];
    for (final exp in expiries) {
      final sj = jMap(await _call('GET', '/marketdata/options/strikes/$underlying', query: {'expiration': isoDate(exp)}));
      final strikes = jList(sj['Strikes'] ?? const [])
          .map((row) => row is List && row.isNotEmpty ? jNum(row.first) : jNum(row))
          .toList()
        ..sort((a, b) => (a - spot).abs().compareTo((b - spot).abs()));
      for (final k in strikes.take(16)) {
        for (final r in OptionRight.values) {
          if (right != null && r != right) continue;
          symbols.add(tsSymbol(OptionContract(underlying: underlying, right: r, expiry: exp, strikeCents: (k * 100).round())));
        }
      }
    }
    final quotes = await _quotes(symbols);
    return quotes.map(_optionQuote).whereType<OptionQuote>().toList();
  }

  @override
  Future<OptionQuote?> optionQuote(OptionContract contract) async {
    final q = await _quotes([tsSymbol(contract)]);
    return q.isEmpty ? null : _optionQuote(q.first);
  }

  OptionQuote? _optionQuote(Map<String, dynamic> q) {
    try {
      return OptionQuote(
        contract: fromTsSymbol(q['Symbol'] as String),
        bidCents: jCents(q['Bid'] ?? 0),
        askCents: jCents(q['Ask'] ?? 0),
        volume: jNum(q['Volume'] ?? 0).round(),
        openInterest: jNum(q['DailyOpenInterest'] ?? 0).round(),
        time: DateTime.tryParse('${q['TradeTime']}')?.toUtc() ?? clock(),
      );
    } on BrokerException {
      return null;
    }
  }
}
