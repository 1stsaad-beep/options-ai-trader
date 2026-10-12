import 'dart:async';

import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:options_ai_trader/demo/backup.dart';
import 'package:options_ai_trader/demo/engine.dart';
import 'package:options_ai_trader/demo/store.dart';

const damaged = '{"version":2,"accounts": [ interrupted';

DemoEngine source() {
  final engine = DemoEngine();
  final account = engine.createAccount('الحساب المستعاد', 2000000);
  engine.submit(account['id'], engine.contract('NVDA', 'CALL'), 'BUY', 1, 'original');
  engine.step(enter: false);
  engine.configure(account['id'], {'automation': true, 'reversal_enabled': true,
    'scaling_enabled': true, 'stop_pct': 7, 'take_pct': 77, 'trailing_pct': 9});
  return engine;
}

DemoBackupPreview preview() => DemoBackup.inspect(DemoBackup.export(source()));

class FaultStore extends MemoryDemoStore {
  bool failArchive = false, wrongArchive = false, failRead = false;
  bool failReplacement = false, failRollback = false, wrongReplacement = false;
  String? changedDuringArchive;
  Completer<void>? releaseArchive;
  final archiveStarted = Completer<void>();
  int activeWrites = 0;
  FaultStore() : super(damaged);
  @override
  Future<String?> load() async {
    if (failRead) throw StateError('unreadable storage');
    return super.load();
  }
  @override
  Future<void> preserveRecoveryCopy(String value) async {
    if (!archiveStarted.isCompleted) archiveStarted.complete();
    if (releaseArchive != null) await releaseArchive!.future;
    if (failArchive) throw StateError('archive unavailable');
    await super.preserveRecoveryCopy(value);
    if (wrongArchive) recoveryCopy = 'not the original';
    if (changedDuringArchive != null) data = changedDuringArchive;
  }
  @override
  Future<void> save(String value) async {
    activeWrites++;
    if (value == damaged && failRollback) throw StateError('rollback unavailable');
    data = value;
    if (failReplacement && value != damaged) {
      failReplacement = false;
      throw StateError('lost write response');
    }
    if (wrongReplacement && value != damaged) data = 'truncated replacement';
  }
}

class LegacyStore implements DemoStore {
  String? data = damaged;
  @override
  Future<String?> load() async => data;
  @override
  Future<void> save(String value) async { data = value; }
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  test('initial invalid snapshot is retained; recovery preserves original and ledger then pauses permissions', () async {
    final original = source();
    final store = MemoryDemoStore(damaged);
    final controller = DemoController(store);
    await controller.load();
    expect(controller.canRecover, true);
    controller.play();
    await controller.change((e) => e.createAccount('must not exist', 1000000));
    expect(controller.playing, false);
    expect(store.data, damaged);
    expect(await controller.recoverBackup(preview(), expectedDamaged: damaged), true);
    expect(store.recoveryCopy, damaged);
    expect(controller.unreadableSnapshot, isNull);
    final account = controller.engine.accounts.single;
    final before = original.accounts.single;
    for (final field in ['orders', 'positions', 'trades', 'audit', 'reversals', 'watch', 'cash']) {
      expect(account[field], before[field], reason: field);
    }
    final risk = controller.engine.risk(account);
    expect([risk['stop_pct'], risk['take_pct'], risk['trailing_pct']], [7, 77, 9]);
    expect([risk['automation'], risk['scaling_enabled'], risk['reversal_enabled']], [false, false, false]);
    expect([account['known'], account['connected'], account['stopped']], [false, false, true]);
    final reopened = DemoController(store);
    await reopened.load();
    expect(reopened.ready, true);
    expect(reopened.engine.encode(), controller.engine.encode());
    expect(await reopened.recoveryCopy(), damaged);
    expect(await reopened.recoverBackup(preview(), expectedDamaged: damaged), false);
    controller.dispose();
    reopened.dispose();
  });

  test('read failure and unsupported archive storage cannot overwrite an unknown original', () async {
    final store = FaultStore()..failRead = true;
    final controller = DemoController(store);
    await controller.load();
    expect(controller.canRecover, false);
    expect(controller.unreadableSnapshot, isNull);
    expect(await controller.recoverBackup(preview(), expectedDamaged: damaged), false);
    expect(store.activeWrites, 0);
    store.failRead = false;
    await controller.load();
    expect(controller.canRecover, true);
    controller.dispose();
    final legacy = LegacyStore();
    final old = DemoController(legacy);
    await old.load();
    expect(old.unreadableSnapshot, damaged);
    expect(old.canRecover, false);
    expect(await old.recoverBackup(preview(), expectedDamaged: damaged), false);
    expect(legacy.data, damaged);
    old.dispose();
  });

