/// Per-account configuration. Every account is fully independent: its own
/// broker connection, mode, watchlist, risk settings, positions and journal.
library;

import '../analysis/signal.dart';
import '../brokers/broker_adapter.dart';
import '../brokers/live_guard.dart';
import '../models.dart';

/// All tunable risk/entry/exit parameters of one account.
/// Percentages are plain numbers (35 = 35%).
class AccountSettings {
  // ---- sizing & exposure ----
  /// Max premium you accept to LOSE on one trade, as % of equity
  /// (premium × stopLossPercent is what is at risk).
  final double riskPerTradePercent;

  /// Max premium spent on one position, as % of equity.
  final double maxPositionPercent;
  final int maxContractsPerTrade;
  final int maxOpenPositions;

  /// Max total premium in open positions, as % of equity.
  final double maxTotalExposurePercent;

  /// New entries stop for the day once equity is down this % from the day's start.
  final double dailyLossLimitPercent;

  /// Max opening orders (entries + scale-ins) per New York trading day.
  /// Exits are never capped (they reduce risk).
  final int maxOrdersPerDay;

  /// After an entry or exit on a symbol, no new entry on it for this many minutes.
  final int symbolCooldownMinutes;

  // ---- entry criteria ----
  final BarTimeframe timeframe;

  /// Minimum |composite score| (0..100) to open a trade.
  final double minScore;

  /// Minimum number of engines agreeing with the direction.
  final int minAgreeingEngines;

  /// Block entries when the trend engine points the other way.
  final bool requireTrendAlignment;
  final bool allowCalls;
  final bool allowPuts;
  final Map<EngineId, double> engineWeights;

  // ---- contract selection ----
  final int minDaysToExpiry;
  final int maxDaysToExpiry;

  /// Target |delta| of the bought option (0.5 ≈ at the money).
  final double targetDelta;
  final double maxSpreadPercent;
  final int minOpenInterest;

  /// 0 = bid, 1 = ask. Entry/normal exits start here; stale orders are repriced to the far side.
  final double entryAggressiveness;

  /// Pending orders older than this many engine cycles are cancelled and repriced.
  final int orderTimeoutCycles;

  // ---- exits ----
  /// Exit when the option premium falls this % below the entry price.
  final double stopLossPercent;

  /// Take partial profit at this % gain...
  final double partialTakeProfitPercent;

  /// ...selling this fraction (0..1) of the position (0 disables).
  final double partialTakeProfitFraction;

  /// Close everything at this % gain.
  final double takeProfitPercent;

  /// Trailing stop arms after this % gain...
  final double trailingActivationPercent;

  /// ...and exits when premium drops this % from its peak.
  final double trailingStopPercent;

  /// Exit when the underlying crosses the pattern invalidation saved at entry.
  final bool exitOnUnderlyingInvalidation;

  /// Exit when the composite score flips beyond minScore in the other direction.
  final bool exitOnOppositeSignal;
  final int maxHoldingDays;

  /// Close this many calendar days before expiry (avoid gamma/expiry risk).
  final int exitDaysBeforeExpiry;

  // ---- scaling in ----
  final bool scaleInEnabled;
  final int maxScaleIns;

  /// Add only when the position is up at least this %...
  final double scaleInMinProfitPercent;

  /// ...and the score in the same direction is at least this.
  final double scaleInMinScore;

  /// Added quantity as a fraction of the initial quantity.
  final double scaleInFraction;

