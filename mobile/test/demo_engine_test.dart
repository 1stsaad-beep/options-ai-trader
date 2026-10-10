import 'dart:convert';
import 'dart:math';
import 'package:flutter_test/flutter_test.dart';
import 'package:options_ai_trader/demo/engine.dart';
import 'package:options_ai_trader/demo/store.dart';

void main() {
  late DemoEngine e;
  late DemoRow a;
  late String id;
  late DemoRow c;
  setUp(() {
    e = DemoEngine();
    a = e.createAccount('الأول', 2000000);
    id = a['id'];
    c = e.contract('NVDA', 'CALL');
  });
  DemoRow buy({int qty = 1, String key = 'buy'}) =>
      e.submit(id, c, 'BUY', qty, key);
  void step([int count = 1]) {
    for (var i = 0; i < count; i++) {
      e.step(enter: false);
      e.validate();
    }
  }

  final rejected = throwsA(isA<DemoRejected>());

  test(
    'default local accounts are independent with explicit synthetic source',
    () {
      final b = e.createAccount('الثاني', 1000000);
      e.configure(id, {
        'trade_pct': 1,
        'strategies': ['breakout'],
      });
      e.watch(id, 'MSFT');
      e.watch(id, 'NVDA', enabled: false);
      e.watch(id, 'AAPL', remove: true);
      expect((a['watch'] as Map).length, 3);
      expect(b['watch'].length, 3);
      expect(b['watch']['NVDA'], true);
      expect(e.risk(b)['trade_pct'], 2);
      expect(e.risk(b)['strategies'], ['breakout', 'pullback']);
      expect(e.performance(id)['source'], DemoEngine.source);
    },
  );
  test('watchlist supports more than three symbols and rejects unknown', () {
    for (final s in DemoEngine.symbols) {
      e.watch(id, s);
    }
    expect(a['watch'].length, 15);
    expect(() => e.watch(id, 'INVALID'), rejected);
    e.watch(id, 'NVDA', enabled: false);
    expect(() => buy(), rejected);
  });
  test(
    'partial fill next tick only, repeat fill and cancellation conserve cash',
    () {
      final o = buy(qty: 3);
      e.fill(id, o['id']);
      expect(o['filled'], 0);
      step();
      expect(o['filled'], 1);
      expect(o['status'], 'PARTIAL');
      final cash = a['cash'];
      e.fill(id, o['id']);
      expect(a['cash'], cash);
      e.cancel(id, o['id']);
      step();
      expect(o['filled'], 1);
      expect(o['status'], 'CANCELLED');
      expect(e.rows(a, 'positions').single['cost'], 10665);
      expect(o['fees_paid'], 65);
    },
  );
  test('full close includes spread both commissions and slippage', () {
    buy();
    step();
    final p = e.rows(a, 'positions').single;
    final o = e.submit(id, p, 'SELL_TO_CLOSE', 1, 'close');
    step();
    expect(o['status'], 'FILLED');
    expect(e.rows(a, 'positions'), isEmpty);
    expect(e.realized(a), -830);
    expect(a['cash'], 2000000 - 830);
  });
  test('idempotency survives persistence and uncertain accepted response', () {
    expect(
      () => e.submit(id, c, 'BUY', 1, 'lost', loseResponse: true),
      rejected,
    );
    expect(a['known'], false);
    expect(() => buy(key: 'another'), rejected);
    e = DemoEngine.decode(e.encode());
    a = e.account(id);
    expect(
      e.submit(id, c, 'BUY', 1, 'lost')['id'],
      e.rows(a, 'orders').single['id'],
    );
    step();
    expect(e.rows(a, 'positions'), isEmpty);
    e.reconcile(id);
    step();
    expect(e.rows(a, 'positions').single['quantity'], 1);
    expect(e.rows(a, 'orders').length, 1);
  });
  test('different contents cannot reuse idempotency key', () {
    buy();
    expect(() => buy(qty: 2), rejected);
    expect(() => e.submit(id, c, 'BUY', 1, 'buy', limit: 107), rejected);
  });
  test('cross account fill cancel and unowned close are denied', () {
    final b = e.createAccount('الثاني', 2000000), o = buy();
    expect(() => e.fill(b['id'], o['id']), rejected);
    expect(() => e.cancel(b['id'], o['id']), rejected);
    step();
    expect(() => e.submit(b['id'], c, 'SELL_TO_CLOSE', 1, 'other'), rejected);
    expect(b['cash'], b['initial']);
    expect(e.rows(b, 'positions'), isEmpty);
  });
  test('same request key in distinct accounts never mixes orders', () {
    final b = e.createAccount('ثان', 2000000), first = buy();
    final second = e.submit(b['id'], c, 'BUY', 1, 'buy');
    step();
    expect(first['id'], isNot(second['id']));
    expect(e.rows(b, 'positions').single['account_id'], b['id']);
  });
  test(
    'pending closes reserve ownership and partial close cannot oversell',
    () {
      buy(qty: 3);
      step(3);
      final close = e.submit(id, c, 'SELL_TO_CLOSE', 3, 'close');
      expect(() => e.submit(id, c, 'SELL_TO_CLOSE', 1, 'extra'), rejected);
      step();
      expect(close['filled'], 1);
      expect(e.rows(a, 'positions').single['quantity'], 2);
      e.cancel(id, close['id']);
      e.submit(id, c, 'SELL_TO_CLOSE', 2, 'rest');
      step(2);
      expect(e.rows(a, 'positions'), isEmpty);
    },
  );
  for (final mode in ['live', 'paper', 'ibkr']) {
    test(
      '$mode cannot be enabled in local Demo',
      () => expect(() => e.configure(id, {'mode': mode}), rejected),
    );
  }
  test('observe mode cannot open but permits owned emergency close', () {
    buy();
    step();
    e.configure(id, {'mode': 'observe'});
    expect(() => buy(key: 'new'), rejected);
    e.submit(id, c, 'SELL_TO_CLOSE', 1, 'close');
    step();
    expect(e.rows(a, 'positions'), isEmpty);
  });
  test('no naked shorts, multi leg or invalid contracts', () {
    expect(() => e.submit(id, c, 'SELL', 1, 's'), rejected);
    expect(() => e.submit(id, c, 'SELL_TO_CLOSE', 1, 's'), rejected);
    for (final changes in [
      {'right': 'SPREAD'},
      {'expiry': '2026-02-31'},
      {'strike': 0},
      {'symbol': 'FAKE'},
    ]) {
      expect(() => e.submit(id, {...c, ...changes}, 'BUY', 1, 'bad'), rejected);
    }
  });
  test('trade and exposure limits include pending reservations and costs', () {
    expect(() => buy(qty: 4), rejected);
    e.configure(id, {'allocation_pct': 1});
    buy();
    expect(() => buy(key: 'second'), rejected);
    step();
    expect(() => buy(key: 'third'), rejected);
  });
  test('limits are rechecked on fill after configuration changes', () {
    final o = buy(qty: 3);
    step();
    e.configure(id, {'trade_pct': 1});
    step();
    expect(o['filled'], 1);
    expect(e.rows(a, 'positions').single['quantity'], 1);
  });
  test('max contracts includes filled and pending per account', () {
    e.configure(id, {'max_contracts': 2});
    buy();
    buy(key: '2');
    expect(() => buy(key: '3'), rejected);
    step();
    expect(() => buy(key: '4'), rejected);
  });
  test('daily loss blocks new entries while close remains allowed', () {
    e.configure(id, {'daily_pct': 1});
    buy(qty: 3);
    step(3);
    e.scenario = 'drop';
    e.submit(id, c, 'SELL_TO_CLOSE', 3, 'close');
    step(3);
    buy(key: 'again');
    step();
    e.submit(id, c, 'SELL_TO_CLOSE', 1, 'round2');
    step();
    // Increase the reproducible losses with fresh one-contract round trips.
    for (var i = 0; i < 30 && e.realized(a, today: true) > -20000; i++) {
      e.submit(id, c, 'BUY', 1, 'loss-$i');
      step();
      e.submit(id, c, 'SELL_TO_CLOSE', 1, 'loss-close-$i');
      step();
    }
    expect(e.realized(a, today: true), lessThanOrEqualTo(-20000));
    expect(() => buy(key: 'blocked'), rejected);
  });
  test(
    'global exposure honors strictest member limit and uncertain accounts',
    () {
      final b = e.createAccount('linked', 2000000);
      e.configure(id, {'group': 'g', 'group_allocation_pct': 1});
      e.configure(b['id'], {'group': 'g'});
      buy(qty: 3);
      expect(() => e.submit(b['id'], c, 'BUY', 1, 'b'), rejected);
      e.cancel(id, e.rows(a, 'orders').single['id']);
      e.disconnect(b['id']);
      expect(() => buy(key: 'new'), rejected);
    },
  );
  test(
    'outage stops fills and new entries then reconciliation permits recovery',
    () {
      final o = buy(qty: 2);
      step();
      e.disconnect(id);
      step();
      expect(o['filled'], 1);
      expect(() => e.submit(id, c, 'SELL_TO_CLOSE', 1, 'close'), rejected);
      e.reconcile(id);
      step();
      expect(o['filled'], 2);
    },
  );
  test('market data outage never fabricates a fill or opportunity', () {
    final o = buy();
    e.marketAvailable = false;
    step();
    expect(o['filled'], 0);
    expect(e.opportunities(id), isEmpty);
    expect(e.performance(id)['stale'], true);
    expect(() => buy(key: 'missing'), rejected);
    e.marketAvailable = true;
    step();
    expect(o['filled'], 1);
  });
  test('emergency cancels entry remainder but permits owned close', () {
    final o = buy(qty: 3);
    step();
    e.stop();
    expect(o['status'], 'CANCELLED');
    expect(() => buy(key: 'new'), rejected);
    e.submit(id, c, 'SELL_TO_CLOSE', 1, 'close');
    step();
    expect(e.rows(a, 'positions'), isEmpty);
    expect(() => e.resume(id), rejected);
    e.globalStop = false;
    e.resume(id);
    expect(a['stopped'], false);
  });
  for (final scenario in ['drop', 'rally']) {
    test('automatic $scenario exit with partial fills and entry disabled', () {
      buy(qty: 2);
      step(2);
      e.configure(id, {'automation': true});
      e.scenario = scenario;
      step();
      expect(e.rows(a, 'orders').last['side'], 'SELL_TO_CLOSE');
      step(2);
      expect(e.rows(a, 'positions'), isEmpty);
      expect(
        e.rows(a, 'trades').last['reason'],
        scenario == 'drop' ? 'وقف خسارة' : 'جني ربح',
      );
    });
  }
  test('automatic quantitative opportunity executes only next observation', () {
    e.configure(id, {'automation': true});
    e.step();
    expect(e.rows(a, 'orders'), isNotEmpty);
    expect(e.rows(a, 'positions'), isEmpty);
    e.step();
    expect(e.rows(a, 'positions'), isNotEmpty);
    final orders = e.rows(a, 'orders').length;
    e.step();
    expect(e.rows(a, 'orders').length, orders);
  });
  test('intraday synthetic session exit is generated and filled', () {
    buy();
    step();
    e.configure(id, {'automation': true});
    e.tick = 329;
    step();
    step();
    expect(e.rows(a, 'positions'), isEmpty);
    expect(e.rows(a, 'trades').single['reason'], 'إغلاق الجلسة الاصطناعية');
  });
  test(
    'expiry writes off owned cost and cancels pending closes without exercise',
    () {
      c = e.contract('NVDA', 'PUT', expiry: '2026-01-06');
      buy();
      step();
      e.submit(id, c, 'SELL_TO_CLOSE', 1, 'close');
      e.tick = 569;
      step();
      expect(e.rows(a, 'positions'), isEmpty);
      expect(e.realized(a), -10665);
      expect(e.rows(a, 'orders').last['status'], 'CANCELLED');
      expect(() => buy(key: 'expired'), rejected);
    },
  );
  test(
    'historical replay is deterministic isolated with costs and equity curve',
    () {
      final before = e.encode(), r = e.backtest(id), second = e.backtest(id);
      expect(e.encode(), before);
      expect(r, second);
      expect(r['curve'].length, 120);
      expect(r['fees'], greaterThan(0));
      expect(r['profitability_evidence'], false);
      expect(r['next_observation_execution'], true);
      expect(r['max_drawdown'], greaterThan(0));
      expect(
        e.backtest(id, steps: 40)['curve'],
        (r['curve'] as List).take(40).toList(),
      );
    },
  );
  test('future replay observations cannot alter prior opportunity', () {
    final earlier = e.opportunities(id, at: 24);
    e.tick = 100;
    expect(e.opportunities(id, at: 24), earlier);
  });
  test('seeded faults preserve ledger and never mix account cash', () {
    final b = e.createAccount('independent', 2000000);
    e.configure(id, {'automation': true});
    final rng = Random(13);
    for (var i = 0; i < 160; i++) {
      e.scenario = ['flat', 'wave', 'drop', 'rally'][rng.nextInt(4)];
      e.marketAvailable = rng.nextInt(6) != 0;
      if (i % 17 == 0) {
        e.disconnect(id);
      }
      if (i % 19 == 0) {
        e.reconcile(id);
      }
      e.step();
      e = DemoEngine.decode(e.encode());
      a = e.account(id);
      expect(e.account(b['id'])['cash'], b['initial']);
    }
  });
  test(
    'tampered account IDs cash status sequence modes and contracts fail closed',
    () {
      buy();
      step();
      final saved = e.encode();
      for (final corrupt in <void Function(Map<String, dynamic>)>[
        (d) => d['sequence'] = 0,
        (d) => d['accounts'][0]['cash'] += 1,
        (d) => d['accounts'][0]['risk']['mode'] = 'live',
        (d) => d['accounts'][0]['orders'][0]['account_id'] = 'other',
        (d) => d['accounts'][0]['orders'][0]['filled'] = 0,
        (d) => d['accounts'][0]['orders'][0]['expiry'] = '2026-02-31',
        (d) => d['accounts'][0]['orders'][0]['commission'] = -1,
      ]) {
        final data = jsonDecode(saved) as Map<String, dynamic>;
        corrupt(data);
        expect(() => DemoEngine.decode(jsonEncode(data)), rejected);
      }
    },
  );
  test(
    'serialized local store restores multi accounts settings watchlists and trades',
    () async {
      final store = MemoryDemoStore(e.encode()), ctrl = DemoController(store);
      await ctrl.load();
      await ctrl.change((e) {
        e.createAccount('persist', 1000000);
        e.watch(id, 'MSFT');
        e.configure(id, {'automation': true});
        e.theme = 'light';
        e.step();
        e.step();
      });
      final saved = ctrl.engine.encode();
      ctrl.dispose();
      final restored = DemoController(store);
      await restored.load();
      expect(restored.ready, true);
      expect(restored.engine.encode(), saved);
      restored.dispose();
    },
  );
  test(
    'accepted unknown order is persisted even when response is lost',
    () async {
      final store = MemoryDemoStore(e.encode()), ctrl = DemoController(store);
      await ctrl.load();
      await ctrl.change(
        (e) => e.submit(id, c, 'BUY', 1, 'lost', loseResponse: true),
      );
      expect(ctrl.error, isNotNull);
      final restored = DemoEngine.decode(store.data!);
      expect(restored.account(id)['known'], false);
      expect(restored.rows(restored.account(id), 'orders').length, 1);
      ctrl.dispose();
    },
  );
  test('corrupt saved data is not erased or silently replaced', () async {
    final store = MemoryDemoStore('broken'), ctrl = DemoController(store);
    await ctrl.load();
    expect(ctrl.ready, false);
    expect(store.data, 'broken');
    expect(ctrl.error, isNotNull);
    ctrl.dispose();
  });
  test('failed persistence rolls back and stops local timer', () async {
    final store = MemoryDemoStore(e.encode()), ctrl = DemoController(store);
    await ctrl.load();
    final saved = store.data;
    ctrl.play();
    store.failWrites = true;
    await ctrl.change((e) => e.step());
    expect(ctrl.playing, false);
    expect(ctrl.engine.encode(), saved);
    expect(store.data, saved);
    expect(ctrl.error, isNotNull);
    ctrl.dispose();
  });
}
