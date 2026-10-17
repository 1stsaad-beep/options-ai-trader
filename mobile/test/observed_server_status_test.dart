import 'package:flutter_test/flutter_test.dart';
import 'package:options_ai_trader/observed_server_status.dart';
import 'package:flutter/material.dart';
import 'observed_server_test.dart' as server_fixture;

Map<String, dynamic> diagnostic() => {'alertScope': 'CURRENT_STATE_READ_ONLY_NO_PUSH_DELIVERY',
  'alerts': ['DATA_AUTH_OR_ENTITLEMENT_DENIED', 'DATA_BACKOFF'], 'diagnosticCode': 'DATA_RATE_LIMITED',
  'dataAccess': {'status': 'OBSERVED', 'authBlocked': true, 'retryAt': '2026-10-13T15:01:30Z', 'chargedRequestsLastMinute': 2}};

void main() {
  test('only approved diagnostic codes with exact persisted reservation amounts', () {
    validateObservedDiagnostics(diagnostic()); validateObservedDiagnostics({});
  });
  for (final mutation in ['unknown', 'duplicate', 'auth', 'fraction', 'time', 'count', 'unverified', 'hidden']) {
    test('rejects $mutation without exposing provider text', () {
      final raw = diagnostic();
      switch (mutation) {
        case 'unknown': raw['alerts'] = ['PRIVATE_PROVIDER_BODY']; break;
        case 'duplicate': raw['alerts'] = ['DATA_BACKOFF', 'DATA_BACKOFF']; break;
        case 'auth': raw['dataAccess']['authBlocked'] = 'true'; break;
        case 'fraction': raw['dataAccess']['chargedRequestsLastMinute'] = 2.0; break;
        case 'time': raw['dataAccess']['retryAt'] = 'private'; break;
        case 'count': raw['dataAccess']['chargedRequestsLastMinute'] = 31; break;
        case 'unverified': raw['dataAccess']['status'] = 'UNVERIFIED'; break;
        case 'hidden': raw['alerts'] = []; break;
      }
      expect(() => validateObservedDiagnostics(raw), throwsFormatException);
    });
  }
  testWidgets('runtime screen labels persistent auth and UTC backoff using GET only', (tester) async {
    final server = server_fixture.Server(), api = server.api(); addTearDown(api.close);
    (server.data['status'] as Map).addAll(diagnostic());
    await server_fixture.mount(tester, api);
    expect(find.byKey(const Key('observed-alert-DATA_AUTH_OR_ENTITLEMENT_DENIED')), findsOneWidget);
    expect(find.textContaining('وقت انتهاء الانتظار UTC'), findsOneWidget);
    expect(server.calls.every((r) => r.method == 'GET'), true);
    expect(tester.takeException(), null);
  });
}
