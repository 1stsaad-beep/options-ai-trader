/// Interactive Brokers adapter via the Client Portal Web API.
///
/// IBKR has no API keys: the user runs the Client Portal Gateway (or IBeam) on
/// a computer/server they own, logs in there (Paper login for paper accounts,
/// account ids start with `DU`), and enters the gateway URL in the app.
/// Base path: `{gatewayUrl}/v1/api`. The gateway uses a self-signed TLS
/// certificate — the app's HttpTransport must trust it for that host only.
///
/// Paper vs live is decided by which login the gateway holds, so this adapter
/// additionally refuses to trade a non-`DU` account unless live is authorised.
///
/// STATUS: written from the public Client Portal API documentation; NOT yet
/// exercised against a real gateway. See HANDOFF.md ("IBKR") for the checklist.
library;

import 'dart:convert';

import '../models.dart';
import 'broker_adapter.dart';
import 'json_util.dart';
import 'live_guard.dart';

class IbkrAdapter implements BrokerAdapter {
  final String accountId;
  final BrokerCredentials credentials;
  final HttpTransport http;
  @override
  final TradingMode mode;
  final LiveApproval? liveApproval;
  final DateTime Function() clock;

  final Map<String, int> _stockConids = {};
  final Map<String, int> _optionConids = {}; // occ -> conid
  final Map<int, OptionContract> _contractsByConid = {};

  IbkrAdapter({
    required this.accountId,
    required this.credentials,
    required this.http,
    this.mode = TradingMode.paper,
    this.liveApproval,
    DateTime Function()? clock,
  }) : clock = clock ?? (() => DateTime.now().toUtc());

  @override
  BrokerKind get kind => BrokerKind.ibkr;

  String get _brokerAccount => credentials.require('accountId');
  String get _base {
    final u = credentials.require('gatewayUrl');
    return '${u.endsWith('/') ? u.substring(0, u.length - 1) : u}/v1/api';
  }

  Future<dynamic> _call(String method, String path, {Map<String, String>? query, Object? json}) async {
    final url = Uri.parse('$_base$path').replace(queryParameters: query);
    final r = await http.send(method, url,
        headers: {'Accept': 'application/json', if (json != null) 'Content-Type': 'application/json'},
        body: json == null ? null : jsonEncode(json));
    if (!r.ok) throwForStatus(r, '$method $path');
    return r.body.isEmpty ? null : jDecode(r.body);
  }

  @override
  Future<void> connect() async {
    final s = jMap(await _call('POST', '/iserver/auth/status'));
    if (s['authenticated'] != true) {
      throw const BrokerException(BrokerErrorCode.auth, 'Gateway is not logged in. Log in at the gateway page first.');
    }
    if (mode == TradingMode.paper && !_brokerAccount.toUpperCase().startsWith('DU')) {
      throw const BrokerException(BrokerErrorCode.liveLocked, 'Paper mode requires an IBKR paper account (DU...)');
    }
    await _call('GET', '/iserver/accounts'); // required once per session before order endpoints
  }

  @override
  Future<AccountSnapshot> account() async {
    final j = jMap(await _call('GET', '/portfolio/$_brokerAccount/summary'));
    int amt(String k) => j[k] is Map ? jCents((j[k] as Map)['amount'] ?? 0) : 0;
    return AccountSnapshot(
      cashCents: amt('totalcashvalue'),
      equityCents: amt('netliquidation'),
      buyingPowerCents: amt('buyingpower'),
      time: clock(),
    );
  }

  @override
  Future<List<Position>> positions() async {
    final list = jList(await _call('GET', '/portfolio/$_brokerAccount/positions/0') ?? const []);
    final out = <Position>[];
    for (final raw in list) {
      final p = jMap(raw);
      if (p['assetClass'] != 'OPT') continue;
      final qty = jNum(p['position']).round();
      if (qty <= 0) continue;
      final conid = jNum(p['conid']).toInt();
      final contract = _contractsByConid[conid] ?? _fromPositionRow(p);
      if (contract == null) continue;
      _contractsByConid[conid] = contract;
      _optionConids[contract.occSymbol] = conid;
      out.add(Position(
        contract: contract,
        quantity: qty,
        averageCostCents: jCents(p['avgPrice'] ?? (jNum(p['avgCost']) / contract.multiplier)),
        openedAt: clock(),
      ));
    }
    return out;
  }

