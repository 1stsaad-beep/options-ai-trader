import 'dart:convert';
import 'dart:io';

import 'package:path_provider/path_provider.dart';
import 'package:trader_core/trader_core.dart';

/// Stores account profiles and per-account engine state as JSON files in the
/// app's private documents directory. Writes are atomic (temp file + rename).
/// No secrets are ever written here (see SecretStore).
class AccountRepository {
  Directory? _dir;

  Future<Directory> _root() async {
    final existing = _dir;
    if (existing != null) return existing;
    final base = await getApplicationDocumentsDirectory();
    final d = Directory('${base.path}/oat_v2');
    await d.create(recursive: true);
    return _dir = d;
  }

  Future<File> _file(String name) async => File('${(await _root()).path}/$name');

  Future<void> _writeAtomic(String name, Object json) async {
    final target = await _file(name);
    final tmp = File('${target.path}.tmp');
    await tmp.writeAsString(jsonEncode(json), flush: true);
    await tmp.rename(target.path);
  }

  Future<Map<String, dynamic>?> _read(String name) async {
    final f = await _file(name);
    if (!await f.exists()) return null;
    return (jsonDecode(await f.readAsString()) as Map).cast<String, dynamic>();
  }

  Future<List<AccountProfile>> loadProfiles() async {
    final j = await _read('accounts.json');
    if (j == null) return [];
    return [for (final a in (j['accounts'] as List)) AccountProfile.fromJson((a as Map).cast<String, dynamic>())];
  }

  Future<void> saveProfiles(List<AccountProfile> profiles) =>
      _writeAtomic('accounts.json', {'v': 1, 'accounts': [for (final p in profiles) p.toJson()]});

  Future<AccountState> loadState(String accountId) async {
    final j = await _read('state_$accountId.json');
    return j == null ? AccountState() : AccountState.fromJson(j);
  }

  Future<void> saveState(String accountId, AccountState state) => _writeAtomic('state_$accountId.json', state.toJson());

  Future<void> deleteState(String accountId) async {
    final f = await _file('state_$accountId.json');
    if (await f.exists()) await f.delete();
  }
}
