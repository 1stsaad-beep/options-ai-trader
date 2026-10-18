import 'dart:async';
import 'dart:math' as math;

import 'package:flutter/foundation.dart';
import 'package:trader_core/trader_core.dart';

import 'account_repository.dart';
import 'http_transport.dart';
import 'secret_store.dart';

/// Runtime of one account: its adapter, engine and persisted state.
class AccountRuntime {
  AccountProfile profile;
  final AccountState state;
  BrokerAdapter? broker;
  TradingEngine? engine;
  String? lastError;
  DateTime? lastCycle;
  AccountSnapshot? snapshot;
  List<Position> positions = const [];

  AccountRuntime(this.profile, this.state);
}

/// App-wide state: accounts, automation timer and persistence.
///
/// Automation runs while the app process is alive (foreground). Continuous
/// background trading needs a host — see HANDOFF.md, "Background execution".
class AppController extends ChangeNotifier {
  final AccountRepository repo;
  final SecretStore secrets;
  final BrokerRegistry registry;
  final SyntheticMarket market;
  final Duration cycleEvery;

  final Map<String, AccountRuntime> _accounts = {};
  Timer? _timer;
  bool _busy = false;
  bool loaded = false;

  AppController({
    AccountRepository? repo,
    SecretStore? secrets,
    BrokerRegistry? registry,
    SyntheticMarket? market,
    this.cycleEvery = const Duration(minutes: 1),
  })  : repo = repo ?? AccountRepository(),
        secrets = secrets ?? SecretStore(),
        registry = registry ?? BrokerRegistry.standard(),
        market = market ?? SyntheticMarket();

  List<AccountRuntime> get accounts => _accounts.values.toList()..sort((a, b) => a.profile.createdAt.compareTo(b.profile.createdAt));

  AccountRuntime? account(String id) => _accounts[id];

