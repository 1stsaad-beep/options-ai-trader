/// Alpaca Trading API, Paper environment only (https://paper-api.alpaca.markets).
library;

import 'package:http/http.dart' as http;

import 'broker_adapter.dart';
import 'broker_http.dart';
import 'broker_models.dart';

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
