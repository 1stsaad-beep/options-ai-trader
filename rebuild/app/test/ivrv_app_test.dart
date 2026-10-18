import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:options_ai_trader_app/screens/settings_help.dart';
import 'package:options_ai_trader_app/screens/settings_screen.dart';
import 'package:options_ai_trader_app/services/app_controller.dart';
import 'package:options_ai_trader_app/services/background_service.dart';
import 'package:options_ai_trader_app/services/notifier.dart';
import 'package:options_ai_trader_app/services/report_exporter.dart';
import 'package:trader_core/trader_core.dart';

import 'app_smoke_test.dart' show MemoryRepository;
import 'chart_account_test.dart' show MemorySecrets;

void main() {
  late Directory tmp;
  late AppController c;

  setUp(() {
    tmp = Directory.systemTemp.createTempSync('oat_iv_');
    c = AppController(
      repo: MemoryRepository(),
      secrets: MemorySecrets(),
      background: NoBackgroundRunner(),
      notifier: RecordingNotifier(),
      exporter: ReportExporter(dir: () async => tmp, share: (f, s) async {}),
      cycleEvery: const Duration(hours: 1),
    );
  });
  tearDown(() {
    c.dispose();
    tmp.deleteSync(recursive: true);
  });

  test('every numeric setting with a range has an Arabic explanation', () {
    for (final k in AccountSettings.allowedRanges.keys) {
      expect(settingsHelp[k], isNotNull, reason: k);
    }
  });

  testWidgets('IV/RV filter: off by default, enabled per account from settings, other account untouched', (tester) async {
    late String a, b;
    await tester.runAsync(() async {
      await c.load();
      a = (await c.addAccount(name: 'A', broker: BrokerKind.simulator, credentials: const {})).id;
      b = (await c.addAccount(name: 'B', broker: BrokerKind.simulator, credentials: const {})).id;
    });
    expect(c.account(a)!.profile.settings.ivRvFilterEnabled, isFalse);
    await tester.pumpWidget(MaterialApp(home: Directionality(textDirection: TextDirection.rtl, child: SettingsScreen(controller: c, accountId: a))));
    final list = find.byType(Scrollable).first;
    await tester.scrollUntilVisible(find.text('تفعيل فلتر التقلب'), 200, scrollable: list);
    expect(find.text('فلتر التقلب IV/RV (اختياري)'), findsOneWidget);
    await tester.tap(find.text('تفعيل فلتر التقلب'));
    await tester.pump();
    await tester.scrollUntilVisible(find.byKey(const Key('setting-maxIvRvRatio')), 200, scrollable: list);
    expect(find.textContaining('المسموح: 0.5–5'), findsOneWidget);
    await tester.enterText(find.byKey(const Key('setting-maxIvRvRatio')), '1.3');
    await tester.runAsync(() async {
      await tester.tap(find.text('حفظ'));
      await Future<void>.delayed(const Duration(milliseconds: 50));
    });
    await tester.pumpAndSettle();
    final s = c.account(a)!.profile.settings;
    expect(s.ivRvFilterEnabled, isTrue);
    expect(s.maxIvRvRatio, 1.3);
    expect(c.account(b)!.profile.settings.ivRvFilterEnabled, isFalse);
  });
}
