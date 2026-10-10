import 'dart:convert';
import 'package:flutter_test/flutter_test.dart';
import 'package:options_ai_trader/demo/chart_analysis.dart';
import 'package:options_ai_trader/demo/engine.dart';
import 'package:options_ai_trader/demo/research_analysis.dart';

void main() {
  DemoEngine fixture() => DemoEngine()..createAccount('الأول', 1000000)..createAccount('الثاني', 1000000);

  test('local workbench is read only and has no execution authority', () {
    final e = fixture();
    final before = e.encode();
    final result = DemoResearchAnalysis.build(e, e.accounts.first['id'], 'NVDA');
    expect(result['source'], DemoEngine.source);
    expect(result['execution_authority'], false);
    expect(result['mode'], 'SHADOW');
    expect(e.encode(), before);
  });
  test('future observations cannot alter earlier research evidence', () {
    final e = fixture()..tick = 90;
    final bars = DemoChartAnalysis.bars(e, 'NVDA', e.tick);
    final at40 = bars.where((b) => b.tick <= 40).toList();
    expect(DemoResearchAnalysis.evidence(bars, 40), DemoResearchAnalysis.evidence(at40, 40));
    expect(DemoResearchAnalysis.tournament(bars, 40), DemoResearchAnalysis.tournament(at40, 40));
  });
  test('walk forward folds only use prior training and observed outcomes', () {
    final e = fixture()..tick = 90;
    final result = DemoResearchAnalysis.tournament(DemoChartAnalysis.bars(e, 'NVDA', 90), 50);
    final folds = (result['folds'] as List).cast<DemoRow>();
    expect(folds, isNotEmpty);
    for (final fold in folds) {
      expect(fold['train_end_tick'], lessThan((fold['test_start_tick'] as int) - 1));
      expect(fold['test_end_tick'], lessThanOrEqualTo(50));
    }
    expect(result['cost_bps_per_interval'], 10);
    expect(result['instrument'], 'underlying_return_proxy_not_options');
  });
  test('insufficient observations produce no tournament result', () {
    final e = fixture();
    final result = DemoResearchAnalysis.tournament(DemoChartAnalysis.bars(e, 'NVDA', 24), 24);
    expect(result['folds'], isEmpty);
  });
  test('invalid research data fails instead of emitting NaN', () {
    final bars = List.generate(21, (i) => DemoCandle(i, 10, 11, 9, i == 4 ? double.nan : 10, 100));
    expect(() => DemoResearchAnalysis.evidence(bars, 20), throwsA(isA<DemoRejected>()));
    final invalidOpen = List.generate(21, (i) => DemoCandle(i, 12, 11, 9, 10, 100));
    expect(() => DemoResearchAnalysis.evidence(invalidOpen, 20), throwsA(isA<DemoRejected>()));
    final valid = List.generate(21, (i) => DemoCandle(i, 10, 11, 9, 10, 100));
    expect(() => DemoResearchAnalysis.evidence(valid, 21), throwsA(isA<DemoRejected>()));
  });
  test('Option Twin includes spread both slippage sides and commission', () {
    final result = DemoResearchAnalysis.optionTwin(spot: 100, premium: 2, right: 'CALL',
      spotChangePct: 0, elapsedDays: 0, ivChangePoints: 0, commissionCents: 65, slippageCents: 1);
    expect(result['scenario_pnl_usd'], closeTo(-8.30, 1e-8));
    expect(result['commissions_usd'], 1.30);
    expect(result['source'], 'assumed_greeks_not_observed');
    expect(result['execution_authority'], false);
  });
  test('Option Twin Call and Put delta move in opposite direction', () {
    DemoRow twin(String right) => DemoResearchAnalysis.optionTwin(spot: 100, premium: 2, right: right,
      spotChangePct: 1, elapsedDays: 0, ivChangePoints: 0, commissionCents: 65, slippageCents: 1);
    expect(twin('CALL')['scenario_pnl_usd'], greaterThan(twin('PUT')['scenario_pnl_usd']));
    expect(() => DemoResearchAnalysis.optionTwin(spot: 100, premium: 2, right: 'CALL',
      spotChangePct: double.nan, elapsedDays: 0, ivChangePoints: 0,
      commissionCents: 65, slippageCents: 1), throwsA(isA<DemoRejected>()));
  });
  test('market loss and unknown account force zero trust without throwing', () {
    final e = fixture();
    final id = e.accounts.first['id'] as String;
    e.marketAvailable = false;
    e.account(id)['known'] = false;
    final result = DemoResearchAnalysis.build(e, id, 'NVDA');
    expect(result['trust_score'], 0);
    expect(result['diagnostic_gates_healthy'], false);
    expect(result['hard_failures'], containsAll(['بيانات السوق غير متاحة', 'حالة الحساب غير موثوقة']));
  });
  test('research account isolation includes pending premium only for selected account', () {
    final e = fixture();
    final a = e.accounts.first['id'] as String, b = e.accounts.last['id'] as String;
    e.submit(a, e.contract('NVDA', 'CALL'), 'BUY', 1, 'a-order');
    final first = DemoResearchAnalysis.build(e, a, 'NVDA');
    final second = DemoResearchAnalysis.build(e, b, 'NVDA');
    expect((first['exposure_cents'] as Map)['NVDA'], greaterThan(0));
    expect(second['exposure_cents'], isEmpty);
    expect((first['decision_memory'] as List).length, 1);
    expect(second['decision_memory'], isEmpty);
    expect(() => DemoResearchAnalysis.build(e, 'absent', 'NVDA'), throwsA(isA<DemoRejected>()));
  });
  test('saved decision replay cannot invent an option path or cross account', () {
    final e = fixture();
    final a = e.accounts.first['id'] as String, b = e.accounts.last['id'] as String;
    final o = e.submit(a, e.contract('NVDA', 'CALL'), 'BUY', 1, 'original', reason: 'سبب محفوظ');
    final before = e.encode();
    e.scenario = 'rally';
    final result = DemoResearchAnalysis.replaySavedDecision(e, a, o['id']);
    expect(result['original_decision']['reason'], 'سبب محفوظ');
    expect(result['counterfactual_pnl'], isNull);
    expect(result['counterfactual_status'], 'NOT_AVAILABLE_OPTION_PATH_NOT_RECORDED');
    expect(() => DemoResearchAnalysis.replaySavedDecision(e, b, o['id']), throwsA(isA<DemoRejected>()));
    expect(jsonDecode(before)['accounts'], jsonDecode(e.encode())['accounts']);
  });
  test('undefined correlation is not a fabricated zero risk result', () {
    expect(DemoResearchAnalysis.correlation([1, 1, 1], [1, 2, 3]), isNull);
    expect(DemoResearchAnalysis.correlation([1, 2, 3], [2, 4, 6]), closeTo(1, 1e-10));
    expect(DemoResearchAnalysis.correlation([1, 2, 3], [6, 4, 2]), closeTo(-1, 1e-10));
  });
}
