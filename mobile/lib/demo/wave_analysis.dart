// Local synthetic/Shadow research. No order, risk, broker or network capability.
import 'dart:convert';
import 'dart:math' as math;

import 'chart_analysis.dart';

const legacyWaveContract='demo-wave-pivots-4-2-v1';
const marketWaveContract='confirmed-wave-pivots-3-1-v1';

class ChartWaveScenario {
  final String id, kind, degree;
  final bool bullish;
  final List<ChartPivot> points;
  final List<String> labels;
  final double invalidation, activation, evidence;
  final List<double> targets;
  final int observedAt;
  final String? parentId;

  ChartWaveScenario._(this.kind, this.degree, List<ChartPivot> points,
      List<String> labels, this.invalidation, this.activation,
      List<double> targets, this.evidence, {this.parentId, int? knownAt})
      : points = List.unmodifiable(points), labels = List.unmodifiable(labels),
        targets = List.unmodifiable(targets.where((t) => t > 0)),
        bullish = !points.first.high,
        observedAt = math.max(knownAt ?? 0,
            points.map((p) => p.confirmedAt).reduce(math.max)),
        // An identity, not a security hash. All original geometry is included.
        id = jsonEncode([kind, degree, parentId,
          for (final p in points) [p.index, p.confirmedAt, p.price, p.high]]);

  String get name => switch (kind) {
    'third' => 'مرشح الموجة الثالثة',
    'abc' => 'مرشح ABC / الموجة C',
    'fifth' => 'الموجة الخامسة قيد الانتظار',
    'impulse' => 'مرشح دافع مكتمل 1–5',
    'third_of_third' => 'مرشح الثالثة من الثالثة 3 of 3',
    _ => kind,
  };

  Map<String, dynamic> toJson() => {
    'id': id, 'kind': kind, 'degree': degree, 'bullish': bullish,
    'points': [for (final p in points)
      [p.index, p.confirmedAt, p.price, p.high]],
    'labels': labels, 'invalidation': invalidation, 'activation': activation,
    'targets': targets, 'evidence': evidence, 'observed_at': observedAt,
    'parent_id': parentId, 'mode': 'SHADOW', 'executable': false,
  };

  ChartPattern drawing({bool alternate = false}) => ChartPattern(
    name, points, invalidation, targets.isEmpty ? activation : targets.first,
    labels: labels, alternate: alternate,
  );
}

class ChartWaveAnalysis {
  /// Non-diagonal impulse and zigzag candidates. ABC and W3 can compete on
  /// identical observed geometry; neither is promoted to an established fact.
  static List<ChartWaveScenario> candidates(List<ChartPivot> points,
      {String degree = 'main'}) {
    if (degree != 'main' && degree != 'internal') {
      throw ArgumentError.value(degree, 'degree');
    }
    for (var i = 0; i < points.length; i++) {
      final p = points[i];
      if (!p.price.isFinite || p.price <= 0 || p.index < 0 ||
          p.confirmedAt < p.index || (i > 0 &&
          (p.index <= points[i - 1].index ||
           p.confirmedAt < points[i - 1].confirmedAt))) {
        throw const FormatException('Invalid or unordered confirmed pivots');
      }
    }
    final out = <ChartWaveScenario>[];
    for (final length in [4, 5, 6]) {
      for (var start = math.max(0, points.length - 64);
          start + length <= points.length; start++) {
        final p = points.sublist(start, start + length);
        if (List.generate(length - 1, (i) => p[i].high == p[i + 1].high)
            .any((v) => v)) { continue; }
        final sign = p.first.high ? -1 : 1;
        final v = p.map((q) => q.price * sign).toList();
        final first = v[1] - v[0];
        if (first <= 0 || !(v[0] < v[2] && v[2] < v[1] && v[1] < v[3])) {
          continue;
        }
        void add(String kind, List<String> labels, double invalidation,
            double activation, List<double> targets, double score) {
          out.add(ChartWaveScenario._(kind, degree, p, labels, invalidation,
              activation, targets, score));
        }
        if (length == 4) {
          final third = v[3] - v[2];
          add('third', ['0', '1', '2', '3?'], p[2].price, p[1].price,
            [p[2].price + sign * first * 1.618,
             p[2].price + sign * first * 2.618], third >= first * 1.618 ? .75 : .6);
          if (third / first >= .5 && third / first <= 2.618) {
            add('abc', ['0', 'A', 'B', 'C'], p[0].price, p[1].price,
              [p[2].price + sign * first, p[2].price + sign * first * 1.618], .5);
          }
        } else if (v[1] < v[4] && v[4] < v[3]) {
          if (length == 5) {
            add('fifth', ['0', '1', '2', '3', '4'], p[4].price, p[3].price,
              [p[4].price + sign * first, p[4].price + sign * first * 1.618], .7);
          } else if (v[5] > v[3] &&
              v[3] - v[2] >= math.min(first, v[5] - v[4])) {
            add('impulse', ['0', '1', '2', '3', '4', '5'], p[4].price,
              p[5].price, [p[5].price - sign * (v[5] - v[0]) * .382,
              p[5].price - sign * (v[5] - v[0]) * .618], .85);
          }
        }
      }
    }
    return List.unmodifiable(out);
  }

