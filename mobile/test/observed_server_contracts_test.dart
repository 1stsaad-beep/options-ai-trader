import 'dart:convert';
import 'dart:io';
import 'package:crypto/crypto.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:options_ai_trader/api.dart';
import 'package:options_ai_trader/observed_server.dart';
import 'package:options_ai_trader/observed_server_contracts.dart';

Map<String, dynamic> scenario(String name) => ((jsonDecode(File('test/fixtures/contract_evidence_v1.json').readAsStringSync()) as Map)['cases'] as List)
    .singleWhere((c) => c['name'] == name) as Map<String, dynamic>;
Map<String, dynamic> parse(Map<String, dynamic> c) => parseObservedContracts(c['report'], ObservedServerAccount.parse(c['snapshot'], 'metadata'));
void rehash(Map<String, dynamic> r) {
  final body = Map<String, dynamic>.from(r)..remove('reportHash')..remove('reportPayload');
  r['reportPayload'] = jsonEncode(body);
  r['reportHash'] = sha256.convert(utf8.encode(r['reportPayload'] as String)).toString();
}

void main() {
  for (final name in ['missing', 'terms', 'complete', 'adjusted', 'delayed', 'stale', 'partial', 'tiny']) {
    test('SQL $name contract qualification agrees independently', () {
      final c = scenario(name), value = parse(c);
      expect(value, c['report']);
      expect(value['entryEligible'], false);
      expect(value['contracts'][0]['qualification']['greeksProviderTimestamp'], null);
      (value['contracts'] as List).clear();
      expect(c['report']['contracts'], isNotEmpty);
    });
  }
  for (final mutation in ['source', 'account', 'version', 'hash', 'payload', 'entry', 'settlement', 'standard',
    'reason', 'greek-time', 'greek-value', 'terms-hash', 'binding', 'future', 'capture', 'missing', 'duplicate']) {
    test('rejects forged $mutation even with recomputed outer hash', () {
      final c = scenario('complete'), r = c['report'] as Map<String, dynamic>, leg = r['contracts'][0];
      switch (mutation) {
        case 'source': r['source'] = 'fixture'; break;
        case 'account': r['account'] = 'other'; break;
        case 'version': r['version'] += 1; break;
        case 'hash': r['eventHash'] = '0' * 64; break;
        case 'payload': r['reportPayload'] = '{}'; break;
        case 'entry': leg['qualification']['entryEligible'] = true; break;
        case 'settlement': r['settlementEligible'] = true; break;
        case 'standard': leg['qualification']['standardDeliverableObserved'] = false; break;
        case 'reason': leg['qualification']['reasons'] = []; break;
        case 'greek-time': leg['greeks']['data']['providerTimestamp'] = r['asOf']; break;
        case 'greek-value': leg['greeks']['data']['values']['delta'] = 2; break;
        case 'terms-hash': leg['terms']['data']['terms']['deliverables'][0]['amount'] = '150'; break;
        case 'binding': leg['terms']['bindings'][0]['account'] = 'other'; break;
        case 'future': leg['terms']['bindings'][0]['version'] = 99; break;
        case 'capture': leg['terms']['capturedAt'] = '2027-01-01T00:00:00Z'; break;
        case 'missing': r['contracts'] = []; break;
        case 'duplicate': r['contracts'].add(leg); break;
      }
      if (mutation != 'payload') rehash(r);
      expect(() => parse(c), throwsFormatException);
    });
  }
  for (final brightness in Brightness.values) {
    testWidgets('360px RTL $brightness contract evidence retries GET and hides invalid claims', (tester) async {
      tester.view.physicalSize = const Size(360, 800); tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize); addTearDown(tester.view.resetDevicePixelRatio);
      final c = scenario('complete'); var calls = 0;
      final api = TraderApi(baseUrl: 'https://server.invalid', token: 'fixture-owner', client: MockClient((request) async {
        expect(request.method, 'GET'); expect(request.headers['authorization'], 'Bearer fixture-owner');
        expect(request.url.path, '/api/observed-paper/accounts/metadata/contract-evidence');
        calls++;
        final response = scenario('complete')['report'] as Map<String, dynamic>;
        if (calls == 1) { response['entryEligible'] = true; rehash(response); }
        return http.Response(jsonEncode(response), 200);
      }));
      addTearDown(api.close);
      await tester.pumpWidget(MaterialApp(theme: ThemeData(brightness: brightness),
        home: ObservedContractsScreen(api: api, saved: ObservedServerAccount.parse(c['snapshot'], 'metadata'))));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('contract-error')).hitTestable(), findsOneWidget);
      expect(find.byKey(const Key('contract-AAPL261120C00200000')), findsNothing);
      await tester.tap(find.byKey(const Key('contract-retry'))); await tester.pumpAndSettle();
      expect(calls, 2); expect(find.byKey(const Key('contract-error')), findsNothing);
      expect(find.text('رُصد مُسلَّم قياسي؛ لا يمنح أهلية'), findsOneWidget);
      await tester.scrollUntilVisible(find.text('الوقت المستقل لحساب Greeks: غير متاح'), 100);
      expect(tester.takeException(), null);
    });
  }
}
