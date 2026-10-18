import 'dart:async';
import 'dart:io';

import 'package:http/http.dart' as http;
import 'package:http/io_client.dart';
import 'package:trader_core/trader_core.dart';

/// `HttpTransport` backed by package:http with a hard timeout.
///
/// [trustSelfSignedHost]: IBKR's Client Portal Gateway serves a self-signed
/// certificate. Only for that exact host (entered by the user) is the
/// certificate accepted; every other host keeps normal TLS validation.
class AppHttpTransport implements HttpTransport {
  final http.Client _client;
  final Duration timeout;

  AppHttpTransport({String? trustSelfSignedHost, this.timeout = const Duration(seconds: 20)})
      : _client = trustSelfSignedHost == null
            ? http.Client()
            : IOClient(HttpClient()..badCertificateCallback = (cert, host, port) => host == trustSelfSignedHost);

  @override
  Future<HttpResult> send(String method, Uri url, {Map<String, String> headers = const {}, String? body}) async {
    try {
      final req = http.Request(method, url)..headers.addAll(headers);
      if (body != null) req.body = body;
      final streamed = await _client.send(req).timeout(timeout);
      final res = await http.Response.fromStream(streamed).timeout(timeout);
      return HttpResult(res.statusCode, res.body);
    } on TimeoutException {
      throw BrokerException(BrokerErrorCode.network, 'Timeout: $method ${url.host}');
    } on SocketException catch (e) {
      throw BrokerException(BrokerErrorCode.network, 'Network error: ${e.message}');
    } on HandshakeException catch (e) {
      throw BrokerException(BrokerErrorCode.network, 'TLS error: ${e.message}');
    }
  }

  void close() => _client.close();
}