  const AccountSettings({
    this.riskPerTradePercent = 1.0,
    this.maxPositionPercent = 10,
    this.maxContractsPerTrade = 5,
    this.maxOpenPositions = 3,
    this.maxTotalExposurePercent = 40,
    this.dailyLossLimitPercent = 3,
    this.maxOrdersPerDay = 10,
    this.symbolCooldownMinutes = 60,
    this.timeframe = BarTimeframe.m15,
    this.minScore = 35,
    this.minAgreeingEngines = 2,
    this.requireTrendAlignment = true,
    this.allowCalls = true,
    this.allowPuts = true,
    this.engineWeights = const {
      EngineId.trend: 1.5,
      EngineId.momentum: 1.0,
      EngineId.divergence: 1.0,
      EngineId.harmonic: 0.8,
      EngineId.elliott: 0.8,
      EngineId.classical: 1.0,
    },
    this.minDaysToExpiry = 7,
    this.maxDaysToExpiry = 45,
    this.targetDelta = 0.45,
    this.maxSpreadPercent = 12,
    this.minOpenInterest = 100,
    this.entryAggressiveness = 0.6,
    this.orderTimeoutCycles = 2,
    this.stopLossPercent = 35,
    this.partialTakeProfitPercent = 40,
    this.partialTakeProfitFraction = 0.5,
    this.takeProfitPercent = 90,
    this.trailingActivationPercent = 30,
    this.trailingStopPercent = 20,
    this.exitOnUnderlyingInvalidation = true,
    this.exitOnOppositeSignal = true,
    this.maxHoldingDays = 10,
    this.exitDaysBeforeExpiry = 2,
    this.scaleInEnabled = false,
    this.maxScaleIns = 1,
    this.scaleInMinProfitPercent = 15,
    this.scaleInMinScore = 50,
    this.scaleInFraction = 0.5,
  });

  /// Returns a list of Arabic validation errors (empty = valid).
  List<String> validate() {
    final e = <String>[];
    void range(num v, num lo, num hi, String name) {
      if (v < lo || v > hi) e.add('$name يجب أن يكون بين $lo و $hi');
    }

    range(riskPerTradePercent, 0.1, 10, 'نسبة المخاطرة');
    range(maxPositionPercent, 1, 100, 'حجم المركز الأقصى');
    range(maxContractsPerTrade, 1, 100, 'عدد العقود الأقصى');
    range(maxOpenPositions, 1, 50, 'عدد المراكز المفتوحة');
    range(maxTotalExposurePercent, 1, 100, 'التعرض الكلي');
    range(dailyLossLimitPercent, 0.5, 50, 'حد الخسارة اليومي');
    range(maxOrdersPerDay, 1, 200, 'أقصى أوامر فتح يوميًا');
    range(symbolCooldownMinutes, 0, 1440, 'فترة التهدئة لكل سهم');
    range(minScore, 5, 100, 'الحد الأدنى للنتيجة');
    range(minAgreeingEngines, 1, EngineId.values.length, 'عدد المحركات المتوافقة');
    range(minDaysToExpiry, 0, 365, 'أقل أيام للانتهاء');
    range(maxDaysToExpiry, minDaysToExpiry, 730, 'أقصى أيام للانتهاء');
    range(targetDelta, 0.1, 0.9, 'الدلتا المستهدفة');
    range(maxSpreadPercent, 1, 50, 'أقصى فرق سعر');
    range(entryAggressiveness, 0, 1, 'جرأة التسعير');
    range(stopLossPercent, 5, 95, 'وقف الخسارة');
    range(takeProfitPercent, 5, 1000, 'هدف الربح');
    range(partialTakeProfitFraction, 0, 0.9, 'نسبة الجني الجزئي');
    range(trailingStopPercent, 1, 90, 'الوقف المتحرك');
    range(scaleInFraction, 0.1, 2, 'نسبة التعزيز');
    if (!allowCalls && !allowPuts) e.add('يجب السماح بـ Call أو Put على الأقل');
    if (partialTakeProfitFraction > 0 && partialTakeProfitPercent >= takeProfitPercent) {
      e.add('الجني الجزئي يجب أن يكون أقل من هدف الربح الكامل');
    }
    return e;
  }

