/// Protective-exit monitoring for Broker Paper positions (B10).
///
/// Uses the shared rule in `protective_exit.dart` on whole-position values reported
/// by the broker: basis = market value - unrealized P/L, value = market value. The
/// peak is tracked per position lot (contract + quantity + basis) and only grows;
/// a changed lot starts a new peak record (old records stay, bounded). Nothing is sent
/// automatically: a hit only proposes a close ticket that still needs review + confirm.
library;

import 'dart:convert';

import '../protective_exit.dart';
import 'broker_models.dart';
import 'broker_options.dart';
import 'broker_store.dart';

class ProtectivePolicy {
  final int stopPercent, takePercent, trailPercent;
  // Same defaults as Market Paper (stop 20, take 40, trail 15).
  const ProtectivePolicy({this.stopPercent = 20, this.takePercent = 40, this.trailPercent = 15});
  bool get valid => [stopPercent, takePercent].every((p) => p >= 1 && p <= 95) && trailPercent >= 0 && trailPercent <= 95;
  Map<String, Object> toJson() => {'stopPercent': stopPercent, 'takePercent': takePercent, 'trailPercent': trailPercent};
  static ProtectivePolicy fromJson(Object? j) {
    if (j is! Map) return const ProtectivePolicy();
    final p = ProtectivePolicy(stopPercent: j['stopPercent'] as int, takePercent: j['takePercent'] as int,
        trailPercent: j['trailPercent'] as int);
    if (!p.valid) throw const FormatException();
    return p;
  }
}

class ProtectiveStatus {
  final String contract, lot;
  final int basisCents, valueCents, peakCents;
  final String? exit; // STOP_LOSS / TAKE_PROFIT / TRAILING_STOP / null
  const ProtectiveStatus(this.contract, this.lot, this.basisCents, this.valueCents, this.peakCents, this.exit);
}

class BrokerProtectiveTracker {
  static const maxLots = 500;
  static String key(String accountId) => 'oat.brokers.protective.v1.$accountId';
  final SecureKeyValue storage;
  final String accountId;
  final DateTime Function() now;
  BrokerProtectiveTracker(this.storage, this.accountId, {DateTime Function()? clock}) : now = clock ?? DateTime.now;

  Future<Map<String, dynamic>> _load() async {
    final text = await storage.read(key(accountId));
    if (text == null) return {'version': 1, 'account': accountId, 'policy': const ProtectivePolicy().toJson(), 'lots': <String, dynamic>{}};
    final j = jsonDecode(text) as Map<String, dynamic>;
    if (j['version'] != 1 || j['account'] != accountId || j['lots'] is! Map) throw const FormatException('PROTECTIVE_STATE_CORRUPT');
    ProtectivePolicy.fromJson(j['policy']);
    return j;
  }

  Future<ProtectivePolicy> policy() async => ProtectivePolicy.fromJson((await _load())['policy']);

  Future<void> setPolicy(ProtectivePolicy p) async {
    if (!p.valid) throw const FormatException('INVALID_POLICY');
    final j = await _load();
    j['policy'] = p.toJson();
    await storage.write(key(accountId), jsonEncode(j));
  }

  /// Updates peaks with the current observation (before evaluating) and returns statuses
  /// for long option positions with usable values.
  Future<List<ProtectiveStatus>> observe(BrokerKind broker, List<BrokerPosition> positions) async {
    final j = await _load();
    final p = ProtectivePolicy.fromJson(j['policy']);
    final lots = Map<String, dynamic>.from(j['lots'] as Map);
    final out = <ProtectiveStatus>[];
    for (final pos in positions) {
      final occ = positionOcc(broker, pos), q = decimalCents(pos.quantity);
      final value = decimalCents(pos.marketValue), pl = decimalCents(pos.unrealizedPl);
      if (occ == null || q == null || q <= 0 || value == null || pl == null) continue;
      final basis = value - pl;
      if (basis <= 0) continue;
      final lot = '$occ/${q ~/ 100}/$basis';
      final prior = lots[lot] is Map ? (lots[lot] as Map)['peakCents'] as int : value;
      final peak = prior > value ? prior : value;
      lots[lot] = {'contract': occ, 'peakCents': peak, 'basisCents': basis, 'at': now().toUtc().toIso8601String(),
        if (lots[lot] is Map) 'firstAt': (lots[lot] as Map)['firstAt'] else 'firstAt': now().toUtc().toIso8601String()};
      out.add(ProtectiveStatus(occ, lot, basis, value, peak, protectiveExitCents(basis: basis, value: value, peak: peak,
          stopPercent: p.stopPercent, takePercent: p.takePercent, trailPercent: p.trailPercent)));
    }
    // Bounded: drop the oldest closed-lot records only beyond the cap.
    if (lots.length > maxLots) {
      final open = out.map((s) => s.lot).toSet();
      final old = lots.entries.where((e) => !open.contains(e.key)).toList()
        ..sort((a, b) => '${(a.value as Map)['at']}'.compareTo('${(b.value as Map)['at']}'));
      for (final e in old.take(lots.length - maxLots)) {
        lots.remove(e.key);
      }
    }
    j['lots'] = lots;
    await storage.write(key(accountId), jsonEncode(j));
    return out;
  }
}
