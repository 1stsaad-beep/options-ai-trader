import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:options_ai_trader/main.dart';
import 'package:options_ai_trader/demo/backup.dart';
import 'package:options_ai_trader/demo/engine.dart';
import 'package:options_ai_trader/demo/store.dart';

Future<void> openBackupImport(WidgetTester tester) async {
  await tester.tap(find.byKey(const Key('demo-backup-menu')));
  await tester.pumpAndSettle();
  await tester.tap(find.text('استيراد نسخة Demo من JSON'));
  await tester.pumpAndSettle();
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  String? clipboard;
  var reads = 0;
  setUp(() {
    clipboard = null;
    reads = 0;
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
      .setMockMethodCallHandler(SystemChannels.platform, (call) async {
        if (call.method == 'Clipboard.setData') {
          clipboard = (call.arguments as Map)['text'] as String;
        }
        if (call.method == 'Clipboard.getData') {
          reads++;
          return {'text': clipboard};
        }
        return null;
      });
  });
  tearDown(() {
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
      .setMockMethodCallHandler(SystemChannels.platform, null);
  });

  testWidgets('explicit export copies complete Demo JSON without changing persisted data', (tester) async {
    final engine = DemoEngine()..createAccount('الجهاز الحالي', 1000000);
    final store = MemoryDemoStore(engine.encode());
    final before = store.data;
    await tester.pumpWidget(TraderApp(demoStore: store));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('demo-backup-menu')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('نسخ نسخة Demo إلى الحافظة'));
    await tester.pumpAndSettle();
    expect(DemoBackup.inspect(clipboard!).accountNames, ['الجهاز الحالي']);
    expect(reads, 0);
    expect(store.data, before);
    expect(find.textContaining('لم يُنشأ ملف تلقائيًا'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('clipboard import previews counts, preserves cancel, then replaces only after confirmation', (tester) async {
    final original = DemoEngine()..createAccount('الجهاز الحالي', 1000000);
    final incoming = DemoEngine();
    final source = incoming.createAccount('الحساب المستعاد', 2000000);
    incoming.submit(source['id'], incoming.contract('NVDA', 'CALL'), 'BUY', 1, 'original-decision');
    incoming.step(enter: false);
    incoming.configure(source['id'], {'automation': true});
    clipboard = DemoBackup.export(incoming);
    final store = MemoryDemoStore(original.encode());
    final before = store.data;
    await tester.pumpWidget(TraderApp(demoStore: store));
    await tester.pumpAndSettle();
    await openBackupImport(tester);
    expect(reads, 0);
    await tester.tap(find.byKey(const Key('demo-backup-paste')));
    await tester.pumpAndSettle();
    expect(reads, 1);
    await tester.tap(find.byKey(const Key('demo-backup-preview')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('demo-backup-preview-counts')), findsOneWidget);
    expect(find.textContaining('الحسابات: 1 • الأوامر: 1'), findsOneWidget);
    expect(store.data, before);
    await tester.tap(find.byKey(const Key('demo-backup-cancel')));
    await tester.pumpAndSettle();
    expect(store.data, before);
    await openBackupImport(tester);
    await tester.tap(find.byKey(const Key('demo-backup-paste')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('demo-backup-preview')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('demo-backup-confirm')));
    await tester.pumpAndSettle();
    final restored = DemoEngine.decode(store.data!);
    expect(restored.accounts.single['name'], 'الحساب المستعاد');
    expect(restored.accounts.single['known'], false);
    expect(restored.risk(restored.accounts.single)['automation'], false);
    expect(restored.rows(restored.accounts.single, 'orders'), incoming.rows(source, 'orders'));
    expect(find.textContaining('استُعيدت بيانات Demo'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('invalid import never reaches replacement confirmation', (tester) async {
    final engine = DemoEngine()..createAccount('تبقى كما هي', 1000000);
    final store = MemoryDemoStore(engine.encode());
    final before = store.data;
    await tester.pumpWidget(TraderApp(demoStore: store));
    await tester.pumpAndSettle();
    await openBackupImport(tester);
    await tester.enterText(find.byKey(const Key('demo-backup-input')), '{"version":999}');
    await tester.tap(find.byKey(const Key('demo-backup-preview')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('demo-backup-confirm')), findsNothing);
    expect(find.textContaining('رُفضت النسخة'), findsOneWidget);
    expect(store.data, before);
    expect(tester.takeException(), isNull);
  });
}
