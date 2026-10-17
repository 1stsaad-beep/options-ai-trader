library;

import 'package:http/http.dart' as http;

import 'alpaca_paper.dart';
import 'broker_options.dart';
import 'broker_models.dart';
import 'ibkr_paper.dart';
import 'live_gate.dart';
import 'tradestation_sim.dart';

/// Paper-only broker contract. No adapter exposes a Live endpoint.
abstract class BrokerAdapter {
  BrokerKind get kind;

  /// Authenticates against the Paper/SIM environment and returns a balance snapshot.
  Future<BrokerAccountSnapshot> connect();
  Future<List<BrokerPosition>> positions();

  /// Limit-only paper order to the paper environment. Callers must use
  /// [BrokerOrderService] so admission, journal and confirmation apply.
  Future<BrokerOrderAck> submitPaperOrder(PaperOrderRequest order);

  /// Option quote from the broker's own Paper host, or null when this broker
  /// has none there (Alpaca: use the existing Direct OPRA session instead).
  Future<BrokerQuote?> optionQuote(OccContract contract, {String? conid});
}

typedef TokenRotated = Future<void> Function(String newRefreshToken);

BrokerAdapter createPaperAdapter(BrokerAccount account, BrokerCredentials credentials,
    {http.Client? client, TokenRotated? onRefreshTokenRotated, DateTime Function()? clock}) {
  LiveTradingGate.requirePaper(account.environment);
  if (account.archived) throw const BrokerException('ACCOUNT_ARCHIVED');
  final c = client ?? http.Client();
  switch (account.broker) {
    case BrokerKind.alpaca:
      return AlpacaPaperAdapter(credentials, client: c);
    case BrokerKind.ibkr:
      return IbkrPaperAdapter(account.settings, client: c);
    case BrokerKind.tradestation:
      return TradeStationSimAdapter(credentials, account.settings,
          client: c, onRefreshTokenRotated: onRefreshTokenRotated, clock: clock);
  }
}
