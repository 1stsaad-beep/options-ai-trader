/// Append-only per-account journal of Paper order intents and broker outcomes.
///
/// Events are never edited or removed; the current state of an order is the fold
/// of its events. An intent is persisted (and read back) before any network
/// send. Uncertain sends are recorded as UNKNOWN and block new orders on that
/// account until reconciled. When the bounded journal is full, new orders are
/// refused rather than dropping history. Storage is segmented (v2) since B12.
library;

import 'dart:convert';
import 'dart:math' as math;

import 'package:crypto/crypto.dart';

import 'broker_store.dart';

class OrderState {
  static const intent = 'INTENT', sent = 'SENT', unknown = 'UNKNOWN', rejected = 'REJECTED',
      notPlaced = 'NOT_PLACED', confirmationRequired = 'CONFIRMATION_REQUIRED';
  // Broker-side states (set by acknowledgement / reconciliation)
  static const open = 'OPEN', partiallyFilled = 'PARTIALLY_FILLED', filled = 'FILLED',
      canceled = 'CANCELED', expired = 'EXPIRED';
  /// Explicit user decision after checking the broker's own app; recorded, never inferred.
  static const userResolvedNotPlaced = 'USER_RESOLVED_NOT_PLACED';
  static const terminal = {rejected, notPlaced, confirmationRequired, filled, canceled, expired, userResolvedNotPlaced};
  /// States that make the account's order truth uncertain.
  static const unresolved = {intent, unknown};
}

class BrokerOrderRecord {
  final String clientOrderId;
  final Map<String, dynamic> intent;
  final String state;
  final String? brokerOrderId;
  final int filledQuantity;
  final List<Map<String, dynamic>> events;
  const BrokerOrderRecord(this.clientOrderId, this.intent, this.state, this.brokerOrderId, this.filledQuantity, this.events);
  bool get terminal => OrderState.terminal.contains(state);
  bool get unresolved => OrderState.unresolved.contains(state);
  String get contract => intent['contract'] as String;
  String get side => intent['side'] as String; // BUY_TO_OPEN | SELL_TO_CLOSE
  int get quantity => intent['quantity'] as int;
  int get remaining => quantity - filledQuantity;
}

class BrokerJournalException implements Exception {
  final String code;
  const BrokerJournalException(this.code);
  @override
  String toString() => 'BrokerJournalException($code)';
}

class BrokerOrderJournal {
  /// B12: segmented storage. Appends rewrite only the last segment and the head,
  /// so capacity is no longer bound by one ever-growing secure-storage value.
  static const segmentSize = 250, maxEvents = 50000;
  /// Legacy single-value v1 journal (max 2000 events). Never deleted or modified.
  static String key(String accountId) => 'oat.brokers.orders.v1.$accountId';
  static String headKey(String accountId) => 'oat.brokers.orders.v2.$accountId.head';
  static String segmentKey(String accountId, int n) => 'oat.brokers.orders.v2.$accountId.seg.$n';
  final SecureKeyValue storage;
  final String accountId;
  final DateTime Function() now;
  BrokerOrderJournal(this.storage, this.accountId, {DateTime Function()? clock}) : now = clock ?? DateTime.now;

  Future<String?> _read(String k) async {
    try {
      return await storage.read(k);
    } catch (_) {
      throw const BrokerJournalException('JOURNAL_UNAVAILABLE');
    }
  }

  Future<void> _write(String k, String text) async {
    try {
      await storage.write(k, text);
      if (await storage.read(k) != text) throw const BrokerJournalException('JOURNAL_WRITE_UNCONFIRMED');
    } on BrokerJournalException {
      rethrow;
    } catch (_) {
      throw const BrokerJournalException('JOURNAL_WRITE_UNCONFIRMED');
    }
  }

  void _checkSeq(List<Map<String, dynamic>> list) {
    for (var i = 0; i < list.length; i++) {
      if (list[i]['seq'] != i + 1) throw const FormatException();
    }
  }

  Future<List<Map<String, dynamic>>> _legacy() async {
    final text = await _read(key(accountId));
    if (text == null) return [];
    try {
      final j = jsonDecode(text) as Map<String, dynamic>;
      if (j['version'] != 1 || j['account'] != accountId) throw const FormatException();
      final list = [for (final e in j['events'] as List) Map<String, dynamic>.from(e as Map)];
      _checkSeq(list);
      return list;
    } catch (_) {
      throw const BrokerJournalException('JOURNAL_CORRUPT');
    }
  }

