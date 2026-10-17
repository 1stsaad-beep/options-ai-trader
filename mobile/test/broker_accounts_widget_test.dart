import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:options_ai_trader/brokers/broker_accounts_screen.dart';
import 'package:options_ai_trader/brokers/broker_store.dart';

void main() {
  testWidgets('add Alpaca paper account with masked fields and test connection', (tester) async {
    final mem = MemorySecureKeyValue();
    final reg = BrokerAccountRegistry(mem);
    final client = MockClient((r) async => http.Response(
        '{"account_number":"PA3FIXTURE","cash":"100000","equity":"100000","buying_power":"200000","currency":"USD"}', 200));
    await tester.pumpWidget(MaterialApp(home: Directionality(textDirection: TextDirection.rtl,
        child: BrokerAccountsScreen(registry: reg, client: client))));
    await tester.pumpAndSettle();
    expect(find.text('لا توجد حسابات.'), findsNWidgets(3));
    expect(tester.widget<SwitchListTile>(find.byType(SwitchListTile)).value, isFalse);
    await tester.tap(find.text('إضافة حساب'));
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const ValueKey('broker-field-alpaca-keyId')), 'PKFIXTURE1');
    await tester.enterText(find.byKey(const ValueKey('broker-field-alpaca-secretKey')), 'fixturesecret1');
    final secretField = tester.widget<TextField>(find.byKey(const ValueKey('broker-field-alpaca-secretKey')));
    expect(secretField.obscureText, isTrue);
    await tester.tap(find.text('حفظ مشفر'));
    await tester.pumpAndSettle();
    expect(find.text('Alpaca'), findsOneWidget);
    expect(find.textContaining('fixturesecret1'), findsNothing);
    await tester.tap(find.byTooltip('فحص الاتصال'));
    // Secure-storage and HTTP futures complete outside the fake clock.
    await tester.runAsync(() => Future<void>.delayed(const Duration(milliseconds: 200)));
    await tester.pumpAndSettle();
    expect(find.textContaining('متصل (Paper) • PA3FIXTURE'), findsOneWidget);
  });
}
