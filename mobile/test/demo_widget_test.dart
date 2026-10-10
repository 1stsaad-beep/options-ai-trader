import 'dart:io';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:options_ai_trader/main.dart';
import 'package:options_ai_trader/demo/engine.dart';
import 'package:options_ai_trader/demo/store.dart';

class NoNetwork extends HttpOverrides {
  int attempts = 0;
  @override
  HttpClient createHttpClient(SecurityContext? context) {
    attempts++;
    throw StateError('Demo attempted network');
  }
}

Future<void> destination(WidgetTester t, String label) async {
  await t.tap(find.byIcon(Icons.menu));
  await t.pumpAndSettle();
  final target = find.descendant(
    of: find.byType(Drawer),
    matching: find.text(label),
  );
  await t.scrollUntilVisible(
    target,
    150,
    scrollable: find.descendant(
      of: find.byType(Drawer),
      matching: find.byType(Scrollable),
    ),
  );
  await t.tap(target);
  await t.pumpAndSettle();
}

Future<void> reveal(WidgetTester t, Finder f) async {
  await t.scrollUntilVisible(
    f,
    120,
    scrollable: find
        .descendant(
          of: find.byType(Scaffold).first,
          matching: find.byType(Scrollable),
        )
        .last,
  );
  await t.pumpAndSettle();
}

void main() {
  testWidgets('offline default all ten pages RTL synthetic dark and no HTTP', (
    t,
  ) async {
    t.view.physicalSize = const Size(390, 844);
    t.view.devicePixelRatio = 1;
    addTearDown(t.view.resetPhysicalSize);
    addTearDown(t.view.resetDevicePixelRatio);
    final blocker = NoNetwork();
    final previous = HttpOverrides.current;
    HttpOverrides.global = blocker;
    addTearDown(() => HttpOverrides.global = previous);
    await t.pumpWidget(TraderApp(demoStore: MemoryDemoStore()));
    await t.pumpAndSettle();
    expect(find.byKey(const Key('local-demo-banner')), findsOneWidget);
    expect(
      Directionality.of(t.element(find.byKey(const Key('local-demo-banner')))),
      TextDirection.rtl,
    );
    expect(
      Theme.of(
        t.element(find.byKey(const Key('local-demo-banner'))),
      ).brightness,
      Brightness.dark,
    );
    for (final page in [
      'الحسابات المحلية',
      'الفرص والتحليلات',
      'الصفقات والأوامر',
      'إعدادات المخاطر',
      'قوائم المراقبة',
      'التقارير والاختبار التاريخي',
      'سجل القرارات',
      'الطوارئ واختبار الأعطال',
      'الاستراتيجيات والإعدادات',
      'مختبر الرسوم المتقدم',
      'إعادة قرارات الصفقات',
      'الرئيسية',
    ]) {
      await destination(t, page);
      expect(t.takeException(), isNull, reason: page);
      await t.drag(find.byType(ListView).last, const Offset(0, -500));
      await t.pumpAndSettle();
      expect(t.takeException(), isNull, reason: 'lower $page');
    }
    expect(blocker.attempts, 0);
  });
  testWidgets(
    'local account creation survives reopening and watchlist add pause remove',
    (t) async {
      final store = MemoryDemoStore();
      await t.pumpWidget(TraderApp(demoStore: store));
      await t.pumpAndSettle();
      await destination(t, 'الحسابات المحلية');
      await t.tap(find.text('إضافة حساب محلي'));
      await t.pumpAndSettle();
      await t.enterText(find.widgetWithText(TextField, 'اسم الحساب'), 'ثانٍ');
      await t.tap(find.text('حفظ'));
      await t.pumpAndSettle();
      await t.pump(const Duration(milliseconds: 400));
      await t.pumpAndSettle();
      expect(DemoEngine.decode(store.data!).accounts.length, 5);
      await destination(t, 'قوائم المراقبة');
      await t.tap(find.text('إضافة سهم'));
      await t.pumpAndSettle();
      await t.enterText(find.byType(TextField), 'MSFT');
      await t.tap(find.text('حفظ'));
      await t.pumpAndSettle();
      await t.pump(const Duration(milliseconds: 400));
      await t.pumpAndSettle();
      final saved = DemoEngine.decode(store.data!);
      expect(saved.accounts.last['watch']['MSFT'], true);
      expect(saved.accounts.first['watch']['MSFT'], isNull);
      await t.pumpWidget(const SizedBox());
      await t.pumpWidget(TraderApp(demoStore: store));
      await t.pumpAndSettle();
      expect(DemoEngine.decode(store.data!).accounts.length, 5);
      expect(t.takeException(), isNull);
    },
  );
  testWidgets('appearance changes persist across restart and supports system', (
    t,
  ) async {
    final store = MemoryDemoStore();
    await t.pumpWidget(TraderApp(demoStore: store));
    await t.pumpAndSettle();
    await t.tap(find.byTooltip('مظهر التطبيق'));
    await t.pumpAndSettle();
    expect(find.text('اتباع مظهر النظام'), findsOneWidget);
    await t.tap(find.text('الوضع الفاتح'));
    await t.pumpAndSettle();
    expect(
      Theme.of(
        t.element(find.byKey(const Key('local-demo-banner'))),
      ).brightness,
      Brightness.light,
    );
    await t.pumpWidget(const SizedBox());
    await t.pumpWidget(TraderApp(demoStore: store));
    await t.pumpAndSettle();
    expect(
      Theme.of(
        t.element(find.byKey(const Key('local-demo-banner'))),
      ).brightness,
      Brightness.light,
    );
  });
  testWidgets('automation changes only chosen local account', (t) async {
    final e = DemoEngine()
      ..createAccount('الأول', 1000000)
      ..createAccount('الثاني', 1000000);
    final store = MemoryDemoStore(e.encode());
    await t.pumpWidget(TraderApp(demoStore: store));
    await t.pumpAndSettle();
    await t.tap(find.byType(DropdownButtonFormField<String>));
    await t.pumpAndSettle();
    await t.tap(find.text('الثاني').last);
    await t.pumpAndSettle();
    await destination(t, 'الاستراتيجيات والإعدادات');
    await t.tap(find.byKey(const Key('demo-automation')));
    await t.pumpAndSettle();
    final restored = DemoEngine.decode(store.data!);
    expect(restored.risk(restored.accounts.first)['automation'], false);
    expect(restored.risk(restored.accounts.last)['automation'], true);
  });
  testWidgets('local timer pauses when app backgrounds', (t) async {
    final store = MemoryDemoStore();
    await t.pumpWidget(TraderApp(demoStore: store));
    await t.pumpAndSettle();
    await t.tap(find.byTooltip('تشغيل الوقت المحلي'));
    await t.pump(const Duration(milliseconds: 1600));
    await t.pump();
    t.binding.handleAppLifecycleStateChanged(AppLifecycleState.paused);
    await t.pump();
    final tick = DemoEngine.decode(store.data!).tick;
    await t.pump(const Duration(seconds: 5));
    expect(DemoEngine.decode(store.data!).tick, tick);
    t.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
    await t.pumpWidget(const SizedBox());
  });
  testWidgets('corrupt storage shows error and retains original data', (
    t,
  ) async {
    final store = MemoryDemoStore('corrupt');
    await t.pumpWidget(TraderApp(demoStore: store));
    await t.pumpAndSettle();
    expect(find.textContaining('لن تُستبدل'), findsOneWidget);
    expect(store.data, 'corrupt');
    expect(find.text('خطوة سوق محلية'), findsNothing);
  });
}
