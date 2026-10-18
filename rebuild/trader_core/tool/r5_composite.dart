// Round 5: the existing default (composite) strategy on real bars, with and
// without the IV/RV filter. Modeled options (see r5_lib.dart).
import 'dart:io';

import 'package:trader_core/trader_core.dart';

import 'r5_lib.dart';

void main() {
  final d = {for (final s in symbols) s: TfSeries.of(BarTimeframe.d1, loadBars('d1', s))};
  final vm = VolModel(d, TfSeries.of(BarTimeframe.d1, loadBars('d1', 'VIX')), TfSeries.of(BarTimeframe.d1, loadBars('d1', 'VXN')));
  const st = AccountSettings();
  final de = DecisionEngine(st);
  final an = Analyzer();
  final md = StringBuffer('# Default (composite) strategy with / without the IV/RV filter\n\n'
      'Analyzer + DecisionEngine with default AccountSettings (minScore ${st.minScore}, ≥ ${st.minAgreeingEngines} engines, '
      'trend alignment) evaluated at every completed bar (window 300 bars). Exits like the app defaults: stop −${st.stopLossPercent}%, '
      'take profit +${st.takeProfitPercent}%, trailing ${st.trailingStopPercent}% after +${st.trailingActivationPercent}%, '
      'max ${st.maxHoldingDays} sessions, out ${st.exitDaysBeforeExpiry} days before expiry; contract ATM, first Friday ≥ ${st.minDaysToExpiry} days. '
      'MODELED option prices. The IV/RV filter only varies for SPY (VIX) and QQQ (VXN); for single stocks the IV proxy is a fixed '
      '1.3 × RV20, so IV/RV is constant and the filter is not testable there.\n');
  for (final (tf, perDay) in [('h1', 7), ('m15', 26)]) {
    final sigs = <String, List<StrategySignal>>{};
    final series = <String, TfSeries>{};
    final sw = Stopwatch()..start();
    for (final sym in symbols) {
      final s = TfSeries.of(tfOf(tf), loadBars(tf, sym));
      series[sym] = s;
      final out = <StrategySignal>[];
      for (var i = 120; i < s.bars.length; i++) {
        final w = s.bars.sublist(i + 1 > 300 ? i + 1 - 300 : 0, i + 1);
        final rep = an.analyze(sym, w, weights: st.engineWeights);
        final intent = de.evaluateEntry(sym, rep);
        if (intent != null) {
          out.add(StrategySignal(index: i, time: s.ends[i], bullish: intent.right == OptionRight.call, reasonAr: intent.reasonAr));
        }
      }
      sigs[sym] = out;
    }
    stdout.writeln('$tf analysis ${sw.elapsed}');
    final hold = st.maxHoldingDays * perDay;
    final x = ExitRule('app', sl: st.stopLossPercent / 100, tp: st.takeProfitPercent / 100,
        trailAct: st.trailingActivationPercent / 100, trailPct: st.trailingStopPercent / 100, maxHoldBars: hold);
    final first = series['SPY']!.bars.first.time, last = series['SPY']!.bars.last.time;
    final sp = Splits(first, last);
    md.writeln('\n## $tf (${NewYorkTime.dateKey(first)} → ${NewYorkTime.dateKey(last)}); ${sp.describe()}\n');
    md.writeln('| universe | filter | dir | split ${Stats.header.substring(1)}');
    md.writeln('|---|---|---|---${Stats.sep}');
    for (final (uni, syms) in [('all 7', symbols), ('SPY+QQQ', const ['SPY', 'QQQ'])]) {
      for (final (fname, ivrv, be) in [
        ('none', null, null),
        ('IV/RV ≤ 1.5', 1.5, null),
        ('IV/RV ≤ 1.2', 1.2, null),
        ('break-even ≤ 1.0× expected', null, 1.0),
      ]) {
        if (uni == 'all 7' && fname != 'none') continue;
        final t = <Trade>[];
        for (final sym in syms) {
          t.addAll(simulate(
              sym: sym, s: series[sym]!, signals: sigs[sym]!, x: x, vm: vm, minDays: st.minDaysToExpiry,
              forceBefore: Duration(days: st.exitDaysBeforeExpiry), maxIvRv: ivrv, maxBeToExp: be));
        }
        for (final dir in ['both', 'call', 'put']) {
          final td = dir == 'both' ? t : [for (final q in t) if (q.bullish == (dir == 'call')) q];
          for (final part in ['disc', 'val', 'hold']) {
            md.writeln('| $uni | $fname | $dir | $part ${Stats.of(sp.pick(td, part)).row}');
          }
          md.writeln('| $uni | $fname | $dir | **all** ${Stats.of(td).row}');
        }
      }
    }
  }
  File('$dataDir/../results/r5/COMPOSITE_IVRV.md').writeAsStringSync(md.toString());
  stdout.writeln('done');
}