  AccountSettings copyWith({
    double? riskPerTradePercent,
    double? maxPositionPercent,
    int? maxContractsPerTrade,
    int? maxOpenPositions,
    double? maxTotalExposurePercent,
    double? dailyLossLimitPercent,
    int? maxOrdersPerDay,
    int? symbolCooldownMinutes,
    BarTimeframe? timeframe,
    double? minScore,
    int? minAgreeingEngines,
    bool? requireTrendAlignment,
    bool? allowCalls,
    bool? allowPuts,
    Map<EngineId, double>? engineWeights,
    int? minDaysToExpiry,
    int? maxDaysToExpiry,
    double? targetDelta,
    double? maxSpreadPercent,
    int? minOpenInterest,
    double? entryAggressiveness,
    int? orderTimeoutCycles,
    double? stopLossPercent,
    double? partialTakeProfitPercent,
    double? partialTakeProfitFraction,
    double? takeProfitPercent,
    double? trailingActivationPercent,
    double? trailingStopPercent,
    bool? exitOnUnderlyingInvalidation,
    bool? exitOnOppositeSignal,
    int? maxHoldingDays,
    int? exitDaysBeforeExpiry,
    bool? scaleInEnabled,
    int? maxScaleIns,
    double? scaleInMinProfitPercent,
    double? scaleInMinScore,
    double? scaleInFraction,
  }) =>
      AccountSettings(
        riskPerTradePercent: riskPerTradePercent ?? this.riskPerTradePercent,
        maxPositionPercent: maxPositionPercent ?? this.maxPositionPercent,
        maxContractsPerTrade: maxContractsPerTrade ?? this.maxContractsPerTrade,
        maxOpenPositions: maxOpenPositions ?? this.maxOpenPositions,
        maxTotalExposurePercent: maxTotalExposurePercent ?? this.maxTotalExposurePercent,
        dailyLossLimitPercent: dailyLossLimitPercent ?? this.dailyLossLimitPercent,
        maxOrdersPerDay: maxOrdersPerDay ?? this.maxOrdersPerDay,
        symbolCooldownMinutes: symbolCooldownMinutes ?? this.symbolCooldownMinutes,
        timeframe: timeframe ?? this.timeframe,
        minScore: minScore ?? this.minScore,
        minAgreeingEngines: minAgreeingEngines ?? this.minAgreeingEngines,
        requireTrendAlignment: requireTrendAlignment ?? this.requireTrendAlignment,
        allowCalls: allowCalls ?? this.allowCalls,
        allowPuts: allowPuts ?? this.allowPuts,
        engineWeights: engineWeights ?? this.engineWeights,
        minDaysToExpiry: minDaysToExpiry ?? this.minDaysToExpiry,
        maxDaysToExpiry: maxDaysToExpiry ?? this.maxDaysToExpiry,
        targetDelta: targetDelta ?? this.targetDelta,
        maxSpreadPercent: maxSpreadPercent ?? this.maxSpreadPercent,
        minOpenInterest: minOpenInterest ?? this.minOpenInterest,
        entryAggressiveness: entryAggressiveness ?? this.entryAggressiveness,
        orderTimeoutCycles: orderTimeoutCycles ?? this.orderTimeoutCycles,
        stopLossPercent: stopLossPercent ?? this.stopLossPercent,
        partialTakeProfitPercent: partialTakeProfitPercent ?? this.partialTakeProfitPercent,
        partialTakeProfitFraction: partialTakeProfitFraction ?? this.partialTakeProfitFraction,
        takeProfitPercent: takeProfitPercent ?? this.takeProfitPercent,
        trailingActivationPercent: trailingActivationPercent ?? this.trailingActivationPercent,
        trailingStopPercent: trailingStopPercent ?? this.trailingStopPercent,
        exitOnUnderlyingInvalidation: exitOnUnderlyingInvalidation ?? this.exitOnUnderlyingInvalidation,
        exitOnOppositeSignal: exitOnOppositeSignal ?? this.exitOnOppositeSignal,
        maxHoldingDays: maxHoldingDays ?? this.maxHoldingDays,
        exitDaysBeforeExpiry: exitDaysBeforeExpiry ?? this.exitDaysBeforeExpiry,
        scaleInEnabled: scaleInEnabled ?? this.scaleInEnabled,
        maxScaleIns: maxScaleIns ?? this.maxScaleIns,
        scaleInMinProfitPercent: scaleInMinProfitPercent ?? this.scaleInMinProfitPercent,
        scaleInMinScore: scaleInMinScore ?? this.scaleInMinScore,
        scaleInFraction: scaleInFraction ?? this.scaleInFraction,
      );

