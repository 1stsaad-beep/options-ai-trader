import 'dart:async';
import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:options_ai_trader/demo/backup.dart';
import 'package:options_ai_trader/demo/engine.dart';
import 'package:options_ai_trader/demo/store.dart';

class WriteThenFailStore extends MemoryDemoStore {
  bool failReplacement = false;
  bool rejectRollback = false;
  WriteThenFailStore(super.data);
  @override
  Future<void> save(String value) async {
    if (failReplacement) {
      data = value;
      failReplacement = false;
      throw const DemoRejected('write acknowledged incompletely');
    }
    if (rejectRollback) throw const DemoRejected('storage unavailable');
    await super.save(value);
  }
}

class BlockingBackupStore extends MemoryDemoStore {
  final started = Completer<void>();
  final release = Completer<void>();
  int reads = 0;
  BlockingBackupStore(super.data);
  @override
  Future<String?> load() async { reads++; return super.load(); }
  @override
  Future<void> save(String value) async {
    started.complete();
    await release.future;
    await super.save(value);
  }
}

DemoEngine backupFixture() {
  final engine = DemoEngine();
  final first = engine.createAccount('نسخة محفوظة', 2000000);
  final id = first['id'] as String;
  final order = engine.submit(id, engine.contract('NVDA', 'CALL'), 'BUY', 2, 'entry');
  engine.step(enter: false);
  engine.cancel(id, order['id'] as String);
  engine.submit(id, engine.rows(first, 'positions').single, 'SELL_TO_CLOSE', 1, 'exit');
  engine.step(enter: false);
  final second = engine.createAccount('حساب مستقل', 2000000);
  engine.submit(second['id'], engine.contract('AAPL', 'PUT'), 'BUY', 2, 'pending');
  engine.step(enter: false);
  engine.configure(id, {'automation': true, 'reversal_enabled': true, 'scaling_enabled': true});
  engine.theme = 'light';
  engine.validate();
  return engine;
}

