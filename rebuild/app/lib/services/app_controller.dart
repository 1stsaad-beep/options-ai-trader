import 'dart:async';
import 'dart:math' as math;

import 'package:flutter/foundation.dart';
import 'package:trader_core/trader_core.dart';

import 'account_repository.dart';
import 'background_service.dart';
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

  /// Latest option quote per held contract (OCC symbol) for P/L and Greeks.
  Map<String, OptionQuote> quotes = const {};

  AccountRuntime(this.profile, this.state);

  /// Serialises refresh / runCycle / testConnection on this account so they
  /// never touch the adapter and state at the same time.
  final AccountLock lock = AccountLock();

  /// Market status seen by this account's last cycle (broker-confirmed when
  /// the adapter has a market clock).
  MarketStatus? get lastMarketStatus => engine?.lastMarketStatus;
}

/// Minimal async mutex: tasks run one after another in call order.
class AccountLock {
  Future<void> _tail = Future<void>.value();
  int _pending = 0;

  bool get isBusy => _pending > 0;

  Future<T> run<T>(Future<T> Function() task) {
    _pending++;
    final result = _tail.then((_) => task());
    _tail = result.then<void>((_) {}, onError: (_) {}).whenComplete(() => _pending--);
    return result;
  }
}

/// App-wide state: accounts, automation timer, kill switch, background
/// service and persistence.
///
/// Automation runs while the app process is alive. The optional Android
/// foreground service ([BackgroundRunner]) keeps the process alive with the
/// screen off / app in the background; see HANDOFF.md §11 for its limits.
class AppController extends ChangeNotifier {
  final AccountRepository repo;
  final SecretStore secrets;
  final BrokerRegistry registry;
  final SyntheticMarket market;
  final Duration cycleEvery;
  final BackgroundRunner background;

  /// Cycles closer together than this are skipped (timer + service ticks).
  static const minCycleGap = Duration(seconds: 30);

  /// Emergency stop: when true no account runs cycles (auto or manual).
  bool killSwitch = false;

