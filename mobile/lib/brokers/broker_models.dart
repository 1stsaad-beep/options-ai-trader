/// Broker account metadata, credential field specs and normalized results.
///
/// Credentials are never part of [BrokerAccount]; they live only in secure
/// storage and are handed to an adapter in memory. `toString` never prints them.
library;

enum BrokerKind { alpaca, ibkr, tradestation }

enum BrokerEnvironment { paper, live }

class BrokerField {
  final String name, label, hint;
  final bool secret, required;
  const BrokerField(this.name, this.label,
      {this.hint = '', this.secret = false, this.required = true});
}

extension BrokerKindInfo on BrokerKind {
  String get id => name;
  String get title => const {
        BrokerKind.alpaca: 'Alpaca',
        BrokerKind.ibkr: 'Interactive Brokers',
        BrokerKind.tradestation: 'TradeStation',
      }[this]!;
  String get paperTitle => const {
        BrokerKind.alpaca: 'Alpaca Paper (paper-api.alpaca.markets)',
        BrokerKind.ibkr: 'IBKR Paper (Client Portal Web API)',
        BrokerKind.tradestation: 'TradeStation SIM (sim-api.tradestation.com)',
      }[this]!;

  /// Non-secret fields are stored with the account; secret fields only in secure storage.
  List<BrokerField> get fields => const {
        BrokerKind.alpaca: [
          BrokerField('keyId', 'API Key ID', hint: 'Paper key من لوحة Alpaca', secret: true),
          BrokerField('secretKey', 'Secret Key', secret: true),
        ],
        BrokerKind.ibkr: [
          BrokerField('gatewayUrl', 'عنوان Client Portal Gateway',
              hint: 'https://host:5000 (جلسة Paper مسجلة الدخول)'),
          BrokerField('accountId', 'رقم حساب Paper', hint: 'يبدأ بـ DU'),
        ],
        BrokerKind.tradestation: [
          BrokerField('clientId', 'API Key (Client ID)', secret: true),
          BrokerField('clientSecret', 'API Secret', secret: true),
          BrokerField('refreshToken', 'Refresh Token', secret: true),
          BrokerField('accountId', 'رقم حساب SIM (اختياري)', required: false),
        ],
      }[this]!;

  static BrokerKind parse(String value) => BrokerKind.values
      .firstWhere((k) => k.name == value, orElse: () => throw const FormatException('Unknown broker'));
}

final _safeId = RegExp(r'^[A-Za-z0-9_-]{1,64}$');

class BrokerAccount {
  final String id, label;
  final BrokerKind broker;
  final BrokerEnvironment environment;
  final Map<String, String> settings; // non-secret fields only
  final DateTime createdAt;
  final bool archived;

  BrokerAccount({required this.id, required this.label, required this.broker,
      this.environment = BrokerEnvironment.paper, Map<String, String> settings = const {},
      required this.createdAt, this.archived = false})
      : settings = Map.unmodifiable(settings) {
    if (!_safeId.hasMatch(id)) throw const FormatException('Invalid account id');
    final trimmed = label.trim();
    if (trimmed.isEmpty || trimmed.length > 60) throw const FormatException('Invalid label');
    final allowed = broker.fields.where((f) => !f.secret).map((f) => f.name).toSet();
    if (settings.keys.any((k) => !allowed.contains(k))) {
      throw const FormatException('Secret or unknown field in account settings');
    }
  }

  BrokerAccount copyWith({bool? archived, String? label}) => BrokerAccount(
      id: id, label: label ?? this.label, broker: broker, environment: environment,
      settings: settings, createdAt: createdAt, archived: archived ?? this.archived);

  Map<String, Object> toJson() => {
        'id': id, 'label': label, 'broker': broker.name, 'environment': environment.name,
        'settings': settings, 'created_at': createdAt.toUtc().toIso8601String(), 'archived': archived,
      };

  factory BrokerAccount.fromJson(Map<String, dynamic> j) => BrokerAccount(
        id: j['id'] as String, label: j['label'] as String,
        broker: BrokerKindInfo.parse(j['broker'] as String),
        environment: BrokerEnvironment.values.byName(j['environment'] as String),
        settings: (j['settings'] as Map).cast<String, String>(),
        createdAt: DateTime.parse(j['created_at'] as String), archived: j['archived'] as bool);

