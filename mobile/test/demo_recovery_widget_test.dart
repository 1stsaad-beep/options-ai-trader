import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:options_ai_trader/main.dart';
import 'package:options_ai_trader/demo/backup.dart';
import 'package:options_ai_trader/demo/engine.dart';
import 'package:options_ai_trader/demo/store.dart';

class NoRecoveryNetwork extends HttpOverrides {
  int attempts = 0;
  @override
  HttpClient createHttpClient(SecurityContext? context) {
    attempts++;
    throw StateError('Recovery must remain offline');
  }
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  String? clipboard;
  var reads = 0;
  late NoRecoveryNetwork network;
  HttpOverrides? prior;
  setUp(() {
    clipboard = null;
    reads = 0;
    prior = HttpOverrides.current;
    network = NoRecoveryNetwork();
    HttpOverrides.global = network;
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
      .setMockMethodCallHandler(SystemChannels.platform, (call) async {
        if (call.method == 'Clipboard.setData') clipboard = (call.arguments as Map)['text'] as String;
        if (call.method == 'Clipboard.getData') { reads++; return {'text': clipboard}; }
        return null;
      });
  });
  tearDown(() {
    HttpOverrides.global = prior;
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
      .setMockMethodCallHandler(SystemChannels.platform, null);
  });

  Future<void> openPreview(WidgetTester tester) async {
    await tester.tap(find.byKey(const Key('demo-recovery-import')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('demo-backup-paste')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('demo-backup-preview')));
    await tester.pumpAndSettle();
  }

  testWidgets('initial recovery exports original, previews, cancels, confirms and reopens without network', (tester) async {
    final store = MemoryDemoStore('unreadable original');
    await tester.pumpWidget(TraderApp(demoStore: store));
    await tester.pumpAndSettle();
    expect(find.text('خطوة سوق محلية'), findsNothing);
    expect(reads, 0);
    await tester.tap(find.byKey(const Key('demo-recovery-export')));
    await tester.pumpAndSettle();
    expect(clipboard, 'unreadable original');
    final incoming = DemoEngine()..createAccount('الحساب المستعاد', 2000000);
    clipboard = DemoBackup.export(incoming);
    await openPreview(tester);
    expect(find.byKey(const Key('demo-backup-preview-counts')), findsOneWidget);
    expect(store.data, 'unreadable original');
    expect(store.recoveryCopy, isNull);
    await tester.tap(find.byKey(const Key('demo-backup-cancel')));
    await tester.pumpAndSettle();
    expect(store.data, 'unreadable original');
    await openPreview(tester);
    await tester.tap(find.byKey(const Key('demo-backup-confirm')));
    await tester.pumpAndSettle();
    expect(store.recoveryCopy, 'unreadable original');
    expect(DemoEngine.decode(store.data!).accounts.single['name'], 'الحساب المستعاد');
    expect(find.byKey(const Key('demo-recovery-import')), findsNothing);
    await tester.tap(find.byKey(const Key('demo-backup-menu')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('نسخ الأصل المحتفظ به قبل الاسترداد'));
    await tester.pumpAndSettle();
    expect(clipboard, 'unreadable original');
    final saved = store.data;
    await tester.pumpWidget(const SizedBox());
    await tester.pumpWidget(TraderApp(demoStore: store));
    await tester.pumpAndSettle();
    expect(store.data, saved);
    expect(find.byKey(const Key('demo-recovery-import')), findsNothing);
    expect(network.attempts, 0);
    expect(tester.takeException(), isNull);
  });

  testWidgets('invalid backup cannot reach recovery confirmation or archive writes', (tester) async {
    final store = MemoryDemoStore('original');
    await tester.pumpWidget(TraderApp(demoStore: store));
    await tester.pumpAndSettle();
    clipboard = '{"version":999}';
    await openPreview(tester);
    expect(find.byKey(const Key('demo-backup-confirm')), findsNothing);
    expect(store.data, 'original');
    expect(store.recoveryCopy, isNull);
    expect(network.attempts, 0);
  });

  testWidgets('failed archive reports recovery error and retains original without opening accounts', (tester) async {
    final store = MemoryDemoStore('original')..failWrites = true;
    await tester.pumpWidget(TraderApp(demoStore: store));
    await tester.pumpAndSettle();
    clipboard = DemoBackup.export(DemoEngine()..createAccount('incoming', 1000000));
    await openPreview(tester);
    await tester.tap(find.byKey(const Key('demo-backup-confirm')));
    await tester.pumpAndSettle();
    expect(find.textContaining('تعذر الاسترداد'), findsOneWidget);
    expect(find.text('خطوة سوق محلية'), findsNothing);
    expect(store.data, 'original');
    expect(store.recoveryCopy, isNull);
    expect(network.attempts, 0);
    expect(tester.takeException(), isNull);
  });
}
