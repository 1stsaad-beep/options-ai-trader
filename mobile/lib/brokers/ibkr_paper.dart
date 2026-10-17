/// Interactive Brokers Client Portal Web API against a logged-in Paper session.
///
/// IBKR authentication happens in the Client Portal Gateway (user signs in with
/// Paper credentials there); this app stores only the gateway URL and the Paper
/// account id. Only `DU…` (IBKR Paper) account ids are accepted, and every call
/// and order is bound to that id, so a gateway logged into a live user cannot
/// be used to reach a live `U…` account from here.
library;

import 'package:http/http.dart' as http;

import 'broker_adapter.dart';
import 'broker_http.dart';
import 'broker_models.dart';
import 'broker_options.dart';

class IbkrPaperAdapter implements BrokerAdapter {
  static final paperAccount = RegExp(r'^DU\d{4,10}$');
  final BrokerHttp _http;
  final Uri _base;
  final String accountId;

  IbkrPaperAdapter._(this._http, this._base, this.accountId);

  factory IbkrPaperAdapter(Map<String, String> settings, {required http.Client client}) {
    final base = parseGateway(settings['gatewayUrl'] ?? '');
    final account = (settings['accountId'] ?? '').trim().toUpperCase();
    if (!paperAccount.hasMatch(account)) throw const BrokerException('NOT_PAPER_ACCOUNT');
    return IbkrPaperAdapter._(BrokerHttp(client, {base.host}), base, account);
  }

  static Uri parseGateway(String text) {
    final uri = Uri.tryParse(text.trim());
    if (uri == null || uri.scheme != 'https' || uri.host.isEmpty || uri.userInfo.isNotEmpty ||
        uri.hasQuery || uri.hasFragment) {
      throw const BrokerException('INVALID_GATEWAY');
    }
    return uri.replace(path: '/v1/api');
  }

  @override
  BrokerKind get kind => BrokerKind.ibkr;

  Uri _uri(String path) => _base.replace(path: '${_base.path}$path');

  @override
  Future<BrokerAccountSnapshot> connect() async {
    final auth = asMap(await _http.send('POST', _uri('/iserver/auth/status')));
    if (auth['authenticated'] != true) throw const BrokerException('IBKR_NOT_AUTHENTICATED');
    final accounts = asList(await _http.send('GET', _uri('/portfolio/accounts')));
    final ids = accounts.map(asMap).map((a) => a['accountId'] ?? a['id']).toSet();
    if (!ids.contains(accountId)) throw const BrokerException('ACCOUNT_NOT_FOUND');
    final s = asMap(await _http.send('GET', _uri('/portfolio/$accountId/summary')));
    String? amount(String key) => s[key] is Map ? decimalText((s[key] as Map)['amount']) : null;
    final currency = s['totalcashvalue'] is Map ? (s['totalcashvalue'] as Map)['currency'] : null;
    return BrokerAccountSnapshot(broker: kind, brokerAccountId: accountId,
        currency: currency is String ? currency : 'USD', cash: amount('totalcashvalue'),
        equity: amount('netliquidation'), buyingPower: amount('buyingpower'),
        paperVerified: true, status: auth['connected'] == true ? 'CONNECTED' : 'AUTHENTICATED');
  }

  @override
  Future<List<BrokerPosition>> positions() async {
    final rows = asList(await _http.send('GET', _uri('/portfolio/$accountId/positions/0')));
    return [
      for (final r in rows.map(asMap))
        BrokerPosition(symbol: '${r['contractDesc'] ?? r['conid']}', quantity: decimalText(r['position'])!,
            averagePrice: decimalText(r['avgPrice']), marketValue: decimalText(r['mktValue']),
            unrealizedPl: decimalText(r['unrealizedPnl']),
            contractId: r['conid'] == null ? null : '${r['conid']}')
    ];
  }

