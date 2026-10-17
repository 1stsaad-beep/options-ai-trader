import 'observed_server.dart';
import 'paper_time.dart';

const observedAlertLabels = {
  'WORKER_UNAVAILABLE': 'نبض العامل غير متاح أو قديم؛ لا نفترض استمرار المعالجة.',
  'LEDGER_REVIEW_REQUIRED': 'حساب محجوب أو تعارض في السجل؛ راجع حالة الحساب والأحداث.',
  'DATA_AUTH_OR_ENTITLEMENT_DENIED': 'المصادقة أو صلاحية البيانات مرفوضة؛ القفل محفوظ ولا يزول بتحديث الصفحة.',
  'DATA_RATE_LIMITED': 'ميزانية الطلبات أو حد المزود يوقف القراءة مؤقتًا.',
  'DATA_BACKOFF': 'انتظار محفوظ قبل إعادة محاولة مصدر البيانات.',
  'INVALID_PROVIDER_RESPONSE': 'رد مزود البيانات غير صالح؛ لم تُختلق بيانات بديلة.',
  'DATA_UNAVAILABLE': 'مصدر البيانات غير متاح لهذه الدورة.',
  'OBSERVED_DEMAND_LIMIT': 'عدد الرموز أو العقود المطلوبة يتجاوز سعة الالتقاط الحالية.',
  'WORKER_LEASE_LOST': 'انتهت ملكية العامل؛ لا تعتمد نتيجة التقاط قديم.',
  'DATA_ROUTE_FORBIDDEN': 'مسار قراءة البيانات محظور بواسطة سياسة الاتصال.',
  'DATA_STATE_REVIEW_REQUIRED': 'حالة اتصال البيانات المحفوظة تحتاج مراجعة؛ لم تُعد تهيئتها تلقائيًا.',
};

void validateObservedDiagnostics(Map<String, dynamic> status) {
  if (!status.containsKey('alerts')) return; // Older read-only server response.
  final alerts = status['alerts'], access = observedObject(status['dataAccess']);
  if (status['alertScope'] != 'CURRENT_STATE_READ_ONLY_NO_PUSH_DELIVERY' || alerts is! List ||
      alerts.length > observedAlertLabels.length || alerts.toSet().length != alerts.length ||
      alerts.any((code) => !observedAlertLabels.containsKey(code)) ||
      !['NOT_OBSERVED', 'OBSERVED', 'UNVERIFIED'].contains(access['status'])) {
    throw const FormatException('Invalid runtime diagnostics');
  }
  if (status['diagnosticCode'] != null && !observedAlertLabels.containsKey(status['diagnosticCode'])) {
    throw const FormatException('Untrusted provider message');
  }
  if (access['status'] == 'OBSERVED') {
    if (access['authBlocked'] is! bool || !observedInteger(access['chargedRequestsLastMinute']) ||
        access['chargedRequestsLastMinute'] > 30) { throw const FormatException('Invalid request accounting'); }
    if (access['retryAt'] != null) observationStamp(access['retryAt']);
    if (access['authBlocked'] == true && !alerts.contains('DATA_AUTH_OR_ENTITLEMENT_DENIED')) {
      throw const FormatException('Hidden authentication block');
    }
  } else if (access['authBlocked'] != null || access['retryAt'] != null || access['chargedRequestsLastMinute'] != null) {
    throw const FormatException('Unverified runtime values');
  }
}