  static List<ChartWaveScenario> nestedThirds(
      List<ChartWaveScenario> main, List<ChartWaveScenario> internal) {
    final out = <ChartWaveScenario>[];
    for (final outer in main.where((s) => s.kind == 'third' && s.degree == 'main')) {
      for (final inner in internal.where((s) => s.kind == 'third' && s.degree == 'internal')) {
        if (inner.bullish != outer.bullish ||
            inner.points.first.index < outer.points[2].index ||
            inner.points.last.index > outer.points[3].index) { continue; }
        out.add(ChartWaveScenario._('third_of_third', 'internal', inner.points,
          ['(0)', '(1)', '(2)', '(3)?'], inner.invalidation, inner.activation,
          inner.targets, math.min(inner.evidence, outer.evidence),
          parentId: outer.id, knownAt: math.max(inner.observedAt, outer.observedAt)));
      }
    }
    return List.unmodifiable(out);
  }

  /// Complete, fixed-origin groups only. In-progress higher-frame candles are
  /// never used. `tick` is the last observed source tick, not a wall-clock minute.
  static List<DemoCandle> aggregate(List<DemoCandle> bars, int factor) {
    if (factor < 1) throw ArgumentError.value(factor, 'factor');
    _validateBars(bars);
    final out = <DemoCandle>[];
    for (var start = 0; start + factor <= bars.length; start += factor) {
      final group = bars.sublist(start, start + factor);
      out.add(DemoCandle(group.last.tick, group.first.open,
        group.map((b) => b.high).reduce(math.max),
        group.map((b) => b.low).reduce(math.min), group.last.close,
        group.fold<double>(0, (v, b) => v + b.volume)));
    }
    return List.unmodifiable(out);
  }

  static List<ChartTimeframe> timeframes(List<DemoCandle> bars) =>
    [for (final factor in [1, 5, 15]) ChartTimeframe(factor, aggregate(bars, factor))];
}

class ChartTimeframe {
  final int factor;
  final List<DemoCandle> bars;
  ChartTimeframe(this.factor, this.bars);
  bool get ready => bars.length >= 20;
  int? get lastTick => bars.isEmpty ? null : bars.last.tick;
  String get bias {
    if (!ready) return 'إحماء غير كافٍ';
    final average = DemoChartAnalysis.ema(bars.map((b) => b.close).toList(), 20).last;
    return bars.last.close > average ? 'صاعد' : bars.last.close < average ? 'هابط' : 'محايد';
  }
  List<ChartWaveScenario> get waves => ChartWaveAnalysis.candidates(
    DemoChartAnalysis.pivots(bars));
}

