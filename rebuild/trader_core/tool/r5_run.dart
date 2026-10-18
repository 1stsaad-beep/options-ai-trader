// Round 5: Strategy A (MTF Elliott) and B (MTF RSI) on real bars, modeled options.
// dart run tool/r5_run.dart  → writes ../research/results/r5/*.md|csv
import 'dart:io';

import 'package:trader_core/trader_core.dart';

import 'r5_lib.dart';

final outDir = Directory('$dataDir/../results/r5')..createSync(recursive: true);

class Cfg {
  final String id, fastTf, slowTf, midTf, topTf;
  final int holdBars, minDays;
  final Duration forceBefore;
  const Cfg(this.id, {required this.fastTf, this.slowTf = '', this.midTf = '', this.topTf = '', required this.holdBars, this.minDays = 2,
      this.forceBefore = const Duration(hours: 1)});
}

late Map<String, Map<String, TfSeries>> S; // tf -> sym -> series
late VolModel vm;

TfSeries? ser(String tf, String sym) {
  if (tf.isEmpty) return null;
  return S[tf]![sym];
}

class Variant {
  final String id;
  final Map<String, List<StrategySignal>> sigs; // per symbol
  final ExitRule exit;
  Variant(this.id, this.sigs, this.exit);
  String get key => '$id|${exit.id}';
}

List<Trade> run(Cfg c, Variant v, {Costs costs = const Costs(), VolModel? model, double? maxIvRv, List<String>? only}) {
  final out = <Trade>[];
  for (final sym in only ?? symbols) {
    final s = ser(c.fastTf, sym);
    if (s == null || v.sigs[sym] == null) continue;
    var x = v.exit;
    if (v is _RsiVariant) {
      final r = v.rf[sym]!;
      x = ExitRule(v.exit.id, maxHoldBars: v.hold, extra: (k, bull) => r[k] != null && (bull ? r[k]! >= 50 : r[k]! <= 50));
    }
    out.addAll(simulate(
        sym: sym, s: s, signals: v.sigs[sym]!, x: x, vm: model ?? vm, costs: costs, minDays: c.minDays,
        forceBefore: c.forceBefore, maxIvRv: maxIvRv));
  }
  return out;
}

List<Trade> dirOf(List<Trade> t, String d) => d == 'both' ? t : [for (final x in t) if (x.bullish == (d == 'call')) x];

final md = StringBuffer();
final csv = StringBuffer('config,variant,exit,direction,split,n,win,expectancy,pf,total,maxdd,hit\n');

Splits splitsFor(Cfg c) {
  DateTime? a, b;
  for (final sym in symbols) {
    final s = ser(c.fastTf, sym);
    if (s == null || s.bars.isEmpty) continue;
    final f = s.bars.first.time, l = s.bars.last.time;
    if (a == null || f.isBefore(a)) a = f;
    if (b == null || l.isAfter(b)) b = l;
  }
  return Splits(a!, b!);
}

