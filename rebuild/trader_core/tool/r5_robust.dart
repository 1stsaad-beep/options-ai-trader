// Post-selection robustness of the one candidate that passed validation and
// holdout (A4 CALL: daily Elliott wave-2 end + RSI divergence, weekly context).
// Not used for selection; reported to show whether the result is a lone peak.
import 'dart:io';

import 'package:trader_core/trader_core.dart';

import 'r5_lib.dart';

void main() {
  final d = {for (final s in symbols) s: TfSeries.of(BarTimeframe.d1, loadBars('d1', s))};
  final w = {for (final s in symbols) s: weeklyFromDaily(d[s]!.bars)};
  final vm = VolModel(d, TfSeries.of(BarTimeframe.d1, loadBars('d1', 'VIX')), TfSeries.of(BarTimeframe.d1, loadBars('d1', 'VXN')));
  final sp = Splits(d['SPY']!.bars.first.time, d['SPY']!.bars.last.time);
  final md = StringBuffer('# A4 CALL robustness (daily entry / weekly context, calls only)\n\n'
      'Post-hoc checks around the selected variant `base k1.5 / time5`; ${sp.describe()}.\n\n');
  List<Trade> runP(ElliottParams p, ExitRule x, {List<String> only = symbols, Costs costs = const Costs()}) => [
        for (final s in only)
          ...simulate(
              sym: s,
              s: d[s]!,
              signals: mtfElliottSignals(entry: d[s]!, mid: w[s], ma: d[s], p: p),
              x: x,
              vm: vm,
              costs: costs,
              forceBefore: const Duration(hours: 26))
      ];
  const t5 = ExitRule('time5', maxHoldBars: 5);
  const p0 = ElliottParams(requireTop: false, kEntry: 1.5, puts: false);
  md.writeln('## Zig-zag sizes (k entry × k fine), exit time5\n');
  md.writeln('| k entry | k fine | split ${Stats.header.substring(1)}');
  md.writeln('|---|---|---${Stats.sep}');
  for (final k in [1.25, 1.5, 1.75, 2.0, 2.5]) {
    for (final kf in [0.5, 0.6, 0.75]) {
      final t = runP(p0.copyWith(kEntry: k, kFine: kf), t5);
      md.writeln('| $k | $kf | all ${Stats.of(t).row}');
      md.writeln('| | | hold ${Stats.of(sp.pick(t, 'hold')).row}');
    }
  }
  md.writeln('\n## Exits and context (k 1.5 / fine 0.6)\n');
  md.writeln('| variant | split ${Stats.header.substring(1)}');
  md.writeln('|---|---${Stats.sep}');
  for (final (name, p, x) in [
    ('time3', p0, const ExitRule('time3', maxHoldBars: 3)),
    ('time5', p0, t5),
    ('time8 (forced Thu close)', p0, const ExitRule('time8', maxHoldBars: 8)),
    ('tp50/sl50', p0, const ExitRule('tp', tp: 0.5, sl: 0.5)),
    ('tp100/sl50', p0, const ExitRule('tp', tp: 1.0, sl: 0.5)),
    ('wave stop+target', p0, const ExitRule('w', useInvalidation: true, useTarget: true)),
    ('no weekly context', p0.copyWith(requireMid: false), t5),
    ('strict impulse rules', p0.copyWith(strictContext: true), t5),
    ('+MA trend', p0.copyWith(maTrend: true), t5),
    ('+MACD', p0.copyWith(macd: true), t5),
    ('+fib price', p0.copyWith(fibPrice: true), t5),
    ('+fib time', p0.copyWith(fibTime: true), t5),
    ('+wave vs MA', p0.copyWith(waveMa: true), t5),
    ('+S/R', p0.copyWith(sr: true), t5),
    ('+double bottom', p0.copyWith(classical: true), t5),
  ]) {
    final t = runP(p, x);
    md.writeln('| $name | all ${Stats.of(t).row}');
    md.writeln('| | hold ${Stats.of(sp.pick(t, 'hold')).row}');
  }
  md.writeln('\n## Per symbol (k 1.5, time5, all periods)\n');
  md.writeln('| symbol ${Stats.header.substring(1)}');
  md.writeln('|---${Stats.sep}');
  for (final s in symbols) {
    md.writeln('| $s ${Stats.of(runP(p0, t5, only: [s])).row}');
  }
  md.writeln('\n## Per symbol — selected variant without weekly context (k 1.5, time5, all periods)\n');
  md.writeln('| symbol ${Stats.header.substring(1)}');
  md.writeln('|---${Stats.sep}');
  final pn = p0.copyWith(requireMid: false);
  for (final s in symbols) {
    md.writeln('| $s ${Stats.of(runP(pn, t5, only: [s])).row}');
  }
  final exA = [for (final s in symbols) if (s != 'AAPL') s];
  md.writeln('| **all except AAPL** ${Stats.of(runP(pn, t5, only: exA)).row}');
  md.writeln('| **all except AAPL, holdout** ${Stats.of(Splits(d['SPY']!.bars.first.time, d['SPY']!.bars.last.time).pick(runP(pn, t5, only: exA), 'hold')).row}');
  md.writeln('\n## Zig-zag sizes — selected variant without weekly context (time5)\n');
  md.writeln('| k entry | k fine | split ${Stats.header.substring(1)}');
  md.writeln('|---|---|---${Stats.sep}');
  for (final k in [1.25, 1.5, 1.75, 2.0, 2.5]) {
    for (final kf in [0.5, 0.6, 0.75]) {
      final t = runP(pn.copyWith(kEntry: k, kFine: kf), t5);
      md.writeln('| $k | $kf | all ${Stats.of(t).row}');
      md.writeln('| | | hold ${Stats.of(sp.pick(t, 'hold')).row}');
    }
  }
  md.writeln('\n| **with weekly context, except AAPL** ${Stats.of(runP(p0, t5, only: exA)).row}');

  md.writeln('\n## By period (k 1.5, time5)\n');
  md.writeln('| years ${Stats.header.substring(1)}');
  md.writeln('|---${Stats.sep}');
  final all = runP(p0, t5);
  for (final (a, b) in [(1998, 2003), (2004, 2008), (2009, 2013), (2014, 2018), (2019, 2022), (2023, 2026)]) {
    md.writeln('| $a–$b ${Stats.of([for (final x in all) if (x.signal.year >= a && x.signal.year <= b) x]).row}');
  }
  md.writeln('\n## Mirror check: same rule for PUTS (bearish wave C), k 1.5, time5\n');
  final puts = [
    for (final s in symbols)
      ...simulate(
          sym: s,
          s: d[s]!,
          signals: mtfElliottSignals(entry: d[s]!, mid: w[s], ma: d[s], p: const ElliottParams(requireTop: false, kEntry: 1.5, calls: false)),
          x: t5,
          vm: vm,
          forceBefore: const Duration(hours: 26))
  ];
  md.writeln('| split ${Stats.header.substring(1)}');
  md.writeln('|---${Stats.sep}');
  for (final part in ['disc', 'val', 'hold']) {
    md.writeln('| $part ${Stats.of(sp.pick(puts, part)).row}');
  }
  final out = File('$dataDir/../results/r5/A4_CALL_ROBUSTNESS.md');
  out.writeAsStringSync(md.toString());
  stdout.write(md);
}
