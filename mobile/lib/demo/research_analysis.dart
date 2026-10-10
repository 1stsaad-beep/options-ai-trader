// Read-only local research. No HTTP, broker, ledger writes or execution authority.
import 'dart:convert';
import 'dart:math' as math;
import 'chart_analysis.dart';
import 'engine.dart';

class DemoResearchAnalysis {
  static const limitations = [
    'بيانات محلية اصطناعية؛ جميع النتائج Shadow ولا تنشئ أوامر.',
    'Greeks مفترضة للتعليم. Option Twin تقريب Taylor وليس تسعير خيارات أمريكية.',
    'الارتباط والبطولة يعتمدان على السهم الاصطناعي، لا عوائد خيارات أو بيانات سوق.',
    'البوابات تشخيصية جزئية؛ محرك المخاطر المستقل وحده يفحص كل أمر.',
    'إعادة القرار تعرض الأسباب المحفوظة وقتها، ولا تولّد تفسيرًا لاحقًا.',
  ];

  static void _require(bool value, String message) {
    if (!value) throw DemoRejected(message);
  }

  static List<DemoCandle> prefix(List<DemoCandle> bars, int throughTick) {
    _require(bars.isNotEmpty && throughTick <= bars.last.tick, 'لا ملاحظات مستقبلية متاحة للبحث');
    final result = bars.where((b) => b.tick <= throughTick).toList();
    _require(result.length >= 21, 'يلزم 21 ملاحظة ماضية للتحليل');
    for (var i = 0; i < result.length; i++) {
      final b = result[i];
      _require(b.open.isFinite && b.open > 0 && b.close.isFinite && b.high.isFinite && b.low.isFinite &&
          b.volume.isFinite && b.close > 0 && b.volume >= 0 &&
          b.low <= b.close && b.close <= b.high && b.low <= b.open && b.open <= b.high &&
          (i == 0 || result[i - 1].tick < b.tick), 'بيانات البحث غير صالحة');
    }
    return result;
  }

  static DemoRow evidence(List<DemoCandle> input, int throughTick) {
    final bars = prefix(input, throughTick);
    final prior = bars.sublist(bars.length - 21, bars.length - 1);
    final last = bars.last;
    final mean = prior.fold<double>(0, (s, b) => s + b.close) / 20;
    final high = prior.map((b) => b.high).reduce(math.max);
    final low = prior.map((b) => b.low).reduce(math.min);
    final volume = prior.fold<double>(0, (s, b) => s + b.volume) / 20;
    final relativeVolume = volume == 0 ? 0.0 : last.volume / volume;
    final range = high - low;
    final trend = (last.close - mean) / math.max(range, .01);
    final bull = (50 + trend * 40).clamp(0.0, 100.0).toDouble();
    final bear = 100 - bull;
    final neutral = (100 - (bull - bear).abs()).clamp(0.0, 100.0);
    final ranked = <DemoRow>[
      {'scenario': 'صاعد', 'score': bull},
      {'scenario': 'هابط', 'score': bear},
      {'scenario': 'محايد', 'score': neutral},
    ]..sort((a, b) => (b['score'] as num).compareTo(a['score'] as num));
    final flags = <String>[
      if (last.high > high && last.close <= high) 'اختراق علوي فشل عند الإغلاق',
      if (last.low < low && last.close >= low) 'كسر سفلي فشل عند الإغلاق',
      if (relativeVolume < 1) 'حجم أقل من متوسط 20 ملاحظة',
      if ((last.close - last.open).abs() < (last.high - last.low) * .1)
        'جسم شمعة صغير؛ حركة غير حاسمة',
    ];
    return {
      'as_of_tick': last.tick, 'mean': mean, 'support': low,
      'resistance': high, 'relative_volume': relativeVolume,
      'scenario_battle': ranked, 'directional_conflict': (bull - bear).abs() < 20,
      'liquidity_flags': flags,
      'liquidity_scope': 'قواعد OHLCV فقط؛ لا دفتر أوامر ولا سيولة وسيط',
    };
  }