  Map<String, Object?> toJson() => {
        'riskPerTradePercent': riskPerTradePercent,
        'maxPositionPercent': maxPositionPercent,
        'maxContractsPerTrade': maxContractsPerTrade,
        'maxOpenPositions': maxOpenPositions,
        'maxTotalExposurePercent': maxTotalExposurePercent,
        'dailyLossLimitPercent': dailyLossLimitPercent,
        'maxOrdersPerDay': maxOrdersPerDay,
        'symbolCooldownMinutes': symbolCooldownMinutes,
        'timeframe': timeframe.name,
        'minScore': minScore,
        'minAgreeingEngines': minAgreeingEngines,
        'requireTrendAlignment': requireTrendAlignment,
        'allowCalls': allowCalls,
        'allowPuts': allowPuts,
        'engineWeights': {for (final e in engineWeights.entries) e.key.name: e.value},
        'minDaysToExpiry': minDaysToExpiry,
        'maxDaysToExpiry': maxDaysToExpiry,
        'targetDelta': targetDelta,
        'maxSpreadPercent': maxSpreadPercent,
        'minOpenInterest': minOpenInterest,
        'entryAggressiveness': entryAggressiveness,
        'orderTimeoutCycles': orderTimeoutCycles,
        'stopLossPercent': stopLossPercent,
        'partialTakeProfitPercent': partialTakeProfitPercent,
        'partialTakeProfitFraction': partialTakeProfitFraction,
        'takeProfitPercent': takeProfitPercent,
        'trailingActivationPercent': trailingActivationPercent,
        'trailingStopPercent': trailingStopPercent,
        'exitOnUnderlyingInvalidation': exitOnUnderlyingInvalidation,
        'exitOnOppositeSignal': exitOnOppositeSignal,
        'maxHoldingDays': maxHoldingDays,
        'exitDaysBeforeExpiry': exitDaysBeforeExpiry,
        'scaleInEnabled': scaleInEnabled,
        'maxScaleIns': maxScaleIns,
        'scaleInMinProfitPercent': scaleInMinProfitPercent,
        'scaleInMinScore': scaleInMinScore,
        'scaleInFraction': scaleInFraction,
      };

  /// Unknown/missing keys fall back to defaults so old saves keep loading.
  factory AccountSettings.fromJson(Map<String, dynamic> j) {
    const d = AccountSettings();
    double dbl(String k, double def) => (j[k] as num?)?.toDouble() ?? def;
    int integer(String k, int def) => (j[k] as num?)?.toInt() ?? def;
    bool flag(String k, bool def) => j[k] as bool? ?? def;
    final weights = <EngineId, double>{...d.engineWeights};
    final rawWeights = j['engineWeights'];
    if (rawWeights is Map) {
      for (final id in EngineId.values) {
        final v = rawWeights[id.name];
        if (v is num) weights[id] = v.toDouble();
      }
    }
    return AccountSettings(
      riskPerTradePercent: dbl('riskPerTradePercent', d.riskPerTradePercent),
      maxPositionPercent: dbl('maxPositionPercent', d.maxPositionPercent),
      maxContractsPerTrade: integer('maxContractsPerTrade', d.maxContractsPerTrade),
      maxOpenPositions: integer('maxOpenPositions', d.maxOpenPositions),
      maxTotalExposurePercent: dbl('maxTotalExposurePercent', d.maxTotalExposurePercent),
      dailyLossLimitPercent: dbl('dailyLossLimitPercent', d.dailyLossLimitPercent),
      maxOrdersPerDay: integer('maxOrdersPerDay', d.maxOrdersPerDay),
      symbolCooldownMinutes: integer('symbolCooldownMinutes', d.symbolCooldownMinutes),
      timeframe: BarTimeframe.values.firstWhere((t) => t.name == j['timeframe'], orElse: () => d.timeframe),
      minScore: dbl('minScore', d.minScore),
      minAgreeingEngines: integer('minAgreeingEngines', d.minAgreeingEngines),
      requireTrendAlignment: flag('requireTrendAlignment', d.requireTrendAlignment),
      allowCalls: flag('allowCalls', d.allowCalls),
      allowPuts: flag('allowPuts', d.allowPuts),
      engineWeights: weights,
      minDaysToExpiry: integer('minDaysToExpiry', d.minDaysToExpiry),
      maxDaysToExpiry: integer('maxDaysToExpiry', d.maxDaysToExpiry),
      targetDelta: dbl('targetDelta', d.targetDelta),
      maxSpreadPercent: dbl('maxSpreadPercent', d.maxSpreadPercent),
      minOpenInterest: integer('minOpenInterest', d.minOpenInterest),
      entryAggressiveness: dbl('entryAggressiveness', d.entryAggressiveness),
      orderTimeoutCycles: integer('orderTimeoutCycles', d.orderTimeoutCycles),
      stopLossPercent: dbl('stopLossPercent', d.stopLossPercent),
      partialTakeProfitPercent: dbl('partialTakeProfitPercent', d.partialTakeProfitPercent),
      partialTakeProfitFraction: dbl('partialTakeProfitFraction', d.partialTakeProfitFraction),
      takeProfitPercent: dbl('takeProfitPercent', d.takeProfitPercent),
      trailingActivationPercent: dbl('trailingActivationPercent', d.trailingActivationPercent),
      trailingStopPercent: dbl('trailingStopPercent', d.trailingStopPercent),
      exitOnUnderlyingInvalidation: flag('exitOnUnderlyingInvalidation', d.exitOnUnderlyingInvalidation),
      exitOnOppositeSignal: flag('exitOnOppositeSignal', d.exitOnOppositeSignal),
      maxHoldingDays: integer('maxHoldingDays', d.maxHoldingDays),
      exitDaysBeforeExpiry: integer('exitDaysBeforeExpiry', d.exitDaysBeforeExpiry),
      scaleInEnabled: flag('scaleInEnabled', d.scaleInEnabled),
      maxScaleIns: integer('maxScaleIns', d.maxScaleIns),
      scaleInMinProfitPercent: dbl('scaleInMinProfitPercent', d.scaleInMinProfitPercent),
      scaleInMinScore: dbl('scaleInMinScore', d.scaleInMinScore),
      scaleInFraction: dbl('scaleInFraction', d.scaleInFraction),
    );
  }
}

