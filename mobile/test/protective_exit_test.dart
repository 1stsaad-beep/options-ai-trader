import 'dart:convert';
import 'dart:math';

import 'package:flutter_test/flutter_test.dart';
import 'package:options_ai_trader/brokers/broker_models.dart';
import 'package:options_ai_trader/brokers/broker_protective.dart';
import 'package:options_ai_trader/brokers/broker_store.dart';
import 'package:options_ai_trader/demo/engine.dart';
import 'package:options_ai_trader/paper_return.dart';
import 'package:options_ai_trader/protective_exit.dart';

String? rule(int basis, int value, int peak, int stop, int take, int trail) =>
    protectiveExitCents(basis: basis, value: value, peak: peak, stopPercent: stop, takePercent: take, trailPercent: trail);

void main() {
  test('shared vectors: thresholds, arming and priority', () {
    // basis, value, peak, stop, take, trail -> expected
    final vectors = <List<Object?>>[
      [10000, 8000, 10000, 20, 40, 15, stopLossExit], // exactly -20 %
      [10000, 8001, 10000, 20, 40, 15, null],
      [10000, 14000, 14000, 20, 40, 15, takeProfitExit], // exactly +40 %
      [10000, 11050, 13000, 20, 40, 15, trailingStopExit], // 15 % off a 13000 peak
      [10000, 11051, 13000, 20, 40, 15, null],
      [10000, 8500, 10000, 20, 40, 15, null], // never above basis: trailing not armed
      [10000, 7000, 13000, 20, 40, 15, stopLossExit], // stop and trail both hit -> stop wins
      [10000, 11000, 20000, 20, 40, 0, null], // trail 0 disables
      [10000, 12000, 11000, 20, 40, 15, null], // peak below value is raised to value
    ];
    for (final v in vectors) {
      expect(rule(v[0] as int, v[1] as int, v[2] as int, v[3] as int, v[4] as int, v[5] as int), v[6], reason: '$v');
    }
  });

  test('Market Paper raw path: identical to the previous floating rule away from exact boundaries', () {
    final r = Random(7);
    var compared = 0;
    for (var i = 0; i < 20000; i++) {
      final qty = 1 + r.nextInt(5), entryBid = 50 + r.nextInt(500), cost = entryBid * qty * 100;
      final high = entryBid + r.nextInt(400) - 100, bid = 1 + r.nextInt(900);
      final stop = 1 + r.nextInt(50), take = 1 + r.nextInt(50), trail = 1 + r.nextInt(50);
      final average = cost / (qty * 100), highest = high.toDouble();
      double gap(double a, double b) => (a - b).abs();
      if (gap(bid.toDouble(), average * (1 - stop / 100)) < 1e-6 || gap(bid.toDouble(), average * (1 + take / 100)) < 1e-6 ||
          gap(bid.toDouble(), highest * (1 - trail / 100)) < 1e-6 || gap(highest, average) < 1e-9) {
        continue;
      }
      final oldStop = bid <= average * (1 - stop / 100), oldTake = bid >= average * (1 + take / 100);
      final oldTrail = highest > average && bid <= highest * (1 - trail / 100);
      final old = oldStop ? stopLossExit : oldTake ? takeProfitExit : oldTrail ? trailingStopExit : null;
      expect(rule(cost, bid * qty * 100, max(high, bid) * qty * 100, stop, take, trail), old, reason: '$qty $entryBid $high $bid');
      compared++;
    }
    expect(compared, greaterThan(19000));
  });

  test('Market Paper costed path: identical to PaperReturn checks', () {
    final r = Random(11);
    for (var i = 0; i < 5000; i++) {
      final qty = 1 + r.nextInt(5), cost = (50 + r.nextInt(500)) * qty * 100, high = 20 + r.nextInt(800), bid = 1 + r.nextInt(900);
      final account = {'executionPolicy': 'conservative-v2'};
      final position = {'cost': cost, 'quantity': qty, 'highBid': high, 'entryFees': 70 * qty};
      final n = PaperReturn(account, position, bid);
      final stop = 1 + r.nextInt(50), take = 1 + r.nextInt(50), trail = 1 + r.nextInt(50);
      final old = n.lossAtLeast(stop) ? stopLossExit : n.gainAtLeast(take) ? takeProfitExit
          : n.trailingAtLeast(trail) ? trailingStopExit : null;
      final now = protectiveExit(basis: n.basis, value: n.liquidation, peak: n.peak > n.liquidation ? n.peak : n.liquidation,
          stopPercent: stop, takePercent: take, trailPercent: trail);
      expect(now, old);
    }
  });

  test('Demo now uses the shared priority: stop beats trailing when both hit', () {
    final e = DemoEngine(), a = e.createAccount('B10', 2000000), id = a['id'] as String;
    e.submit(id, e.contract('NVDA', 'CALL'), 'BUY', 1, 'entry');
    e.step(enter: false);
    e.configure(id, {'automation': true, 'take_pct': 500, 'trailing_pct': 5, 'stop_pct': 1});
    e.scenario = 'rally';
    e.step(enter: false);
    e.scenario = 'drop';
    for (var i = 0; i < 6 && e.rows(a, 'orders').length < 2; i++) {
      e.step(enter: false);
    }
    final exit = e.rows(a, 'orders').last;
    final p = (jsonDecode(exit['decision_json'] as String) as Map)['evidence'] as Map? ?? const {};
    // Whatever the synthetic path, the chosen reason must equal the shared rule on the recorded evidence.
    expect(exit['side'], 'SELL_TO_CLOSE');
    expect(p, isNotEmpty);
    // Both conditions hold on this path; previously Demo let the trailing stop override.
    expect(trailingArmedAndHit(basis: BigInt.from(p['cost'] as int), value: BigInt.from(p['mark'] as int),
        peak: BigInt.from((p['high_bid'] as int) * 100), trailPercent: 5), isTrue);
    expect(exit['reason'], 'وقف خسارة');
    {
      final expected = rule(p['cost'] as int, p['mark'] as int, (p['high_bid'] as int) * 100, 1, 500, 5);
      expect(exit['reason'], {stopLossExit: 'وقف خسارة', takeProfitExit: 'جني ربح', trailingStopExit: 'وقف متحرك'}[expected]);
    }
  });

  group('Broker Paper tracker', () {
    late MemorySecureKeyValue mem;
    setUp(() => mem = MemorySecureKeyValue());
    BrokerPosition pos(String value, String pl, {String qty = '2'}) =>
        BrokerPosition(symbol: 'AAPL261120C00200000', quantity: qty, marketValue: value, unrealizedPl: pl);

    test('peak grows per lot, trailing proposes a close only after a gain', () async {
      final t = BrokerProtectiveTracker(mem, 'acc1', clock: () => DateTime.utc(2026, 10, 19, 15));
      var s = (await t.observe(BrokerKind.alpaca, [pos('250', '0')])).single;
      expect([s.basisCents, s.valueCents, s.peakCents, s.exit], [25000, 25000, 25000, null]);
      s = (await t.observe(BrokerKind.alpaca, [pos('320', '70')])).single;
      expect(s.peakCents, 32000);
      s = (await t.observe(BrokerKind.alpaca, [pos('272', '22')])).single; // 15 % off 320
      expect(s.exit, trailingStopExit);
      expect(s.peakCents, 32000);
      s = (await t.observe(BrokerKind.alpaca, [pos('200', '-50')])).single;
      expect(s.exit, stopLossExit);
    });

    test('a new lot (quantity/basis change) starts a new peak; policy is configurable and validated', () async {
      final t = BrokerProtectiveTracker(mem, 'acc1');
      await t.observe(BrokerKind.alpaca, [pos('400', '150')]);
      final s = (await t.observe(BrokerKind.alpaca, [pos('500', '0', qty: '4')])).single;
      expect(s.peakCents, 50000);
      await t.setPolicy(const ProtectivePolicy(stopPercent: 10, takePercent: 30, trailPercent: 0));
      expect((await t.policy()).trailPercent, 0);
      await expectLater(t.setPolicy(const ProtectivePolicy(stopPercent: 0)), throwsFormatException);
      expect((await t.observe(BrokerKind.alpaca, [pos('440', '-60', qty: '4')])).single.exit, stopLossExit); // -12 % vs stop 10 %
    });
  });
}
