// Round-5 research harness (not shipped in the app). Modeled option P&L on real
// underlying bars; see rebuild/ROUND5.md for the assumptions.
import 'dart:io';
import 'dart:math' as math;

import 'package:trader_core/trader_core.dart';

const symbols = ['SPY', 'QQQ', 'AAPL', 'MSFT', 'NVDA', 'TSLA', 'AMZN'];
final dataDir = '${File(Platform.script.toFilePath()).parent.parent.parent.path}/research/data';

List<Candle> loadBars(String tf, String sym) {
  final f = File('$dataDir/$tf/$sym.csv');
  if (!f.existsSync()) return const [];
  final out = <Candle>[];
  for (final line in f.readAsLinesSync()) {
    if (line.startsWith('#') || line.startsWith('time')) continue;
    final x = line.split(',');
    if (x.length < 6) continue;
    final t = DateTime.parse(x[0]);
    var o = double.tryParse(x[1]), h = double.tryParse(x[2]), l = double.tryParse(x[3]), c = double.tryParse(x[4]);
    final v = double.tryParse(x[5]) ?? 0;
    if (o == null || h == null || l == null || c == null || o <= 0 || c <= 0 || l <= 0) continue;
    if (tf != 'd1') {
      final w = NewYorkTime.wall(t);
      if (w.hour * 60 + w.minute >= 16 * 60) continue; // 16:00 closing print
      if (w.hour * 60 + w.minute < 9 * 60 + 30) continue;
    }
    h = [h, o, c, l].reduce(math.max);
    l = [l, o, c, h].reduce(math.min);
    if (out.isNotEmpty && !t.isAfter(out.last.time)) continue;
    out.add(Candle(time: t, open: o, high: h, low: l, close: c, volume: v));
  }
  return out;
}

BarTimeframe tfOf(String s) => BarTimeframe.values.firstWhere((t) => t.name == s);

/// Option cost model (modeled, not real fills).
class Costs {
  final double spreadPct; // full bid/ask spread as fraction of mid
  final double minSpread; // $ per share
  final double slipPct; // extra slippage per side, fraction of mid
  final double feePerContract; // $ per contract per side
  const Costs({this.spreadPct = 0.05, this.minSpread = 0.02, this.slipPct = 0.01, this.feePerContract = 0.65});
  double buy(double mid) => mid + math.max(minSpread / 2, mid * spreadPct / 2) + mid * slipPct + feePerContract / 100;
  double sell(double mid) => math.max(0, mid - math.max(minSpread / 2, mid * spreadPct / 2) - mid * slipPct - feePerContract / 100);
}

/// IV proxy per symbol: VIX (SPY) / VXN (QQQ) previous completed close, else
/// RV20 of completed daily bars × [rvMult]. Also RV20 for the IV/RV filter.
class VolModel {
  final Map<String, TfSeries> daily;
  final TfSeries? vix, vxn;
  final double rvMult, indexMult;
  VolModel(this.daily, this.vix, this.vxn, {this.rvMult = 1.3, this.indexMult = 1.0});

  double? rv(String sym, DateTime t, {int lookback = 20}) {
    final d = daily[sym]!;
    final n = d.completedAt(t);
    if (n < lookback + 1) return null;
    return realizedVol([for (var i = n - lookback - 1; i < n; i++) d.bars[i].close], lookback: lookback);
  }

  double? iv(String sym, DateTime t) {
    final idx = sym == 'SPY' ? vix : (sym == 'QQQ' ? vxn : null);
    if (idx != null) {
      final n = idx.completedAt(t);
      if (n == 0) return null;
      return idx.bars[n - 1].close / 100 * indexMult;
    }
    final r = rv(sym, t);
    return r == null ? null : math.max(0.08, r * rvMult);
  }
}

