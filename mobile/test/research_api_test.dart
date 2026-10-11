import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:options_ai_trader/api.dart';
import 'package:options_ai_trader/analysis_contract.dart';
import 'research_test_support.dart';

void main() {
  test('Dart accepts the exact Python-generated versioned endpoint fixture', () {
    final fixture = jsonDecode(File('test/fixtures/research_contract_v1.json').readAsStringSync()) as Map;
    final account = fixture['current']['account_id'] as String;
    final symbol = fixture['current']['symbol'] as String;
    final current = ResearchWorkbench.parse(fixture['current'], account, symbol);
    final saved = ResearchSnapshot.parse(fixture['snapshot'], account, symbol);
    final listing = ResearchSnapshotList.parse(fixture['list'], account, symbol);
    final replay = ResearchReplay.parse(fixture['replay'], account, symbol, saved.snapshotId);
    expect(current.decision['decision_id'], saved.workbench.decision['decision_id']);
    expect(listing.items.single.snapshotId, saved.snapshotId);
    expect(replay.original.data, saved.workbench.data);
    expect(replay.hasOutcome, true);
  });

  test('versioned research endpoint lifecycle is account-scoped and explicit', () async {
    final calls = <String>[];
    final api = TraderApi(client: MockClient((request) async {
      calls.add('${request.method} ${request.url.path}');
      final path = request.url.path;
      final value = path.endsWith('/snapshot') ? researchSavedFixture() :
        path.endsWith('/snapshots') ? researchListFixture(saved: true) :
        path.endsWith('/replay') ? researchReplayFixture(outcome: true) : researchFixture();
      if (request.method == 'POST') expect(jsonDecode(request.body), isEmpty);
      return http.Response(jsonEncode(value), 200);
    }));
    expect((await api.inspectResearch('a', 'NVDA')).symbol, 'NVDA');
    expect((await api.saveResearchSnapshot('a', 'NVDA')).snapshotId, 'saved-a');
    expect((await api.listResearchSnapshots('a', 'NVDA')).items.single.decisionId, 'decision-a');
    expect((await api.replayResearchSnapshot('a', 'NVDA', 'saved-a')).hasOutcome, true);
    expect(calls, [
      'GET /api/accounts/a/research/NVDA',
      'POST /api/accounts/a/research/NVDA/snapshot',
      'GET /api/accounts/a/research/NVDA/snapshots',
      'GET /api/accounts/a/research/NVDA/snapshots/saved-a/replay',
    ]);
  });

  test('research rejects unsupported versions, scope, authority and future evidence', () async {
    final cases = [
      {...researchFixture(), 'schema_version': 2},
      {...researchFixture(), 'schema_version': 1.0},
      {...researchFixture(), 'account_id': 'b'},
      {...researchFixture(), 'symbol': 'TSLA'},
      {...researchFixture(), 'source': 'live'},
      {...researchFixture(), 'execution_authority': true},
      {...researchFixture(), 'external_connections': true},
      {...researchFixture(), 'profitability_evidence': true},
      {...researchFixture(), 'as_of': '2026-01-05T15:00:30'},
      {...researchFixture(), 'observed_at': '2026-01-05T15:01:00Z'},
      {...researchFixture(), 'decision': {
        ...researchFixture()['decision'] as Map<String, dynamic>, 'account_id': 'b',
      }},
    ];
    for (final data in cases) {
      final api = TraderApi(client: MockClient((_) async => http.Response(jsonEncode(data), 200)));
      await expectLater(api.inspectResearch('a', 'NVDA'), throwsA(isA<ApiException>()));
    }
  });

  test('snapshot list rejects foreign rows and duplicate identifiers', () async {
    final valid = researchListFixture(saved: true);
    for (final items in [
      researchListFixture(account: 'b', saved: true)['items'],
      [valid['items'][0], valid['items'][0]],
    ]) {
      final api = TraderApi(client: MockClient((_) async =>
        http.Response(jsonEncode({...valid, 'items': items}), 200)));
      await expectLater(api.listResearchSnapshots('a', 'NVDA'), throwsA(isA<ApiException>()));
    }
  });

  test('replay rejects identity, decision substitution, fabricated or future outcomes', () async {
    final valid = researchReplayFixture(outcome: true);
    final unavailable = researchReplayFixture();
    final cases = [
      {...valid, 'snapshot_id': 'other-snapshot'},
      {...valid, 'original_workbench': researchFixture(account: 'b')},
      {...valid, 'counterfactual': {...valid['counterfactual'] as Map<String, dynamic>,
        'decision_digest': 'changed'}},
      {...valid, 'counterfactual': {...valid['counterfactual'] as Map<String, dynamic>,
        'decision_reasons': ['INVENTED_REASON']}},
      {...valid, 'counterfactual': {...valid['counterfactual'] as Map<String, dynamic>,
        'exit_at': '2026-01-05T16:00:00Z'}},
      {...unavailable, 'counterfactual': {...unavailable['counterfactual'] as Map<String, dynamic>,
        'pnl': 100}},
    ];
    for (final data in cases) {
      final api = TraderApi(client: MockClient((_) async => http.Response(jsonEncode(data), 200)));
      await expectLater(api.replayResearchSnapshot('a', 'NVDA', 'saved-a'),
        throwsA(isA<ApiException>()));
    }
  });

  test('snapshot mutation is never retried after lost response', () async {
    var attempts = 0;
    final api = TraderApi(client: MockClient((_) async {
      attempts++;
      throw http.ClientException('response lost after server saved');
    }));
    await expectLater(api.saveResearchSnapshot('a', 'NVDA'), throwsA(isA<ApiException>()));
    expect(attempts, 1);
  });

  test('invalid research identity is rejected before network access', () async {
    var attempts = 0;
    final api = TraderApi(client: MockClient((_) async {
      attempts++;
      return http.Response('{}', 200);
    }));
    await expectLater(api.inspectResearch('', 'NVDA'), throwsA(isA<ApiException>()));
    await expectLater(api.saveResearchSnapshot('a', '../NVDA'), throwsA(isA<ApiException>()));
    await expectLater(api.replayResearchSnapshot('a', 'NVDA', ''), throwsA(isA<ApiException>()));
    expect(attempts, 0);
  });
}