  @override
  String toString() => 'BrokerAccount($id, ${broker.name}, ${environment.name})';
}

/// In-memory credentials. Redacted in `toString`.
class BrokerCredentials {
  final Map<String, String> values;
  BrokerCredentials(Map<String, String> values) : values = Map.unmodifiable(values);
  String operator [](String name) => values[name] ?? '';
  static String mask(String value) =>
      value.length <= 4 ? '••••' : '••••${value.substring(value.length - 4)}';
  @override
  String toString() => 'BrokerCredentials(${values.keys.join(',')}: redacted)';
}

/// Normalized broker error codes; messages never contain credentials.
class BrokerException implements Exception {
  final String code;
  final int? status;
  const BrokerException(this.code, [this.status]);
  @override
  String toString() => 'BrokerException($code)';
}

class BrokerAccountSnapshot {
  final BrokerKind broker;
  final String brokerAccountId, currency;
  final String? cash, equity, buyingPower; // decimal strings exactly as reported
  final bool paperVerified;
  final String status;
  const BrokerAccountSnapshot({required this.broker, required this.brokerAccountId,
      this.currency = 'USD', this.cash, this.equity, this.buyingPower,
      required this.paperVerified, this.status = 'CONNECTED'});
}

class BrokerPosition {
  final String symbol;
  final String quantity;
  final String? averagePrice, marketValue, unrealizedPl;
  final String? contractId; // IBKR conid
  const BrokerPosition({required this.symbol, required this.quantity,
      this.averagePrice, this.marketValue, this.unrealizedPl, this.contractId});
}

enum OrderSide { buy, sell }

enum AssetClass { equity, option }

/// Limit-only paper order. Market orders are intentionally not supported.
class PaperOrderRequest {
  final String symbol;
  final AssetClass assetClass;
  final OrderSide side;
  final int quantity;
  final String limitPrice;
  final String? ibkrConid;
  final String clientOrderId;
  static final _price = RegExp(r'^\d{1,7}(\.\d{1,4})?$');
  static final _symbol = RegExp(r'^[A-Z0-9 .]{1,32}$');
  static final _client = RegExp(r'^[A-Za-z0-9_-]{8,48}$');
  PaperOrderRequest({required this.symbol, required this.assetClass, required this.side,
      required this.quantity, required this.limitPrice, required this.clientOrderId, this.ibkrConid}) {
    if (!_symbol.hasMatch(symbol)) throw const BrokerException('INVALID_ORDER');
    if (quantity <= 0 || quantity > 1000) throw const BrokerException('INVALID_ORDER');
    if (!_price.hasMatch(limitPrice) || double.parse(limitPrice) <= 0) {
      throw const BrokerException('INVALID_ORDER');
    }
    if (!_client.hasMatch(clientOrderId)) throw const BrokerException('INVALID_ORDER');
    if (ibkrConid != null && !RegExp(r'^\d{1,12}$').hasMatch(ibkrConid!)) {
      throw const BrokerException('INVALID_ORDER');
    }
  }
}

/// Normalized broker order status. [state] uses `OrderState` names.
class BrokerOrderStatus {
  final String brokerOrderId, state, rawStatus;
  final int filledQuantity;
  final String? averageFillPrice;
  final String? clientOrderId;
  const BrokerOrderStatus({required this.brokerOrderId, required this.state, required this.rawStatus,
      required this.filledQuantity, this.averageFillPrice, this.clientOrderId});
}

/// Lookup result: [status] null with [definitiveNotFound] means the broker
/// proved no order exists for the client id (Alpaca client_order_id lookup).
class BrokerOrderLookup {
  final BrokerOrderStatus? status;
  final bool definitiveNotFound;
  const BrokerOrderLookup(this.status, {this.definitiveNotFound = false});
}

class BrokerOrderAck {
  final String orderId, status;
  final String? message;
  const BrokerOrderAck({required this.orderId, required this.status, this.message});
}
