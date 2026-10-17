import 'dart:convert';
import '../bounded_json.dart';

import 'engine.dart';

/// Manual local-data portability, not a signature or proof of historical truth.
class DemoBackupPreview {
  final String _payload;
  final List<String> accountNames;
  final int orderCount;
  final int positionCount;
  final int tradeCount;
  final int tick;
  int get accountCount => accountNames.length;

  DemoBackupPreview._(this._payload, this.accountNames, this.orderCount,
      this.positionCount, this.tradeCount, this.tick);
}

class DemoBackup {
  static const format = 'options-ai-trader-local-demo-backup';
  static const version = 1;
  static const maxBytes = 2 * 1024 * 1024;

  static void _bounded(String text) {
    if (text.length > maxBytes) {
      throw const DemoRejected('النسخة تتجاوز حد 2 MiB؛ لم تتغير بيانات الجهاز');
    }
  }

  static String export(DemoEngine engine) {
    engine.validate();
    final text = jsonEncode({'format': format, 'version': version,
      'payload': engine.encode()});
    // Apply the same credential and schema boundary in both directions.
    inspect(text);
    return text;
  }

  static DemoBackupPreview inspect(String text) {
    _bounded(text);
    try {
      final envelope = decodeBoundedJson(text, maxBytes: maxBytes, maxNodes: 4, maxDepth: 1);
      if (envelope is! Map<String, dynamic> ||
          envelope.length != 3 ||
          !['format', 'version', 'payload'].every(envelope.containsKey) ||
          envelope['format'] != format || envelope['version'] is! int ||
          envelope['version'] != version || envelope['payload'] is! String) {
        throw const DemoRejected('صيغة النسخة أو إصدارها غير مدعوم');
      }
      final payload = envelope['payload'] as String;
      _bounded(payload);
      final data = decodeBoundedJson(payload, maxBytes: maxBytes, maxNodes: 100000, maxDepth: 64);
      const keys = ['version', 'source', 'tick', 'sequence', 'scenario',
        'theme', 'market', 'global_stop', 'accounts'];
      if (data is! Map<String, dynamic> || data.length != keys.length ||
          !keys.every(data.containsKey) || data['version'] is! int || data['version'] != 2 ||
          data['accounts'] is! List) {
        throw const DemoRejected('محتوى النسخة ليس حالة Demo مدعومة');
      }
      const accountKeys = ['id', 'name', 'initial', 'cash', 'known', 'connected',
        'stopped', 'risk', 'orders', 'positions', 'trades', 'audit', 'reversals', 'watch'];
      for (final account in data['accounts'] as List) {
        if (account is! Map<String, dynamic> || account.length != accountKeys.length ||
            !accountKeys.every(account.containsKey)) {
          throw const DemoRejected('تحتوي النسخة على حقول حساب غير مدعومة');
        }
      }
      var visited = 0;
      void inspectFields(dynamic value, int depth) {
        if (++visited > 100000 || depth > 64) {
          throw const DemoRejected('بنية النسخة تتجاوز حدود التحقق الآمن');
        }
        if (value is Map) {
          for (final item in value.entries) {
            final key = '${item.key}'.toLowerCase().replaceAll(RegExp(r'[_\-]'), '');
            if (const ['token', 'accesstoken', 'refreshtoken', 'password',
              'privatekey', 'apikey', 'clientsecret', 'authorization',
              'baseurl', 'apiurl', 'serverurl'].contains(key)) {
              throw const DemoRejected('لا يسمح بنقل بيانات اعتماد أو إعداد اتصال خادم');
            }
            inspectFields(item.value, depth + 1);
          }
        } else if (value is List) {
          for (final item in value) { inspectFields(item, depth + 1); }
        } else if (value is String) {
          final trimmed = value.trimLeft();
          if (trimmed.startsWith('{') || trimmed.startsWith('[')) {
            dynamic nested;
            try {
              nested = decodeBoundedJson(value, maxBytes: maxBytes,
                maxNodes: 100000 - visited, maxDepth: 64 - depth - 1);
            } on JsonBoundsException { rethrow; } on JsonDuplicateKeyException { rethrow; } on FormatException { return; }
            inspectFields(nested, depth + 1);
          }
        }
      }
      inspectFields(data, 0);
      final engine = DemoEngine.decode(payload);
      int count(String field) => engine.accounts.fold(0,
        (total, account) => total + engine.rows(account, field).length);
      return DemoBackupPreview._(engine.encode(),
        List.unmodifiable(engine.accounts.map((account) => account['name'] as String)),
        count('orders'), count('positions'), count('trades'), engine.tick);
    } on DemoRejected {
      rethrow;
    } catch (_) {
      throw const DemoRejected('النسخة غير صالحة؛ لن تُستبدل بيانات الجهاز');
    }
  }

  static DemoEngine prepareImport(DemoBackupPreview preview) {
    final engine = DemoEngine.decode(preview._payload);
    for (final account in engine.accounts) {
      account['connected'] = false;
      account['known'] = false;
      account['stopped'] = true;
      final risk = engine.risk(account);
      risk['automation'] = false;
      risk['reversal_enabled'] = false;
      risk['scaling_enabled'] = false;
    }
    engine.validate();
    return engine;
  }
}