  /// Snapshot fields 84 bid, 86 ask, 88 bid size, 85 ask size; `_updated` epoch ms.
  /// The first snapshot after subscribing often lacks fields: that yields null (no quote).
  @override
  Future<BrokerQuote?> optionQuote(OccContract contract, {String? conid}) async {
    if (conid == null || !RegExp(r'^\d{1,12}$').hasMatch(conid)) return null;
    final rows = asList(await _http.send('GET', _base.replace(path: '${_base.path}/iserver/marketdata/snapshot',
        queryParameters: {'conids': conid, 'fields': '84,86,88,85'})));
    if (rows.isEmpty) return null;
    final r = asMap(rows.first);
    if ('${r['conid']}' != conid) return null;
    final bid = decimalCents(r['84']?.toString()), ask = decimalCents(r['86']?.toString(), up: true);
    final bs = int.tryParse('${r['88'] ?? ''}'.replaceAll(',', '')), as = int.tryParse('${r['85'] ?? ''}'.replaceAll(',', ''));
    final updated = r['_updated'];
    if (bid == null || ask == null || bs == null || as == null || updated is! int) return null;
    return BrokerQuote(contract: contract.occ, bid: bid, ask: ask, bidSize: bs, askSize: as,
        time: DateTime.fromMillisecondsSinceEpoch(updated, isUtc: true), source: 'ibkr-paper', timeSource: 'QUOTE');
  }

  static const _states = {
    'Filled': 'FILLED', 'Cancelled': 'CANCELED', 'Inactive': 'REJECTED', 'ApiCancelled': 'CANCELED',
  };

  /// Matches today's orders for the Paper account by `order_ref` (cOID) or orderId.
  /// Absence is never treated as proof that nothing was placed.
  @override
  Future<BrokerOrderLookup> orderStatus({required String clientOrderId, String? brokerOrderId,
      Map<String, dynamic>? match}) async {
    final j = asMap(await _http.send('GET', _uri('/iserver/account/orders')));
    final rows = asList(j['orders'] ?? const []).map(asMap).where((o) =>
        (o['acct'] == null || o['acct'] == accountId) &&
        (o['order_ref'] == clientOrderId || (brokerOrderId != null && '${o['orderId']}' == brokerOrderId))).toList();
    if (rows.isEmpty) return const BrokerOrderLookup(null);
    if (rows.length > 1) throw const BrokerException('ORDER_IDENTITY_MISMATCH');
    final o = rows.first;
    final status = '${o['status']}';
    final filled = decimalCents(decimalText(o['filledQuantity']) ?? '0');
    if (filled == null || filled % 100 != 0) throw const BrokerException('INVALID_DATA');
    final qty = filled ~/ 100;
    final state = _states[status] ?? (qty > 0 ? 'PARTIALLY_FILLED' : 'OPEN');
    return BrokerOrderLookup(BrokerOrderStatus(brokerOrderId: '${o['orderId']}', state: state, rawStatus: status,
        filledQuantity: qty, averageFillPrice: decimalText(o['avgPrice']), clientOrderId: clientOrderId));
  }

  @override
  Future<BrokerOrderAck> submitPaperOrder(PaperOrderRequest o) async {
    if (o.ibkrConid == null) throw const BrokerException('INVALID_ORDER');
    final rows = asList(await _http.send('POST', _uri('/iserver/account/$accountId/orders'), jsonBody: {
      'orders': [
        {
          'acctId': accountId, 'conid': int.parse(o.ibkrConid!), 'orderType': 'LMT',
          'side': o.side == OrderSide.buy ? 'BUY' : 'SELL', 'quantity': o.quantity,
          'price': num.parse(o.limitPrice), 'tif': 'DAY', 'cOID': o.clientOrderId,
        }
      ]
    }));
    if (rows.isEmpty) throw const BrokerException('INVALID_DATA');
    final r = asMap(rows.first);
    if (r['order_id'] != null) {
      return BrokerOrderAck(orderId: '${r['order_id']}', status: '${r['order_status'] ?? 'Submitted'}');
    }
    // IBKR precautionary questions are never auto-confirmed.
    if (r['id'] != null) {
      final m = r['message'];
      return BrokerOrderAck(orderId: '${r['id']}', status: 'NEEDS_CONFIRMATION',
          message: m is List ? m.join(' ') : m?.toString());
    }
    throw const BrokerException('INVALID_DATA');
  }
}
