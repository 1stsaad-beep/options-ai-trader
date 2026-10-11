import 'dart:convert';
import 'dart:io';
import 'dart:async';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:options_ai_trader/api.dart';
import 'package:options_ai_trader/main.dart';
import 'package:options_ai_trader/demo/engine.dart';
import 'package:options_ai_trader/demo/research_lab.dart';
import 'research_test_support.dart';

class ResearchNoNetwork extends HttpOverrides {
  int attempts = 0;
  @override
  HttpClient createHttpClient(SecurityContext? context) {
    attempts++;
    throw StateError('No network allowed in local research');
  }
}

Future<void> openResearch(WidgetTester t) async {
  await t.tap(find.byIcon(Icons.menu));
  await t.pumpAndSettle();
  final label = find.text('مختبر الأبحاث في الخادم');
  await t.scrollUntilVisible(label, 150, scrollable: find.descendant(
    of: find.byType(Drawer), matching: find.byType(Scrollable)));
  await t.ensureVisible(label);
  await t.tap(label);
  await t.pumpAndSettle();
}

void main() {
  testWidgets('offline research controls render with no HTTP or ledger mutation', (t) async {
    final e = DemoEngine()..createAccount('محلي', 1000000);
    final before = e.encode();
    final blocker = ResearchNoNetwork(), previous = HttpOverrides.current;
    HttpOverrides.global = blocker;
    addTearDown(() => HttpOverrides.global = previous);
    await t.pumpWidget(MaterialApp(home: Scaffold(body: SingleChildScrollView(
      child: DemoResearchLab(engine: e, accountId: e.accounts.first['id'])))));
    await t.pumpAndSettle();
    expect(find.byKey(const Key('research-shadow-banner')), findsOneWidget);
    await t.scrollUntilVisible(find.text('Option Twin — سيناريو عقد واحد'), 200);
    await t.tap(find.text('Option Twin — سيناريو عقد واحد'));
    await t.pumpAndSettle();
    await t.scrollUntilVisible(find.byKey(const Key('twin-spot-change')), 150);
    await t.drag(find.byKey(const Key('twin-spot-change')), const Offset(50, 0));
    await t.pumpAndSettle();
    expect(t.takeException(), isNull);
    expect(e.encode(), before);
    expect(blocker.attempts, 0);
  });
  testWidgets('offline research visibly blocks trust when market data is lost', (t) async {
    final e = DemoEngine()..createAccount('محلي', 1000000)..marketAvailable = false;
    await t.pumpWidget(MaterialApp(home: Scaffold(body: SingleChildScrollView(
      child: DemoResearchLab(engine: e, accountId: e.accounts.first['id'])))));
    await t.pumpAndSettle();
    expect(find.textContaining('درجة صحة البوابات التشخيصية: 0/100'), findsOneWidget);
    expect(find.textContaining('بيانات السوق غير متاحة'), findsOneWidget);
    expect(t.takeException(), isNull);
  });
  testWidgets('backend research makes only GET and rejects wrong account result', (t) async {
    final methods = <String>[];
    final api = TraderApi(client: MockClient((request) async {
      methods.add(request.method);
      if (request.url.path == '/api/accounts') {
        return http.Response('[{"id":"a","name":"one","broker":"mock"}]', 200);
      }
      if (request.url.path.endsWith('/performance')) {
        return http.Response('{"realized_pnl_cents":0,"source":"synthetic_mock"}', 200);
      }
      if (request.url.path.endsWith('/snapshots')) {
        return http.Response(jsonEncode(researchListFixture()), 200);
      }
      return http.Response(jsonEncode(researchFixture(account: 'different')), 200);
    }));
    await t.pumpWidget(TraderApp(api: api));
    await t.pumpAndSettle();
    await openResearch(t);
    expect(find.textContaining('استجابة البحث غير موثوقة'), findsOneWidget);
    expect(find.byKey(const ValueKey('backend-research-option_twin')), findsNothing);
    expect(methods.every((m) => m == 'GET'), true);
  });
  testWidgets('backend research displays verified synthetic Shadow response only', (t) async {
    final calls = <String>[];
    final api = TraderApi(client: MockClient((request) async {
      calls.add('${request.method} ${request.url.path}');
      if (request.url.path == '/api/accounts') {
        return http.Response('[{"id":"a","name":"one","broker":"mock"},{"id":"b","name":"two","broker":"mock"}]', 200);
      }
      if (request.url.path.endsWith('/performance')) {
        return http.Response('{"realized_pnl_cents":0,"source":"synthetic_mock"}', 200);
      }
      final account = request.url.path.split('/')[3];
      return http.Response(jsonEncode(request.url.path.endsWith('/snapshots')
        ? researchListFixture(account: account) : researchFixture(account: account)), 200);
    }));
    await t.pumpWidget(TraderApp(api: api));
    await t.pumpAndSettle();
    await openResearch(t);
    expect(find.byKey(const ValueKey('backend-research-option_twin')), findsOneWidget);
    expect(find.textContaining('الحساب: a •'), findsOneWidget);
    await t.tap(find.byType(DropdownButtonFormField<String>));
    await t.pumpAndSettle();
    await t.tap(find.text('two • محاكاة اصطناعية').last);
    await t.pumpAndSettle();
    expect(find.textContaining('الحساب: b •'), findsOneWidget);
    expect(find.textContaining('الحساب: a •'), findsNothing);
    expect(calls, contains('GET /api/accounts/b/research/NVDA'));
    expect(calls.every((c) => c.startsWith('GET ')), true);
  });

  testWidgets('server research explicitly saves, lists and replays original evidence', (t) async {
    var saved = false;
    final calls = <String>[];
    final api = TraderApi(client: MockClient((request) async {
      calls.add('${request.method} ${request.url.path}');
      if (request.url.path == '/api/accounts') {
        return http.Response('[{"id":"a","name":"one","broker":"mock"}]', 200);
      }
      if (request.url.path.endsWith('/performance')) {
        return http.Response('{"realized_pnl_cents":0,"source":"synthetic_mock"}', 200);
      }
      if (request.url.path.endsWith('/snapshot')) {
        saved = true;
        return http.Response(jsonEncode(researchSavedFixture()), 200);
      }
      if (request.url.path.endsWith('/snapshots')) {
        return http.Response(jsonEncode(researchListFixture(saved: saved)), 200);
      }
      if (request.url.path.endsWith('/replay')) {
        return http.Response(jsonEncode(researchReplayFixture()), 200);
      }
      return http.Response(jsonEncode(researchFixture()), 200);
    }));
    await t.pumpWidget(TraderApp(api: api));
    await t.pumpAndSettle();
    await openResearch(t);
    expect(calls.where((call) => call.startsWith('POST')), isEmpty);
    await t.ensureVisible(find.byKey(const Key('backend-research-save')));
    await t.tap(find.byKey(const Key('backend-research-save')));
    await t.pumpAndSettle();
    expect(calls.where((call) => call.startsWith('POST')).toList(),
      ['POST /api/accounts/a/research/NVDA/snapshot']);
    expect(find.textContaining('حُفظت لقطة البحث'), findsOneWidget);
    await t.ensureVisible(find.byKey(const Key('backend-research-replay')));
    await t.tap(find.byKey(const Key('backend-research-replay')));
    await t.pumpAndSettle();
    await t.scrollUntilVisible(find.byKey(const Key('backend-replay-unavailable')), 100);
    expect(find.byKey(const Key('backend-replay-unavailable')), findsOneWidget);
    expect(find.byKey(const Key('backend-replay-outcome')), findsNothing);
    expect(calls.last, 'GET /api/accounts/a/research/NVDA/snapshots/saved-a/replay');
    expect(t.takeException(), isNull);
  });

  testWidgets('snapshot response loss is visible and does not retry the write', (t) async {
    var saves = 0;
    final api = TraderApi(client: MockClient((request) async {
      if (request.url.path == '/api/accounts') {
        return http.Response('[{"id":"a","name":"one","broker":"mock"}]', 200);
      }
      if (request.url.path.endsWith('/performance')) {
        return http.Response('{"realized_pnl_cents":0,"source":"synthetic_mock"}', 200);
      }
      if (request.url.path.endsWith('/snapshot')) {
        saves++;
        throw http.ClientException('response lost');
      }
      return http.Response(jsonEncode(request.url.path.endsWith('/snapshots')
        ? researchListFixture() : researchFixture()), 200);
    }));
    await t.pumpWidget(TraderApp(api: api));
    await t.pumpAndSettle();
    await openResearch(t);
    await t.ensureVisible(find.byKey(const Key('backend-research-save')));
    await t.tap(find.byKey(const Key('backend-research-save')));
    await t.pumpAndSettle();
    expect(saves, 1);
    expect(find.textContaining('لم تُعد المحاولة تلقائيًا'), findsOneWidget);
    expect(t.takeException(), isNull);
  });

  testWidgets('late snapshot response cannot replace another account research', (t) async {
    final pending = Completer<http.Response>();
    final api = TraderApi(client: MockClient((request) async {
      if (request.url.path == '/api/accounts') {
        return http.Response('[{"id":"a","name":"one","broker":"mock"},{"id":"b","name":"two","broker":"mock"}]', 200);
      }
      if (request.url.path.endsWith('/performance')) {
        return http.Response('{"realized_pnl_cents":0,"source":"synthetic_mock"}', 200);
      }
      final account = request.url.path.split('/')[3];
      if (request.url.path.endsWith('/snapshot')) return pending.future;
      return http.Response(jsonEncode(request.url.path.endsWith('/snapshots')
        ? researchListFixture(account: account) : researchFixture(account: account)), 200);
    }));
    await t.pumpWidget(TraderApp(api: api));
    await t.pumpAndSettle();
    await openResearch(t);
    await t.ensureVisible(find.byKey(const Key('backend-research-save')));
    await t.tap(find.byKey(const Key('backend-research-save')));
    await t.pump();
    await t.tap(find.byIcon(Icons.menu));
    // Start the drawer animation before advancing its clock. The pending
    // response keeps a progress indicator active, so pumpAndSettle is unsafe.
    await t.pump();
    await t.pump(const Duration(milliseconds: 400));
    final home = find.descendant(of: find.byType(Drawer), matching: find.text('الرئيسية'));
    await t.ensureVisible(home);
    await t.tap(home.hitTestable());
    await t.pumpAndSettle();
    await t.tap(find.byType(DropdownButtonFormField<String>));
    await t.pumpAndSettle();
    await t.tap(find.text('two • محاكاة اصطناعية').last);
    await t.pumpAndSettle();
    await openResearch(t);
    pending.complete(http.Response(jsonEncode(researchSavedFixture()), 200));
    await t.pumpAndSettle();
    expect(find.textContaining('الحساب: b •'), findsOneWidget);
    expect(find.textContaining('الحساب: a •'), findsNothing);
    expect(find.textContaining('حُفظت لقطة البحث'), findsNothing);
    expect(t.takeException(), isNull);
  });
}