  OptionContract? _fromPositionRow(Map<String, dynamic> p) {
    // contractDesc usually embeds the OCC symbol: "AAPL NOV2026 150 C [AAPL  261120C00150000 100]"
    final desc = '${p['contractDesc'] ?? ''}';
    final m = RegExp(r'\[([A-Z.]+)\s+(\d{6}[CP]\d{8})').firstMatch(desc);
    if (m != null) return OptionContract.fromOcc('${m.group(1)}${m.group(2)}');
    final expiry = '${p['expiry'] ?? ''}';
    if (expiry.length == 8 && p['strike'] != null && p['putOrCall'] != null && p['ticker'] != null) {
      return OptionContract(
        underlying: p['ticker'] as String,
        right: OptionRight.parse('${p['putOrCall']}'),
        expiry: DateTime.utc(int.parse(expiry.substring(0, 4)), int.parse(expiry.substring(4, 6)), int.parse(expiry.substring(6))),
        strikeCents: jCents(p['strike']),
      );
    }
    return null;
  }

  @override
  Future<List<BrokerOrder>> openOrders() async {
    final j = jMap(await _call('GET', '/iserver/account/orders'));
    final out = <BrokerOrder>[];
    for (final raw in jList(j['orders'] ?? const [])) {
      final o = await _order(jMap(raw));
      if (o != null && o.status.isOpen) out.add(o);
    }
    return out;
  }

  @override
  Future<BrokerOrder?> order(String orderId) async {
    final j = jMap(await _call('GET', '/iserver/account/order/status/$orderId'));
    return _order({...j, 'orderId': orderId});
  }