class ExitRule {
  final String id;
  final double tp, sl; // option value change, fraction; 0 = off
  final double trailAct, trailPct;
  final int maxHoldBars; // entry-timeframe bars; 0 = until forced
  final bool useInvalidation, useTarget;
  final bool Function(int k, bool bullish)? extra;
  const ExitRule(this.id,
      {this.tp = 0,
      this.sl = 0,
      this.trailAct = 0,
      this.trailPct = 0,
      this.maxHoldBars = 0,
      this.useInvalidation = false,
      this.useTarget = false,
      this.extra});
}

class Trade {
  final String sym;
  final DateTime signal, entry, exit;
  final bool bullish;
  final double ret, undMove;
  final double? ivRv, beToExp;
  final int bars;
  final String exitWhy;
  Trade(this.sym, this.signal, this.entry, this.exit, this.bullish, this.ret, this.undMove, this.ivRv, this.beToExp, this.bars,
      this.exitWhy);
}

DateTime expiryFor(DateTime entry, {int minDays = 2, bool weekly = true}) {
  final w = NewYorkTime.wall(entry);
  var d = DateTime.utc(w.year, w.month, w.day);
  final today = d;
  while (true) {
    d = d.add(const Duration(days: 1));
    if (d.weekday == DateTime.friday && d.difference(today).inDays >= minDays) break;
  }
  return NewYorkTime.toUtc(d.year, d.month, d.day, 16);
}

double years(DateTime a, DateTime b) => math.max(0, b.difference(a).inMinutes) / (365 * 24 * 60);

/// Simulates one long option per signal (one open trade per symbol at a time).
List<Trade> simulate({
  required String sym,
  required TfSeries s,
  required List<StrategySignal> signals,
  required ExitRule x,
  required VolModel vm,
  Costs costs = const Costs(),
  int minDays = 2,
  Duration forceBefore = const Duration(hours: 1),
  double? maxIvRv,
  double? maxBeToExp,
}) {
  final out = <Trade>[];
  DateTime? busyUntil;
  for (final sig in signals) {
    final f = sig.index + 1;
    if (f >= s.bars.length) continue;
    final t0 = s.bars[f].time;
    if (busyUntil != null && !t0.isAfter(busyUntil)) continue;
    // Prices are normalised so the underlying is 100 at the fill (scale
    // invariant: split-adjusted history and \$ minimum spreads/fees comparable).
    final scale = 100 / s.bars[f].open;
    const s0 = 100.0;
    final exp = expiryFor(t0, minDays: minDays);
    const k = 100.0;
    final iv0 = vm.iv(sym, t0), rv0 = vm.rv(sym, t0);
    if (iv0 == null) continue;
    final call = sig.bullish;
    final y0 = years(t0, exp);
    final mid0 = blackScholes(isCall: call, spot: s0, strike: k, years: y0, vol: iv0).price;
    if (mid0 < 0.05) continue;
    final ivRv = rv0 == null || rv0 <= 0 ? null : iv0 / rv0;
    final be = call ? math.max(0.0, k + mid0 - s0) : math.max(0.0, s0 - (k - mid0));
    final expMove = rv0 == null ? null : s0 * rv0 * math.sqrt(y0);
    final beExp = expMove == null || expMove <= 0 ? null : be / expMove;
    if (maxIvRv != null && (ivRv == null || ivRv > maxIvRv)) continue;
    if (maxBeToExp != null && (beExp == null || beExp > maxBeToExp)) continue;
    final cost = costs.buy(mid0);
    var peak = mid0;
    Trade? tr;
    for (var j = f; j < s.bars.length; j++) {
      final e = s.ends[j];
      final sp = s.bars[j].close * scale;
      final left = exp.difference(e);
      final iv = vm.iv(sym, e) ?? iv0;
      final mid = left.inMinutes <= 0
          ? math.max(0.0, call ? sp - k : k - sp)
          : blackScholes(isCall: call, spot: sp, strike: k, years: years(e, exp), vol: iv).price;
      peak = math.max(peak, mid);
      String? why;
      final ch = mid / mid0 - 1;
      if (x.sl > 0 && ch <= -x.sl) why = 'sl';
      if (why == null && x.tp > 0 && ch >= x.tp) why = 'tp';
      if (why == null && x.trailAct > 0 && peak / mid0 - 1 >= x.trailAct && mid <= peak * (1 - x.trailPct)) why = 'trail';
      if (why == null && x.useInvalidation && sig.invalidation != null && (call ? sp < sig.invalidation! * scale : sp > sig.invalidation! * scale)) {
        why = 'invalid';
      }
      if (why == null && x.useTarget && sig.target != null && (call ? sp >= sig.target! * scale : sp <= sig.target! * scale)) why = 'target';
      if (why == null && x.extra != null && x.extra!(j, call)) why = 'rule';
      if (why == null && x.maxHoldBars > 0 && j - f + 1 >= x.maxHoldBars) why = 'time';
      if (why == null && left <= forceBefore) why = 'expiry';
      if (why != null) {
        final proceeds = costs.sell(mid);
        tr = Trade(sym, sig.time, t0, e, call, proceeds / cost - 1, (call ? 1 : -1) * (sp / s0 - 1), ivRv, beExp, j - f + 1, why);
        break;
      }
    }
    if (tr == null) continue; // data ended with the trade open: dropped
    out.add(tr);
    busyUntil = tr.exit;
  }
  return out;
}