/// Identity + configuration of one trading account (no secrets — those live in
/// the platform secure store keyed by [id]).
class AccountProfile {
  final String id;
  final String name;
  final BrokerKind broker;
  final TradingMode mode;

  /// Underlying symbols this account may trade. Nothing else is ever traded.
  final List<String> watchlist;
  final AccountSettings settings;

  /// Automation runs only while true.
  final bool enabled;

  /// Starting virtual cash for simulator accounts (cents).
  final int startingCashCents;
  final LiveApproval? liveApproval;
  final DateTime createdAt;

  const AccountProfile({
    required this.id,
    required this.name,
    required this.broker,
    required this.mode,
    required this.createdAt,
    this.watchlist = const [],
    this.settings = const AccountSettings(),
    this.enabled = false,
    this.startingCashCents = 1000000,
    this.liveApproval,
  });

  static final RegExp symbolPattern = RegExp(r'^[A-Z][A-Z0-9.]{0,5}$');

  static String normalizeSymbol(String s) => s.trim().toUpperCase();

  AccountProfile copyWith({
    String? name,
    TradingMode? mode,
    List<String>? watchlist,
    AccountSettings? settings,
    bool? enabled,
    LiveApproval? liveApproval,
    bool clearLiveApproval = false,
  }) =>
      AccountProfile(
        id: id,
        name: name ?? this.name,
        broker: broker,
        mode: mode ?? this.mode,
        createdAt: createdAt,
        watchlist: watchlist ?? this.watchlist,
        settings: settings ?? this.settings,
        enabled: enabled ?? this.enabled,
        startingCashCents: startingCashCents,
        liveApproval: clearLiveApproval ? null : (liveApproval ?? this.liveApproval),
      );

  Map<String, Object?> toJson() => {
        'id': id,
        'name': name,
        'broker': broker.name,
        'mode': mode.name,
        'createdAt': createdAt.toIso8601String(),
        'watchlist': watchlist,
        'settings': settings.toJson(),
        'enabled': enabled,
        'startingCashCents': startingCashCents,
        if (liveApproval != null) 'liveApproval': liveApproval!.toJson(),
      };

  factory AccountProfile.fromJson(Map<String, dynamic> j) => AccountProfile(
        id: j['id'] as String,
        name: j['name'] as String,
        broker: BrokerKind.parse(j['broker'] as String),
        mode: TradingMode.values.byName(j['mode'] as String),
        createdAt: DateTime.parse(j['createdAt'] as String),
        watchlist: [for (final s in (j['watchlist'] as List? ?? const [])) s as String],
        settings: AccountSettings.fromJson((j['settings'] as Map?)?.cast<String, dynamic>() ?? const {}),
        enabled: j['enabled'] as bool? ?? false,
        startingCashCents: (j['startingCashCents'] as num?)?.toInt() ?? 1000000,
        liveApproval: j['liveApproval'] == null
            ? null
            : LiveApproval.fromJson((j['liveApproval'] as Map).cast<String, dynamic>()),
      );
}