  Future<void> load() async {
    for (final p in await repo.loadProfiles()) {
      _accounts[p.id] = AccountRuntime(p, await repo.loadState(p.id));
    }
    loaded = true;
    _timer = Timer.periodic(cycleEvery, (_) => runAllCycles());
    notifyListeners();
    unawaited(refreshAll());
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  static String newId() {
    final r = math.Random.secure();
    return List.generate(12, (_) => r.nextInt(256).toRadixString(16).padLeft(2, '0')).join();
  }

  Future<AccountProfile> addAccount({
    required String name,
    required BrokerKind broker,
    required Map<String, String> credentials,
    int startingCashCents = 1000000,
  }) async {
    final p = AccountProfile(
      id: newId(),
      name: name,
      broker: broker,
      mode: TradingMode.paper, // new accounts are always paper
      createdAt: DateTime.now().toUtc(),
      startingCashCents: startingCashCents,
    );
    await secrets.save(p.id, broker, credentials);
    _accounts[p.id] = AccountRuntime(p, AccountState());
    await _saveProfiles();
    notifyListeners();
    return p;
  }

  Future<void> updateProfile(AccountProfile p) async {
    final rt = _accounts[p.id];
    if (rt == null) return;
    final modeChanged = rt.profile.mode != p.mode;
    rt.profile = p;
    if (modeChanged) {
      rt.broker = null; // rebuild adapter with the new endpoints
      rt.engine = null;
    } else {
      rt.engine = null; // engine reads settings from the profile
    }
    await _saveProfiles();
    notifyListeners();
  }

  Future<void> updateCredentials(String id, Map<String, String> credentials) async {
    final rt = _accounts[id];
    if (rt == null) return;
    await secrets.save(id, rt.profile.broker, credentials);
    rt.broker = null;
    rt.engine = null;
    notifyListeners();
  }

  Future<void> deleteAccount(String id) async {
    final rt = _accounts.remove(id);
    if (rt == null) return;
    await secrets.deleteAll(id, rt.profile.broker);
    await repo.deleteState(id);
    await _saveProfiles();
    notifyListeners();
  }

  Future<void> _saveProfiles() => repo.saveProfiles([for (final a in accounts) a.profile]);

  Future<BrokerAdapter> _adapter(AccountRuntime rt) async {
    final existing = rt.broker;
    if (existing != null) return existing;
    final creds = await secrets.load(rt.profile.id, rt.profile.broker);
    if (!creds.isCompleteFor(rt.profile.broker)) {
      throw const BrokerException(BrokerErrorCode.auth, 'بيانات الدخول غير مكتملة');
    }
    String? selfSignedHost;
    if (rt.profile.broker == BrokerKind.ibkr) {
      selfSignedHost = Uri.tryParse(creds.values['gatewayUrl'] ?? '')?.host;
    }
    final b = registry.create(
      rt.profile.broker,
      AdapterContext(
        accountId: rt.profile.id,
        mode: rt.profile.mode,
        credentials: creds,
        http: rt.profile.broker == BrokerKind.simulator ? null : AppHttpTransport(trustSelfSignedHost: selfSignedHost),
        liveApproval: rt.profile.liveApproval,
        startingCashCents: rt.profile.startingCashCents,
        market: market,
        clock: () => DateTime.now().toUtc(),
      ),
    );
    if (b is SimulatorBroker && rt.state.brokerState != null) b.restore(rt.state.brokerState!);
    await b.connect();
    rt.broker = b;
    return b;
  }

  /// Validates credentials by connecting once. Returns null or an Arabic error.
  Future<String?> testConnection(String id) async {
    final rt = _accounts[id];
    if (rt == null) return 'الحساب غير موجود';
    try {
      rt.broker = null;
      final b = await _adapter(rt);
      rt.snapshot = await b.account();
      rt.lastError = null;
      notifyListeners();
      return null;
    } catch (e) {
      rt.lastError = '$e';
      notifyListeners();
      return '$e';
    }
  }

  Future<void> refresh(String id) async {
    final rt = _accounts[id];
    if (rt == null) return;
    try {
      final b = await _adapter(rt);
      rt.snapshot = await b.account();
      rt.positions = await b.positions();
      rt.lastError = null;
      _captureBrokerState(rt);
    } catch (e) {
      rt.lastError = '$e';
    }
    notifyListeners();
  }

  Future<void> refreshAll() async {
    for (final rt in accounts) {
      await refresh(rt.profile.id);
    }
  }

  /// Runs one cycle for every enabled account, one account at a time.
  Future<void> runAllCycles() async {
    if (_busy) return;
    _busy = true;
    try {
      for (final rt in accounts.where((a) => a.profile.enabled)) {
        await runCycle(rt.profile.id);
      }
    } finally {
      _busy = false;
    }
  }

  Future<CycleSummary?> runCycle(String id) async {
    final rt = _accounts[id];
    if (rt == null) return null;
    try {
      final b = await _adapter(rt);
      final engine = rt.engine ??= TradingEngine(profile: rt.profile, broker: b, state: rt.state);
      final summary = await engine.runCycle();
      rt.lastCycle = DateTime.now();
      rt.snapshot = await b.account();
      rt.positions = await b.positions();
      rt.lastError = summary.errors > 0 ? summary.noteAr : null;
      _captureBrokerState(rt);
      await repo.saveState(id, rt.state);
      notifyListeners();
      return summary;
    } catch (e) {
      rt.lastError = '$e';
      notifyListeners();
      return null;
    }
  }

  /// Bars for the chart: exactly the call the trading engine makes
  /// (`bars(symbol, timeframe, limit: 300)` on the account's own adapter), so
  /// the chart and the engines see the same candles.
  Future<List<Candle>> chartBars(String id, String symbol, BarTimeframe timeframe, {int limit = 300}) async {
    final rt = _accounts[id];
    if (rt == null) throw StateError('الحساب غير موجود');
    final b = await _adapter(rt);
    return b.bars(symbol, timeframe, limit: limit);
  }

  void _captureBrokerState(AccountRuntime rt) {
    final b = rt.broker;
    if (b is SimulatorBroker) rt.state.brokerState = b.toJson();
  }

  // ---- paper readiness & live approval ----

  /// Conditions that must hold before live can even be requested.
  List<String> liveReadinessIssues(AccountRuntime rt) {
    final issues = <String>[];
    if (!LiveTradingGuard.buildAllowsLive) issues.add('هذه النسخة من التطبيق لا تسمح بالتداول الحقيقي إطلاقًا');
    if (rt.profile.broker == BrokerKind.simulator) issues.add('المحاكي الداخلي لا يدعم Live');
    final days = rt.state.equityCurve.isEmpty
        ? 0
        : rt.state.equityCurve.last.time.difference(rt.state.equityCurve.first.time).inDays;
    if (days < 14) issues.add('يلزم 14 يومًا على الأقل من التشغيل في وضع Paper (الحالي: $days)');
    if (rt.state.trades.length < 20) issues.add('يلزم 20 صفقة مغلقة على الأقل في Paper (الحالي: ${rt.state.trades.length})');
    final errors = rt.state.journal.where((e) => e.action == JournalAction.error).length;
    if (errors > 0) issues.add('يوجد $errors خطأ في السجل يجب مراجعته');
    return issues;
  }
}
