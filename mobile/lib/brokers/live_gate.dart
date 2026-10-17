/// Live trading lock for every broker adapter.
///
/// Live is hard-disabled. The only approval switch is a compile-time define
/// (`--dart-define=OAT_LIVE_TRADING_APPROVED=true`) that defaults to false, and
/// even when it is set this batch ships no Live endpoint: [requirePaper] still
/// rejects Live so nothing can reach a real-money host by configuration alone.
library;

import 'broker_models.dart';

class LiveTradingDisabled implements Exception {
  final String message;
  const LiveTradingDisabled([this.message = 'LIVE_DISABLED']);
  @override
  String toString() => 'LiveTradingDisabled: $message';
}

class LiveTradingGate {
  const LiveTradingGate._();

  /// Explicit approval flag. Defaults off; never read from storage or network.
  static const bool buildApproved =
      bool.fromEnvironment('OAT_LIVE_TRADING_APPROVED', defaultValue: false);

  /// No Live adapter is implemented, regardless of [buildApproved].
  static const bool liveImplemented = false;

  static bool get liveAvailable => buildApproved && liveImplemented;

  /// Throws unless [environment] is Paper. Every adapter calls this before I/O.
  static void requirePaper(BrokerEnvironment environment) {
    if (environment == BrokerEnvironment.paper) return;
    if (!buildApproved) throw const LiveTradingDisabled('LIVE_NOT_APPROVED');
    throw const LiveTradingDisabled('LIVE_NOT_IMPLEMENTED');
  }
}
