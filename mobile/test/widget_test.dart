import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:options_ai_trader/api.dart';
import 'package:options_ai_trader/main.dart';

void main() {
  testWidgets('SQLite enabled=1 displays an active watchlist switch', (
    tester,
  ) async {
    final api = TraderApi(
      client: MockClient((request) async {
        if (request.url.path == '/api/accounts') {
          return http.Response('[{"id":"a","name":"demo"}]', 200);
        }
        if (request.url.path.endsWith('/watchlist')) {
          return http.Response('[{"symbol":"NVDA","enabled":1}]', 200);
        }
        return http.Response('{}', 200);
      }),
    );
    await tester.pumpWidget(TraderApp(api: api));
    await tester.pumpAndSettle();
    await tester.tap(find.byIcon(Icons.menu));
    await tester.pumpAndSettle();
    await tester.scrollUntilVisible(
      find.text('قائمة المراقبة'),
      100,
      scrollable: find.descendant(
        of: find.byType(Drawer),
        matching: find.byType(Scrollable),
      ),
    );
    await tester.tap(find.text('قائمة المراقبة'));
    await tester.pumpAndSettle();
    expect(tester.widget<Switch>(find.byType(Switch)).value, true);
  });
  testWidgets('Arabic RTL paper dashboard and all ten destinations render', (
    tester,
  ) async {
    final api = TraderApi(
      client: MockClient((_) async => http.Response('[]', 200)),
    );
    await tester.pumpWidget(TraderApp(api: api));
    await tester.pumpAndSettle();
    expect(
      find.text('محاكاة فقط — Live مقفل. النتائج لا تثبت الربحية.'),
      findsOneWidget,
    );
    final direction = Directionality.of(
      tester.element(find.text('الرئيسية').first),
    );
    expect(direction, TextDirection.rtl);
    expect(
      Theme.of(tester.element(find.text('الرئيسية').first)).brightness,
      Brightness.dark,
    );
    await tester.tap(find.byIcon(Icons.menu));
    await tester.pumpAndSettle();
    for (final label in [
      'الحسابات وربط الوسطاء',
      'الفرص والتحليلات',
      'الصفقات والأوامر',
      'إعدادات المخاطر',
      'قائمة المراقبة',
      'التقارير والإحصاءات',
      'سجل القرارات',
      'الإشعارات والإيقاف الطارئ',
      'إعدادات الاستراتيجيات',
    ]) {
      await tester.scrollUntilVisible(
        find.text(label),
        100,
        scrollable: find.descendant(
          of: find.byType(Drawer),
          matching: find.byType(Scrollable),
        ),
      );
      expect(find.text(label), findsOneWidget);
    }
  });
  testWidgets('appearance menu supports explicit light and system modes', (
    tester,
  ) async {
    final api = TraderApi(
      client: MockClient((_) async => http.Response('[]', 200)),
    );
    await tester.pumpWidget(TraderApp(api: api));
    await tester.pumpAndSettle();
    await tester.tap(find.byTooltip('مظهر التطبيق'));
    await tester.pumpAndSettle();
    expect(find.text('اتباع مظهر النظام'), findsOneWidget);
    await tester.tap(find.text('الوضع الفاتح'));
    await tester.pumpAndSettle();
    expect(
      Theme.of(tester.element(find.text('الرئيسية').first)).brightness,
      Brightness.light,
    );
  });
  testWidgets(
    'watchlist supports more than default three symbols and account-scoped mutations',
    (tester) async {
      final writes = <String>[];
      final api = TraderApi(
        client: MockClient((request) async {
          final path = request.url.path;
          if (request.method != 'GET') writes.add(path);
          if (path == '/api/accounts') {
            return http.Response('[{"id":"a","name":"demo"}]', 200);
          }
          if (path.endsWith('/watchlist') && request.method == 'GET') {
            return http.Response(
              '[{"symbol":"NVDA","enabled":1},{"symbol":"AAPL","enabled":1},{"symbol":"TSLA","enabled":0},{"symbol":"MSFT","enabled":1}]',
              200,
            );
          }
          return http.Response('{}', 200);
        }),
      );
      await tester.pumpWidget(TraderApp(api: api));
      await tester.pumpAndSettle();
      await tester.tap(find.byIcon(Icons.menu));
      await tester.pumpAndSettle();
      await tester.scrollUntilVisible(
        find.text('قائمة المراقبة'),
        100,
        scrollable: find.descendant(
          of: find.byType(Drawer),
          matching: find.byType(Scrollable),
        ),
      );
      await tester.tap(find.text('قائمة المراقبة'));
      await tester.pumpAndSettle();
      await tester.scrollUntilVisible(
        find.text('MSFT'),
        100,
        scrollable: find.descendant(
          of: find.byType(RefreshIndicator),
          matching: find.byType(Scrollable),
        ),
      );
      expect(find.text('MSFT'), findsOneWidget);
      final msftRow = find.ancestor(
        of: find.text('MSFT'),
        matching: find.byType(ListTile),
      );
      await tester.tap(
        find.descendant(of: msftRow, matching: find.byType(Switch)),
      );
      await tester.pumpAndSettle();
      expect(writes, ['/api/accounts/a/watchlist/MSFT']);
    },
  );
  testWidgets(
    'home aggregates only server-provided realized account performance',
    (tester) async {
      final api = TraderApi(
        client: MockClient((request) async {
          if (request.url.path == '/api/accounts') {
            return http.Response(
              '[{"id":"a","name":"first"},{"id":"b","name":"second"}]',
              200,
            );
          }
          if (request.url.path == '/api/accounts/a/performance') {
            return http.Response(
              '{"realized_pnl_cents":1250,"source":"synthetic_mock"}',
              200,
            );
          }
          if (request.url.path == '/api/accounts/b/performance') {
            return http.Response(
              '{"realized_pnl_cents":-500,"source":"synthetic_mock"}',
              200,
            );
          }
          return http.Response('{}', 200);
        }),
      );
      await tester.pumpWidget(TraderApp(api: api));
      await tester.pumpAndSettle();
      expect(find.text('الحسابات المحمّلة: 2'), findsOneWidget);
      expect(
        find.text('إجمالي الربح والخسارة المحققة: 7.50 USD'),
        findsOneWidget,
      );
    },
  );
  testWidgets('missing performance does not become a fabricated zero', (
    tester,
  ) async {
    final api = TraderApi(
      client: MockClient(
        (request) async => http.Response(
          request.url.path == '/api/accounts' ? '[{"id":"a"}]' : '{}',
          200,
        ),
      ),
    );
    await tester.pumpWidget(TraderApp(api: api));
    await tester.pumpAndSettle();
    expect(find.textContaining('إجمالي الربح والخسارة المحققة:'), findsNothing);
  });
  testWidgets(
    'duplicate account identifiers fail closed before selector rendering',
    (tester) async {
      final api = TraderApi(
        client: MockClient(
          (_) async => http.Response('[{"id":"a"},{"id":"a"}]', 200),
        ),
      );
      await tester.pumpWidget(TraderApp(api: api));
      await tester.pumpAndSettle();
      expect(find.textContaining('معرّفات غير صالحة أو مكررة'), findsOneWidget);
      expect(find.byType(DropdownButtonFormField<String>), findsNothing);
      expect(tester.takeException(), isNull);
    },
  );
  testWidgets(
    'disconnected server displays failure instead of synthetic metrics',
    (tester) async {
      final api = TraderApi(
        client: MockClient(
          (_) async => http.Response('{"detail":"unauthorized"}', 401),
        ),
      );
      await tester.pumpWidget(TraderApp(api: api));
      await tester.pumpAndSettle();
      expect(find.text('unauthorized'), findsOneWidget);
      expect(
        find.text('إجمالي الربح والخسارة المحققة: 0.00 USD'),
        findsNothing,
      );
    },
  );
  testWidgets('automation is disabled by default and cycle button is locked', (
    tester,
  ) async {
    final fixture = AutomationFixture();
    await tester.pumpWidget(TraderApp(api: fixture.api));
    await tester.pumpAndSettle();
    await openStrategies(tester);
    await revealBody(tester, find.byKey(const Key('automation-enabled')));
    expect(
      tester
          .widget<SwitchListTile>(find.byKey(const Key('automation-enabled')))
          .value,
      false,
    );
    await revealBody(tester, find.byKey(const Key('automation-run')));
    expect(
      tester
          .widget<FilledButton>(find.byKey(const Key('automation-run')))
          .onPressed,
      isNull,
    );
    expect(fixture.writes, isEmpty);
  });
  testWidgets('automation toggle changes only the selected account', (
    tester,
  ) async {
    final fixture = AutomationFixture();
    await tester.pumpWidget(TraderApp(api: fixture.api));
    await tester.pumpAndSettle();
    await selectSecondAccount(tester);
    await openStrategies(tester);
    await revealBody(tester, find.byKey(const Key('automation-enabled')));
    await tester.tap(find.byKey(const Key('automation-enabled')));
    await tester.pumpAndSettle();
    expect(fixture.writes.single.url.path, '/api/accounts/b/risk');
    expect(jsonDecode(fixture.writes.single.body), {
      'automation_enabled': true,
    });
    expect(fixture.configs['a']!['automation_enabled'], false);
    expect(fixture.configs['b']!['automation_enabled'], true);
  });
  testWidgets(
    'exit and quantity configuration stays with the selected account',
    (tester) async {
      final fixture = AutomationFixture();
      await tester.pumpWidget(TraderApp(api: fixture.api));
      await tester.pumpAndSettle();
      await selectSecondAccount(tester);
      await openStrategies(tester);
      await revealBody(tester, find.byKey(const Key('automation-settings')));
      await tester.tap(find.byKey(const Key('automation-settings')));
      await tester.pumpAndSettle();
      await tester.enterText(
        find.widgetWithText(TextField, 'وقف الخسارة %'),
        '15',
      );
      await tester.enterText(
        find.widgetWithText(TextField, 'جني الربح %'),
        '35',
      );
      await tester.enterText(
        find.widgetWithText(TextField, 'عقود الدخول الآلي'),
        '2',
      );
      await tester.tap(find.text('حفظ'));
      await tester.pumpAndSettle();
      expect(fixture.writes.single.url.path, '/api/accounts/b/risk');
      expect(jsonDecode(fixture.writes.single.body), {
        'stop_loss_pct': 15,
        'take_profit_pct': 35,
        'auto_quantity': 2,
        'auto_fill_chunk': 1,
        'max_spread_pct': 10,
      });
      expect(fixture.configs['a']!['stop_loss_pct'], 20);
    },
  );
  testWidgets(
    'automation quantity above account maximum is rejected before request',
    (tester) async {
      final fixture = AutomationFixture();
      await tester.pumpWidget(TraderApp(api: fixture.api));
      await tester.pumpAndSettle();
      await openStrategies(tester);
      await revealBody(tester, find.byKey(const Key('automation-settings')));
      await tester.tap(find.byKey(const Key('automation-settings')));
      await tester.pumpAndSettle();
      await tester.enterText(
        find.widgetWithText(TextField, 'عقود الدخول الآلي'),
        '4',
      );
      await tester.tap(find.text('حفظ'));
      await tester.pumpAndSettle();
      expect(fixture.writes, isEmpty);
      expect(find.textContaining('وبحد الحساب (3)'), findsOneWidget);
    },
  );
  testWidgets(
    'one manual cycle uses the selected account and renders only its server report',
    (tester) async {
      final fixture = AutomationFixture(enabled: true);
      await tester.pumpWidget(TraderApp(api: fixture.api));
      await tester.pumpAndSettle();
      await selectSecondAccount(tester);
      await openStrategies(tester);
      await revealBody(tester, find.byKey(const Key('automation-run')));
      await tester.tap(find.byKey(const Key('automation-run')));
      await tester.pumpAndSettle();
      expect(fixture.writes.single.url.path, '/api/accounts/b/automation/run');
      expect(jsonDecode(fixture.writes.single.body), <String, dynamic>{});
      await revealBody(
        tester,
        find.text('نتيجة آخر دورة من الخادم لهذا الحساب'),
      );
      expect(find.text('نتيجة آخر دورة من الخادم لهذا الحساب'), findsOneWidget);
      expect(find.textContaining('server-verified-b'), findsOneWidget);
      await tester.tap(find.byType(DropdownButtonFormField<String>));
      await tester.pumpAndSettle();
      await tester.tap(find.text('first • محاكاة اصطناعية').last);
      await tester.pumpAndSettle();
      expect(find.textContaining('server-verified-b'), findsNothing);
    },
  );
}