  Future<Map<String, dynamic>?> _head() async {
    final text = await _read(headKey(accountId));
    if (text == null) return null;
    try {
      final h = jsonDecode(text) as Map<String, dynamic>;
      final count = h['count'], segments = h['segments'];
      if (h['version'] != 2 || h['account'] != accountId || count is! int || segments is! int || count < 0 ||
          segments != (count + segmentSize - 1) ~/ segmentSize) {
        throw const FormatException();
      }
      return h;
    } catch (_) {
      throw const BrokerJournalException('JOURNAL_CORRUPT');
    }
  }

  /// Storage facts for the UI/report (no event content).
  Future<Map<String, Object?>> stats() async {
    final h = await _head();
    return {'format': h == null ? 'v1' : 'v2-segmented', 'events': h?['count'] ?? (await _legacy()).length,
      'segments': h?['segments'] ?? 0, 'maxEvents': maxEvents, 'migratedFrom': h?['migratedFrom']};
  }

  Future<List<Map<String, dynamic>>> events() async {
    final h = await _head();
    if (h == null) return _legacy();
    final count = h['count'] as int, out = <Map<String, dynamic>>[];
    try {
      for (var n = 0; n < (h['segments'] as int); n++) {
        final text = await _read(segmentKey(accountId, n));
        if (text == null) throw const FormatException();
        final seg = jsonDecode(text) as Map<String, dynamic>;
        if (seg['version'] != 2 || seg['account'] != accountId || seg['segment'] != n) throw const FormatException();
        out.addAll([for (final e in seg['events'] as List) Map<String, dynamic>.from(e as Map)]);
      }
      // A segment may hold one event beyond the head if a crash hit between the two
      // writes; that append never returned, so it is not part of the journal.
      if (out.length < count) throw const FormatException();
      final list = out.sublist(0, count);
      _checkSeq(list);
      return list;
    } on BrokerJournalException {
      rethrow;
    } catch (_) {
      throw const BrokerJournalException('JOURNAL_CORRUPT');
    }
  }

  String _segment(int n, List<Map<String, dynamic>> events) =>
      jsonEncode({'version': 2, 'account': accountId, 'segment': n, 'events': events});

  /// Appends one event after re-reading the current journal; verified by read-back.
  /// The first append on a v1 journal copies it into segments (v1 value kept as-is).
  Future<Map<String, dynamic>> append(String clientOrderId, String type, Map<String, dynamic> data) async {
    final head = await _head();
    final list = await events();
    if (list.length >= maxEvents) throw const BrokerJournalException('JOURNAL_FULL');
    final event = <String, dynamic>{'seq': list.length + 1, 'at': now().toUtc().toIso8601String(),
        'clientOrderId': clientOrderId, 'type': type, ...data};
    final all = [...list, event];
    Object? migratedFrom = head?['migratedFrom'];
    if (head == null) {
      // Migration (or first use): write every segment, then the head.
      final legacyText = await _read(key(accountId));
      migratedFrom = legacyText == null ? null : {'format': 'v1', 'events': list.length,
        'sha256': sha256.convert(utf8.encode(legacyText)).toString(), 'at': now().toUtc().toIso8601String()};
      for (var n = 0; n * segmentSize < all.length; n++) {
        await _write(segmentKey(accountId, n), _segment(n, all.sublist(n * segmentSize, math.min(all.length, (n + 1) * segmentSize))));
      }
    } else {
      final n = list.length ~/ segmentSize;
      await _write(segmentKey(accountId, n), _segment(n, all.sublist(n * segmentSize)));
    }
    await _write(headKey(accountId), jsonEncode({'version': 2, 'account': accountId, 'count': all.length,
      'segments': (all.length + segmentSize - 1) ~/ segmentSize, 'segmentSize': segmentSize,
      if (migratedFrom != null) 'migratedFrom': migratedFrom}));
    return event;
  }

  Future<List<BrokerOrderRecord>> orders() async => fold(await events());

  static List<BrokerOrderRecord> fold(List<Map<String, dynamic>> events) {
    final order = <String>[];
    final byId = <String, List<Map<String, dynamic>>>{};
    for (final e in events) {
      final id = e['clientOrderId'] as String;
      if (!byId.containsKey(id)) order.add(id);
      byId.putIfAbsent(id, () => []).add(e);
    }
    return [
      for (final id in order)
        () {
          final evs = byId[id]!;
          final intent = evs.firstWhere((e) => e['type'] == 'INTENT', orElse: () => const {});
          var state = OrderState.intent;
          String? brokerId;
          var filled = 0;
          for (final e in evs) {
            if (e['state'] is String) state = e['state'] as String;
            if (e['brokerOrderId'] is String) brokerId = e['brokerOrderId'] as String;
            if (e['filledQuantity'] is int) filled = e['filledQuantity'] as int;
          }
          return BrokerOrderRecord(id, Map<String, dynamic>.from(intent), state, brokerId, filled, List.unmodifiable(evs));
        }()
    ];
  }
}
