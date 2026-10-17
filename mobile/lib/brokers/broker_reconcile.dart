/// Reconciles the append-only order journal with broker order status, fills and positions.
///
/// Only new events are appended (STATUS / FILL / RESOLVED); existing events are
/// never rewritten. A broker-reported filled quantity that goes backwards, exceeds
/// the ordered quantity or changes broker identity is recorded as a discrepancy and
/// the order stays unchanged. Position differences are reported, not "fixed".
library;

import 'broker_adapter.dart';
import 'broker_models.dart';
import 'broker_options.dart';
import 'broker_order_journal.dart';

class ReconcileResult {
  final int checked, updated, fills;
  final List<String> discrepancies; // codes with order/contract context, no secrets
  final List<String> stillUnresolved; // client order ids
  const ReconcileResult(this.checked, this.updated, this.fills, this.discrepancies, this.stillUnresolved);
}

class BrokerReconciler {
  static const notPlacedAfter = Duration(seconds: 60);
  final BrokerOrderJournal journal;
  final DateTime Function() now;
  BrokerReconciler(this.journal, {DateTime Function()? clock}) : now = clock ?? DateTime.now;

  Future<ReconcileResult> run(BrokerAccount account, BrokerAdapter adapter, {List<BrokerPosition>? positions}) async {
    var checked = 0, updated = 0, fills = 0;
    final discrepancies = <String>[], unresolved = <String>[];
    final orders = await journal.orders();
    final linked = orders.map((o) => o.brokerOrderId).whereType<String>().toSet();
    for (final o in orders.where((o) => !o.terminal)) {
      checked++;
      final c = OccContract.parse(o.contract);
      final BrokerOrderLookup lookup;
      try {
        lookup = await adapter.orderStatus(clientOrderId: o.clientOrderId, brokerOrderId: o.brokerOrderId, match: {
          'symbol': c?.symbolFor(account.broker), 'buy': o.side == 'BUY_TO_OPEN', 'quantity': o.quantity,
          'limitCents': o.intent['limitCents'], 'linkedIds': linked,
        });
      } on BrokerException catch (e) {
        discrepancies.add('${o.clientOrderId}:LOOKUP_${e.code}');
        if (o.unresolved) unresolved.add(o.clientOrderId);
        continue;
      }
      final s = lookup.status;
      if (s == null) {
        final intentAt = DateTime.tryParse('${o.intent['at']}');
        final oldEnough = intentAt != null && now().difference(intentAt) >= notPlacedAfter;
        if (o.unresolved && lookup.definitiveNotFound && oldEnough) {
          await journal.append(o.clientOrderId, 'RESOLVED', {'state': OrderState.notPlaced,
              'basis': 'BROKER_CLIENT_ID_NOT_FOUND'});
          updated++;
        } else {
          if (o.brokerOrderId != null) discrepancies.add('${o.clientOrderId}:BROKER_ORDER_NOT_FOUND');
          if (o.unresolved) unresolved.add(o.clientOrderId);
        }
        continue;
      }
      if (o.brokerOrderId != null && s.brokerOrderId != o.brokerOrderId) {
        discrepancies.add('${o.clientOrderId}:ORDER_IDENTITY_MISMATCH');
        if (o.unresolved) unresolved.add(o.clientOrderId);
        continue;
      }
      if (s.filledQuantity < o.filledQuantity || s.filledQuantity > o.quantity) {
        discrepancies.add('${o.clientOrderId}:FILL_QUANTITY_INCONSISTENT');
        continue;
      }
      var state = s.state;
      if (state == OrderState.filled && s.filledQuantity != o.quantity) state = OrderState.partiallyFilled;
      if (state == OrderState.open && s.filledQuantity > 0) state = OrderState.partiallyFilled;
      final changed = state != o.state || s.filledQuantity != o.filledQuantity || o.brokerOrderId == null;
      if (!changed) continue;
      if (s.filledQuantity > o.filledQuantity) {
        await journal.append(o.clientOrderId, 'FILL', {'state': state, 'brokerOrderId': s.brokerOrderId,
            'fillQuantity': s.filledQuantity - o.filledQuantity, 'filledQuantity': s.filledQuantity,
            'averageFillPrice': s.averageFillPrice, 'brokerStatus': s.rawStatus});
        fills++;
      } else {
        await journal.append(o.clientOrderId, 'STATUS', {'state': state, 'brokerOrderId': s.brokerOrderId,
            'filledQuantity': s.filledQuantity, 'brokerStatus': s.rawStatus});
      }
      linked.add(s.brokerOrderId);
      updated++;
    }
    if (positions != null) discrepancies.addAll(positionDiscrepancies(account.broker, await journal.orders(), positions));
    return ReconcileResult(checked, updated, fills, List.unmodifiable(discrepancies), List.unmodifiable(unresolved));
  }

  /// Explicit, logged user decision for an unresolved order after checking the broker app.
  Future<void> resolveManually(String clientOrderId, {required String note}) async {
    final o = (await journal.orders()).where((x) => x.clientOrderId == clientOrderId).toList();
    if (o.length != 1 || !o.first.unresolved) throw const BrokerJournalException('NOT_UNRESOLVED');
    final text = note.trim();
    await journal.append(clientOrderId, 'RESOLVED', {'state': OrderState.userResolvedNotPlaced,
        'basis': 'USER_CHECKED_BROKER', 'note': text.length > 200 ? text.substring(0, 200) : text});
  }
}

/// Contracts traded through this journal whose broker long quantity is below the
/// journal's net filled quantity. Extra broker holdings from outside the app are not flagged.
List<String> positionDiscrepancies(BrokerKind broker, List<BrokerOrderRecord> orders, List<BrokerPosition> positions) {
  final net = <String, int>{};
  for (final o in orders) {
    if (o.filledQuantity == 0) continue;
    net[o.contract] = (net[o.contract] ?? 0) + (o.side == 'BUY_TO_OPEN' ? o.filledQuantity : -o.filledQuantity);
  }
  final held = <String, int>{};
  for (final p in positions) {
    final occ = positionOcc(broker, p), q = decimalCents(p.quantity);
    if (occ != null && q != null) held[occ] = (held[occ] ?? 0) + q ~/ 100;
  }
  return [
    for (final e in net.entries)
      if (e.value > 0 && (held[e.key] ?? 0) < e.value) '${e.key}:POSITION_BELOW_JOURNAL(${held[e.key] ?? 0}<${e.value})'
  ];
}
