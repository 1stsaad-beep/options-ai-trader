import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:options_ai_trader_app/chart/interactive_chart.dart';
import 'package:options_ai_trader_app/screens/chart_screen.dart';
import 'package:options_ai_trader_app/services/app_controller.dart';
import 'package:options_ai_trader_app/services/secret_store.dart';
import 'package:trader_core/trader_core.dart';

import 'app_smoke_test.dart' show MemoryRepository;

class MemorySecrets extends SecretStore {
  @override
  Future<void> save(String accountId, BrokerKind kind, Map<String, String> values) async {}
  @override
  Future<BrokerCredentials> load(String accountId, BrokerKind kind) async => const BrokerCredentials({});
  @override
  Future<void> deleteAll(String accountId, BrokerKind kind) async {}
}

void main() {
  testWidgets('account chart uses the account adapter bars (same call as the engine) and a real isolate', (tester) async {
    final controller =
        AppController(repo: MemoryRepository(), secrets: MemorySecrets(), cycleEvery: const Duration(hours: 1));
    await tester.runAsync(() async {
      await controller.load();
      await controller.addAccount(name: 'sim', broker: BrokerKind.simulator, credentials: const {});
    });
    final id = controller.accounts.single.profile.id;
    final tf = controller.accounts.single.profile.settings.timeframe;
    late List<Candle> engineBars;
    await tester.runAsync(() async {
      engineBars = await controller.chartBars(id, 'AAPL', tf);
    });
    await tester.pumpWidget(MaterialApp(home: ChartScreen.forAccount(controller, id, 'AAPL')));
    // Let the isolate finish.
    for (var k = 0; k < 50 && find.byType(InteractiveChart).evaluate().isEmpty; k++) {
      await tester.runAsync(() => Future<void>.delayed(const Duration(milliseconds: 100)));
      await tester.pump();
    }
    final chart = tester.widget<InteractiveChart>(find.byType(InteractiveChart));
    expect(chart.data.candles.length, engineBars.length);
    expect(chart.data.candles.last.time, engineBars.last.time);
    expect(chart.data.candles.last.close, engineBars.last.close);
    expect(chart.data.analysis.report.toJson(),
        Analyzer().analyze('AAPL', engineBars, weights: controller.accounts.single.profile.settings.engineWeights).toJson());
    controller.dispose();
  });
}
