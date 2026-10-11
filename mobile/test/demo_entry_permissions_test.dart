import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:options_ai_trader/demo/engine.dart';

// Real offline engine/ledger execution; no mocked fills, signals or risk gates.
void main() {
  late DemoEngine engine;
  late DemoRow account;
  late String id;
  final rejected = throwsA(isA<DemoRejected>());

  setUp(() {
    engine = DemoEngine();
    account = engine.createAccount('إذن التنفيذ', 2000000);
    id = account['id'] as String;
  });

  void step([int count = 1]) {
    for (var i = 0; i < count; i++) {
      engine.step(enter: false);
      engine.validate();
    }
  }

  DemoRow automatedEntry(String symbol) {
    for (final other in List<String>.from((account['watch'] as Map).keys)) {
      engine.watch(id, other, enabled: other == symbol);
    }
    engine.configure(id, {'automation': true, 'quantity': 2, 'entry_method': 'early'});
    engine.step();
    return engine.rows(account, 'orders').single;
  }

  DemoRow automaticReversal(String symbol, String target) {
    engine.submit(id, engine.contract(symbol, target == 'CALL' ? 'PUT' : 'CALL'),
      'BUY', 1, 'initial-owned');
    step();
    engine.configure(id, {'automation': true, 'reversal_enabled': true,
      'quantity': 2, 'entry_method': 'early'});
    return engine.requestReversal(id, symbol, target, 'auto-reverse-test', automatic: true);
  }

  for (final direction in {'NVDA': 'CALL', 'AAPL': 'PUT'}.entries) {
    test('${direction.value} pending automatic entry stops when automation is disabled', () {
      final order = automatedEntry(direction.key);
      expect(order['right'], direction.value);
      final original = order['decision_json'];
      engine.configure(id, {'automation': false});
      step();
      expect(order['filled'], 0);
      expect(engine.rows(account, 'positions'), isEmpty);
      expect(order['decision_json'], original);
    });

    test('${direction.value} pending partial entry rechecks original strategy after restart', () {
      final order = automatedEntry(direction.key);
      step();
      expect(order['filled'], 1);
      final original = order['decision_json'] as String;
      final strategy = jsonDecode(original)['entry_authorization']['strategy'];
      engine = DemoEngine.decode(engine.encode());
      account = engine.account(id);
      engine.configure(id, {'strategies': ['breakout', 'pullback'].where((s) => s != strategy).toList()});
      final saved = engine.order(id, order['id'] as String);
      final beforeCash = account['cash'];
      step();
      expect(saved['filled'], 1);
      expect(account['cash'], beforeCash);
      expect(engine.rows(account, 'positions').single['quantity'], 1);
      expect(saved['decision_json'], original);
    });

    for (final setting in ['automation', 'reversal_enabled']) {
      test('${direction.value} reversal close completes but $setting blocks new entry', () {
        final reversal = automaticReversal(direction.key, direction.value);
        engine.configure(id, {setting: false});
        step();
        expect(engine.rows(account, 'positions'), isEmpty);
        expect(reversal['state'], 'BLOCKED');
        expect(reversal['entry_order'], isNull);
        expect(engine.rows(account, 'orders').last['status'], 'FILLED');
      });

      test('${direction.value} partial reversal rechecks $setting before next fill', () {
        final reversal = automaticReversal(direction.key, direction.value);
        step();
        expect(reversal['state'], 'ENTERING');
        step();
        final order = engine.order(id, reversal['entry_order'] as String);
        expect(order['filled'], 1);
        engine.configure(id, {setting: false});
        step();
        expect(order['filled'], 1);
        expect(order['status'], 'CANCELLED');
        expect(reversal['state'], 'BLOCKED');
        expect(engine.rows(account, 'positions').single['right'], direction.value);
        expect(engine.rows(account, 'positions').single['quantity'], 1);
      });
    }
  }

  test('explicit manual entry and reversal remain available without automation opt-in', () {
    engine.configure(id, {'strategies': []});
    final manual = engine.submit(id, engine.contract('NVDA', 'PUT'), 'BUY', 1, 'manual');
    step();
    expect(manual['status'], 'FILLED');
    engine.configure(id, {'strategies': ['breakout', 'pullback'], 'entry_method': 'early'});
    final reversal = engine.requestReversal(id, 'NVDA', 'CALL', 'auto-reverse-looking-manual');
    step(2);
    expect(reversal['state'], 'COMPLETED');
    expect(engine.risk(account)['automation'], false);
    expect(engine.risk(account)['reversal_enabled'], false);
    expect(engine.rows(account, 'positions').single['right'], 'CALL');
  });

  test('filled receipt and duplicate submission remain idempotent after disable', () {
    final order = automatedEntry('NVDA');
    step(2);
    expect(order['status'], 'FILLED');
    engine.configure(id, {'automation': false, 'strategies': []});
    final before = engine.encode();
    engine.fill(id, order['id'] as String);
    final duplicate = engine.submit(id, order, 'BUY', 2, order['request_key'] as String,
      entryOrigin: 'automation');
    expect(identical(duplicate, order), true);
    expect(engine.encode(), before);
  });

  test('legacy automatic decision is gated without rewriting saved evidence', () {
    final order = automatedEntry('NVDA');
    final snapshot = jsonDecode(order['decision_json'] as String) as DemoRow;
    snapshot.remove('entry_authorization');
    order['decision_json'] = jsonEncode(snapshot); // Model the exact older persisted format.
    final original = order['decision_json'];
    engine = DemoEngine.decode(engine.encode());
    account = engine.account(id);
    engine.configure(id, {'automation': false});
    step();
    final restored = engine.order(id, order['id'] as String);
    expect(restored['filled'], 0);
    expect(restored['decision_json'], original);
  });

  test('legacy automatic reversal provenance blocks entry after disable', () {
    final reversal = automaticReversal('NVDA', 'CALL');
    step();
    final order = engine.order(id, reversal['entry_order'] as String);
    final snapshot = jsonDecode(order['decision_json'] as String) as DemoRow;
    snapshot.remove('entry_authorization');
    order['decision_json'] = jsonEncode(snapshot);
    reversal.remove('automatic');
    final original = order['decision_json'];
    engine = DemoEngine.decode(engine.encode());
    account = engine.account(id);
    engine.configure(id, {'reversal_enabled': false});
    step();
    final restored = engine.order(id, order['id'] as String);
    expect(restored['filled'], 0);
    expect(restored['status'], 'CANCELLED');
    expect(restored['decision_json'], original);
  });

  test('new automatic admission is rejected when automation is disabled', () {
    final signal = engine.opportunities(id).first;
    expect(() => engine.submit(id, engine.contract(signal['symbol'], signal['right']),
      'BUY', 1, 'unauthorized', reason: signal['strategy'], evidence: signal,
      entryOrigin: 'automation'), rejected);
    expect(engine.rows(account, 'orders'), isEmpty);
  });
}