class ChartWaveEvent {
  final int sequence, observedAt;
  final String scenarioId, event, snapshotJson;
  final double close;
  ChartWaveEvent(this.sequence, this.observedAt, this.scenarioId, this.event,
      this.close, this.snapshotJson);
  Map<String, dynamic> toJson() => {'sequence': sequence,
    'observed_at': observedAt, 'scenario_id': scenarioId, 'event': event,
    'close': close, 'snapshot_json': snapshotJson};
}

class ChartWaveView {
  final int asOf;
  final List<ChartWaveScenario> active;
  final List<ChartWaveEvent> events;
  final String contract;
  ChartWaveView(this.asOf, this.active, this.events,{this.contract=legacyWaveContract});
  ChartWaveScenario? get primary => active.isEmpty ? null : active.first;
  ChartWaveScenario? get alternate => active.length < 2 ? null : active[1];
}

/// Append-only deterministic journal, reconstructed from the persisted synthetic
/// history. Moving the replay cursor reads an old view; it never edits events.
/// The JSON checkpoint is semantically checked by replay, not a signed audit log.
class ChartWaveJournal {
  final int factor;
  final bool strictMarket;
  ChartWaveJournal({this.factor=1,this.strictMarket=false}) {
    if(factor<1)throw const FormatException('Invalid wave journal observation factor');
  }
  final List<DemoCandle> _source = [];
  final List<ChartPivot> _mainPivots = [], _internalPivots = [];
  final List<ChartWaveEvent> _events = [];
  final Map<String, ChartWaveScenario> _scenarios = {};
  final Map<String, int> _invalidated = {};
  List<ChartWaveScenario> _main = [], _internal = [];

  List<ChartWaveEvent> get events => List.unmodifiable(_events);
  int? get latestTick => _source.isEmpty ? null : _source.last.tick;

  void append(List<DemoCandle> history) {
    _validateBars(history,factor:factor);
    if (history.length < _source.length) {
      throw const FormatException('Use view for replay; source history cannot shrink');
    }
    for (var i = 0; i < _source.length; i++) {
      if (jsonEncode(_bar(_source[i])) != jsonEncode(_bar(history[i]))) {
        throw const FormatException('Historical source candles cannot be revised');
      }
    }
    for (final bar in history.skip(_source.length)) {
      _source.add(bar);
      bool confirmed(List<ChartPivot> pivots, int radius) {
        if (_source.length < radius * 2 + 1) return false;
        final window = _source.sublist(_source.length - radius * 2 - 1);
        if(strictMarket) {
          final center=window[radius];
          final others=[...window.take(radius),...window.skip(radius+1)];
          final high=others.every((b)=>center.high>b.high);
          final low=others.every((b)=>center.low<b.low);
          // Equal extrema and outside bars have no ordered, unique pivot.
          if(high==low)return false;
          pivots.add(ChartPivot(center.tick,window.last.tick,high?center.high:center.low,high));
        }else{
          final fresh=DemoChartAnalysis.pivots(window,radius:radius);
          if(fresh.isEmpty)return false;
          pivots.add(fresh.single);
        }
        return true;
      }
      final mainChanged = confirmed(_mainPivots, strictMarket?3:4);
      final internalChanged = confirmed(_internalPivots, strictMarket?1:2);
      if (mainChanged) _main = ChartWaveAnalysis.candidates(_mainPivots);
      if (internalChanged) {
        _internal = ChartWaveAnalysis.candidates(_internalPivots, degree: 'internal');
      }
      if (mainChanged || internalChanged) {
        for (final scenario in [..._main, ..._internal,
            ...ChartWaveAnalysis.nestedThirds(_main, _internal)]) {
          if (_scenarios.containsKey(scenario.id)) continue;
          if (scenario.observedAt > bar.tick) {
            throw const FormatException('Future wave scenario');
          }
          _scenarios[scenario.id] = scenario;
          _record(scenario, 'DETECTED', bar);
        }
      }
      for (final scenario in _scenarios.values) {
        if (_invalidated.containsKey(scenario.id)) continue;
        // Structural invalidation is based on the observed candle CLOSE. It is
        // not a stop order, and does not guarantee any execution price.
        if (scenario.bullish ? bar.close <= scenario.invalidation
            : bar.close >= scenario.invalidation) {
          _invalidated[scenario.id] = bar.tick;
          _record(scenario, 'INVALIDATED', bar);
        }
      }
    }
  }

