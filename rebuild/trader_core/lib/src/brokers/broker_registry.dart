/// Creates the right adapter for an account. The only place that knows the
/// concrete adapter classes.
library;

import '../models.dart';
import 'alpaca_adapter.dart';
import 'broker_adapter.dart';
import 'ibkr_adapter.dart';
import 'live_guard.dart';
import 'simulator_broker.dart';
import 'synthetic_market.dart';
import 'tradestation_adapter.dart';

class AdapterContext {
  final String accountId;
  final TradingMode mode;
  final BrokerCredentials credentials;
  final HttpTransport? http;
  final LiveApproval? liveApproval;
  final int startingCashCents;
  final SyntheticMarket market;
  final DateTime Function() clock;

  const AdapterContext({
    required this.accountId,
    required this.mode,
    required this.credentials,
    required this.market,
    required this.clock,
    this.http,
    this.liveApproval,
    this.startingCashCents = 1000000,
  });

  HttpTransport get requireHttp =>
      http ?? (throw const BrokerException(BrokerErrorCode.network, 'No HTTP transport configured'));
}

typedef AdapterFactory = BrokerAdapter Function(AdapterContext ctx);

class BrokerRegistry {
  final Map<BrokerKind, AdapterFactory> _factories = {};

  void register(BrokerKind kind, AdapterFactory factory) => _factories[kind] = factory;

  bool supports(BrokerKind kind) => _factories.containsKey(kind);

  BrokerAdapter create(BrokerKind kind, AdapterContext ctx) {
    final f = _factories[kind];
    if (f == null) throw BrokerException(BrokerErrorCode.unsupported, 'No adapter registered for ${kind.name}');
    if (kind == BrokerKind.simulator && ctx.mode == TradingMode.live) {
      throw const BrokerException(BrokerErrorCode.unsupported, 'The simulator is paper-only');
    }
    return f(ctx);
  }

  /// Registry with every built-in adapter.
  factory BrokerRegistry.standard() {
    final r = BrokerRegistry();
    r.register(
      BrokerKind.simulator,
      (c) => SimulatorBroker(market: c.market, startingCashCents: c.startingCashCents, clock: c.clock),
    );
    r.register(
      BrokerKind.alpaca,
      (c) => AlpacaAdapter(
          accountId: c.accountId, credentials: c.credentials, http: c.requireHttp, mode: c.mode,
          liveApproval: c.liveApproval, clock: c.clock),
    );
    r.register(
      BrokerKind.tradestation,
      (c) => TradeStationAdapter(
          accountId: c.accountId, credentials: c.credentials, http: c.requireHttp, mode: c.mode,
          liveApproval: c.liveApproval, clock: c.clock),
    );
    r.register(
      BrokerKind.ibkr,
      (c) => IbkrAdapter(
          accountId: c.accountId, credentials: c.credentials, http: c.requireHttp, mode: c.mode,
          liveApproval: c.liveApproval, clock: c.clock),
    );
    return r;
  }
}
