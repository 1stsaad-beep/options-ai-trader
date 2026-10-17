/// Alpaca Trading API, Paper environment only (https://paper-api.alpaca.markets).
library;

import 'package:http/http.dart' as http;

import 'broker_adapter.dart';
import 'broker_http.dart';
import 'broker_models.dart';
import 'broker_options.dart';

class AlpacaPaperAdapter implements BrokerAdapter {
  static const host = 'paper-api.alpaca.markets';
  static final _key = RegExp(r'^[A-Za-z0-9]{8,128}$');
  final BrokerHttp _http;
  final String _keyId, _secret;

  AlpacaPaperAdapter(BrokerCredentials credentials, {required http.Client client,
      Duration timeout = const Duration(seconds: 15)})
      : _http = BrokerHttp(client, const {host}, timeout: timeout),
        _keyId = credentials['keyId'],
        _secret = credentials['secretKey'] {
    if (!_key.hasMatch(_keyId) || !_key.hasMatch(_secret)) throw const BrokerException('INVALID_KEYS');
  }

  @override
  BrokerKind get kind => BrokerKind.alpaca;

  Map<String, String> get _auth => {'APCA-API-KEY-ID': _keyId, 'APCA-API-SECRET-KEY': _secret};
  Uri _uri(String path) => Uri.https(host, path);

  @override
  Future<BrokerAccountSnapshot> connect() async {
    final j = asMap(await _http.send('GET', _uri('/v2/account'), headers: _auth));
    final id = j['account_number'] ?? j['id'];
    if (id is! String || id.isEmpty) throw const BrokerException('INVALID_DATA');
    return BrokerAccountSnapshot(
        broker: kind, brokerAccountId: id, currency: (j['currency'] as String?) ?? 'USD',
        cash: decimalText(j['cash']), equity: decimalText(j['equity']),
        buyingPower: decimalText(j['buying_power']),
        // Host is the Paper environment by construction.
        paperVerified: true, status: (j['status'] as String?) ?? 'UNKNOWN');
  }

  @override
  Future<List<BrokerPosition>> positions() async {
    final rows = asList(await _http.send('GET', _uri('/v2/positions'), headers: _auth));
    return [
      for (final r in rows.map(asMap))
        BrokerPosition(symbol: r['symbol'] as String, quantity: decimalText(r['qty'])!,
            averagePrice: decimalText(r['avg_entry_price']), marketValue: decimalText(r['market_value']),
            unrealizedPl: decimalText(r['unrealized_pl']))
    ];
  }

  /// Contract terms (status, tradable, style, multiplier, deliverables, open interest) from
  /// the Trading API on the same Paper host. Read-only.
  Future<Map<String, dynamic>> contractTerms(OccContract contract) async =>
      asMap(await _http.send('GET', _uri('/v2/options/contracts/${contract.occ}'), headers: _auth));

  /// paper-api has no option quotes; the allowlist is not widened for data hosts.
  @override
  Future<BrokerQuote?> optionQuote(OccContract contract, {String? conid}) async => null;

  static const _states = {
    'filled': 'FILLED', 'partially_filled': 'PARTIALLY_FILLED', 'canceled': 'CANCELED', 'expired': 'EXPIRED',
    'rejected': 'REJECTED', 'done_for_day': 'OPEN', 'replaced': 'CANCELED',
  };

  @override
  Future<BrokerOrderLookup> orderStatus({required String clientOrderId, String? brokerOrderId,
      Map<String, dynamic>? match}) async {
    final Object? raw;
    try {
      raw = brokerOrderId != null
          ? await _http.send('GET', _uri('/v2/orders/$brokerOrderId'), headers: _auth)
          : await _http.send('GET', Uri.https(host, '/v2/orders:by_client_order_id', {'client_order_id': clientOrderId}),
              headers: _auth);
    } on BrokerException catch (e) {
      if (e.code == 'HTTP_404' && brokerOrderId == null) return const BrokerOrderLookup(null, definitiveNotFound: true);
      if (e.code == 'HTTP_404') return const BrokerOrderLookup(null);
      rethrow;
    }
    final j = asMap(raw);
    final id = j['id'], status = j['status'];
    if (id is! String || status is! String) throw const BrokerException('INVALID_DATA');
    if (j['client_order_id'] != null && j['client_order_id'] != clientOrderId) throw const BrokerException('ORDER_IDENTITY_MISMATCH');
    final filled = decimalCents(decimalText(j['filled_qty']) ?? '0');
    if (filled == null || filled % 100 != 0) throw const BrokerException('INVALID_DATA');
    return BrokerOrderLookup(BrokerOrderStatus(brokerOrderId: id, state: _states[status] ?? 'OPEN', rawStatus: status,
        filledQuantity: filled ~/ 100, averageFillPrice: decimalText(j['filled_avg_price']), clientOrderId: clientOrderId));
  }

  @override
  Future<BrokerOrderAck> submitPaperOrder(PaperOrderRequest o) async {
    final j = asMap(await _http.send('POST', _uri('/v2/orders'), headers: _auth, jsonBody: {
      'symbol': o.symbol, 'qty': '${o.quantity}', 'side': o.side.name, 'type': 'limit',
      'time_in_force': 'day', 'limit_price': o.limitPrice, 'client_order_id': o.clientOrderId,
    }));
    final id = j['id'];
    if (id is! String) throw const BrokerException('INVALID_DATA');
    return BrokerOrderAck(orderId: id, status: (j['status'] as String?) ?? 'unknown');
  }
}
