/// Strategy A — multi-timeframe Elliott (round 5, experimental).
///
/// Waves are labelled from deterministic ATR zig-zag pivots on three degrees
/// (top, mid, entry). Entry is the end of a corrective leg on the entry degree,
/// confirmed by an RSI divergence between its sub-waves a and c, inside a
/// higher-degree impulse:
///   CALL: top (and optionally mid) impulse context bullish; entry-degree
///         L0-H1-L2 with L2 > L0 (wave 2 not beyond the start of wave 1), the
///         wave-2 retracement in range, and wave 2's c-low below its a-low
///         with a higher RSI (bullish divergence).
///   PUT : mirror — bearish context; H0-L1-H2 with H2 < H0 (the corrective
///         rally, wave C, ends below the start of the prior down-leg) and wave
///         C's high above wave A's high with a lower RSI (bearish divergence).
/// The signal fires at the bar that *confirms* L2/H2 (the zig-zag reversal),
/// never at the pivot bar itself. Optional confluences: MA trend, wave vs MA,
/// S/R, double bottom/top, Fibonacci price and time ratios, MACD.
/// Rules in `rebuild/docs/STRATEGY_MTF_ELLIOTT.md`.
library;


import '../analysis/indicators.dart';
import 'common.dart';

class ElliottParams {
  final double kTop, kMid, kEntry, kFine;
  final double retraceMin, retraceMax;
  final bool requireTop, requireMid;

  /// Enforce wave-4/wave-3 impulse rules on the higher-degree counts.
  final bool strictContext;
  final int rsiLength;

  // confluences (all off = base variant)
  final bool maTrend; // MA series: close > SMA50, SMA20 > SMA50 > SMA200 (mirror for puts)
  final bool waveMa; // entry: wave 1 crossed SMA50, wave-2 end within 1 ATR of SMA50, close back beyond it
  final bool sr; // wave-2 end within 0.5 ATR of a mid-degree pivot level
  final bool classical; // double bottom/top: |a - c| <= 0.5 ATR
  final bool fibPrice; // retrace 0.5–0.786 (±0.03) and C/A ≈ 1 or 1.618 (±15%)
  final bool fibTime; // duration(w2)/duration(w1) within 10% of 0.382/0.618/1/1.618/2.618
  final bool macd; // MACD histogram divergence a→c and histogram turning in trade direction
  final bool calls, puts;

  const ElliottParams({
    this.kTop = 2.0,
    this.kMid = 2.0,
    this.kEntry = 2.0,
    this.kFine = 0.6,
    this.retraceMin = 0.236,
    this.retraceMax = 0.999,
    this.requireTop = true,
    this.requireMid = true,
    this.strictContext = false,
    this.rsiLength = 14,
    this.maTrend = false,
    this.waveMa = false,
    this.sr = false,
    this.classical = false,
    this.fibPrice = false,
    this.fibTime = false,
    this.macd = false,
    this.calls = true,
    this.puts = true,
  });

  ElliottParams copyWith({
    bool? requireTop,
    bool? requireMid,
    bool? strictContext,
    double? kFine,
    bool? maTrend,
    bool? waveMa,
    bool? sr,
    bool? classical,
    bool? fibPrice,
    bool? fibTime,
    bool? macd,
    double? kEntry,
  }) =>
      ElliottParams(
        kTop: kTop,
        kMid: kMid,
        kEntry: kEntry ?? this.kEntry,
        kFine: kFine ?? this.kFine,
        retraceMin: retraceMin,
        retraceMax: retraceMax,
        requireTop: requireTop ?? this.requireTop,
        requireMid: requireMid ?? this.requireMid,
        strictContext: strictContext ?? this.strictContext,
        rsiLength: rsiLength,
        maTrend: maTrend ?? this.maTrend,
        waveMa: waveMa ?? this.waveMa,
        sr: sr ?? this.sr,
        classical: classical ?? this.classical,
        fibPrice: fibPrice ?? this.fibPrice,
        fibTime: fibTime ?? this.fibTime,
        macd: macd ?? this.macd,
        calls: calls,
        puts: puts,
      );