  for (final fault in ['archive failure', 'archive mismatch', 'existing archive']) {
    test('$fault blocks replacement and retains the active original', () async {
      final store = FaultStore();
      if (fault == 'archive failure') store.failArchive = true;
      if (fault == 'archive mismatch') store.wrongArchive = true;
      if (fault == 'existing archive') store.recoveryCopy = 'older original';
      final controller = DemoController(store);
      await controller.load();
      expect(await controller.recoverBackup(preview(), expectedDamaged: damaged), false);
      expect(controller.ready, false);
      expect(store.data, damaged);
      expect(store.activeWrites, 0);
      if (fault == 'existing archive') expect(store.recoveryCopy, 'older original');
      controller.dispose();
    });
  }

  for (final afterArchive in [false, true]) {
    test('changed disk ${afterArchive ? "during archive" : "since preview"} is never overwritten', () async {
      final store = FaultStore();
      final controller = DemoController(store);
      await controller.load();
      final newer = source().encode();
      if (afterArchive) { store.changedDuringArchive = newer; }
      else { store.data = newer; }
      expect(await controller.recoverBackup(preview(), expectedDamaged: damaged), false);
      expect(store.data, newer);
      expect(store.activeWrites, 0);
      await controller.load();
      expect(controller.ready, true);
      controller.dispose();
    });
  }

  for (final mismatch in [false, true]) {
    test('replacement ${mismatch ? "readback mismatch" : "write then throw"} rolls back exact original', () async {
      final store = FaultStore()..failReplacement = !mismatch..wrongReplacement = mismatch;
      final controller = DemoController(store);
      await controller.load();
      expect(await controller.recoverBackup(preview(), expectedDamaged: damaged), false);
      expect(store.data, damaged);
      expect(store.recoveryCopy, damaged);
      expect(controller.ready, false);
      expect(controller.storageUncertain, false);
      store.wrongReplacement = false;
      expect(await controller.recoverBackup(preview(), expectedDamaged: damaged), true);
      controller.dispose();
    });
  }

  test('failed rollback latches writes and leaves original available; readback resolves actual saved state', () async {
    final store = FaultStore()..failReplacement = true..failRollback = true;
    final controller = DemoController(store);
    await controller.load();
    expect(await controller.recoverBackup(preview(), expectedDamaged: damaged), false);
    expect(controller.storageUncertain, true);
    expect(controller.canRecover, false);
    expect(controller.unreadableSnapshot, damaged);
    expect(await controller.recoveryCopy(), damaged);
    final writes = store.activeWrites;
    expect(await controller.recoverBackup(preview(), expectedDamaged: damaged), false);
    await controller.change((e) => e.step());
    expect(store.activeWrites, writes);
    await controller.load();
    expect(controller.ready, true);
    expect(controller.storageUncertain, false);
    expect(controller.engine.risk(controller.engine.accounts.single)['automation'], false);
    controller.dispose();
  });

  test('concurrent recovery load and changes serialize without duplicate writes', () async {
    final store = FaultStore()..releaseArchive = Completer<void>();
    final controller = DemoController(store);
    await controller.load();
    final pending = controller.recoverBackup(preview(), expectedDamaged: damaged);
    await store.archiveStarted.future;
    expect(await controller.recoverBackup(preview(), expectedDamaged: damaged), false);
    await controller.load();
    await controller.change((e) => e.step());
    controller.play();
    expect(controller.playing, false);
    expect(store.activeWrites, 0);
    store.releaseArchive!.complete();
    expect(await pending, true);
    expect(store.activeWrites, 1);
    controller.dispose();
  });

  test('valid in-memory ledger is preserved when an ordinary reload finds corruption', () async {
    final store = MemoryDemoStore(source().encode());
    final controller = DemoController(store);
    await controller.load();
    final before = controller.exportBackup();
    store.data = damaged;
    await controller.load();
    expect(controller.ready, true);
    expect(controller.storageUncertain, true);
    expect(controller.canRecover, false);
    expect(controller.exportBackup(), before);
    expect(store.data, damaged);
    controller.dispose();
  });

  test('preferences adapter retains separate immutable original across controller instances', () async {
    SharedPreferences.setMockInitialValues({PreferencesDemoStore.key: damaged, 'unrelated': 'keep'});
    final controller = DemoController(PreferencesDemoStore());
    await controller.load();
    expect(await controller.recoverBackup(preview(), expectedDamaged: damaged), true);
    final reopened = DemoController(PreferencesDemoStore());
    await reopened.load();
    expect(reopened.ready, true);
    expect(await reopened.recoveryCopy(), damaged);
    final prefs = await SharedPreferences.getInstance();
    expect(prefs.getString('unrelated'), 'keep');
    await expectLater(PreferencesDemoStore().preserveRecoveryCopy('different'), throwsA(isA<DemoRejected>()));
    expect(await reopened.recoveryCopy(), damaged);
    controller.dispose();
    reopened.dispose();
  });
}
