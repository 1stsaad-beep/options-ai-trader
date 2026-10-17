/// Secure local storage of broker accounts and credentials.
///
/// Android: flutter_secure_storage (AES-GCM data key wrapped by Android
/// Keystore), with `resetOnError: false` so a Keystore failure is reported
/// instead of silently wiping keys. Account metadata (no secrets) and each
/// account's secret fields are separate entries. Every write is read back
/// before success is reported. Archiving keeps the account record (history is
/// never deleted); only the user's explicit "forget keys" removes secrets.
library;

import 'dart:convert';
import 'dart:math';

import 'package:flutter_secure_storage/flutter_secure_storage.dart';

import 'broker_models.dart';
import 'live_gate.dart';

abstract class SecureKeyValue {
  Future<String?> read(String key);
  Future<void> write(String key, String value);
  Future<void> delete(String key);
}

class PlatformSecureKeyValue implements SecureKeyValue {
  final FlutterSecureStorage _storage;
  PlatformSecureKeyValue()
      : _storage = const FlutterSecureStorage(
            aOptions: AndroidOptions(resetOnError: false, storageNamespace: 'oat_brokers_v1'));
  @override
  Future<String?> read(String key) => _storage.read(key: key);
  @override
  Future<void> write(String key, String value) => _storage.write(key: key, value: value);
  @override
  Future<void> delete(String key) => _storage.delete(key: key);
}

class BrokerStoreException implements Exception {
  final String code;
  const BrokerStoreException(this.code);
  @override
  String toString() => 'BrokerStoreException($code)';
}

class BrokerAccountRegistry {
  static const indexKey = 'oat.brokers.accounts.v1';
  static const maxAccountsPerBroker = 20;
  static String secretKey(String id) => 'oat.brokers.secret.v1.$id';

  final SecureKeyValue storage;
  final DateTime Function() now;
  final Random _random;
  BrokerAccountRegistry(this.storage, {DateTime Function()? clock, Random? random})
      : now = clock ?? DateTime.now, _random = random ?? Random.secure();

  Future<List<BrokerAccount>> list() async {
    final String? text;
    try {
      text = await storage.read(indexKey);
    } catch (_) {
      throw const BrokerStoreException('KEYSTORE_UNAVAILABLE');
    }
    if (text == null) return const [];
    try {
      final j = jsonDecode(text) as Map<String, dynamic>;
      if (j['version'] != 1) throw const FormatException();
      return [for (final a in j['accounts'] as List) BrokerAccount.fromJson(a as Map<String, dynamic>)];
    } catch (_) {
      throw const BrokerStoreException('STORE_CORRUPT');
    }
  }

  Future<void> _writeVerified(String key, String value) async {
    try {
      await storage.write(key, value);
      if (await storage.read(key) != value) throw const BrokerStoreException('KEY_SAVE_FAILED');
    } on BrokerStoreException {
      rethrow;
    } catch (_) {
      throw const BrokerStoreException('KEY_SAVE_FAILED');
    }
  }

  Future<void> _saveIndex(List<BrokerAccount> accounts) => _writeVerified(
      indexKey, jsonEncode({'version': 1, 'accounts': [for (final a in accounts) a.toJson()]}));

  String _newId(BrokerKind kind) {
    const alphabet = 'abcdefghijklmnopqrstuvwxyz0123456789';
    return '${kind.name}-${List.generate(12, (_) => alphabet[_random.nextInt(alphabet.length)]).join()}';
  }

  /// Splits [values] into non-secret settings and secrets by the broker field spec.
  Future<BrokerAccount> add({required BrokerKind broker, required String label,
      required Map<String, String> values, BrokerEnvironment environment = BrokerEnvironment.paper}) async {
    LiveTradingGate.requirePaper(environment);
    final settings = <String, String>{}, secrets = <String, String>{};
    for (final f in broker.fields) {
      final v = (values[f.name] ?? '').trim();
      if (v.isEmpty) {
        if (f.required) throw const BrokerStoreException('INVALID_KEYS');
        continue;
      }
      if (v.length > 4096 || v.contains(RegExp(r'\s'))) throw const BrokerStoreException('INVALID_KEYS');
      // Alpaca issues live trading key IDs with an "AK" prefix (Paper: "PK"); never store a known live key.
      if (broker == BrokerKind.alpaca && f.name == 'keyId' && v.startsWith('AK')) {
        throw const BrokerStoreException('ALPACA_LIVE_KEY');
      }
      (f.secret ? secrets : settings)[f.name] = v;
    }
    final accounts = await list();
    if (accounts.where((a) => a.broker == broker && !a.archived).length >= maxAccountsPerBroker) {
      throw const BrokerStoreException('TOO_MANY_ACCOUNTS');
    }
    final account = BrokerAccount(id: _newId(broker), label: label, broker: broker,
        environment: environment, settings: settings, createdAt: now());
    if (secrets.isNotEmpty) await _writeVerified(secretKey(account.id), jsonEncode(secrets));
    await _saveIndex([...accounts, account]);
    return account;
  }

  Future<BrokerCredentials> credentials(String id) async {
    final String? text;
    try {
      text = await storage.read(secretKey(id));
    } catch (_) {
      throw const BrokerStoreException('KEYSTORE_UNAVAILABLE');
    }
    if (text == null) return BrokerCredentials(const {});
    try {
      return BrokerCredentials((jsonDecode(text) as Map).cast<String, String>());
    } catch (_) {
      throw const BrokerStoreException('STORE_CORRUPT');
    }
  }

  /// Persists a rotated OAuth refresh token for [id] (TradeStation).
  Future<void> updateSecret(String id, String field, String value) async {
    final current = Map<String, String>.of((await credentials(id)).values);
    current[field] = value;
    await _writeVerified(secretKey(id), jsonEncode(current));
  }

  /// Keeps the account record; hides it from active use.
  Future<void> archive(String id) async {
    final accounts = await list();
    if (!accounts.any((a) => a.id == id)) throw const BrokerStoreException('ACCOUNT_NOT_FOUND');
    await _saveIndex([for (final a in accounts) a.id == id ? a.copyWith(archived: true) : a]);
  }

  /// Explicit user action: removes only the secret entry; the account record stays (archived).
  Future<void> forgetKeys(String id) async {
    await archive(id);
    try {
      await storage.delete(secretKey(id));
      if (await storage.read(secretKey(id)) != null) throw const BrokerStoreException('KEY_DELETE_FAILED');
    } on BrokerStoreException {
      rethrow;
    } catch (_) {
      throw const BrokerStoreException('KEY_DELETE_FAILED');
    }
  }
}

class MemorySecureKeyValue implements SecureKeyValue {
  final Map<String, String> data = {};
  @override
  Future<String?> read(String key) async => data[key];
  @override
  Future<void> write(String key, String value) async => data[key] = value;
  @override
  Future<void> delete(String key) async => data.remove(key);
}
