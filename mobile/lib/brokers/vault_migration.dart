/// B12: merge the older Direct Alpaca vault into broker accounts.
///
/// Explicit, user-confirmed, idempotent copy. The Direct vault (native Keystore) is
/// never modified or deleted, so Direct market data keeps working unchanged. Every
/// migration attempt that changes state is appended to a record (never rewritten);
/// the record holds only a short fingerprint of the key id, never key material.
library;

import 'dart:convert';

import 'package:crypto/crypto.dart';

import 'broker_models.dart';
import 'broker_store.dart';

typedef VaultExport = Future<(String, String)?> Function();

class VaultMigrationResult {
  final String status; // MIGRATED / LINKED_EXISTING / ALREADY_MIGRATED / NO_VAULT_KEYS / INCOMPATIBLE_KEYS
  final String? accountId;
  const VaultMigrationResult(this.status, [this.accountId]);
}

class VaultMigration {
  static const recordKey = 'oat.brokers.migration.v1';
  static const label = 'Alpaca (من خزنة Direct)';
  static final _alpacaKey = RegExp(r'^[A-Za-z0-9]{8,128}$');
  final BrokerAccountRegistry registry;
  final DateTime Function() now;
  VaultMigration(this.registry, {DateTime Function()? clock}) : now = clock ?? DateTime.now;

  static String fingerprint(String keyId) =>
      sha256.convert(utf8.encode('oat-direct-vault:$keyId')).toString().substring(0, 16);

  Future<List<Map<String, dynamic>>> history() async {
    final text = await registry.storage.read(recordKey);
    if (text == null) return [];
    final j = jsonDecode(text) as Map<String, dynamic>;
    if (j['version'] != 1 || j['entries'] is! List) throw const BrokerStoreException('STORE_CORRUPT');
    return [for (final e in j['entries'] as List) Map<String, dynamic>.from(e as Map)];
  }

  Future<void> _append(Map<String, dynamic> entry) async {
    final entries = [...await history(), {'at': now().toUtc().toIso8601String(), ...entry}];
    final text = jsonEncode({'version': 1, 'entries': entries});
    await registry.storage.write(recordKey, text);
    if (await registry.storage.read(recordKey) != text) throw const BrokerStoreException('WRITE_UNCONFIRMED');
  }

  Future<VaultMigrationResult> migrate(VaultExport export) async {
    final keys = await export();
    if (keys == null) return const VaultMigrationResult('NO_VAULT_KEYS');
    final (keyId, secret) = keys;
    if (!_alpacaKey.hasMatch(keyId) || !_alpacaKey.hasMatch(secret)) return const VaultMigrationResult('INCOMPATIBLE_KEYS');
    final fp = fingerprint(keyId);
    final accounts = await registry.list();
    final active = {for (final a in accounts.where((a) => !a.archived && a.broker == BrokerKind.alpaca)) a.id: a};
    for (final e in (await history()).reversed) {
      if (e['fingerprint'] == fp && active.containsKey(e['accountId'])) return VaultMigrationResult('ALREADY_MIGRATED', e['accountId'] as String);
    }
    for (final a in active.values) {
      final c = await registry.credentials(a.id);
      if (c.values['keyId'] == keyId) {
        await _append({'fingerprint': fp, 'accountId': a.id, 'action': 'LINKED_EXISTING'});
        return VaultMigrationResult('LINKED_EXISTING', a.id);
      }
    }
    final added = await registry.add(broker: BrokerKind.alpaca, label: label, values: {'keyId': keyId, 'secretKey': secret});
    await _append({'fingerprint': fp, 'accountId': added.id, 'action': 'MIGRATED', 'vaultUnchanged': true});
    return VaultMigrationResult('MIGRATED', added.id);
  }
}
