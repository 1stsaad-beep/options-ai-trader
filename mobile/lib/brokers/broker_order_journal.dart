/// Append-only per-account journal of Paper order intents and broker outcomes.
///
/// Events are never edited or removed; the current state of an order is the fold
/// of its events. An intent is persisted (and read back) before any network
/// send. Uncertain sends are recorded as UNKNOWN and block new orders on that
/// account until reconciled. When the bounded journal is full, new orders are
/// refused rather than dropping history.
library;

import 'dart:convert';

import 'broker_store.dart';

class OrderState {
  static const intent = 'INTENT', sent = 'SENT', unknown = 'UNKNOWN', rejected = 'REJECTED',
      notPlaced = 'NOT_PLACED', confirmationRequired = 'CONFIRMATION_REQUIRED';
  // Broker-side states (set by acknowledgement / reconciliation)
  static const open = 'OPEN', partiallyFilled = 'PARTIALLY_FILLED', filled = 'FILLED',
      canceled = 'CANCELED', expired = 'EXPIRED';
  static const terminal = {rejected, notPlaced, confirmationRequired, filled, canceled, expired};
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
  static const maxEvents = 2000;
  static String key(String accountId) => 'oat.brokers.orders.v1.$accountId';
  final SecureKeyValue storage;
  final String accountId;
  final DateTime Function() now;
  BrokerOrderJournal(this.storage, this.accountId, {DateTime Function()? clock}) : now = clock ?? DateTime.now;

  Future<List<Map<String, dynamic>>> events() async {
    final String? text;
    try {
      text = await storage.read(key(accountId));
    } catch (_) {
      throw const BrokerJournalException('JOURNAL_UNAVAILABLE');
    }
    if (text == null) return [];
    try {
      final j = jsonDecode(text) as Map<String, dynamic>;
      if (j['version'] != 1 || j['account'] != accountId) throw const FormatException();
      final list = [for (final e in j['events'] as List) Map<String, dynamic>.from(e as Map)];
      for (var i = 0; i < list.length; i++) {
        if (list[i]['seq'] != i + 1) throw const FormatException();
      }
      return list;
    } catch (_) {
      throw const BrokerJournalException('JOURNAL_CORRUPT');
    }
  }

  /// Appends one event after re-reading the current journal; verified by read-back.
  Future<Map<String, dynamic>> append(String clientOrderId, String type, Map<String, dynamic> data) async {
    final list = await events();
    if (list.length >= maxEvents) throw const BrokerJournalException('JOURNAL_FULL');
    final event = <String, dynamic>{'seq': list.length + 1, 'at': now().toUtc().toIso8601String(),
        'clientOrderId': clientOrderId, 'type': type, ...data};
    final text = jsonEncode({'version': 1, 'account': accountId, 'events': [...list, event]});
    try {
      await storage.write(key(accountId), text);
      if (await storage.read(key(accountId)) != text) throw const BrokerJournalException('JOURNAL_WRITE_UNCONFIRMED');
    } on BrokerJournalException {
      rethrow;
    } catch (_) {
      throw const BrokerJournalException('JOURNAL_WRITE_UNCONFIRMED');
    }
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