  static DemoRow optionTwin({
    required double spot,
    required double premium,
    required String right,
    required double spotChangePct,
    required int elapsedDays,
    required double ivChangePoints,
    required int commissionCents,
    required int slippageCents,
    double spread = .05,
  }) {
    _require(spot.isFinite && spot > 0 && premium.isFinite && premium > 0 &&
        ['CALL', 'PUT'].contains(right) && spotChangePct.isFinite &&
        spotChangePct.abs() <= 10 && elapsedDays >= 0 && elapsedDays <= 7 &&
        ivChangePoints.isFinite && ivChangePoints.abs() <= 15 &&
        commissionCents >= 0 && slippageCents >= 0 && spread.isFinite && spread >= 0,
        'مدخلات Option Twin خارج الحدود التعليمية');
    final delta = right == 'CALL' ? .5 : -.5;
    const gamma = .01, theta = -.04, vega = .08;
    final move = spot * spotChangePct / 100;
    final estimated = math.max(0.0, premium + delta * move +
        .5 * gamma * move * move + theta * elapsedDays + vega * ivChangePoints);
    final entry = premium + spread / 2 + slippageCents / 100;
    final exit = math.max(0.0, estimated - spread / 2 - slippageCents / 100);
    final totalFees = commissionCents * 2 / 100;
    return {
      'source': 'assumed_greeks_not_observed', 'right': right,
      'delta': delta, 'gamma': gamma, 'theta_per_day': theta,
      'vega_per_iv_point': vega, 'spot_change_pct': spotChangePct,
      'elapsed_days': elapsedDays, 'iv_change_points': ivChangePoints,
      'multiplier': 100, 'entry_cost_usd': entry * 100 + commissionCents / 100,
      'exit_value_usd': exit * 100 - commissionCents / 100,
      'scenario_pnl_usd': (exit - entry) * 100 - totalFees,
      'commissions_usd': totalFees, 'estimated_mid': estimated,
      'execution_authority': false,
    };
  }

  static double? correlation(List<double> first, List<double> second) {
    if (first.length != second.length || first.length < 3) return null;
    if (first.any((v) => !v.isFinite) || second.any((v) => !v.isFinite)) return null;
    final a = first.reduce((a, b) => a + b) / first.length;
    final b = second.reduce((a, b) => a + b) / second.length;
    var cross = 0.0, aa = 0.0, bb = 0.0;
    for (var i = 0; i < first.length; i++) {
      cross += (first[i] - a) * (second[i] - b);
      aa += math.pow(first[i] - a, 2);
      bb += math.pow(second[i] - b, 2);
    }
    if (aa == 0 || bb == 0) return null;
    return (cross / math.sqrt(aa * bb)).clamp(-1.0, 1.0).toDouble();
  }

  static DemoRow tournament(List<DemoCandle> input, int throughTick) {
    final bars = prefix(input, throughTick);
    // Train on completed intervals, purge one observation, score the following
    // disjoint test interval. Predictions use the prior close only.
    final folds = <DemoRow>[];
    double score(int from, int to, bool follow) {
      var result = 0.0;
      for (var i = from; i < to; i++) {
        final trend = bars[i - 1].close >= bars[i - 2].close ? 1 : -1;
        final direction = follow ? trend : -trend;
        result += direction * (bars[i].close / bars[i - 1].close - 1) * 10000 - 10;
      }
      return result;
    }
    for (var start = 23; start + 8 <= bars.length; start += 8) {
      final trainEnd = start - 1;
      final trainStart = trainEnd - 20;
      final trendScore = score(trainStart, trainEnd, true);
      final reverseScore = score(trainStart, trainEnd, false);
      final follow = trendScore >= reverseScore;
      folds.add({
        'train_end_tick': bars[trainEnd - 1].tick,
        'test_start_tick': bars[start].tick,
        'test_end_tick': bars[start + 7].tick,
        'selected': follow ? 'متابعة الزخم' : 'عكس الزخم',
        'test_score_bps': score(start, start + 8, follow),
      });
    }
    return {
      'folds': folds, 'cost_bps_per_interval': 10,
      'out_of_sample_bps': folds.fold<double>(0, (s, f) => s + (f['test_score_bps'] as num).toDouble()),
      'instrument': 'underlying_return_proxy_not_options',
      'no_profitability_claim': true,
    };
  }

