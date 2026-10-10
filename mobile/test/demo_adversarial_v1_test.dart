import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:options_ai_trader/demo/chart_analysis.dart';
import 'package:options_ai_trader/demo/engine.dart';
import 'package:options_ai_trader/demo/store.dart';

// Independent regressions for lifecycle and saved-ledger review findings.
// All prices, accounts and receipts here belong to the offline synthetic demo.
void main() {
  late DemoEngine engine;
  late DemoRow account;
  late String id;
  final rejected = throwsA(isA<DemoRejected>());

  setUp(() {
    engine = DemoEngine();
    account = engine.createAccount('مراجعة مستقلة', 2000000);
    id = account['id'] as String;
  });

  void step([int count = 1]) {
    for (var i = 0; i < count; i++) {
      engine.step(enter: false);
      engine.validate();
    }
  }

  DemoRow buy([int quantity = 1]) => engine.submit(
    id, engine.contract('NVDA', 'CALL'), 'BUY', quantity, 'entry',
  );

  DemoRow saved() => jsonDecode(engine.encode()) as DemoRow;
  DemoRow firstAccount(DemoRow data) => (data['accounts'] as List).first as DemoRow;
  DemoRow firstOrder(DemoRow data) =>
      (firstAccount(data)['orders'] as List).first as DemoRow;
  void rejectsSaved(void Function(DemoRow) mutate) {
    final data = saved();
    mutate(data);
    expect(() => DemoEngine.decode(jsonEncode(data)), rejected);
  }

  test('cancelled stop exit can be replaced with a new bounded close', () {
    buy();
    step();
    engine.configure(id, {'automation': true});
    engine.scenario = 'drop';
    step();
    final firstClose = engine.rows(account, 'orders').last;
    expect(firstClose['reason'], 'وقف خسارة');
    engine.cancel(id, firstClose['id'] as String);
    step();
    final replacement = engine.rows(account, 'orders').last;
    expect(firstClose['status'], 'CANCELLED');
    expect(replacement['id'], isNot(firstClose['id']));
    expect(replacement['request_key'], isNot(firstClose['request_key']));
    expect(replacement['quantity'], 1);
    step();
    expect(engine.rows(account, 'positions'), isEmpty);
    expect(engine.rows(account, 'orders').length, 3);
    expect(engine.rows(account, 'trades').single['quantity'], 1);
  });

  test('partially filled cancelled exit closes only the remaining ownership', () {
    buy(3);
    step(3);
    engine.configure(id, {'automation': true});
    engine.scenario = 'drop';
    step(2);
    final partial = engine.rows(account, 'orders').last;
    expect(partial['status'], 'PARTIAL');
    expect(partial['filled'], 1);
    engine.cancel(id, partial['id'] as String);
    step();
    final replacement = engine.rows(account, 'orders').last;
    expect(replacement['quantity'], 2);
    expect(replacement['id'], isNot(partial['id']));
    step(2);
    expect(engine.rows(account, 'positions'), isEmpty);
    expect(engine.rows(account, 'trades').fold<int>(0, (n, t) => n + (t['quantity'] as int)), 3);
    expect(engine.rows(account, 'orders').fold<int>(0, (n, o) => n + (o['fees_paid'] as int)), 390);
    expect(account['cash'], account['initial'] + engine.realized(account));
  });

  test('unknown account never replaces or duplicates a pending automatic exit', () {
    buy();
    step();
    engine.configure(id, {'automation': true});
    engine.scenario = 'drop';
    step();
    final close = engine.rows(account, 'orders').last;
    engine.disconnect(id);
    step(4);
    expect(engine.rows(account, 'orders').length, 2);
    expect(close['filled'], 0);
    engine = DemoEngine.decode(engine.encode());
    account = engine.account(id);
    engine.reconcile(id);
    step();
    expect(engine.rows(account, 'positions'), isEmpty);
    expect(engine.rows(account, 'orders').length, 2);
  });

  test('session end overrides a staged take profit with full owned quantity', () {
    buy(2);
    step(2);
    engine.configure(id, {'automation': true, 'take_pct': 500, 'partial_take_pct': 20});
    engine.scenario = 'rally';
    engine.tick = 329; // 19:59 UTC in the explicitly synthetic session.
    step();
    final close = engine.rows(account, 'orders').last;
    expect(close['reason'], 'إغلاق الجلسة الاصطناعية');
    expect(close['quantity'], 2);
    step(2);
    expect(engine.rows(account, 'positions'), isEmpty);
  });

  test('zero-fill cancellation does not consume staged profit entitlement', () {
    buy(2);
    step(2);
    engine.configure(id, {'automation': true, 'take_pct': 500, 'partial_take_pct': 20});
    engine.scenario = 'rally';
    step();
    final cancelled = engine.rows(account, 'orders').last;
    expect(cancelled['reason'], 'جني ربح مرحلي');
    expect(engine.rows(account, 'positions').single['partial_taken'], false);
    engine.cancel(id, cancelled['id'] as String);
    step();
    final replacement = engine.rows(account, 'orders').last;
    expect(replacement['id'], isNot(cancelled['id']));
    expect(replacement['quantity'], 1);
    step();
    expect(engine.rows(account, 'positions').single['quantity'], 1);
    expect(engine.rows(account, 'positions').single['partial_taken'], true);
    step();
    expect(engine.rows(account, 'orders').length, 3);
  });

  for (final mutation in <String, void Function(DemoRow)>{
    'overstated filled quantity': (o) => o['fills'][0]['quantity'] = 2,
    'missing filled receipt': (o) => o['fills'] = <DemoRow>[],
    'wrong receipt fee': (o) => o['fills'][0]['fee'] = 0,
    'future receipt': (o) => o['fills'][0]['tick'] = 999,
    'non-object receipt': (o) => o['fills'] = ['untrusted'],
    'non-integer price': (o) => o['fills'][0]['price'] = 1.25,
  }.entries) {
    test('saved V1 ledger rejects ${mutation.key}', () {
      buy();
      step();
      rejectsSaved((data) => mutation.value(firstOrder(data)));
    });
  }

  test('saved position rejects malformed decision JSON and inconsistent high', () {
    buy();
    step();
    rejectsSaved((data) => firstAccount(data)['positions'][0]['entry_decisions'] = ['{invalid']);
    rejectsSaved((data) {
      final p = firstAccount(data)['positions'][0] as DemoRow;
      p['high_bid'] = p['last_bid'] - 1;
    });
  });

  test('trade replay rejects malformed exit snapshot before opening UI', () {
    buy();
    step();
    engine.submit(id, engine.rows(account, 'positions').single, 'SELL_TO_CLOSE', 1, 'close');
    step();
    rejectsSaved((data) => firstAccount(data)['trades'][0]['exit_decision'] = '{invalid');
  });

  test('trade and position cannot claim another account decision snapshot', () {
    buy(2);
    step(2);
    final other = engine.createAccount('حساب آخر', 2000000);
    final foreignOrder = engine.submit(other['id'] as String,
      engine.contract('NVDA', 'CALL'), 'BUY', 1, 'foreign-entry');
    step();
    engine.submit(id, engine.rows(account, 'positions').single, 'SELL_TO_CLOSE', 1, 'close-one');
    step();
    final foreign = foreignOrder['decision_json'] as String;
    rejectsSaved((data) => firstAccount(data)['trades'][0]['entry_decisions'] = [foreign]);
    rejectsSaved((data) => firstAccount(data)['positions'][0]['entry_decisions'] = [foreign]);
  });

  for (final field in <String, Object>{
    'trailing_pct': 96,
    'partial_take_pct': -1,
    'swing_max_ticks': 0,
    'expiry_guard_days': 31,
    'scaling_max': 21,
    'scaling_quantity': 0,
    'scaling_cooldown': 0,
    'scaling_enabled': 1,
    'reversal_enabled': 'true',
    'exposure_pct': 101,
    'trade_pct': 1.5,
  }.entries) {
    test('new saved risk rejects invalid ${field.key}', () {
      rejectsSaved((data) => firstAccount(data)['risk'][field.key] = field.value);
    });
  }

  test('corrupted snapshot is retained on disk and cannot start local timer', () async {
    buy();
    step();
    final data = saved();
    firstAccount(data)['positions'][0]['entry_decisions'] = ['{invalid'];
    final raw = jsonEncode(data);
    final store = MemoryDemoStore(raw);
    final controller = DemoController(store);
    await controller.load();
    expect(controller.ready, false);
    expect(controller.error, isNotNull);
    controller.play();
    expect(controller.playing, false);
    expect(store.data, raw);
    controller.dispose();
  });

  test('all chart prefixes retain confirmed pivots and indicators without future observations', () {
    engine.tick = 160;
    final full = DemoChartAnalysis.bars(engine, 'NVDA', engine.tick);
    final allPivots = DemoChartAnalysis.pivots(full);
    for (var end = 24; end <= 160; end++) {
      final prefix = DemoChartAnalysis.bars(engine, 'NVDA', end);
      expect(prefix.map((b) => [b.tick, b.open, b.high, b.low, b.close, b.volume]).toList(),
        full.take(end + 1).map((b) => [b.tick, b.open, b.high, b.low, b.close, b.volume]).toList());
      final pivots = DemoChartAnalysis.pivots(prefix);
      expect(pivots.map((p) => [p.index, p.confirmedAt, p.price, p.high]).toList(),
        allPivots.where((p) => p.confirmedAt <= end)
          .map((p) => [p.index, p.confirmedAt, p.price, p.high]).toList());
      final closes = prefix.map((b) => b.close).toList();
      expect(DemoChartAnalysis.ema(closes, 20),
        DemoChartAnalysis.ema(full.map((b) => b.close).toList(), 20).take(end + 1).toList());
      for (final pattern in [...DemoChartAnalysis.waves(pivots), ...DemoChartAnalysis.harmonics(pivots)]) {
        expect(pattern.points.every((p) => p.confirmedAt <= end), true);
      }
    }
    expect(() => DemoChartAnalysis.bars(engine, 'NVDA', 161), rejected);
  });
}
