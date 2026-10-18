/// Deterministic synthetic market used by the internal simulator broker.
///
/// * Same symbol + same clock => same prices on every device (FNV seed, own PRNG).
/// * Base series is 5-minute bars from [epoch]; larger timeframes aggregate it,
///   so every timeframe and the option prices agree with each other.
/// * Trend regimes + cycles give the analysis engines real swings to find.
/// * Runs 24/7 (no exchange calendar) — it is a simulator, not market data.
library;

import 'dart:math' as math;

import '../models.dart';
import '../options_math.dart';
import 'broker_adapter.dart';

class SyntheticMarket implements MarketDataSource {
  static final DateTime epoch = DateTime.utc(2025, 1, 1);
  static const Duration base = Duration(minutes: 5);

  final DateTime Function() clock;
  final double annualVol;
  final int seed;
  final Map<String, _SeriesState> _series = {};

  SyntheticMarket({DateTime Function()? clock, this.annualVol = 0.35, this.seed = 7})
      : clock = clock ?? (() => DateTime.now().toUtc());

  int _lastCompletedIndex() {
    final elapsed = clock().difference(epoch).inMinutes ~/ base.inMinutes;
    return elapsed - 1; // the current bar is still forming
  }

  /// Base bars kept in memory per symbol (~69 days of 5-minute bars). Older bars
  /// are generated (to keep the random stream identical) but not stored.
  static const int keepBars = 20000;

  /// Returns the stored base series up to [lastIndex]; element k has absolute
  /// index `st.offset + k`.
  _SeriesState _ensure(String symbol, int lastIndex) {
    final st = _series.putIfAbsent(symbol, () => _SeriesState(symbol, seed));
    final stepVol = annualVol / math.sqrt(252 * 78);
    final rng = st.rng;
    for (var i = st.generated; i <= lastIndex; i++) {
      if (st.regimeLeft <= 0) {
        st.regimeLeft = 120 + rng.nextInt(280);
        st.drift = (rng.nextDouble() - 0.5) * 0.0008;
      }
      st.regimeLeft--;
      final wave = 0.35 * math.sin(2 * math.pi * i / st.cycleLen);
      final ret = st.drift + stepVol * (wave + rng.nextGaussian());
      final open = st.close;
      final close = math.max(0.5, open * math.exp(ret));
      st.close = close;
      final wick = stepVol * 0.6;
      final gHigh = rng.nextGaussian().abs(), gLow = rng.nextGaussian().abs();
      final volume = (50000 + rng.nextInt(150000)).toDouble();
      st.generated = i + 1;
      if (i <= lastIndex - keepBars) continue; // too old to keep
      final high = math.max(open, close) * (1 + gHigh * wick);
      final low = math.min(open, close) * (1 - gLow * wick);
      final o = _r(open), c = _r(close);
      if (st.candles.isEmpty) st.offset = i;
      st.candles.add(Candle(
        time: epoch.add(base * i),
        open: o,
        high: math.max(_r(high), math.max(o, c)),
        low: math.min(_r(low), math.min(o, c)),
        close: c,
        volume: volume,
      ));
    }
    final excess = st.candles.length - keepBars;
    if (excess > 0) {
      st.candles.removeRange(0, excess);
      st.offset += excess;
    }
    return st;
  }

  @override
  Future<List<Candle>> bars(String symbol, BarTimeframe timeframe, {int limit = 300}) async {
    final last = _lastCompletedIndex();
    if (last < 0) return const [];
    final per = timeframe.duration.inMinutes ~/ base.inMinutes;
    // Only whole groups that are complete.
    final groups = (last + 1) ~/ per;
    if (groups == 0) return const [];
    final st = _ensure(symbol, groups * per - 1);
    final oldestGroup = (st.offset + per - 1) ~/ per; // first group fully in memory
    final firstGroup = math.max(oldestGroup, groups - limit);
    final out = <Candle>[];
    for (var g = firstGroup; g < groups; g++) {
      final from = g * per - st.offset;
      final slice = st.candles.sublist(from, from + per);
      out.add(Candle(
        time: slice.first.time,
        open: slice.first.open,
        high: slice.map((c) => c.high).reduce(math.max),
        low: slice.map((c) => c.low).reduce(math.min),
        close: slice.last.close,
        volume: slice.fold<double>(0, (s, c) => s + c.volume),
      ));
    }
    return out;
  }

  @override
  Future<double> lastPrice(String symbol) async {
    final last = _lastCompletedIndex();
    if (last < 0) throw const BrokerException(BrokerErrorCode.notFound, 'No synthetic data yet');
    final st = _ensure(symbol, last);
    return st.candles[last - st.offset].close;
  }