class Stats {
  final int n;
  final double win, exp, pf, total, maxDd, hit, avgWin, avgLoss;
  Stats(this.n, this.win, this.exp, this.pf, this.total, this.maxDd, this.hit, this.avgWin, this.avgLoss);

  /// [riskFrac]: premium per trade as fraction of starting equity (simple sum).
  factory Stats.of(List<Trade> t, {double riskFrac = 0.02}) {
    if (t.isEmpty) return Stats(0, 0, 0, 0, 0, 0, 0, 0, 0);
    final s = [...t]..sort((a, b) => a.exit.compareTo(b.exit));
    var eq = 1.0, peak = 1.0, dd = 0.0, gp = 0.0, gl = 0.0, w = 0, h = 0, sum = 0.0;
    for (final x in s) {
      eq += x.ret * riskFrac;
      peak = math.max(peak, eq);
      dd = math.max(dd, (peak - eq) / peak);
      if (x.ret > 0) {
        w++;
        gp += x.ret;
      } else {
        gl += -x.ret;
      }
      if (x.undMove > 0) h++;
      sum += x.ret;
    }
    final l = s.length - w;
    return Stats(s.length, w / s.length, sum / s.length, gl == 0 ? (gp > 0 ? 99 : 0) : gp / gl, eq - 1, dd, h / s.length,
        w == 0 ? 0 : gp / w, l == 0 ? 0 : -gl / l);
  }

  String get warn => n < 10 ? ' ⚠⚠' : (n < 30 ? ' ⚠' : '');
  static const header = '| n | win % | expectancy | PF | total (2%/trade) | max DD | dir. hit % |';
  static const sep = '|---|---|---|---|---|---|---|';
  String get row => n == 0
      ? '| 0 | — | — | — | — | — | — |'
      : '| $n$warn | ${(win * 100).toStringAsFixed(0)} | ${_pct(exp)} | ${pf >= 99 ? '∞' : pf.toStringAsFixed(2)} | '
          '${_pct(total)} | ${(maxDd * 100).toStringAsFixed(1)}% | ${(hit * 100).toStringAsFixed(0)} |';
  static String _pct(double v) => '${v >= 0 ? '+' : ''}${(v * 100).toStringAsFixed(1)}%';
}

/// Chronological split boundaries: discovery 50%, validation 25%, holdout 25%.
class Splits {
  final DateTime a, b;
  Splits(DateTime start, DateTime end)
      : a = start.add(end.difference(start) * 0.5),
        b = start.add(end.difference(start) * 0.75);
  String of(DateTime t) => t.isBefore(a) ? 'disc' : (t.isBefore(b) ? 'val' : 'hold');
  List<Trade> pick(List<Trade> t, String part) => [for (final x in t) if (of(x.signal) == part) x];
  String describe() => 'discovery < ${NewYorkTime.dateKey(a)} ≤ validation < ${NewYorkTime.dateKey(b)} ≤ holdout';
}
