/// Shared bounded HTTPS transport for Paper broker adapters.
///
/// Every request is HTTPS, host-allowlisted per adapter, never follows redirects
/// (credentials must not be forwarded), has a total deadline and a response cap.
library;

import 'dart:async';
import 'dart:convert';
import 'dart:io' show SocketException, HandshakeException;

import 'package:http/http.dart' as http;

import '../bounded_json.dart';
import 'broker_models.dart';

class BrokerHttp {
  final http.Client client;
  final Set<String> allowedHosts;
  final Duration timeout;
  static const maxResponseBytes = 2 * 1024 * 1024;

  BrokerHttp(this.client, this.allowedHosts, {this.timeout = const Duration(seconds: 15)});

  void _checkUri(Uri uri) {
    if (uri.scheme != 'https' || !allowedHosts.contains(uri.host) || uri.userInfo.isNotEmpty) {
      throw const BrokerException('HOST_NOT_ALLOWED');
    }
  }

  Future<Object?> send(String method, Uri uri,
      {Map<String, String> headers = const {}, Object? jsonBody, Map<String, String>? form}) async {
    _checkUri(uri);
    final request = http.Request(method, uri)
      ..followRedirects = false
      ..headers.addAll({'Accept': 'application/json', ...headers});
    if (jsonBody != null) {
      request.headers['Content-Type'] = 'application/json';
      request.body = jsonEncode(jsonBody);
    } else if (form != null) {
      request.bodyFields = form;
    }
    final http.Response response;
    try {
      final streamed = await client.send(request).timeout(timeout);
      if (streamed.contentLength != null && streamed.contentLength! > maxResponseBytes) {
        throw const BrokerException('INVALID_DATA');
      }
      final bytes = <int>[];
      await for (final chunk in streamed.stream.timeout(timeout)) {
        bytes.addAll(chunk);
        if (bytes.length > maxResponseBytes) throw const BrokerException('INVALID_DATA');
      }
      response = http.Response.bytes(bytes, streamed.statusCode, headers: streamed.headers);
    } on BrokerException {
      rethrow;
    } on TimeoutException {
      throw const BrokerException('TIMEOUT');
    } on HandshakeException {
      throw const BrokerException('TLS_ERROR');
    } on SocketException {
      throw const BrokerException('NETWORK_ERROR');
    } on http.ClientException {
      throw const BrokerException('NETWORK_ERROR');
    }
    final status = response.statusCode;
    if (status >= 300 && status < 400) throw BrokerException('REDIRECT_REJECTED', status);
    if (status == 401 || status == 403 || status == 404 || status == 422 || status == 429) {
      throw BrokerException('HTTP_$status', status);
    }
    if (status < 200 || status >= 300) throw BrokerException('HTTP_$status', status);
    if (response.body.trim().isEmpty) return null;
    try {
      return decodeBoundedJson(utf8.decode(response.bodyBytes),
          maxBytes: maxResponseBytes, maxNodes: 200000, maxDepth: 32);
    } on FormatException {
      throw const BrokerException('INVALID_DATA');
    }
  }
}

Map<String, dynamic> asMap(Object? value) {
  if (value is Map<String, dynamic>) return value;
  throw const BrokerException('INVALID_DATA');
}

List<dynamic> asList(Object? value) {
  if (value is List) return value;
  throw const BrokerException('INVALID_DATA');
}

/// Broker numbers are carried as exact decimal strings; never parsed to double for storage.
String? decimalText(Object? value) {
  if (value == null) return null;
  if (value is num) {
    if (!value.isFinite) throw const BrokerException('INVALID_DATA');
    return value.toString();
  }
  if (value is String && RegExp(r'^-?\d+(\.\d+)?$').hasMatch(value)) return value;
  throw const BrokerException('INVALID_DATA');
}