  /// User wants the background service (persisted; re-started on launch).
  bool backgroundWanted = false;
  bool backgroundRunning = false;
  String? backgroundError;
  DateTime? lastAllCycles;

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
    BackgroundRunner? background,
  })  : background = background ?? NoBackgroundRunner(),
        repo = repo ?? AccountRepository(),
        secrets = secrets ?? SecretStore(),
        registry = registry ?? BrokerRegistry.standard(),
        market = market ?? SyntheticMarket();

  List<AccountRuntime> get accounts => _accounts.values.toList()..sort((a, b) => a.profile.createdAt.compareTo(b.profile.createdAt));

  AccountRuntime? account(String id) => _accounts[id];

  Future<void> load() async {
    for (final p in await repo.loadProfiles()) {
      _accounts[p.id] = AccountRuntime(p, await repo.loadState(p.id));
    }
    try {
      final app = await repo.loadAppSettings();
      killSwitch = app['killSwitch'] == true;
      backgroundWanted = app['background'] == true;
    } catch (_) {
      // Unreadable app.json: safe defaults (kill switch off, service off).
    }
    background.init(_onBackgroundCommand);
    loaded = true;
    _timer = Timer.periodic(cycleEvery, (_) => runAllCycles());
    notifyListeners();
    unawaited(_restoreBackground());
    unawaited(refreshAll());
  }

  Future<void> _saveAppSettings() async {
    try {
      await repo.saveAppSettings({'v': 1, 'killSwitch': killSwitch, 'background': backgroundWanted});
    } catch (_) {}
  }

  // ---- kill switch ----

  /// One tap pauses all auto-trading (every account, timer and service).
  /// Open positions are left as they are; nothing is sent while paused.
  Future<void> setKillSwitch(bool on) async {
    killSwitch = on;
    await _saveAppSettings();
    notifyListeners();
    await _updateNotification();
  }

  // ---- background service ----

  Future<void> _restoreBackground() async {
    try {
      backgroundRunning = await background.isRunning();
      if (backgroundWanted && !backgroundRunning) await startBackground();
    } catch (e) {
      backgroundError = '$e';
    }
    notifyListeners();
  }

  /// Starts the foreground service (user action). Returns an Arabic error or null.
  Future<String?> startBackground() async {
    if (!await background.notificationsAllowed()) await background.requestNotifications();
    final err = await background.start(title: _notificationTitle(), text: _notificationText());
    backgroundError = err;
    backgroundRunning = err == null;
    backgroundWanted = err == null;
    await _saveAppSettings();
    notifyListeners();
    return err;
  }

  Future<void> stopBackground() async {
    await background.stop();
    backgroundRunning = false;
    backgroundWanted = false;
    await _saveAppSettings();
    notifyListeners();
  }

  void _onBackgroundCommand(String command) {
    switch (command) {
      case BackgroundCommand.tick:
        unawaited(runAllCycles());
      case BackgroundCommand.pauseAll:
        unawaited(setKillSwitch(true));
      case BackgroundCommand.stopService:
        unawaited(stopBackground());
    }
  }

  String _notificationTitle() => killSwitch ? 'التداول الآلي: إيقاف طارئ' : 'التداول الآلي يعمل (Paper)';

  String _notificationText() {
    if (killSwitch) return 'لن تُرسل أي أوامر حتى تلغي الإيقاف الطارئ من التطبيق';
    final enabled = accounts.where((a) => a.profile.enabled).length;
    final t = lastAllCycles;
    final last = t == null ? 'لم تعمل دورة بعد' : 'آخر دورة ${NewYorkTime.hm(t.toUtc())} ET';
    return '$enabled حساب مفعّل • $last • ${marketStatus().summaryAr()}';
  }

  Future<void> _updateNotification() async {
    if (!backgroundRunning) return;
    try {
      await background.update(title: _notificationTitle(), text: _notificationText());
    } catch (_) {}
  }

  bool _disposed = false;

  @override
  void dispose() {
    _disposed = true;
    _timer?.cancel();
    super.dispose();
  }

  /// Async work (cycles, service callbacks) may finish after dispose.
  @override
  void notifyListeners() {
    if (!_disposed) super.notifyListeners();
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

  final Map<String, Future<BrokerAdapter>> _connecting = {};

  /// One adapter per account; concurrent callers share one connection attempt.
  Future<BrokerAdapter> _adapter(AccountRuntime rt) {
    final existing = rt.broker;
    if (existing != null) return Future.value(existing);
    // Note: the callback must not return the removed Future (whenComplete would
    // wait on it, i.e. on itself).
    return _connecting[rt.profile.id] ??= _createAdapter(rt).whenComplete(() {
      _connecting.remove(rt.profile.id);
    });
  }

  Future<BrokerAdapter> _createAdapter(AccountRuntime rt) async {
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
    return rt.lock.run(() => _testConnection(rt));
  }

  Future<String?> _testConnection(AccountRuntime rt) async {
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
    return rt.lock.run(() => _refresh(rt));
  }

  Future<void> _refresh(AccountRuntime rt) async {
    try {
      final b = await _adapter(rt);
      rt.snapshot = await b.account();
      rt.positions = await b.positions();
      rt.quotes = await _quotesFor(b, rt.positions);
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
  /// Skipped while the kill switch is on, while a pass is running, or when the
  /// last pass was under [minCycleGap] ago (timer and service both call this),
  /// unless [force] (the manual "run now" button).
  Future<void> runAllCycles({bool force = false}) async {
    if (_busy || killSwitch) return;
    final now = DateTime.now();
    final last = lastAllCycles;
    if (!force && last != null && now.difference(last) < minCycleGap) return;
    _busy = true;
    lastAllCycles = now;
    try {
      for (final rt in accounts.where((a) => a.profile.enabled)) {
        await runCycle(rt.profile.id);
      }
    } finally {
      _busy = false;
    }
    await _updateNotification();
  }

  Future<CycleSummary?> runCycle(String id) async {
    final rt = _accounts[id];
    if (rt == null) return null;
    if (killSwitch) return const CycleSummary(ran: false, noteAr: 'الإيقاف الطارئ مفعّل — لا تعمل أي دورة');
    return rt.lock.run(() => _runCycle(rt));
  }

  Future<CycleSummary?> _runCycle(AccountRuntime rt) async {
    final id = rt.profile.id;
    try {
      final b = await _adapter(rt);
      final engine = rt.engine ??= TradingEngine(profile: rt.profile, broker: b, state: rt.state);
      final summary = await engine.runCycle();
      rt.lastCycle = DateTime.now();
      rt.snapshot = await b.account();
      rt.positions = await b.positions();
      rt.quotes = await _quotesFor(b, rt.positions);
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

  /// Bars the engines would analyse: [chartBars] minus the still-forming bar
  /// (same rule as `TradingEngine`).
  List<Candle> completedBars(String id, List<Candle> bars, BarTimeframe timeframe, {DateTime? now}) {
    final rt = _accounts[id];
    final kind = rt?.profile.broker ?? BrokerKind.alpaca;
    return TradingEngine.completedBarsFor(kind, bars, timeframe, now ?? DateTime.now().toUtc());
  }

  /// Market status for the UI: the most recent broker-confirmed status from a
  /// cycle (if under 2 minutes old), otherwise the offline NYSE calendar.
  MarketStatus marketStatus({DateTime? now}) {
    final t = now ?? DateTime.now().toUtc();
    for (final rt in accounts) {
      final st = rt.lastMarketStatus;
      if (st != null && st.source == StatusSource.broker && t.difference(st.at).inSeconds.abs() < 120) return st;
    }
    return const MarketCalendar().statusAt(t);
  }

  Future<Map<String, OptionQuote>> _quotesFor(BrokerAdapter b, List<Position> positions) async {
    final out = <String, OptionQuote>{};
    for (final p in positions) {
      try {
        final q = await b.optionQuote(p.contract);
        if (q != null) out[p.contract.occSymbol] = q;
      } catch (_) {
        // A missing quote only hides P/L for that position.
      }
    }
    return out;
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
