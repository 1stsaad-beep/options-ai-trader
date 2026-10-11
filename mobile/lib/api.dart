import 'dart:async';
import 'dart:convert';

import 'package:http/http.dart' as http;

import 'analysis_contract.dart';

class ApiException implements Exception {
  final String message;
  final int? status;
  const ApiException(this.message, [this.status]);
  @override
  String toString() => message;
}

/// Each request names the account explicitly. There is no live-order route here.
class TraderApi {
  final http.Client client;
  String baseUrl;
  String token;
  TraderApi({
    http.Client? client,
    this.baseUrl = const String.fromEnvironment(
      'API_URL',
      defaultValue: 'http://10.0.2.2:8000',
    ),
    this.token = '',
  }) : client = client ?? http.Client();

  Future<dynamic> request(String method, String path, [Object? body]) async {
    final base = Uri.tryParse(baseUrl);
    if (base == null ||
        !['http', 'https'].contains(base.scheme) ||
        base.host.isEmpty ||
        base.userInfo.isNotEmpty) {
      throw const ApiException('عنوان الخادم غير صالح');
    }
    if (base.scheme != 'https' &&
        !['localhost', '127.0.0.1', '10.0.2.2'].contains(base.host)) {
      throw const ApiException('استخدم HTTPS للخادم البعيد أو نفقًا محليًا');
    }
    if (!path.startsWith('/api/') ||
        path.contains('://') ||
        path.contains('..')) {
      throw const ApiException('مسار API غير صالح');
    }
    if (base.hasQuery || base.hasFragment) {
      throw const ApiException(
        'عنوان الخادم لا يقبل استعلامًا أو جزءًا إضافيًا',
      );
    }
    final req = http.Request(
      method,
      Uri.parse('${baseUrl.replaceAll(RegExp(r'/$'), '')}$path'),
    );
    req.followRedirects = false;
    req.headers['Content-Type'] = 'application/json';
    if (token.isNotEmpty) req.headers['Authorization'] = 'Bearer $token';
    if (body != null) req.body = jsonEncode(body);
    try {
      final response = await client
          .send(req)
          .then(http.Response.fromStream)
          .timeout(const Duration(seconds: 12));
      if (response.statusCode >= 300 && response.statusCode < 400) {
        throw const ApiException(
          'رفض إعادة توجيه اتصال الخادم حفاظًا على رمز الوصول',
        );
      }
      final dynamic value = response.body.isEmpty
          ? null
          : jsonDecode(response.body);
      if (response.statusCode >= 400) {
        throw ApiException(
          value is Map
              ? '${value['detail'] ?? 'تعذر تنفيذ الطلب'}'
              : 'تعذر تنفيذ الطلب',
          response.statusCode,
        );
      }
      return value;
    } on TimeoutException {
      throw const ApiException(
        'انتهت مهلة الاتصال؛ لا يتم إرسال أوامر تلقائيًا من التطبيق',
      );
    } on FormatException {
      throw const ApiException('استجابة الخادم غير صالحة');
    } on http.ClientException {
      throw const ApiException('تعذر الاتصال بالخادم');
    }
  }

  Future<List<Map<String, dynamic>>> list(String path) async {
    final dynamic value = await request('GET', path);
    final dynamic rows = value is List
        ? value
        : (value is Map ? value['items'] : null);
    if (rows is! List ||
        rows.any((e) => e is! Map || e.keys.any((key) => key is! String))) {
      throw const ApiException(
        'استجابة القائمة غير صالحة؛ لن نعرض بيانات ناقصة',
      );
    }
    final List<dynamic> validRows = rows;
    return validRows.map((e) => Map<String, dynamic>.from(e as Map)).toList();
  }

  /// Runs one server-owned, risk-gated Mock cycle. Never retries a mutation.
  Future<Map<String, dynamic>> runMockCycle(String accountId) async {
    if (accountId.trim().isEmpty) {
      throw const ApiException('معرّف الحساب غير صالح');
    }
    final dynamic value = await request(
      'POST',
      '/api/accounts/${Uri.encodeComponent(accountId)}/automation/run',
      <String, dynamic>{},
    );
    if (value is! Map ||
        value.keys.any((key) => key is! String) ||
        value['account_id'] != accountId ||
        value['source'] != 'synthetic_mock') {
      throw const ApiException('نتيجة دورة المحاكاة لا تطابق الحساب أو المصدر');
    }
    return Map<String, dynamic>.from(value);
  }

  String _researchPath(String accountId, String symbol) {
    if (accountId.trim().isEmpty ||
        !RegExp(r'^[A-Z][A-Z0-9.]{0,9}$').hasMatch(symbol)) {
      throw const ApiException('الحساب أو رمز البحث غير صالح');
    }
    return '/api/accounts/${Uri.encodeComponent(accountId)}/research/${Uri.encodeComponent(symbol)}';
  }

  T _researchResult<T>(T Function() parse) {
    try {
      return parse();
    } on FormatException {
      throw const ApiException(
        'استجابة البحث غير موثوقة أو لا تخص الحساب والرمز المحددين؛ تحقق من توافق إصدار الخادم',
      );
    }
  }

  Future<ResearchWorkbench> inspectResearch(String accountId, String symbol) async {
    final value = await request('GET', _researchPath(accountId, symbol));
    return _researchResult(() => ResearchWorkbench.parse(value, accountId, symbol));
  }

  /// A snapshot journals research only. An uncertain response is never retried.
  Future<ResearchSnapshot> saveResearchSnapshot(String accountId, String symbol) async {
    final value = await request('POST', '${_researchPath(accountId, symbol)}/snapshot',
      <String, dynamic>{});
    return _researchResult(() => ResearchSnapshot.parse(value, accountId, symbol));
  }

  Future<ResearchSnapshotList> listResearchSnapshots(String accountId, String symbol) async {
    final value = await request('GET', '${_researchPath(accountId, symbol)}/snapshots');
    return _researchResult(() => ResearchSnapshotList.parse(value, accountId, symbol));
  }

  Future<ResearchReplay> replayResearchSnapshot(
      String accountId, String symbol, String snapshotId) async {
    if (snapshotId.trim().isEmpty) {
      throw const ApiException('معرّف لقطة البحث غير صالح');
    }
    final value = await request('GET',
      '${_researchPath(accountId, symbol)}/snapshots/${Uri.encodeComponent(snapshotId)}/replay');
    return _researchResult(() => ResearchReplay.parse(value, accountId, symbol, snapshotId));
  }

  /// Explicitly persists a later synthetic observation; never retries a write.
  Future<ResearchObservation> captureResearchObservation(
      String accountId, String symbol, String snapshotId) async {
    if (snapshotId.trim().isEmpty) {
      throw const ApiException('معرّف لقطة البحث غير صالح');
    }
    final value = await request('POST',
      '${_researchPath(accountId, symbol)}/snapshots/${Uri.encodeComponent(snapshotId)}/observations',
      <String, dynamic>{});
    return _researchResult(() => ResearchObservation.parse(value, accountId, symbol, snapshotId));
  }

  void close() => client.close();
}
