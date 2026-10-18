/// The only gate between the engine and real-money orders.
///
/// Two independent conditions must BOTH hold before any live order is sent:
///
/// 1. The build was compiled with `--dart-define=OAT_ENABLE_LIVE=true`.
///    Default builds (including every build produced so far) compile this to
///    `false`, which makes live trading impossible regardless of settings.
/// 2. The account carries a [LiveApproval] the user created explicitly in the
///    app after the paper-readiness checklist passed.
///
/// Do not add bypasses. Changing this file needs explicit user approval.
library;

import '../models.dart';
import 'broker_adapter.dart';

class LiveApproval {
  final String accountId;
  final DateTime approvedAt;

  /// The exact acknowledgement sentence the user typed.
  final String acknowledgement;

  const LiveApproval({required this.accountId, required this.approvedAt, required this.acknowledgement});

  static const requiredAcknowledgement = 'أوافق على التداول بأموال حقيقية وأتحمل المخاطر';

  bool get isValid => acknowledgement.trim() == requiredAcknowledgement;

  Map<String, dynamic> toJson() =>
      {'accountId': accountId, 'approvedAt': approvedAt.toIso8601String(), 'acknowledgement': acknowledgement};

  factory LiveApproval.fromJson(Map<String, dynamic> j) => LiveApproval(
        accountId: j['accountId'] as String,
        approvedAt: DateTime.parse(j['approvedAt'] as String),
        acknowledgement: j['acknowledgement'] as String,
      );
}

class LiveTradingGuard {
  static const bool buildAllowsLive = bool.fromEnvironment('OAT_ENABLE_LIVE', defaultValue: false);

  /// Throws unless [mode] is paper, or live is fully authorised for [accountId].
  static void ensureAllowed({required TradingMode mode, required String accountId, LiveApproval? approval}) {
    if (mode == TradingMode.paper) return;
    if (!buildAllowsLive) {
      throw const BrokerException(BrokerErrorCode.liveLocked, 'Live trading is disabled in this build');
    }
    if (approval == null || approval.accountId != accountId || !approval.isValid) {
      throw const BrokerException(BrokerErrorCode.liveLocked, 'Live trading needs explicit user approval');
    }
  }
}
