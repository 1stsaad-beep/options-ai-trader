/// Capitulation-rebound strategy: the Dart port must reproduce the research numbers exactly
/// (fixtures from rebuild/research/capit_fixtures.py, real Yahoo daily closes) and its calendar rules.
import 'dart:convert';
import 'dart:io';

import 'package:test/test.dart';
import 'package:trader_core/trader_core.dart';

void main() {
  const cal = MarketCalendar();
  final fx = jsonDecode(File('test/fixtures/capitulation_cases.json').readAsStringSync()) as Map<String, dynamic>;
  final cases = (fx['cases'] as List).cast<Map<String, dynamic>>();
  List<double> dl(Object? v) => [for (final x in v as List) (x as num).toDouble()];

  group('research parity (real daily closes)', () {
    test('fixture has signal and no-signal cases', () {
      expect(cases.where((c) => (c['expected'] as Map)['fire'] == true).length, greaterThanOrEqualTo(6));
      expect(cases.where((c) => (c['expected'] as Map)['fire'] == false).length, greaterThanOrEqualTo(6));
    });
    for (final c in cases) {
      test('${c['symbol']} ${c['date']} (${c['note']})', () {
        final e = c['expected'] as Map<String, dynamic>;
        final sig = evaluateCapitulation(
          dailyCloses: dl(c['closes']),
          price: (c['price'] as num).toDouble(),
          spyCloses: dl(c['spyCloses']),
          spyPrice: (c['spyPrice'] as num).toDouble(),
        );
        expect(sig.bbwPct, closeTo((e['bbwPct'] as num).toDouble(), 1e-6));
        expect(sig.roc, closeTo((e['roc20'] as num).toDouble(), 1e-6));
        expect(sig.spyRoc, closeTo((e['spyRoc5'] as num).toDouble(), 1e-6));
        expect(sig.fire, e['fire']);
        expect(sig.reasonAr, contains('ارتداد'));
      });
    }
  });

  group('indicator definitions', () {
    test('BandWidth = 4·σ(pop)/SMA', () {
      final c = [for (var i = 0; i < 20; i++) 100.0 + (i.isEven ? 1 : -1)];
      final w = bandWidthSeries(c);
      expect(w[18].isNaN, isTrue);
      expect(w[19], closeTo(4 * 1.0 / 100.0, 1e-12)); // σ = 1 exactly, mean 100
    });
    test('percentile = share of the previous window−1 values strictly below today', () {
      final s = [for (var i = 0; i < 126; i++) i.toDouble()];
      expect(percentileOfLast(s, 126), 1.0);
      s[125] = -1;
      expect(percentileOfLast(s, 126), 0.0);
      s[125] = 62.5; // 63 of 125 values (0..62) are below
      expect(percentileOfLast(s, 126), closeTo(63 / 125, 1e-12));
    });
    test('too little history never fires', () {
      final sig = evaluateCapitulation(dailyCloses: List.filled(50, 100.0), price: 80, spyCloses: List.filled(10, 100.0), spyPrice: 90);
      expect(sig.fire, isFalse);
    });
  });

  group('calendar rules', () {
    test('entry window 15:45–15:57 New York on regular sessions only', () {
      expect(inEntryWindow(DateTime.utc(2026, 10, 15, 19, 50), cal), isTrue); // Thu 15:50 EDT
      expect(inEntryWindow(DateTime.utc(2026, 10, 15, 19, 45), cal), isTrue);
      expect(inEntryWindow(DateTime.utc(2026, 10, 15, 19, 44), cal), isFalse);
      expect(inEntryWindow(DateTime.utc(2026, 10, 15, 19, 57), cal), isFalse);
      expect(inEntryWindow(DateTime.utc(2026, 10, 17, 19, 50), cal), isFalse); // Saturday
      expect(inEntryWindow(DateTime.utc(2026, 12, 15, 20, 50), cal), isTrue); // 15:50 EST
      expect(inEntryWindow(DateTime.utc(2026, 11, 27, 17, 50), cal), isFalse); // early close day
      expect(inEntryWindow(DateTime.utc(2026, 11, 26, 20, 50), cal), isFalse); // Thanksgiving
    });
    test('time exit = 15:50 New York on the 2nd session after entry', () {
      // Thu → Fri, Mon
      expect(capitulationExitDue(DateTime.utc(2026, 10, 15, 19, 52), cal), DateTime.utc(2026, 10, 19, 19, 50));
      // Wed before Thanksgiving → Fri (early close) is session 1, Mon session 2 (EST)
      expect(capitulationExitDue(DateTime.utc(2026, 11, 25, 20, 52), cal), DateTime.utc(2026, 11, 30, 20, 50));
      // Tue → Wed, Fri early close: exit 10 min before the 13:00 close
      expect(capitulationExitDue(DateTime.utc(2026, 11, 24, 20, 52), cal), DateTime.utc(2026, 11, 27, 17, 50));
    });
    test('exit helper: time exit, expiry guard, never a price stop', () {
      final contract = OptionContract(
          underlying: 'AAPL', right: OptionRight.call, expiry: DateTime.utc(2026, 10, 23), strikeCents: 25000);
      final pos = Position(contract: contract, quantity: 2, averageCostCents: 500, openedAt: DateTime.utc(2026, 10, 15, 19, 52));
      final meta = PositionMeta(
          occSymbol: contract.occSymbol,
          entryTime: DateTime.utc(2026, 10, 15, 19, 52),
          entryPremiumCents: 500,
          initialQuantity: 2,
          entryScore: 0,
          entryReasonAr: 'test');
      ExitDecision? at(DateTime t) => capitulationExit(position: pos, meta: meta, now: t, exitDaysBeforeExpiry: 0);
      expect(at(DateTime.utc(2026, 10, 16, 19, 50)), isNull);
      expect(at(DateTime.utc(2026, 10, 19, 19, 49)), isNull);
      final x = at(DateTime.utc(2026, 10, 19, 19, 50))!;
      expect(x.kind, ExitKind.maxHolding);
      expect(x.quantity, 2);
      final e = capitulationExit(position: pos, meta: meta, now: DateTime.utc(2026, 10, 16, 14), exitDaysBeforeExpiry: 7)!;
      expect(e.kind, ExitKind.expiry);
    });
  });

  group('settings', () {
    test('preset is valid and round-trips', () {
      const p = AccountSettings.capitulationPreset;
      expect(p.validate(), isEmpty);
      final back = AccountSettings.fromJson(jsonDecode(jsonEncode(p.toJson())) as Map<String, dynamic>);
      expect(back.entryStrategy, EntryStrategy.capitulationRebound);
      expect(back.toJson(), p.toJson());
      expect(back.allowPuts, isFalse);
      expect(back.targetDelta, 0.5);
    });
    test('old saves load as composite', () {
      expect(AccountSettings.fromJson(const {}).entryStrategy, EntryStrategy.composite);
    });
    test('capitulation without calls is rejected', () {
      final bad = AccountSettings.capitulationPreset.copyWith(allowCalls: false, allowPuts: true);
      expect(bad.validate(), isNotEmpty);
    });
    test('premium per trade stays ≈0.8 % of equity', () {
      const s = AccountSettings.capitulationPreset;
      expect(s.riskPerTradePercent / (s.stopLossPercent / 100), lessThan(0.8));
      expect(s.maxPositionPercent, lessThanOrEqualTo(1));
    });
  });
}