void evaluate(Cfg c, List<Variant> vs, String specPrefix) {
  final sp = splitsFor(c);
  md.writeln('\n## ${c.id}\n');
  md.writeln('Entry ${c.fastTf}${c.slowTf.isEmpty ? '' : ', slow ${c.slowTf}'}${c.midTf.isEmpty ? '' : ', mid ${c.midTf}'}'
      '${c.topTf.isEmpty ? '' : ', top ${c.topTf}'}; ${sp.describe()}; ${vs.length} variants × 3 directions.\n');
  final all = <String, List<Trade>>{};
  for (final v in vs) {
    all[v.key] = run(c, v);
  }
  for (final d in ['put', 'call', 'both']) {
    final rows = <(Variant, Stats, Stats)>[];
    for (final v in vs) {
      final t = dirOf(all[v.key]!, d);
      final ds = Stats.of(sp.pick(t, 'disc')), va = Stats.of(sp.pick(t, 'val'));
      rows.add((v, ds, va));
      for (final (part, st) in [('disc', ds), ('val', va)]) {
        csv.writeln('${c.id},"${v.id}",${v.exit.id},$d,$part,${st.n},${st.win.toStringAsFixed(3)},${st.exp.toStringAsFixed(4)},'
            '${st.pf.toStringAsFixed(3)},${st.total.toStringAsFixed(4)},${st.maxDd.toStringAsFixed(4)},${st.hit.toStringAsFixed(3)}');
      }
    }
    // pre-registered selection: discovery only (n >= 30), then validation gate
    final elig = rows.where((r) => r.$2.n >= 30).toList()..sort((x, y) => y.$2.exp.compareTo(x.$2.exp));
    md.writeln('### ${c.id} — direction: ${d.toUpperCase()}\n');
    md.writeln('Discovery top 5 (eligible n ≥ 30: ${elig.length}/${rows.length}; positive expectancy in discovery: '
        '${rows.where((r) => r.$2.n >= 30 && r.$2.exp > 0).length}):\n');
    md.writeln('| variant | exit | split ${Stats.header.substring(1)}');
    md.writeln('|---|---|---${Stats.sep}');
    for (final r in elig.take(5)) {
      md.writeln('| ${r.$1.id} | ${r.$1.exit.id} | disc ${r.$2.row}');
      md.writeln('| | | val ${r.$3.row}');
    }
    final passed = elig.take(5).where((r) => r.$3.n >= 20 && r.$3.exp > 0 && r.$3.pf > 1.1).toList();
    final chosen = passed.isNotEmpty ? passed.first : (elig.isNotEmpty ? elig.first : null);
    if (chosen == null) {
      md.writeln('\nNo variant reached n ≥ 30 in discovery — no selection possible.\n');
    } else {
      final t = dirOf(all[chosen.$1.key]!, d);
      final h = Stats.of(sp.pick(t, 'hold'));
      md.writeln('\n**Selected (discovery rank, ${passed.isNotEmpty ? 'passed validation' : 'FAILED validation — shown for information'}):** '
          '`${chosen.$1.id}` / `${chosen.$1.exit.id}` — holdout ${h.row.replaceAll('|', ' ').trim()}\n');
      csv.writeln('${c.id},"${chosen.$1.id}",${chosen.$1.exit.id},$d,hold,${h.n},${h.win.toStringAsFixed(3)},${h.exp.toStringAsFixed(4)},'
          '${h.pf.toStringAsFixed(3)},${h.total.toStringAsFixed(4)},${h.maxDd.toStringAsFixed(4)},${h.hit.toStringAsFixed(3)}');
      selections.add((c, chosen.$1, d, passed.isNotEmpty, h));
    }
  }
  // the user's spec variants, every split (pre-declared, not selected)
  md.writeln('### ${c.id} — specified rules (pre-declared), all splits\n');
  md.writeln('| variant | exit | dir | split ${Stats.header.substring(1)}');
  md.writeln('|---|---|---|---${Stats.sep}');
  for (final v in vs.where((v) => v.id.startsWith(specPrefix))) {
    for (final d in ['put', 'call', 'both']) {
      final t = dirOf(all[v.key]!, d);
      for (final part in ['disc', 'val', 'hold']) {
        md.writeln('| ${v.id} | ${v.exit.id} | $d | $part ${Stats.of(sp.pick(t, part)).row}');
      }
      md.writeln('| ${v.id} | ${v.exit.id} | $d | **all** ${Stats.of(t).row}');
    }
  }
}

final selections = <(Cfg, Variant, String, bool, Stats)>[];