  @override
  Future<BrokerOrder> placeOrder(OrderRequest r) async {
    LiveTradingGuard.ensureAllowed(mode: mode, accountId: accountId, approval: liveApproval);
    if (mode == TradingMode.paper && !_brokerAccount.toUpperCase().startsWith('DU')) {
      throw const BrokerException(BrokerErrorCode.liveLocked, 'Refusing: account is not an IBKR paper account');
    }
    final conid = await _optionConid(r.contract);
    dynamic reply = await _call('POST', '/iserver/account/$_brokerAccount/orders', json: {
      'orders': [
        {
          'conid': conid,
          'orderType': 'LMT',
          'price': r.limitPriceCents / 100,
          'side': r.side == OrderSide.buyToOpen ? 'BUY' : 'SELL',
          'quantity': r.quantity,
          'tif': 'DAY',
          'cOID': r.clientOrderId,
        }
      ]
    });
    // IBKR may answer with confirmation questions; confirm up to 3 times.
    for (var i = 0; i < 3; i++) {
      final first = reply is List && reply.isNotEmpty ? jMap(reply.first) : <String, dynamic>{};
      if (first['order_id'] != null) {
        return (await order('${first['order_id']}')) ??
            BrokerOrder(
              id: '${first['order_id']}',
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
      if (first['id'] == null) break;
      reply = await _call('POST', '/iserver/reply/${first['id']}', json: {'confirmed': true});
    }
    throw BrokerException(BrokerErrorCode.rejected, 'IBKR did not accept the order: $reply');
  }

  @override
  Future<void> cancelOrder(String orderId) async {
    await _call('DELETE', '/iserver/account/$_brokerAccount/order/$orderId');
  }

  Future<BrokerOrder?> _order(Map<String, dynamic> o) async {
    final conid = o['conid'] == null ? null : jNum(o['conid']).toInt();
    final contract = conid == null ? null : _contractsByConid[conid];
    if (contract == null) return null; // not an order this app knows about
    final st = '${o['status'] ?? o['order_status'] ?? ''}'.toLowerCase();
    final status = switch (st) {
      'filled' => OrderStatus.filled,
      'cancelled' || 'apicancelled' => OrderStatus.cancelled,
      'inactive' || 'rejected' => OrderStatus.rejected,
      _ => OrderStatus.pending, // presubmitted, submitted, pendingsubmit, ...
    };
    final total = jNum(o['totalSize'] ?? o['total_size'] ?? o['size'] ?? 0).round();
    final filled = jNum(o['filledQuantity'] ?? o['cum_fill'] ?? 0).round();
    return BrokerOrder(
      id: '${o['orderId'] ?? o['order_id']}',
      clientOrderId: '${o['order_ref'] ?? o['cOID'] ?? ''}',
      contract: contract,
      side: '${o['side']}'.toUpperCase().startsWith('B') ? OrderSide.buyToOpen : OrderSide.sellToClose,
      quantity: total,
      filledQuantity: filled,
      limitPriceCents: jCents(o['price'] ?? o['limit_price'] ?? 0),
      averageFillCents: o['avgPrice'] == null ? null : jCents(o['avgPrice']),
      status: status == OrderStatus.pending && filled > 0 ? OrderStatus.partiallyFilled : status,
      createdAt: clock(),
    );
  }

  // ---- contract resolution ----

  Future<int> _stockConid(String symbol) async {
    final cached = _stockConids[symbol];
    if (cached != null) return cached;
    final list = jList(await _call('GET', '/iserver/secdef/search', query: {'symbol': symbol, 'secType': 'STK'}));
    for (final raw in list) {
      final m = jMap(raw);
      if (m['conid'] != null) {
        final id = jNum(m['conid']).toInt();
        _stockConids[symbol] = id;
        return id;
      }
    }
    throw BrokerException(BrokerErrorCode.notFound, 'IBKR: unknown symbol $symbol');
  }

  static const _months = ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC'];
  static String _monthCode(DateTime d) => '${_months[d.month - 1]}${(d.year % 100).toString().padLeft(2, '0')}';

  Future<int> _optionConid(OptionContract c) async {
    final cached = _optionConids[c.occSymbol];
    if (cached != null) return cached;
    final under = await _stockConid(c.underlying);
    final list = jList(await _call('GET', '/iserver/secdef/info', query: {
      'conid': '$under',
      'sectype': 'OPT',
      'month': _monthCode(c.expiry),
      'strike': c.strike.toString(),
      'right': c.right.occ,
    }));
    final want = isoDate(c.expiry).replaceAll('-', '');
    for (final raw in list) {
      final m = jMap(raw);
      if ('${m['maturityDate']}' == want && m['conid'] != null) {
        final id = jNum(m['conid']).toInt();
        _optionConids[c.occSymbol] = id;
        _contractsByConid[id] = c;
        return id;
      }
    }
    throw BrokerException(BrokerErrorCode.notFound, 'IBKR: no contract for ${c.occSymbol}');
  }

  // ---- market data ----

  @override
  Future<List<Candle>> bars(String symbol, BarTimeframe timeframe, {int limit = 300}) async {
    final conid = await _stockConid(symbol);
    final (bar, period) = switch (timeframe) {
      BarTimeframe.m5 => ('5min', '1w'),
      BarTimeframe.m15 => ('15min', '2w'),
      BarTimeframe.h1 => ('1h', '2m'),
      BarTimeframe.d1 => ('1d', '2y'),
    };
    final j = jMap(await _call('GET', '/iserver/marketdata/history',
        query: {'conid': '$conid', 'bar': bar, 'period': period, 'outsideRth': 'false'}));
    final data = jList(j['data'] ?? const []).map((b) {
      final m = jMap(b);
      return Candle(
        time: DateTime.fromMillisecondsSinceEpoch(jNum(m['t']).toInt(), isUtc: true),
        open: jNum(m['o']),
        high: jNum(m['h']),
        low: jNum(m['l']),
        close: jNum(m['c']),
        volume: jNum(m['v'] ?? 0),
      );
    }).toList();
    return data.length > limit ? data.sublist(data.length - limit) : data;
  }

  /// Snapshot fields: 31 last, 84 bid, 86 ask, 7308 delta, 7633 implied vol, 87 volume.
  Future<List<Map<String, dynamic>>> _snapshot(List<int> conids) async {
    final q = {'conids': conids.join(','), 'fields': '31,84,86,87,7308,7633'};
    // The first request only subscribes; IBKR returns data on the next one.
    await _call('GET', '/iserver/marketdata/snapshot', query: q);
    return jList(await _call('GET', '/iserver/marketdata/snapshot', query: q)).map(jMap).toList();
  }

  static double? _field(Map<String, dynamic> m, String k) {
    final v = m[k];
    if (v == null) return null;
    return double.tryParse('$v'.replaceAll(RegExp(r'[^0-9.\-]'), ''));
  }

  @override
  Future<double> lastPrice(String symbol) async {
    final s = await _snapshot([await _stockConid(symbol)]);
    final p = s.isEmpty ? null : _field(s.first, '31');
    if (p == null) throw BrokerException(BrokerErrorCode.notFound, 'No IBKR price for $symbol');
    return p;
  }

  @override
  Future<List<OptionQuote>> optionChain(String underlying,
      {required DateTime minExpiry, required DateTime maxExpiry, OptionRight? right}) async {
    final under = await _stockConid(underlying);
    final spot = await lastPrice(underlying);
    final contracts = <OptionContract>[];
    final seenMonths = <String>{};
    for (var d = DateTime.utc(minExpiry.year, minExpiry.month); !d.isAfter(maxExpiry); d = DateTime.utc(d.year, d.month + 1)) {
      final month = _monthCode(d);
      if (!seenMonths.add(month)) continue;
      final sj = jMap(await _call('GET', '/iserver/secdef/strikes', query: {'conid': '$under', 'sectype': 'OPT', 'month': month}));
      final strikes = jList(sj['call'] ?? const []).map(jNum).toList()
        ..sort((a, b) => (a - spot).abs().compareTo((b - spot).abs()));
      for (final k in strikes.take(8)) {
        for (final r in OptionRight.values) {
          if (right != null && r != right) continue;
          final info = jList(await _call('GET', '/iserver/secdef/info', query: {
            'conid': '$under',
            'sectype': 'OPT',
            'month': month,
            'strike': '$k',
            'right': r.occ,
          }));
          for (final raw in info) {
            final m = jMap(raw);
            final md = '${m['maturityDate']}';
            if (md.length != 8 || m['conid'] == null) continue;
            final exp = DateTime.utc(int.parse(md.substring(0, 4)), int.parse(md.substring(4, 6)), int.parse(md.substring(6)));
            if (exp.isBefore(minExpiry) || exp.isAfter(maxExpiry)) continue;
            final c = OptionContract(underlying: underlying, right: r, expiry: exp, strikeCents: (k * 100).round());
            final id = jNum(m['conid']).toInt();
            _optionConids[c.occSymbol] = id;
            _contractsByConid[id] = c;
            contracts.add(c);
          }
        }
      }
    }
    if (contracts.isEmpty) return const [];
    final snaps = await _snapshot(contracts.map((c) => _optionConids[c.occSymbol]!).toList());
    final out = <OptionQuote>[];
    for (final s in snaps) {
      final conid = s['conid'] == null ? null : jNum(s['conid']).toInt();
      final c = conid == null ? null : _contractsByConid[conid];
      if (c == null) continue;
      out.add(OptionQuote(
        contract: c,
        bidCents: ((_field(s, '84') ?? 0) * 100).round(),
        askCents: ((_field(s, '86') ?? 0) * 100).round(),
        volume: (_field(s, '87') ?? 0).round(),
        delta: _field(s, '7308'),
        impliedVolatility: _field(s, '7633') == null ? null : _field(s, '7633')! / 100,
        time: clock(),
      ));
    }
    return out;
  }

  @override
  Future<OptionQuote?> optionQuote(OptionContract contract) async {
    final conid = await _optionConid(contract);
    final s = await _snapshot([conid]);
    if (s.isEmpty) return null;
    return OptionQuote(
      contract: contract,
      bidCents: ((_field(s.first, '84') ?? 0) * 100).round(),
      askCents: ((_field(s.first, '86') ?? 0) * 100).round(),
      delta: _field(s.first, '7308'),
      time: clock(),
    );
  }
}
