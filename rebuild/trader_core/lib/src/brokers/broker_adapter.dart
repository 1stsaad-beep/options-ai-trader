/// Broker abstraction (Adapter Pattern).
///
/// Every broker — the internal simulator, Alpaca, IBKR, TradeStation and any
/// future one — implements [BrokerAdapter]. The trading engine talks only to
/// this interface, so adding a broker never touches engine code:
///
/// 1. Add a value to `BrokerKind`.
/// 2. Implement [BrokerAdapter] (see `alpaca_adapter.dart` as the reference).
/// 3. Declare its key fields in [BrokerCredentialSpec.forKind].
/// 4. Register a factory in `BrokerRegistry.standard()`.
library;

import '../models.dart';

enum BarTimeframe {
  m5(Duration(minutes: 5)),
  m15(Duration(minutes: 15)),
  h1(Duration(hours: 1)),
  d1(Duration(days: 1));

  final Duration duration;
  const BarTimeframe(this.duration);
}

/// Categorised broker failure. Adapters must translate transport errors into
/// one of these so the engine can react deterministically.
enum BrokerErrorCode { auth, rateLimited, rejected, notFound, network, unsupported, liveLocked, invalidResponse }

class BrokerException implements Exception {
  final BrokerErrorCode code;
  final String message;
  const BrokerException(this.code, this.message);

  @override
  String toString() => 'BrokerException(${code.name}): $message';
}

/// Market data needed by the engines.
abstract interface class MarketDataSource {
  /// Most recent [limit] completed bars, oldest first.
  Future<List<Candle>> bars(String symbol, BarTimeframe timeframe, {int limit = 300});

  /// Last trade/mid price of the underlying stock.
  Future<double> lastPrice(String symbol);

  /// Quotes for listed contracts of [underlying] expiring in [minExpiry, maxExpiry].
  Future<List<OptionQuote>> optionChain(
    String underlying, {
    required DateTime minExpiry,
    required DateTime maxExpiry,
    OptionRight? right,
  });

  /// Fresh quote for one contract, or null if unavailable.
  Future<OptionQuote?> optionQuote(OptionContract contract);
}

/// Account and order operations. One adapter instance == one account.
abstract interface class BrokerAdapter implements MarketDataSource {
  BrokerKind get kind;
  TradingMode get mode;

  /// Validates credentials/session. Throws [BrokerException] on failure.
  Future<void> connect();

  Future<AccountSnapshot> account();
  Future<List<Position>> positions();

  /// Orders that are still working (pending / partially filled).
  Future<List<BrokerOrder>> openOrders();

  /// Places a limit order. Live-mode adapters must call
  /// `LiveTradingGuard.ensureAllowed` first.
  Future<BrokerOrder> placeOrder(OrderRequest request);

  Future<void> cancelOrder(String orderId);

  Future<BrokerOrder?> order(String orderId);
}

/// One field of a broker's credential form.
class CredentialField {
  final String key;
  final String labelAr;
  final bool secret;
  final bool optional;
  final String? hintAr;
  const CredentialField(this.key, this.labelAr, {this.secret = false, this.optional = false, this.hintAr});
}

/// Which fields the "add account" screen must ask for. Secrets are stored only
/// in the platform secure store (Keychain / Android Keystore), never in JSON.
class BrokerCredentialSpec {
  static List<CredentialField> forKind(BrokerKind kind) => switch (kind) {
        BrokerKind.simulator => const [],
        BrokerKind.alpaca => const [
            CredentialField('keyId', 'معرّف المفتاح (Key ID)'),
            CredentialField('secretKey', 'المفتاح السري (Secret)', secret: true),
          ],
        BrokerKind.tradestation => const [
            CredentialField('clientId', 'Client ID'),
            CredentialField('clientSecret', 'Client Secret', secret: true),
            CredentialField('refreshToken', 'Refresh Token', secret: true),
            CredentialField('accountId', 'رقم الحساب', hintAr: 'حساب SIM في وضع Paper'),
          ],
        BrokerKind.ibkr => const [
            CredentialField('gatewayUrl', 'عنوان Client Portal Gateway',
                hintAr: 'مثال: https://192.168.1.10:5000 — يجب تشغيل البوابة وتسجيل الدخول فيها'),
            CredentialField('accountId', 'رقم الحساب', hintAr: 'يبدأ بـ DU لحسابات Paper'),
          ],
      };
}

/// Plain key/value credentials handed to an adapter at construction time.
class BrokerCredentials {
  final Map<String, String> values;
  const BrokerCredentials(this.values);

  String require(String key) {
    final v = values[key];
    if (v == null || v.trim().isEmpty) {
      throw BrokerException(BrokerErrorCode.auth, 'Missing credential: $key');
    }
    return v.trim();
  }

  /// True when every non-optional field of [kind] is present.
  bool isCompleteFor(BrokerKind kind) => BrokerCredentialSpec.forKind(kind)
      .where((f) => !f.optional)
      .every((f) => (values[f.key] ?? '').trim().isNotEmpty);
}

/// Minimal HTTP port so the core stays free of Flutter/plugin dependencies.
/// The app provides an implementation backed by `package:http`.
abstract interface class HttpTransport {
  Future<HttpResult> send(String method, Uri url, {Map<String, String> headers = const {}, String? body});
}

class HttpResult {
  final int status;
  final String body;
  const HttpResult(this.status, this.body);
  bool get ok => status >= 200 && status < 300;
}

/// Maps common HTTP statuses to [BrokerException]. Adapters call this on every
/// non-2xx response.
Never throwForStatus(HttpResult r, String context) {
  final snippet = r.body.length > 300 ? r.body.substring(0, 300) : r.body;
  throw BrokerException(
    switch (r.status) {
      401 || 403 => BrokerErrorCode.auth,
      404 => BrokerErrorCode.notFound,
      422 || 400 => BrokerErrorCode.rejected,
      429 => BrokerErrorCode.rateLimited,
      _ => BrokerErrorCode.network,
    },
    '$context: HTTP ${r.status} $snippet',
  );
}