void main() {
  final tfs = ['d1', 'h1', 'm15', 'm5'];
  S = {for (final tf in tfs) tf: {for (final s in symbols) s: TfSeries.of(tfOf(tf), loadBars(tf, s))}};
  S['w1'] = {for (final s in symbols) s: weeklyFromDaily(S['d1']![s]!.bars)};
  vm = VolModel(S['d1']!, TfSeries.of(BarTimeframe.d1, loadBars('d1', 'VIX')), TfSeries.of(BarTimeframe.d1, loadBars('d1', 'VXN')));
  for (final tf in [...tfs, 'w1']) {
    stdout.writeln('$tf: ${[for (final s in symbols) '$s=${S[tf]![s]!.bars.length}'].join(' ')}');
  }
  md.writeln('# Round 5 — strategy backtests (MODELED option prices on real underlying bars)\n');
  md.writeln('Generated by `trader_core/tool/r5_run.dart`. Options: ATM, next Friday expiry (≥ 2 calendar days), '
      'Black-Scholes with IV proxy (SPY: VIX, QQQ: VXN, stocks: 1.3 × RV20), fill at next bar open + half spread (5% of mid, min \$0.01) '
      '+ 1% slippage + \$0.65/contract each side. Returns are % of premium; "total" sums 2% of equity per trade. '
      'One open trade per symbol. ⚠ = n < 30, ⚠⚠ = n < 10. "dir. hit" = share of trades where the underlying moved in the trade '
      'direction between fill and exit (model-independent).\n');

  // ---------------- Strategy B: MTF RSI ----------------
  final bCfgs = [
    const Cfg('B1 spec: 15m entry / 1h zone (60 days)', fastTf: 'm15', slowTf: 'h1', holdBars: 8),
    const Cfg('B2 shifted: 1h entry / daily zone (~2 years)', fastTf: 'h1', slowTf: 'd1', holdBars: 7),
    const Cfg('B3 shifted: daily entry / weekly zone (since 1998)', fastTf: 'd1', slowTf: 'w1', holdBars: 3, forceBefore: Duration(hours: 26)),
  ];
  for (final c in bCfgs) {
    final vs = <Variant>[];
    for (final ob in [65.0, 70.0, 75.0]) {
      for (final len in [14, 9]) {
        for (final w in [4, 8, 16]) {
          final p = MtfRsiParams(slowOverbought: ob, slowLength: len, fastLength: len, window: w);
          final sigs = {
            for (final sym in symbols)
              if (ser(c.fastTf, sym)!.bars.isNotEmpty) sym: mtfRsiSignals(ser(c.fastTf, sym)!, ser(c.slowTf, sym)!, p)
          };
          final rf = {for (final sym in symbols) sym: rsi([for (final b in ser(c.fastTf, sym)!.bars) b.close], period: len)};
          // the exit closure needs the symbol: build per-symbol variants via a shared map keyed by series identity
          for (final x in [
            ExitRule('time${c.holdBars}', maxHoldBars: c.holdBars),
            const ExitRule('tp50/sl50', tp: 0.5, sl: 0.5),
            ExitRule('rsi50|time${c.holdBars * 3}', maxHoldBars: c.holdBars * 3),
          ]) {
            if (x.id.startsWith('rsi50')) {
              // RSI-50 exit is symbol specific → expand signals into one variant with per-symbol exits
              vs.add(_RsiVariant(p.id, sigs, x, rf, c.holdBars * 3));
            } else {
              vs.add(Variant(p.id, sigs, x));
            }
          }
        }
      }
    }
    evaluate(c, vs, 'ob70-L14/14-W8');
    // threshold 75 as requested
    md.writeln('\n(Threshold 75 spec row: see variants `ob75-L14/14-W8` in the CSV and below.)\n');
    final sp = splitsFor(c);
    md.writeln('| variant | exit | dir | split ${Stats.header.substring(1)}');
    md.writeln('|---|---|---|---${Stats.sep}');
    for (final v in vs.where((v) => v.id == 'ob75-L14/14-W8')) {
      final t = run(c, v);
      for (final d in ['put', 'call', 'both']) {
        for (final part in ['disc', 'val', 'hold']) {
          md.writeln('| ${v.id} | ${v.exit.id} | $d | $part ${Stats.of(sp.pick(dirOf(t, d), part)).row}');
        }
      }
    }
  }

  // ---------------- Strategy A: MTF Elliott ----------------
  final aCfgs = [
    const Cfg('A1 spec: 15m entry / 1h mid / daily top (60 days)', fastTf: 'm15', midTf: 'h1', topTf: 'd1', holdBars: 26),
    const Cfg('A2 spec: 5m entry / 1h mid / daily top (60 days)', fastTf: 'm5', midTf: 'h1', topTf: 'd1', holdBars: 78),
    const Cfg('A3 shifted: 1h entry / daily mid / weekly top (~2 years)', fastTf: 'h1', midTf: 'd1', topTf: 'w1', holdBars: 14),
    const Cfg('A4 shifted: daily entry / weekly mid (since 1998)', fastTf: 'd1', midTf: 'w1', holdBars: 5, forceBefore: Duration(hours: 26)),
  ];
  const base = ElliottParams();
  final variants = <ElliottParams>[
    base,
    base.copyWith(maTrend: true),
    base.copyWith(waveMa: true),
    base.copyWith(sr: true),
    base.copyWith(classical: true),
    base.copyWith(fibPrice: true),
    base.copyWith(fibTime: true),
    base.copyWith(macd: true),
    base.copyWith(maTrend: true, fibPrice: true),
    base.copyWith(maTrend: true, macd: true),
    base.copyWith(fibPrice: true, fibTime: true),
    base.copyWith(maTrend: true, waveMa: true),
    base.copyWith(requireMid: false),
    base.copyWith(kEntry: 1.5),
    base.copyWith(kEntry: 3.0),
    base.copyWith(kEntry: 1.5, requireMid: false),
    base.copyWith(strictContext: true),
  ];
  for (final c in aCfgs) {
    final vs = <Variant>[];
    for (final p0 in variants) {
      final p = c.topTf.isEmpty ? p0.copyWith(requireTop: false) : p0;
      final sigs = {
        for (final sym in symbols)
          if (ser(c.fastTf, sym)!.bars.isNotEmpty)
            sym: mtfElliottSignals(
                entry: ser(c.fastTf, sym)!, mid: ser(c.midTf, sym), top: ser(c.topTf, sym), ma: ser('d1', sym), p: p)
      };
      for (final x in [
        const ExitRule('tp50/sl50', tp: 0.5, sl: 0.5),
        const ExitRule('wave stop+target', useInvalidation: true, useTarget: true),
        ExitRule('time${c.holdBars}', maxHoldBars: c.holdBars),
      ]) {
        vs.add(Variant(p.id, sigs, x));
      }
    }
    evaluate(c, vs, c.topTf.isEmpty ? '+mid base' : 'top+mid base');
  }

  md.writeln('\n## Selections summary\n');
  md.writeln('| config | dir | variant | exit | validation gate | holdout ${Stats.header.substring(1)}');
  md.writeln('|---|---|---|---|---${Stats.sep}');
  for (final (c, v, d, ok, h) in selections) {
    md.writeln('| ${c.id.split(':').first} | $d | ${v.id} | ${v.exit.id} | ${ok ? 'pass' : 'fail'} ${h.row}');
  }

  // Controls: same exits/costs, entries without the strategy's rule.
  md.writeln('\n## Controls (same exit and cost model, no strategy rule)\n');
  md.writeln('`every-5`: an entry on every 5th bar of the entry timeframe (pure drift / option-decay control); '
      '`ctx-only`: every 5th bar but only when the higher-degree impulse context (mid series, same zig-zag) agrees.\n');
  md.writeln('| config | dir | exit | control | split ${Stats.header.substring(1)}');
  md.writeln('|---|---|---|---|---${Stats.sep}');
  for (final (c, v, d, _, _) in selections) {
    if (d == 'both') continue;
    final bull = d == 'call';
    final sp = splitsFor(c);
    for (final ctrl in ['every-5', 'ctx-only']) {
      if (ctrl == 'ctx-only' && c.midTf.isEmpty && c.slowTf.isEmpty) continue;
      final sigs = <String, List<StrategySignal>>{};
      for (final sym in symbols) {
        final e = ser(c.fastTf, sym);
        if (e == null || e.bars.isEmpty) continue;
        final m = ser(c.midTf.isNotEmpty ? c.midTf : c.slowTf, sym);
        final mz = m == null ? const <ZzPivot>[] : atrZigZag(m.bars);
        sigs[sym] = [
          for (var i = 50; i < e.bars.length; i += 5)
            if (ctrl == 'every-5' ||
                (m != null &&
                    impulseContext(knownPivots(mz, m.completedAt(e.ends[i]) - 1), e.bars[i].close) == (bull ? 1 : -1)))
              StrategySignal(index: i, time: e.ends[i], bullish: bull, reasonAr: ctrl)
        ];
      }
      final cv = v is _RsiVariant ? _RsiVariant(ctrl, sigs, v.exit, v.rf, v.hold) : Variant(ctrl, sigs, v.exit);
      final t = run(c, cv);
      for (final part in ['disc', 'val', 'hold']) {
        md.writeln('| ${c.id.split(':').first} | $d | ${v.exit.id} | $ctrl | $part ${Stats.of(sp.pick(t, part)).row}');
      }
      md.writeln('| ${c.id.split(':').first} | $d | ${v.exit.id} | $ctrl | **all** ${Stats.of(t).row}');
    }
  }

  // Sensitivity of selections that passed validation (all periods)
  md.writeln('\n## Sensitivity (selections that passed validation; all periods)\n');
  md.writeln('| config | dir | variant | scenario ${Stats.header.substring(1)}');
  md.writeln('|---|---|---|---${Stats.sep}');
  final cheap = VolModel(vm.daily, vm.vix, vm.vxn, rvMult: 1.0, indexMult: 0.85);
  final rich = VolModel(vm.daily, vm.vix, vm.vxn, rvMult: 1.6, indexMult: 1.15);
  for (final (c, v, d, _, _) in selections.where((s) => s.$4)) {
    for (final (name, costs, model) in [
      ('base', const Costs(), vm),
      ('spread 3%, no slip', const Costs(spreadPct: 0.03, slipPct: 0), vm),
      ('spread 10%, slip 2%', const Costs(spreadPct: 0.10, slipPct: 0.02), vm),
      ('IV cheaper (×1.0 RV / ×0.85 VIX)', const Costs(), cheap),
      ('IV richer (×1.6 RV / ×1.15 VIX)', const Costs(), rich),
    ]) {
      md.writeln('| ${c.id.split(':').first} | $d | ${v.id} / ${v.exit.id} | $name ${Stats.of(dirOf(run(c, v, costs: costs, model: model), d)).row}');
    }
    final idx = dirOf(run(c, v, only: const ['SPY', 'QQQ']), d);
    final f = dirOf(run(c, v, only: const ['SPY', 'QQQ'], maxIvRv: 1.5), d);
    md.writeln('| ${c.id.split(':').first} | $d | ${v.id} / ${v.exit.id} | SPY+QQQ only ${Stats.of(idx).row}');
    md.writeln('| ${c.id.split(':').first} | $d | ${v.id} / ${v.exit.id} | SPY+QQQ, IV/RV ≤ 1.5 ${Stats.of(f).row}');
  }

  File('${outDir.path}/R5_BACKTESTS.md').writeAsStringSync(md.toString());
  File('${outDir.path}/r5_variants.csv').writeAsStringSync(csv.toString());
  stdout.writeln('wrote ${outDir.path}/R5_BACKTESTS.md');
}

/// Variant whose exit also closes when the fast RSI crosses back through 50.
class _RsiVariant extends Variant {
  _RsiVariant(super.id, super.sigs, super.exit, this.rf, this.hold);
  final Map<String, List<double?>> rf;
  final int hold;
}
