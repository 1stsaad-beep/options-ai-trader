import 'dart:convert';
import 'dart:math';

import 'package:flutter_test/flutter_test.dart';
import 'package:options_ai_trader/brokers/broker_models.dart';
import 'package:options_ai_trader/brokers/broker_store.dart';
import 'package:options_ai_trader/brokers/live_gate.dart';

class FlakyStore extends MemorySecureKeyValue {
  bool dropWrites = false, failReads = false;
  @override
  Future<void> write(String key, String value) async { if (!dropWrites) await super.write(key, value); }
  @override
  Future<String?> read(String key) async { if (failReads) throw StateError('keystore'); return super.read(key); }
}

void main() {
  late MemorySecureKeyValue mem;
  late BrokerAccountRegistry reg;
  setUp(() {
    mem = MemorySecureKeyValue();
    reg = BrokerAccountRegistry(mem, clock: () => DateTime.utc(2026, 10, 17), random: Random(1));
  });

  test('multiple independent accounts per broker; secrets kept out of metadata', () async {
    final a1 = await reg.add(broker: BrokerKind.alpaca, label: 'Alpaca 1', values: {'keyId': 'PKONE1234', 'secretKey': 'secretone1'});
    final a2 = await reg.add(broker: BrokerKind.alpaca, label: 'Alpaca 2', values: {'keyId': 'PKTWO1234', 'secretKey': 'secrettwo1'});
    final ib = await reg.add(broker: BrokerKind.ibkr, label: 'IB', values: {'gatewayUrl': 'https://g:5000', 'accountId': 'DU1234567'});
    final ts = await reg.add(broker: BrokerKind.tradestation, label: 'TS', values: {'clientId': 'c1234567', 'clientSecret': 's1234567', 'refreshToken': 'r1234567'});
    final list = await reg.list();
    expect(list.map((a) => a.id).toSet().length, 4);
    expect(list.where((a) => a.broker == BrokerKind.alpaca).length, 2);
    final index = mem.data[BrokerAccountRegistry.indexKey]!;
    for (final secret in ['secretone1', 'secrettwo1', 'PKONE1234', 's1234567', 'r1234567']) {
      expect(index, isNot(contains(secret)));
    }
    expect((await reg.credentials(a1.id))['secretKey'], 'secretone1');
    expect((await reg.credentials(a2.id))['secretKey'], 'secrettwo1');
    expect(ib.settings['accountId'], 'DU1234567');
    expect((await reg.credentials(ib.id)).values, isEmpty);
    await reg.updateSecret(ts.id, 'refreshToken', 'r7654321');
    expect((await reg.credentials(ts.id))['refreshToken'], 'r7654321');
    expect((await reg.credentials(ts.id))['clientId'], 'c1234567');
    expect(list.every((a) => a.environment == BrokerEnvironment.paper), isTrue);
  });

  test('Live accounts cannot be stored', () async {
    await expectLater(reg.add(broker: BrokerKind.alpaca, label: 'x', environment: BrokerEnvironment.live,
        values: {'keyId': 'PKONE1234', 'secretKey': 'secretone1'}), throwsA(isA<LiveTradingDisabled>()));
    expect(mem.data, isEmpty);
  });

  test('missing required fields or whitespace rejected', () async {
    await expectLater(reg.add(broker: BrokerKind.alpaca, label: 'x', values: {'keyId': 'PK1'}),
        throwsA(isA<BrokerStoreException>()));
    await expectLater(reg.add(broker: BrokerKind.alpaca, label: 'x', values: {'keyId': 'PK 1', 'secretKey': 'a'}),
        throwsA(isA<BrokerStoreException>()));
  });

  test('archive keeps the record; forgetKeys removes only secrets', () async {
    final a = await reg.add(broker: BrokerKind.alpaca, label: 'A', values: {'keyId': 'PKONE1234', 'secretKey': 'secretone1'});
    await reg.forgetKeys(a.id);
    final list = await reg.list();
    expect(list.single.id, a.id);
    expect(list.single.archived, isTrue);
    expect(mem.data.containsKey(BrokerAccountRegistry.secretKey(a.id)), isFalse);
  });

  test('unverified writes are not reported as success', () async {
    final flaky = FlakyStore()..dropWrites = true;
    final r = BrokerAccountRegistry(flaky);
    await expectLater(r.add(broker: BrokerKind.alpaca, label: 'A', values: {'keyId': 'PKONE1234', 'secretKey': 'secretone1'}),
        throwsA(isA<BrokerStoreException>().having((e) => e.code, 'code', 'KEY_SAVE_FAILED')));
  });

  test('keystore read failures and corrupt index are surfaced, not wiped', () async {
    final flaky = FlakyStore()..failReads = true;
    await expectLater(BrokerAccountRegistry(flaky).list(),
        throwsA(isA<BrokerStoreException>().having((e) => e.code, 'code', 'KEYSTORE_UNAVAILABLE')));
    mem.data[BrokerAccountRegistry.indexKey] = jsonEncode({'version': 9});
    await expectLater(reg.list(), throwsA(isA<BrokerStoreException>().having((e) => e.code, 'code', 'STORE_CORRUPT')));
    expect(mem.data[BrokerAccountRegistry.indexKey], isNotNull);
  });

  test('account metadata refuses secret fields', () {
    expect(() => BrokerAccount(id: 'alpaca-x', label: 'A', broker: BrokerKind.alpaca,
        settings: {'secretKey': 'x'}, createdAt: DateTime.utc(2026)), throwsFormatException);
  });
}
