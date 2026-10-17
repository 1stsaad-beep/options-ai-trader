import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:options_ai_trader/brokers/broker_accounts_screen.dart';
import 'package:options_ai_trader/brokers/broker_models.dart';
import 'package:options_ai_trader/brokers/broker_order_journal.dart';
import 'package:options_ai_trader/brokers/broker_store.dart';
import 'package:options_ai_trader/brokers/vault_migration.dart';

/// Counts writes per key to prove appends no longer rewrite the whole journal.
class CountingStore extends MemorySecureKeyValue {
  final writes = <String, int>{};
  int bytesWritten = 0;
  @override
  Future<void> write(String key, String value) {
    writes[key] = (writes[key] ?? 0) + 1;
    bytesWritten += value.length;
    return super.write(key, value);
  }
}

void main() {
  group('segmented order journal', () {
    test('v1 journal is migrated on first append; v1 value is kept byte-identical', () async {
      final mem = CountingStore();
      final v1 = jsonEncode({'version': 1, 'account': 'a1', 'events': [
        for (var i = 1; i <= 3; i++) {'seq': i, 'at': '2026-10-17T10:00:0${i}Z', 'clientOrderId': 'oat-x$i', 'type': 'INTENT',
          'state': 'INTENT', 'contract': 'AAPL261120C00200000', 'side': 'BUY_TO_OPEN', 'quantity': 1}
      ]});
      mem.data[BrokerOrderJournal.key('a1')] = v1;
      final j = BrokerOrderJournal(mem, 'a1', clock: () => DateTime.utc(2026, 10, 17, 12));
      expect((await j.stats())['format'], 'v1');
      expect((await j.events()).length, 3);
      await j.append('oat-x1', 'SEND_RESULT', {'state': 'UNKNOWN'});
      expect(mem.data[BrokerOrderJournal.key('a1')], v1); // never modified or deleted
      final events = await j.events();
      expect(events.map((e) => e['seq']), [1, 2, 3, 4]);
      final stats = await j.stats();
      expect(stats['format'], 'v2-segmented');
      expect((stats['migratedFrom'] as Map)['events'], 3);
      expect((stats['migratedFrom'] as Map)['sha256'], hasLength(64));
      expect((await j.orders()).first.state, 'UNKNOWN');
    });

    test('appends rewrite only the last segment; capacity well beyond the old 2000 cap', () async {
      final mem = CountingStore();
      final j = BrokerOrderJournal(mem, 'a2');
      for (var i = 0; i < 2600; i++) {
        await j.append('oat-o${i ~/ 2}', i.isEven ? 'INTENT' : 'SEND_RESULT', {'state': i.isEven ? 'INTENT' : 'REJECTED',
          if (i.isEven) ...{'contract': 'AAPL261120C00200000', 'side': 'BUY_TO_OPEN', 'quantity': 1}});
      }
      final s = await j.stats();
      expect([s['events'], s['segments']], [2600, 11]);
      expect(mem.writes[BrokerOrderJournal.segmentKey('a2', 0)], BrokerOrderJournal.segmentSize);
      expect(mem.writes[BrokerOrderJournal.segmentKey('a2', 10)], 100);
      // Each append writes at most one segment (<= 250 events) plus the small head.
      expect(mem.bytesWritten / 2600, lessThan(60000));
      final events = await j.events();
      expect(events.length, 2600);
      expect(events.last['seq'], 2600);
    });

    test('an orphan event beyond the head (crash between writes) is ignored; corruption fails closed', () async {
      final mem = MemorySecureKeyValue();
      final j = BrokerOrderJournal(mem, 'a3');
      await j.append('oat-a', 'INTENT', {'state': 'INTENT', 'contract': 'AAPL261120C00200000', 'side': 'BUY_TO_OPEN', 'quantity': 1});
      final seg = jsonDecode(mem.data[BrokerOrderJournal.segmentKey('a3', 0)]!) as Map<String, dynamic>;
      (seg['events'] as List).add({'seq': 2, 'clientOrderId': 'oat-a', 'type': 'ACK'});
      mem.data[BrokerOrderJournal.segmentKey('a3', 0)] = jsonEncode(seg);
      expect((await j.events()).length, 1);
      await j.append('oat-a', 'SEND_RESULT', {'state': 'REJECTED'});
      expect((await j.events()).last['type'], 'SEND_RESULT');
      mem.data[BrokerOrderJournal.headKey('a3')] = '{"version":2,"account":"a3","count":9,"segments":1}';
      await expectLater(j.events(), throwsA(isA<BrokerJournalException>()));
      mem.data.remove(BrokerOrderJournal.segmentKey('a3', 0));
      mem.data[BrokerOrderJournal.headKey('a3')] = '{"version":2,"account":"a3","count":2,"segments":1}';
      await expectLater(j.events(), throwsA(isA<BrokerJournalException>()));
    });

    test('a corrupt v1 journal is never migrated or overwritten', () async {
      final mem = MemorySecureKeyValue();
      mem.data[BrokerOrderJournal.key('a4')] = '{"version":1,"account":"other","events":[]}';
      final j = BrokerOrderJournal(mem, 'a4');
      await expectLater(j.append('oat-z', 'INTENT', {}), throwsA(isA<BrokerJournalException>()));
      expect(mem.data.containsKey(BrokerOrderJournal.headKey('a4')), isFalse);
      expect(mem.data[BrokerOrderJournal.key('a4')], contains('"other"'));
    });
  });

  group('Direct vault -> broker accounts', () {
    late MemorySecureKeyValue mem;
    late BrokerAccountRegistry reg;
    setUp(() {
      mem = MemorySecureKeyValue();
      reg = BrokerAccountRegistry(mem);
    });

    test('migrates once, links an existing key, and never stores key material in the record', () async {
      var calls = 0;
      Future<(String, String)?> vault() async { calls++; return ('PKVAULT001', 'vaultsecret1'); }
      final m = VaultMigration(reg, clock: () => DateTime.utc(2026, 10, 17, 12));
      final r = await m.migrate(vault);
      expect(r.status, 'MIGRATED');
      final a = (await reg.list()).single;
      expect([a.broker, a.label], [BrokerKind.alpaca, VaultMigration.label]);
      expect((await reg.credentials(a.id)).values, {'keyId': 'PKVAULT001', 'secretKey': 'vaultsecret1'});
      expect((await m.migrate(vault)).status, 'ALREADY_MIGRATED');
      expect((await reg.list()).length, 1);
      final record = mem.data[VaultMigration.recordKey]!;
      expect(record, isNot(contains('PKVAULT001')));
      expect(record, isNot(contains('vaultsecret1')));
      expect((await m.history()).single['fingerprint'], VaultMigration.fingerprint('PKVAULT001'));
      expect(calls, 2);
      // Archived account: a fresh migration is allowed, and the earlier entry is kept.
      await reg.forgetKeys(a.id);
      expect((await m.migrate(vault)).status, 'MIGRATED');
      expect((await m.history()).length, 2);
    });

    test('existing manual account with the same key is linked, not duplicated', () async {
      final manual = await reg.add(broker: BrokerKind.alpaca, label: 'mine', values: {'keyId': 'PKVAULT001', 'secretKey': 'vaultsecret1'});
      final r = await VaultMigration(reg).migrate(() async => ('PKVAULT001', 'vaultsecret1'));
      expect([r.status, r.accountId], ['LINKED_EXISTING', manual.id]);
      expect((await reg.list()).length, 1);
    });

    test('missing or incompatible vault keys change nothing', () async {
      expect((await VaultMigration(reg).migrate(() async => null)).status, 'NO_VAULT_KEYS');
      expect((await VaultMigration(reg).migrate(() async => ('id-with-dash!', 'sec:ret+1234'))).status, 'INCOMPATIBLE_KEYS');
      expect(await reg.list(), isEmpty);
      expect(mem.data.containsKey(VaultMigration.recordKey), isFalse);
    });

    testWidgets('import button asks for confirmation and reports the result', (t) async {
      await t.pumpWidget(MaterialApp(home: BrokerAccountsScreen(registry: reg,
          vaultExport: () async => ('PKVAULT001', 'vaultsecret1'))));
      await t.runAsync(() => Future<void>.delayed(const Duration(milliseconds: 20)));
      await t.pumpAndSettle();
      await t.tap(find.byKey(const ValueKey('import-direct-vault')));
      await t.pumpAndSettle();
      await t.tap(find.byKey(const ValueKey('confirm-vault-import')));
      for (var i = 0; i < 5; i++) {
        await t.runAsync(() => Future<void>.delayed(const Duration(milliseconds: 20)));
        await t.pump();
      }
      await t.pumpAndSettle();
      expect(find.byKey(const ValueKey('vault-import-notice')), findsOneWidget);
      expect(find.textContaining('نُقلت المفاتيح'), findsOneWidget);
      expect(find.text(VaultMigration.label), findsOneWidget);
    });
  });
}