void main() {
  final rejected = throwsA(isA<DemoRejected>());

  test('manual backup roundtrip preserves ledger evidence and pauses imported permissions', () async {
    final source = backupFixture();
    final raw = DemoBackup.export(source);
    final preview = DemoBackup.inspect(raw);
    expect(preview.accountCount, 2);
    expect(preview.tradeCount, 1);
    expect(preview.orderCount, 3);
    expect(preview.positionCount, 1);
    final prior = DemoEngine()..createAccount('الجهاز الحالي', 1000000);
    final store = MemoryDemoStore(prior.encode());
    final controller = DemoController(store);
    await controller.load();
    controller.play();
    expect(await controller.importBackup(preview, expectedCurrent: prior.encode()), true);
    expect(controller.playing, false);
    expect(controller.engine.theme, source.theme);
    for (final original in source.accounts) {
      final imported = controller.engine.account(original['id']);
      for (final field in ['orders', 'positions', 'trades', 'audit', 'reversals', 'watch']) {
        expect(imported[field], original[field], reason: '$field must remain original');
      }
      expect(imported['cash'], original['cash']);
      expect(imported['known'], false);
      expect(imported['connected'], false);
      expect(imported['stopped'], true);
      for (final setting in ['automation', 'reversal_enabled', 'scaling_enabled']) {
        expect(controller.engine.risk(imported)[setting], false);
      }
    }
    final saved = controller.engine.encode();
    controller.dispose();
    final reopened = DemoController(store);
    await reopened.load();
    expect(reopened.engine.encode(), saved);
    expect(reopened.playing, false);
    reopened.dispose();
  });

  test('imported automatic order cannot fill after reconcile until permissions are re-enabled', () async {
    final source = DemoEngine();
    final account = source.createAccount('أمر آلي', 2000000);
    final id = account['id'] as String;
    source.configure(id, {'automation': true, 'entry_method': 'early'});
    source.watch(id, 'AAPL', enabled: false);
    source.watch(id, 'TSLA', enabled: false);
    source.step();
    expect(source.rows(account, 'orders').single['filled'], 0);
    final imported = DemoBackup.prepareImport(DemoBackup.inspect(DemoBackup.export(source)));
    imported.step(enter: false);
    expect(imported.rows(imported.account(id), 'orders').single['filled'], 0);
    imported.reconcile(id);
    imported.resume(id);
    imported.step(enter: false);
    expect(imported.rows(imported.account(id), 'orders').single['filled'], 0);
    expect(imported.risk(imported.account(id))['automation'], false);
  });

  test('future schema, invalid ledger, cross-account ownership and credentials are rejected', () {
    final source = backupFixture();
    final before = source.encode();
    final backup = DemoBackup.export(source);
    String altered(void Function(DemoRow) mutate) {
      final envelope = jsonDecode(backup) as DemoRow;
      final payload = jsonDecode(envelope['payload'] as String) as DemoRow;
      mutate(payload);
      envelope['payload'] = jsonEncode(payload);
      return jsonEncode(envelope);
    }
    for (final mutation in <void Function(DemoRow)>[
      (data) => data['version'] = 99,
      (data) => data['source'] = 'live',
      (data) => data['accounts'][0]['cash'] += 1,
      (data) => data['accounts'][0]['orders'][0]['account_id'] = data['accounts'][1]['id'],
      (data) => data['accounts'][1]['id'] = data['accounts'][0]['id'],
      (data) => data['accounts'][0]['risk']['mode'] = 'live',
      (data) => data['base_url'] = 'https://server.invalid',
      (data) => data['accounts'][0]['token'] = 'not-a-real-token',
      (data) {
        final order = data['accounts'][0]['orders'][0];
        final decision = jsonDecode(order['decision_json'] as String) as DemoRow;
        decision['evidence'] = {'api_key': 'not-a-real-key'};
        order['decision_json'] = jsonEncode(decision);
      },
    ]) {
      expect(() => DemoBackup.inspect(altered(mutation)), rejected);
    }
    final envelope = jsonDecode(backup) as DemoRow;
    expect(() => DemoBackup.inspect(jsonEncode({...envelope, 'version': 2})), rejected);
    expect(() => DemoBackup.inspect(jsonEncode({...envelope, 'extra': true})), rejected);
    expect(() => DemoBackup.inspect('broken JSON'), rejected);
    expect(source.encode(), before);
  });

  test('UTF-8 size bound applies before parsing and export excludes backend fields', () {
    final large = String.fromCharCodes(List.filled(DemoBackup.maxBytes ~/ 2 + 1, 0x0639));
    expect(() => DemoBackup.inspect(large), rejected);
    final engine = DemoEngine();
    final account = engine.createAccount('بدون اتصال', 2000000);
    engine.submit(account['id'], engine.contract('NVDA', 'CALL'), 'BUY', 1, 'manual',
      evidence: {'server_url': 'https://server.invalid'});
    expect(() => DemoBackup.export(engine), rejected);
  });

  test('failed save leaves existing memory and persisted data intact', () async {
    final prior = DemoEngine()..createAccount('قديم', 1000000);
    final store = MemoryDemoStore(prior.encode());
    final controller = DemoController(store);
    await controller.load();
    store.failWrites = true;
    expect(await controller.importBackup(DemoBackup.inspect(DemoBackup.export(backupFixture())), expectedCurrent: prior.encode()), false);
    expect(controller.engine.encode(), prior.encode());
    expect(store.data, prior.encode());
    expect(controller.storageUncertain, false);
    controller.dispose();
  });

  test('write then throw restores previous persistent bytes before returning failure', () async {
    final prior = DemoEngine()..createAccount('قديم', 1000000);
    final store = WriteThenFailStore(prior.encode());
    final controller = DemoController(store);
    await controller.load();
    store.failReplacement = true;
    expect(await controller.importBackup(DemoBackup.inspect(DemoBackup.export(backupFixture())), expectedCurrent: prior.encode()), false);
    expect(controller.engine.encode(), prior.encode());
    expect(store.data, prior.encode());
    expect(controller.storageUncertain, false);
    controller.dispose();
  });

  test('unverifiable rollback locks mutations while preserving export until explicit reload', () async {
    final prior = DemoEngine()..createAccount('قديم', 1000000);
    final store = WriteThenFailStore(prior.encode());
    final controller = DemoController(store);
    await controller.load();
    store.failReplacement = true;
    store.rejectRollback = true;
    final preview = DemoBackup.inspect(DemoBackup.export(backupFixture()));
    expect(await controller.importBackup(preview, expectedCurrent: prior.encode()), false);
    expect(controller.storageUncertain, true);
    final uncertainDisk = store.data;
    await controller.change((engine) => engine.createAccount('لا يُكتب', 1000000));
    controller.play();
    expect(await controller.importBackup(preview, expectedCurrent: prior.encode()), false);
    expect(controller.playing, false);
    expect(controller.engine.encode(), prior.encode());
    expect(store.data, uncertainDisk);
    expect(DemoBackup.inspect(controller.exportBackup()).accountNames, ['قديم']);
    store.rejectRollback = false;
    await controller.load();
    expect(controller.storageUncertain, false);
    expect(controller.engine.accounts.length, 2);
    controller.dispose();
  });

  test('overlapping load, changes and playback cannot race an import save', () async {
    final prior = DemoEngine()..createAccount('قديم', 1000000);
    final store = BlockingBackupStore(prior.encode());
    final controller = DemoController(store);
    await controller.load();
    final pending = controller.importBackup(DemoBackup.inspect(DemoBackup.export(backupFixture())), expectedCurrent: prior.encode());
    await store.started.future;
    final reads = store.reads;
    await controller.load();
    await controller.change((engine) => engine.step());
    controller.play();
    expect(store.reads, reads);
    expect(controller.playing, false);
    expect(controller.engine.encode(), prior.encode());
    store.release.complete();
    expect(await pending, true);
    expect(controller.engine.accounts.length, 2);
    controller.dispose();
  });

  test('target state changed after preview cannot be silently replaced', () async {
    final prior = DemoEngine()..createAccount('قديم', 1000000);
    final store = MemoryDemoStore(prior.encode());
    final controller = DemoController(store);
    await controller.load();
    final expectedCurrent = controller.engine.encode();
    final preview = DemoBackup.inspect(DemoBackup.export(backupFixture()));
    await controller.change((engine) => engine.createAccount('تغيير أحدث', 1000000));
    final updated = store.data;
    expect(await controller.importBackup(preview, expectedCurrent: expectedCurrent), false);
    expect(store.data, updated);
    expect(controller.engine.accounts.last['name'], 'تغيير أحدث');
    expect(controller.error, contains('تغيرت بيانات Demo'));
    controller.dispose();
  });

  test('missing or corrupt disk on uncertain reload keeps original memory exportable', () async {
    for (final diskValue in <String?>[null, 'corrupted']) {
      final prior = DemoEngine()..createAccount('النسخة المتبقية', 1000000);
      final store = WriteThenFailStore(prior.encode());
      final controller = DemoController(store);
      await controller.load();
      store.failReplacement = true;
      store.rejectRollback = true;
      final preview = DemoBackup.inspect(DemoBackup.export(backupFixture()));
      expect(await controller.importBackup(preview, expectedCurrent: prior.encode()), false);
      store.data = diskValue;
      await controller.load();
      expect(controller.ready, true);
      expect(controller.storageUncertain, true);
      expect(controller.engine.encode(), prior.encode());
      expect(store.data, diskValue);
      expect(DemoBackup.inspect(controller.exportBackup()).accountNames, ['النسخة المتبقية']);
      controller.dispose();
    }
  });

  test('ordinary change restores memory and disk when save writes then throws', () async {
    final prior = DemoEngine()..createAccount('النسخة الحالية', 1000000);
    final store = WriteThenFailStore(prior.encode());
    final controller = DemoController(store);
    await controller.load();
    controller.play();
    store.failReplacement = true;
    await controller.change((engine) => engine.createAccount('كتابة فاشلة', 1000000));
    expect(controller.engine.encode(), prior.encode());
    expect(store.data, prior.encode());
    expect(controller.storageUncertain, false);
    expect(controller.playing, false);
    expect(controller.error, isNotNull);
    controller.dispose();
  });

  test('ordinary change rollback failure latches writes and preserves original export', () async {
    final prior = DemoEngine()..createAccount('النسخة القابلة للتصدير', 1000000);
    final store = WriteThenFailStore(prior.encode());
    final controller = DemoController(store);
    await controller.load();
    controller.play();
    store.failReplacement = true;
    store.rejectRollback = true;
    await controller.change((engine) => engine.createAccount('حفظ غير مؤكد', 1000000));
    expect(controller.storageUncertain, true);
    expect(controller.playing, false);
    expect(controller.engine.encode(), prior.encode());
    final uncertainDisk = store.data;
    await controller.change((engine) => engine.createAccount('يجب ألا يُكتب', 1000000));
    controller.play();
    expect(controller.playing, false);
    expect(controller.engine.encode(), prior.encode());
    expect(store.data, uncertainDisk);
    expect(DemoBackup.inspect(controller.exportBackup()).accountNames, ['النسخة القابلة للتصدير']);
    controller.dispose();
  });
}
