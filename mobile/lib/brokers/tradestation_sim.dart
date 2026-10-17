/// TradeStation API v3 against the SIM (paper) environment only.
///
/// OAuth: the user authorizes once (see [TradeStationSimAdapter.authorizeUrl])
/// and pastes the resulting refresh token. The adapter exchanges it for a
/// 20-minute access token at signin.tradestation.com and calls only
/// https://sim-api.tradestation.com/v3. Rotated refresh tokens are handed back
/// to secure storage through [TokenRotated].
library;

import 'package:http/http.dart' as http;

import 'broker_adapter.dart';
import 'broker_http.dart';
import 'broker_models.dart';

class TradeStationSimAdapter implements BrokerAdapter {
  static const apiHost = 'sim-api.tradestation.com';
  static const authHost = 'signin.tradestation.com';
  static const scopes = 'openid offline_access ReadAccount Trade MarketData';
  final BrokerHttp _http;
  final String _clientId, _clientSecret;
  String _refreshToken;
  final String? configuredAccountId;
  final TokenRotated? onRefreshTokenRotated;
  final DateTime Function() now;
  String? _accessToken;
  DateTime _expiresAt = DateTime.fromMillisecondsSinceEpoch(0);
  String? _accountId;

  TradeStationSimAdapter(BrokerCredentials c, Map<String, String> settings,
      {required http.Client client, this.onRefreshTokenRotated, DateTime Function()? clock})
      : _http = BrokerHttp(client, const {apiHost, authHost}),
        _clientId = c['clientId'], _clientSecret = c['clientSecret'], _refreshToken = c['refreshToken'],
        configuredAccountId = (settings['accountId'] ?? '').trim().isEmpty ? null : settings['accountId']!.trim(),
        now = clock ?? DateTime.now {
    final token = RegExp(r'^[A-Za-z0-9._~+/=-]{8,4096}$');
    if (!token.hasMatch(_clientId) || !token.hasMatch(_clientSecret) || !token.hasMatch(_refreshToken)) {
      throw const BrokerException('INVALID_KEYS');
    }
    if (configuredAccountId != null && !RegExp(r'^[A-Za-z0-9]{3,32}$').hasMatch(configuredAccountId!)) {
      throw const BrokerException('INVALID_SETTINGS');
    }
  }

  static Uri authorizeUrl({required String clientId, required String redirectUri, required String state}) =>
      Uri.https(authHost, '/authorize', {
        'response_type': 'code', 'client_id': clientId, 'audience': 'https://api.tradestation.com',
        'redirect_uri': redirectUri, 'scope': scopes, 'state': state,
      });

  @override
  BrokerKind get kind => BrokerKind.tradestation;

  Future<Map<String, String>> _auth() async {
    if (_accessToken == null || !now().isBefore(_expiresAt)) {
      final j = asMap(await _http.send('POST', Uri.https(authHost, '/oauth/token'), form: {
        'grant_type': 'refresh_token', 'client_id': _clientId, 'client_secret': _clientSecret,
        'refresh_token': _refreshToken,
      }));
      final access = j['access_token'];
      if (access is! String || access.isEmpty) throw const BrokerException('INVALID_DATA');
      final ttl = j['expires_in'] is int ? j['expires_in'] as int : 1200;
      _accessToken = access;
      _expiresAt = now().add(Duration(seconds: ttl > 60 ? ttl - 60 : ttl));
      final rotated = j['refresh_token'];
      if (rotated is String && rotated.isNotEmpty && rotated != _refreshToken) {
        _refreshToken = rotated;
        await onRefreshTokenRotated?.call(rotated);
      }
    }
    return {'Authorization': 'Bearer $_accessToken'};
  }

  Uri _uri(String path) => Uri.https(apiHost, '/v3$path');

  Future<String> _account() async {
    if (_accountId != null) return _accountId!;
    final j = asMap(await _http.send('GET', _uri('/brokerage/accounts'), headers: await _auth()));
    final ids = asList(j['Accounts']).map(asMap).map((a) => a['AccountID']).whereType<String>().toList();
    if (ids.isEmpty) throw const BrokerException('ACCOUNT_NOT_FOUND');
    final chosen = configuredAccountId ?? ids.first;
    if (!ids.contains(chosen)) throw const BrokerException('ACCOUNT_NOT_FOUND');
    return _accountId = chosen;
  }

  @override
  Future<BrokerAccountSnapshot> connect() async {
    final id = await _account();
    final j = asMap(await _http.send('GET', _uri('/brokerage/accounts/$id/balances'), headers: await _auth()));
    final rows = asList(j['Balances']).map(asMap).where((b) => b['AccountID'] == id).toList();
    if (rows.isEmpty) throw const BrokerException('INVALID_DATA');
    final b = rows.first;
    return BrokerAccountSnapshot(broker: kind, brokerAccountId: id, cash: decimalText(b['CashBalance']),
        equity: decimalText(b['Equity']), buyingPower: decimalText(b['BuyingPower']),
        // SIM host by construction.
        paperVerified: true, status: 'CONNECTED');
  }

  @override
  Future<List<BrokerPosition>> positions() async {
    final id = await _account();
    final j = asMap(await _http.send('GET', _uri('/brokerage/accounts/$id/positions'), headers: await _auth()));
    return [
      for (final p in asList(j['Positions']).map(asMap))
        BrokerPosition(symbol: p['Symbol'] as String, quantity: decimalText(p['Quantity'])!,
            averagePrice: decimalText(p['AveragePrice']), marketValue: decimalText(p['MarketValue']),
            unrealizedPl: decimalText(p['UnrealizedProfitLoss']))
    ];
  }

  @override
  Future<BrokerOrderAck> submitPaperOrder(PaperOrderRequest o) async {
    final id = await _account();
    final action = o.assetClass == AssetClass.option
        ? (o.side == OrderSide.buy ? 'BUYTOOPEN' : 'SELLTOCLOSE')
        : (o.side == OrderSide.buy ? 'BUY' : 'SELL');
    final j = asMap(await _http.send('POST', _uri('/orderexecution/orders'), headers: await _auth(), jsonBody: {
      'AccountID': id, 'Symbol': o.symbol, 'Quantity': '${o.quantity}', 'OrderType': 'Limit',
      'LimitPrice': o.limitPrice, 'TradeAction': action, 'TimeInForce': {'Duration': 'DAY'},
      'Route': 'Intelligent',
    }));
    final orders = asList(j['Orders']);
    if (orders.isEmpty) throw const BrokerException('ORDER_REJECTED');
    final r = asMap(orders.first);
    final orderId = r['OrderID'];
    if (orderId is! String) throw const BrokerException('ORDER_REJECTED');
    return BrokerOrderAck(orderId: orderId, status: 'SUBMITTED', message: r['Message'] as String?);
  }
}