  static DemoRow build(DemoEngine engine, String accountId, String symbol) {
    _require(DemoEngine.symbols.contains(symbol), 'رمز بحث غير موجود في الكتالوج المحلي');
    final account = engine.account(accountId), risk = engine.risk(account);
    final bars = DemoChartAnalysis.bars(engine, symbol, engine.tick);
    final analysis = evidence(bars, engine.tick);
    final opportunities = engine.opportunities(accountId)
        .where((v) => v['symbol'] == symbol).toList();
    final signal = opportunities.isEmpty ? null : opportunities.first;
    final prior = engine.tick > 24 ? engine.opportunities(accountId, at: engine.tick - 1)
        .where((v) => v['symbol'] == symbol && v['strategy'] != null).toList() : <DemoRow>[];
    final methods = <DemoRow>[];
    for (final method in ['early', 'confirmed', 'pullback']) {
      final candidate = signal != null && signal['strategy'] != null &&
          (risk['entry_profile'] != 'conservative' || signal['score'] >= 80) &&
          (method != 'confirmed' || prior.any((v) => v['right'] == signal['right'])) &&
          (method != 'pullback' || signal['strategy'] == 'pullback');
      methods.add({'method': method, 'candidate': candidate,
        'activation': signal?['activation'], 'invalidation': signal?['invalidation'],
        'expires_tick': signal?['expires_tick'], 'profile': risk['entry_profile']});
    }
    final failures = <String>[
      if (!engine.marketAvailable) 'بيانات السوق غير متاحة',
      if (account['known'] != true) 'حالة الحساب غير موثوقة',
      if (account['connected'] != true) 'الحساب منفصل اصطناعيًا',
      if (account['stopped'] == true || engine.globalStop) 'إيقاف طارئ',
      if (risk['mode'] != 'demo') 'وضع مراقبة فقط',
      if (account['watch'][symbol] != true) 'الرمز غير مفعّل في قائمة الحساب',
      if (engine.exposure(account) >= account['initial'] *
          math.min(risk['allocation_pct'] as int, risk['exposure_pct'] as int) / 100)
        'استنفاد حد التعرض أو التخصيص',
      if (engine.realized(account, today: true) + engine.unrealized(account) <=
          -(account['initial'] * risk['daily_pct'] / 100)) 'بلوغ حد الخسارة اليومية',
    ];
    final exposure = <String, int>{};
    for (final position in engine.rows(account, 'positions')) {
      exposure.update(position['symbol'], (v) => v + (position['cost'] as int),
          ifAbsent: () => position['cost'] as int);
    }
    for (final order in engine.rows(account, 'orders')) {
      if (DemoEngine.active.contains(order['status']) && order['side'] == 'BUY') {
        exposure.update(order['symbol'], (v) => v + engine.reserved(order),
            ifAbsent: () => engine.reserved(order));
      }
    }
    final pairs = <DemoRow>[];
    final symbols = exposure.keys.toList()..sort();
    List<double> returns(String s) => List.generate(20, (i) {
      final at = engine.tick - 19 + i;
      return engine.underlying(s, at) / engine.underlying(s, at - 1) - 1;
    });
    for (var i = 0; i < symbols.length; i++) {
      for (var j = i + 1; j < symbols.length; j++) {
        final value = correlation(returns(symbols[i]), returns(symbols[j]));
        pairs.add({'first': symbols[i], 'second': symbols[j], 'correlation': value,
          'flagged': value == null || value.abs() >= .8});
      }
    }
    return {
      'account_id': accountId, 'symbol': symbol, 'as_of_tick': engine.tick,
      'source': DemoEngine.source, 'mode': 'SHADOW', 'execution_authority': false,
      'analysis': analysis, 'entry_methods': methods,
      'hard_failures': failures, 'diagnostic_gates_healthy': failures.isEmpty,
      'trust_score': failures.isEmpty ? 100 : 0,
      'correlation_pairs': pairs, 'exposure_cents': exposure,
      'tournament': tournament(bars, engine.tick),
      'decision_memory': engine.rows(account, 'orders').where((o) =>
          o['symbol'] == symbol && o['decision_json'] != null).map((o) => {
            'order_id': o['id'], 'decision_json': o['decision_json'],
            'filled': o['filled'], 'fills': jsonDecode(jsonEncode(o['fills'])),
          }).toList(),
      'limitations': limitations,
    };
  }

  static DemoRow replaySavedDecision(DemoEngine engine, String accountId, String orderId) {
    final account = engine.account(accountId);
    final matches = engine.rows(account, 'orders').where((o) => o['id'] == orderId).toList();
    _require(matches.length == 1, 'القرار لا ينتمي إلى الحساب المحدد');
    final order = matches.single;
    _require(order['decision_json'] is String, 'لا لقطة قرار محفوظة لهذا الأمر');
    final decision = jsonDecode(order['decision_json'] as String) as DemoRow;
    _require(decision['account_id'] == accountId && decision['tick'] <= engine.tick,
        'لقطة القرار غير متوافقة مع الحساب أو الوقت');
    return {
      'order_id': orderId, 'account_id': accountId,
      'original_decision': decision,
      'fills': jsonDecode(jsonEncode(order['fills'])),
      'status': order['status'], 'execution_authority': false,
      // Don't regenerate historical option prices from a potentially changed
      // market scenario. Missing path data means no valid counterfactual PnL.
      'counterfactual_status': 'NOT_AVAILABLE_OPTION_PATH_NOT_RECORDED',
      'counterfactual_pnl': null,
      'reason': 'لا تُحفظ سلسلة أسعار الخيار الكاملة؛ لا يمكن احتساب خروج بديل موثوق محليًا.',
    };
  }
}