  /// Strike spacing similar to US listed options.
  static double strikeStep(double spot) => spot < 25 ? 0.5 : spot < 100 ? 1 : spot < 250 ? 2.5 : 5;

  /// Weekly Friday expirations strictly after today.
  List<DateTime> expirations(DateTime from, DateTime to) {
    final out = <DateTime>[];
    var d = DateTime.utc(from.year, from.month, from.day);
    final now = clock();
    final today = DateTime.utc(now.year, now.month, now.day);
    while (!d.isAfter(to)) {
      if (d.weekday == DateTime.friday && d.isAfter(today)) out.add(d);
      d = d.add(const Duration(days: 1));
    }
    return out;
  }

  OptionQuote quoteFor(OptionContract c, double spot) {
    final now = clock();
    // Expire at 20:00 UTC on expiry day.
    final expiryMoment = c.expiry.add(const Duration(hours: 20));
    final years = math.max(0.0, expiryMoment.difference(now).inMinutes / (365 * 24 * 60));
    final bs = blackScholes(
      isCall: c.right == OptionRight.call,
      spot: spot,
      strike: c.strike,
      years: years,
      vol: annualVol,
    );
    final midCents = math.max(1, (bs.price * 100).round());
    final half = math.max(1, (midCents * 0.015).round());
    return OptionQuote(
      contract: c,
      bidCents: math.max(0, midCents - half),
      askCents: midCents + half,
      time: now,
      volume: 500,
      openInterest: 5000,
      delta: bs.delta,
      impliedVolatility: annualVol,
    );
  }

  @override
  Future<List<OptionQuote>> optionChain(String underlying,
      {required DateTime minExpiry, required DateTime maxExpiry, OptionRight? right}) async {
    final spot = await lastPrice(underlying);
    final step = strikeStep(spot);
    final atm = (spot / step).round() * step;
    final out = <OptionQuote>[];
    for (final exp in expirations(minExpiry, maxExpiry)) {
      for (var k = -12; k <= 12; k++) {
        final strike = atm + k * step;
        if (strike <= 0) continue;
        for (final r in OptionRight.values) {
          if (right != null && r != right) continue;
          final c = OptionContract(
              underlying: underlying, right: r, expiry: exp, strikeCents: (strike * 100).round());
          out.add(quoteFor(c, spot));
        }
      }
    }
    return out;
  }

  @override
  Future<OptionQuote?> optionQuote(OptionContract contract) async {
    final spot = await lastPrice(contract.underlying);
    return quoteFor(contract, spot);
  }

  static double _r(double v) => (v * 100).roundToDouble() / 100;

  static int _fnv(String s) {
    var h = 0x811c9dc5;
    for (final cu in s.codeUnits) {
      h ^= cu;
      h = (h * 0x01000193) & 0xffffffff;
    }
    return h;
  }
}

class _SeriesState {
  final _Prng rng;
  final List<Candle> candles = [];
  int offset = 0; // absolute index of candles[0]
  int generated = 0; // number of base bars generated so far
  final int cycleLen;
  double close;
  double drift = 0;
  int regimeLeft = 0;

  _SeriesState(String symbol, int seed)
      : rng = _Prng(SyntheticMarket._fnv(symbol) ^ seed),
        cycleLen = 60 + SyntheticMarket._fnv('$symbol/c') % 140,
        close = 20.0 + SyntheticMarket._fnv(symbol) % 480;
}

/// Small deterministic PRNG (mulberry32) — identical on every platform,
/// unlike `dart:math` Random whose algorithm is not specified.
class _Prng {
  int _state;
  double? _spare;
  _Prng(int seed) : _state = seed & 0xffffffff;

  int _next32() {
    _state = (_state + 0x6D2B79F5) & 0xffffffff;
    var t = _state;
    t = _imul(t ^ (t >> 15), t | 1);
    t ^= (t + _imul(t ^ (t >> 7), t | 61)) & 0xffffffff;
    return (t ^ (t >> 14)) & 0xffffffff;
  }

  static int _imul(int a, int b) => (a * b) & 0xffffffff;

  double nextDouble() => _next32() / 4294967296.0;

  int nextInt(int max) => (nextDouble() * max).floor();

  double nextGaussian() {
    final s = _spare;
    if (s != null) {
      _spare = null;
      return s;
    }
    double u, v, q;
    do {
      u = nextDouble() * 2 - 1;
      v = nextDouble() * 2 - 1;
      q = u * u + v * v;
    } while (q == 0 || q >= 1);
    final m = math.sqrt(-2 * math.log(q) / q);
    _spare = v * m;
    return u * m;
  }
}