  String get id {
    final f = [
      if (maTrend) 'MA',
      if (waveMa) 'waveMA',
      if (sr) 'SR',
      if (classical) 'DBL',
      if (fibPrice) 'fibP',
      if (fibTime) 'fibT',
      if (macd) 'MACD',
    ];
    return '${requireTop ? 'top' : ''}${requireMid ? '+mid' : ''}${f.isEmpty ? ' base' : ' ${f.join('+')}'}'
        '${kEntry != 2.0 ? ' k${kEntry.toStringAsFixed(1)}' : ''}${kFine != 0.6 ? ' fine${kFine.toStringAsFixed(2)}' : ''}'
        '${strictContext ? ' strict' : ''}';
  }
}

bool _nearFib(double r, List<double> levels, double tol) => levels.any((l) => (r - l).abs() <= l * tol);

/// Signals on [entry]; [mid] and [top] are higher degrees; [ma] is the series
/// for the MA-trend confluence (usually daily). Any of them may be null when the
/// corresponding requirement/filter is off.
List<StrategySignal> mtfElliottSignals({
  required TfSeries entry,
  TfSeries? mid,
  TfSeries? top,
  TfSeries? ma,
  required ElliottParams p,
}) {
  final c = entry.bars;
  final cl = [for (final b in c) b.close];
  final r = rsi(cl, period: p.rsiLength);
  final a = atr(c);
  final sma50 = sma(cl, 50);
  final hist = macd(cl).histogram;
  final zz = atrZigZag(c, k: p.kEntry);
  final fine = atrZigZag(c, k: p.kFine);
  final midZz = mid == null ? const <ZzPivot>[] : atrZigZag(mid.bars, k: p.kMid);
  final topZz = top == null ? const <ZzPivot>[] : atrZigZag(top.bars, k: p.kTop);
  List<double?>? m20, m50, m200;
  if (ma != null) {
    final mc = [for (final b in ma.bars) b.close];
    m20 = sma(mc, 20);
    m50 = sma(mc, 50);
    m200 = sma(mc, 200);
  }

  List<ZzPivot> known(List<ZzPivot> z, TfSeries s, DateTime t) {
    final n = s.completedAt(t);
    if (n == 0) return const [];
    return knownPivots(z, n - 1);
  }

  final out = <StrategySignal>[];
  var fineKnown = 0;
  for (var zi = 0; zi < zz.length; zi++) {
    final piv = zz[zi];
    final i = piv.confirmedIndex;
    if (zi < 2 || i >= c.length) continue;
    final bull = !piv.isHigh;
    if (bull && !p.calls || !bull && !p.puts) continue;
    final p0 = zz[zi - 2], p1 = zz[zi - 1], p2 = piv;
    final t = entry.ends[i];
    final price = cl[i];
    final atrI = a[i];
    if (atrI == null || r[p2.index] == null) continue;
    final dir = bull ? 1 : -1;

    // wave 2 / wave C structure on the entry degree
    final w1 = (p1.price - p0.price).abs();
    if (w1 <= 0) continue;
    if (bull ? p2.price <= p0.price : p2.price >= p0.price) continue;
    final retr = (p1.price - p2.price).abs() / w1;
    if (retr < p.retraceMin || retr > p.retraceMax) continue;
    if (bull ? price <= p2.price : price >= p2.price) continue;

    // sub-waves a-b-c of the correction from the fine zig-zag known at i
    while (fineKnown < fine.length && fine[fineKnown].confirmedIndex <= i) {
      fineKnown++;
    }
    final seg = [for (var k = 0; k < fineKnown; k++) if (fine[k].index > p1.index && fine[k].index < p2.index) fine[k]];
    ZzPivot? subA, subB;
    for (var k = seg.length - 1; k >= 0; k--) {
      final f = seg[k];
      if (subB == null) {
        if (f.isHigh == bull) subB = f; // b is a high in a down-correction
      } else if (f.isHigh != bull) {
        subA = f;
        break;
      }
    }
    if (subA == null || subB == null || r[subA.index] == null) continue;
    final div = bull ? r[p2.index]! > r[subA.index]! : r[p2.index]! < r[subA.index]!;
    if (!div) continue;

    // higher-degree context
    final topCtx = top == null ? 0 : impulseContext(known(topZz, top, t), price, strict: p.strictContext);
    final midCtx = mid == null ? 0 : impulseContext(known(midZz, mid, t), price, strict: p.strictContext);
    if (p.requireTop && topCtx != dir) continue;
    if (p.requireMid && midCtx != dir) continue;

    // confluences
    final feats = <String, Object?>{
      'retrace': retr,
      'rsiA': r[subA.index],
      'rsiC': r[p2.index],
      'topCtx': topCtx,
      'midCtx': midCtx,
    };
    var ok = true;
    if (p.maTrend) {
      final n = ma == null ? 0 : ma.completedAt(t);
      final j = n - 1;
      bool pass = false;
      if (j >= 0 && m200![j] != null) {
        final x = ma!.bars[j].close, s20 = m20![j]!, s50 = m50![j]!, s200 = m200[j]!;
        pass = bull ? (x > s50 && s20 > s50 && s50 > s200) : (x < s50 && s20 < s50 && s50 < s200);
      }
      ok &= pass;
    }
    if (ok && p.waveMa) {
      final m1 = sma50[p1.index], m2 = sma50[p2.index], mi = sma50[i];
      ok = m1 != null &&
          m2 != null &&
          mi != null &&
          (bull ? p1.price > m1 : p1.price < m1) &&
          (p2.price - m2).abs() <= atrI &&
          (bull ? price > mi : price < mi);
    }
    if (ok && p.sr) {
      final mp = mid == null ? const <ZzPivot>[] : known(midZz, mid, t);
      final recent = mp.length > 12 ? mp.sublist(mp.length - 12) : mp;
      ok = recent.any((q) => (q.price - p2.price).abs() <= 0.5 * atrI);
    }
    if (ok && p.classical) ok = (subA.price - p2.price).abs() <= 0.5 * atrI;
    final lenA = (p1.price - subA.price).abs(), lenC = (subB.price - p2.price).abs();
    final ca = lenA > 0 ? lenC / lenA : 0.0;
    feats['cOverA'] = ca;
    if (ok && p.fibPrice) {
      ok = retr >= 0.47 && retr <= 0.816 && _nearFib(ca, const [1.0, 1.618], 0.15);
    }
    final d1 = (p1.index - p0.index).abs(), d2 = (p2.index - p1.index).abs();
    final tr = d1 > 0 ? d2 / d1 : 0.0;
    feats['timeRatio'] = tr;
    if (ok && p.fibTime) ok = _nearFib(tr, const [0.382, 0.618, 1.0, 1.618, 2.618], 0.10);
    if (ok && p.macd) {
      final hc = hist[p2.index], ha = hist[subA.index], h0 = hist[i], hm = hist[i - 1];
      ok = hc != null &&
          ha != null &&
          h0 != null &&
          hm != null &&
          (bull ? (hc > ha && h0 > hm) : (hc < ha && h0 < hm));
    }
    if (!ok) continue;

    out.add(StrategySignal(
      index: i,
      time: t,
      bullish: bull,
      reasonAr: bull
          ? 'نهاية الموجة 2 (a-b-c) مع انحراف RSI إيجابي داخل دافعة صاعدة أعلى؛ تصحيح ${(retr * 100).toStringAsFixed(0)}% → Call'
          : 'نهاية الموجة C مع انحراف RSI سلبي داخل اتجاه هابط أعلى؛ ارتداد ${(retr * 100).toStringAsFixed(0)}% → Put',
      invalidation: p2.price,
      target: p2.price + dir * 1.618 * w1,
      features: feats,
    ));
  }
  return out;
}


