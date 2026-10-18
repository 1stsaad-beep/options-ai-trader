import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:options_ai_trader_app/main.dart';
import 'package:options_ai_trader_app/services/account_repository.dart';
import 'package:options_ai_trader_app/services/app_controller.dart';
import 'package:trader_core/trader_core.dart';

class MemoryRepository extends AccountRepository {
  List<AccountProfile> profiles = [];
  final Map<String, AccountState> states = {};

  @override
  Future<List<AccountProfile>> loadProfiles() async => profiles;
  @override
  Future<void> saveProfiles(List<AccountProfile> p) async {
    profiles = p;
  }
  @override
  Future<AccountState> loadState(String accountId) async => states[accountId] ?? AccountState();
  @override
  Future<void> saveState(String accountId, AccountState state) async {
    states[accountId] = state;
  }
  Map<String, dynamic> app = {};
  @override
  Future<Map<String, dynamic>> loadAppSettings() async => Map.of(app);
  @override
  Future<void> saveAppSettings(Map<String, Object?> settings) async {
    app = Map<String, dynamic>.of(settings);
  }

  @override
  Future<void> deleteState(String accountId) async {
    states.remove(accountId);
  }
}

void main() {
  testWidgets('starts in Arabic RTL with the empty accounts state', (tester) async {
    final controller = AppController(repo: MemoryRepository(), cycleEvery: const Duration(hours: 1));
    await controller.load();
    await tester.pumpWidget(OptionsAiTraderApp(controller: controller));
    await tester.pumpAndSettle();
    expect(find.text('الحسابات'), findsOneWidget);
    expect(find.text('إضافة حساب'), findsOneWidget);
    final dir = Directionality.of(tester.element(find.text('الحسابات')));
    expect(dir, TextDirection.rtl);
    controller.dispose();
  });
}
