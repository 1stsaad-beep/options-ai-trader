import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:trader_core/trader_core.dart';

/// Broker credentials live ONLY here: iOS Keychain / Android Keystore-backed
/// encrypted storage. They are never written to JSON files, logs or backups.
class SecretStore {
  static const _storage = FlutterSecureStorage(
    aOptions: AndroidOptions(encryptedSharedPreferences: true),
    iOptions: IOSOptions(accessibility: KeychainAccessibility.first_unlock_this_device),
  );

  String _key(String accountId, String field) => 'oat.v2.$accountId.$field';

  Future<void> save(String accountId, BrokerKind kind, Map<String, String> values) async {
    for (final f in BrokerCredentialSpec.forKind(kind)) {
      final v = values[f.key]?.trim();
      if (v == null || v.isEmpty) {
        await _storage.delete(key: _key(accountId, f.key));
      } else {
        await _storage.write(key: _key(accountId, f.key), value: v);
      }
    }
  }

  Future<BrokerCredentials> load(String accountId, BrokerKind kind) async {
    final out = <String, String>{};
    for (final f in BrokerCredentialSpec.forKind(kind)) {
      final v = await _storage.read(key: _key(accountId, f.key));
      if (v != null) out[f.key] = v;
    }
    return BrokerCredentials(out);
  }

  Future<void> deleteAll(String accountId, BrokerKind kind) async {
    for (final f in BrokerCredentialSpec.forKind(kind)) {
      await _storage.delete(key: _key(accountId, f.key));
    }
  }
}