  void _record(ChartWaveScenario scenario, String event, DemoCandle bar) {
    _events.add(ChartWaveEvent(_events.length + 1, bar.tick, scenario.id, event,
      bar.close, jsonEncode(scenario.toJson())));
  }

  ChartWaveView view(int asOf) {
    if (_source.isEmpty || asOf < 0 || asOf > _source.last.tick) {
      throw const FormatException('Wave replay cursor is outside observed history');
    }
    final visible = _events.where((e) => e.observedAt <= asOf).toList();
    final detected = visible.where((e) => e.event == 'DETECTED')
        .map((e) => e.scenarioId).toSet();
    final active = _scenarios.values.where((s) => detected.contains(s.id) &&
      (!_invalidated.containsKey(s.id) || _invalidated[s.id]! > asOf)).toList();
    active.sort((a, b) {
      final time = b.observedAt.compareTo(a.observedAt);
      if (time != 0) return time;
      final score = b.evidence.compareTo(a.evidence);
      return score != 0 ? score : a.id.compareTo(b.id);
    });
    return ChartWaveView(asOf, List.unmodifiable(active), List.unmodifiable(visible),
      contract:strictMarket?marketWaveContract:legacyWaveContract);
  }

  Map<String, dynamic> toJson() => {'version': strictMarket?2:1, 'factor':factor,
    if(strictMarket)'contract':marketWaveContract,
    'source': _source.map(_bar).toList(),
    'events': _events.map((e) => e.toJson()).toList()};

  static ChartWaveJournal restore(Map<String, dynamic> value) {
    if (![1,2].contains(value['version']) ||
        (value['version']==2&&value['contract']!=marketWaveContract)||
        (value['version']==1&&value.containsKey('contract'))||
        value['source'] is! List || value['events'] is! List) {
      throw const FormatException('Invalid wave journal checkpoint');
    }
    try {
      final bars = (value['source'] as List).map<DemoCandle>((v) {
        final row = v as List;
        if (row.length != 6 || row[0] is! int) {
          throw const FormatException('Invalid source candle');
        }
        return DemoCandle(row[0] as int, (row[1] as num).toDouble(),
          (row[2] as num).toDouble(), (row[3] as num).toDouble(),
          (row[4] as num).toDouble(), (row[5] as num).toDouble());
      }).toList();
      final journal = ChartWaveJournal(factor:value['factor'] as int? ?? 1,strictMarket:value['version']==2)..append(bars);
      if (jsonEncode(journal.toJson()['events']) != jsonEncode(value['events'])) {
        throw const FormatException('Wave journal disagrees with causal replay');
      }
      return journal;
    } on TypeError {
      throw const FormatException('Invalid wave journal value');
    }
  }
}

List<num> _bar(DemoCandle b) => [b.tick, b.open, b.high, b.low, b.close, b.volume];

void _validateBars(List<DemoCandle> bars,{int factor=1}) {
  for (var i = 0; i < bars.length; i++) {
    final b = bars[i];
    if (b.tick != (i+1)*factor-1 || ![b.open, b.high, b.low, b.close, b.volume]
        .every((v) => v.isFinite) || b.low <= 0 || b.volume < 0 ||
        b.low > math.min(b.open, b.close) || b.high < math.max(b.open, b.close)) {
      throw const FormatException('Contiguous fixed-origin valid candles required');
    }
  }
}