Future<void> openStrategies(WidgetTester tester) async {
  await tester.tap(find.byIcon(Icons.menu));
  await tester.pumpAndSettle();
  await tester.scrollUntilVisible(
    find.text('إعدادات الاستراتيجيات'),
    150,
    scrollable: find.descendant(
      of: find.byType(Drawer),
      matching: find.byType(Scrollable),
    ),
  );
  await tester.tap(find.text('إعدادات الاستراتيجيات'));
  await tester.pumpAndSettle();
}

Future<void> revealBody(WidgetTester tester, Finder finder) async {
  await tester.scrollUntilVisible(
    finder,
    100,
    scrollable: find.descendant(
      of: find.byType(RefreshIndicator),
      matching: find.byType(Scrollable),
    ),
  );
  await tester.pumpAndSettle();
}

Future<void> selectSecondAccount(WidgetTester tester) async {
  await tester.tap(find.byType(DropdownButtonFormField<String>));
  await tester.pumpAndSettle();
  await tester.tap(find.text('second • محاكاة اصطناعية').last);
  await tester.pumpAndSettle();
}

class AutomationFixture {
  final writes = <http.Request>[];
  late final Map<String, Map<String, dynamic>> configs;
  late final TraderApi api;
  AutomationFixture({bool enabled = false}) {
    configs = {
      for (final id in ['a', 'b'])
        id: {
          'mode': 'paper',
          'strategies': ['breakout', 'pullback'],
          'holding': 'intraday',
          'max_contracts': 3,
          'automation_enabled': enabled,
          'stop_loss_pct': 20,
          'take_profit_pct': 30,
          'auto_quantity': 1,
          'auto_fill_chunk': 1,
          'max_spread_pct': 10,
        },
    };
    api = TraderApi(
      client: MockClient((request) async {
        final path = request.url.path;
        if (request.method != 'GET') writes.add(request);
        if (path == '/api/accounts') {
          return http.Response(
            '[{"id":"a","name":"first","broker":"mock"},'
            '{"id":"b","name":"second","broker":"mock"}]',
            200,
          );
        }
        final account = path.split('/')[3];
        if (path.endsWith('/performance')) {
          return http.Response(
            '{"realized_pnl_cents":0,"source":"synthetic_mock"}',
            200,
          );
        }
        if (path.endsWith('/risk')) {
          if (request.method == 'PUT') {
            configs[account]!.addAll(
              Map<String, dynamic>.from(jsonDecode(request.body) as Map),
            );
          }
          return http.Response(jsonEncode(configs[account]), 200);
        }
        if (path.endsWith('/automation/run')) {
          return http.Response(
            jsonEncode({
              'account_id': account,
              'source': 'synthetic_mock',
              'actions': ['server-verified-$account'],
            }),
            200,
          );
        }
        return http.Response('{}', 200);
      }),
    );
  }
}
