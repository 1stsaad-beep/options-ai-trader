/// Versioned boundary for server-owned synthetic research. These models grant
/// no execution authority; unsupported versions and mismatched identities fail.
class ResearchContract {
  static const int schemaVersion = 1;

  static Map<String, dynamic> object(dynamic value) {
    if (value is! Map || value.keys.any((key) => key is! String)) {
      throw const FormatException('Research object required');
    }
    return Map<String, dynamic>.from(value);
  }

  static String text(dynamic value) {
    if (value is! String || value.trim().isEmpty) {
      throw const FormatException('Research identifier required');
    }
    return value;
  }

  static DateTime timestamp(dynamic value) {
    final stamp = text(value);
    if (!RegExp(r'(Z|[+-]\d{2}:\d{2})$').hasMatch(stamp)) {
      throw const FormatException('Aware research timestamp required');
    }
    final parsed = DateTime.tryParse(stamp);
    if (parsed == null) throw const FormatException('Invalid timestamp');
    return parsed.toUtc();
  }

  static List<String> strings(dynamic value) {
    if (value is! List || value.any((item) => item is! String)) {
      throw const FormatException('Research text list required');
    }
    return List<String>.unmodifiable(value.cast<String>());
  }

  static Map<String, dynamic> envelope(
    dynamic value,
    String accountId,
    String symbol,
  ) {
    final data = object(value);
    if (data['schema_version'] is! int ||
        data['schema_version'] != schemaVersion ||
        data['account_id'] != accountId ||
        data['symbol'] != symbol ||
        data['mode'] != 'SHADOW' ||
        data['source'] != 'synthetic_fixture' ||
        data['execution_authority'] != false ||
        data['external_connections'] != false ||
        data['profitability_evidence'] != false) {
      throw const FormatException('Unsupported research identity or authority');
    }
    return data;
  }
}

class ResearchWorkbench {
  final Map<String, dynamic> data;
  final String accountId;
  final String symbol;
  final DateTime asOf;
  final Map<String, dynamic> modules;
  final Map<String, dynamic> decision;
  final List<String> limitations;

  ResearchWorkbench._(this.data, this.accountId, this.symbol, this.asOf,
      this.modules, this.decision, this.limitations);

  factory ResearchWorkbench.parse(dynamic value, String accountId, String symbol) {
    final data = ResearchContract.envelope(value, accountId, symbol);
    final asOf = ResearchContract.timestamp(data['as_of']);
    final observed = ResearchContract.timestamp(data['observed_at']);
    final contract = ResearchContract.object(data['contract']);
    final decision = ResearchContract.object(data['decision']);
    final decided = ResearchContract.timestamp(decision['decided_at']);
    final decisionObserved = ResearchContract.timestamp(decision['observed_at']);
    final reasons = ResearchContract.strings(decision['reasons']);
    ResearchContract.text(decision['decision_id']);
    ResearchContract.text(decision['digest']);
    ResearchContract.text(decision['evidence_json']);
    ResearchContract.text(contract['contract_id']);
    if (contract['symbol'] != symbol ||
        !['CALL', 'PUT'].contains(contract['right']) ||
        decision['account_id'] != accountId ||
        decision['contract_id'] != contract['contract_id'] ||
        observed.isAfter(asOf) || decisionObserved.isAfter(decided) ||
        decided.isAfter(asOf) || reasons.isEmpty ||
        reasons.any((reason) => reason.trim().isEmpty)) {
      throw const FormatException('Research decision identity or timing mismatch');
    }
    return ResearchWorkbench._(
      Map<String, dynamic>.unmodifiable(data), accountId, symbol, asOf,
      Map<String, dynamic>.unmodifiable(ResearchContract.object(data['modules'])),
      Map<String, dynamic>.unmodifiable(decision),
      ResearchContract.strings(data['limitations']),
    );
  }
}

class ResearchSnapshot {
  final String snapshotId;
  final ResearchWorkbench workbench;
  ResearchSnapshot._(this.snapshotId, this.workbench);

  factory ResearchSnapshot.parse(dynamic value, String accountId, String symbol) {
    final data = ResearchContract.envelope(value, accountId, symbol);
    return ResearchSnapshot._(ResearchContract.text(data['snapshot_id']),
      ResearchWorkbench.parse(data['workbench'], accountId, symbol));
  }
}

class ResearchSnapshotSummary {
  final String snapshotId;
  final DateTime asOf;
  final String decisionId;
  final String digest;
  ResearchSnapshotSummary._(this.snapshotId, this.asOf, this.decisionId, this.digest);

  factory ResearchSnapshotSummary.parse(dynamic value, String accountId, String symbol) {
    final data = ResearchContract.object(value);
    if (data['account_id'] != accountId || data['symbol'] != symbol) {
      throw const FormatException('Snapshot list identity mismatch');
    }
    final asOf = ResearchContract.timestamp(data['as_of']);
    if (ResearchContract.timestamp(data['decided_at']).isAfter(asOf)) {
      throw const FormatException('Snapshot list timestamp mismatch');
    }
    return ResearchSnapshotSummary._(ResearchContract.text(data['snapshot_id']),
      asOf, ResearchContract.text(data['decision_id']),
      ResearchContract.text(data['digest']));
  }
}

class ResearchSnapshotList {
  final List<ResearchSnapshotSummary> items;
  final bool truncated;
  ResearchSnapshotList._(this.items, this.truncated);

  factory ResearchSnapshotList.parse(dynamic value, String accountId, String symbol) {
    final data = ResearchContract.envelope(value, accountId, symbol);
    if (data['items'] is! List || data['truncated'] is! bool) {
      throw const FormatException('Snapshot list required');
    }
    final items = (data['items'] as List).map((item) =>
      ResearchSnapshotSummary.parse(item, accountId, symbol)).toList();
    if (items.map((item) => item.snapshotId).toSet().length != items.length) {
      throw const FormatException('Duplicate snapshot identifiers');
    }
    return ResearchSnapshotList._(List.unmodifiable(items), data['truncated']);
  }
}

class ResearchReplay {
  final String snapshotId;
  final ResearchWorkbench original;
  final Map<String, dynamic> counterfactual;
  bool get hasOutcome => counterfactual['status'] == 'REPLAYED';
  ResearchReplay._(this.snapshotId, this.original, this.counterfactual);

  factory ResearchReplay.parse(dynamic value, String accountId, String symbol,
      String snapshotId) {
    final data = ResearchContract.envelope(value, accountId, symbol);
    final original = ResearchWorkbench.parse(data['original_workbench'], accountId, symbol);
    final decision = ResearchContract.object(data['original_decision']);
    final outcome = ResearchContract.object(data['counterfactual']);
    final reasons = ResearchContract.strings(outcome['decision_reasons']);
    final originalReasons = ResearchContract.strings(original.decision['reasons']);
    final asOf = ResearchContract.timestamp(data['as_of']);
    final outcomeAsOf = ResearchContract.timestamp(data['outcome_as_of']);
    if (data['snapshot_id'] != snapshotId || asOf != original.asOf ||
        outcomeAsOf.isBefore(original.asOf) ||
        decision['account_id'] != accountId ||
        decision['decision_id'] != original.decision['decision_id'] ||
        decision['contract_id'] != original.decision['contract_id'] ||
        decision['digest'] != original.decision['digest'] ||
        outcome['decision_digest'] != original.decision['digest'] ||
        outcome['mode'] != 'SHADOW' || outcome['counterfactual'] != true ||
        outcome['execution_authority'] != false ||
        outcome['profitability_evidence'] != false ||
        reasons.length != originalReasons.length ||
        List.generate(reasons.length, (i) => reasons[i] != originalReasons[i]).contains(true)) {
      throw const FormatException('Replay does not match original saved evidence');
    }
    if (outcome['status'] == 'INSUFFICIENT_OBSERVED_OUTCOME') {
      if (outcome['pnl'] != null) {
        throw const FormatException('Unavailable outcomes cannot report profit');
      }
    } else if (outcome['status'] == 'REPLAYED') {
      final entry = ResearchContract.timestamp(outcome['entry_at']);
      final exit = ResearchContract.timestamp(outcome['exit_at']);
      if (outcome['pnl'] is! num || !(outcome['pnl'] as num).isFinite ||
          outcome['commissions'] is! num || !(outcome['commissions'] as num).isFinite ||
          (outcome['commissions'] as num) < 0 ||
          !entry.isAfter(ResearchContract.timestamp(original.decision['decided_at'])) ||
          !exit.isAfter(entry) || exit.isAfter(outcomeAsOf)) {
        throw const FormatException('Invalid observed replay outcome');
      }
    } else {
      throw const FormatException('Unsupported replay outcome');
    }
    return ResearchReplay._(snapshotId, original, Map.unmodifiable(outcome));
  }
}
