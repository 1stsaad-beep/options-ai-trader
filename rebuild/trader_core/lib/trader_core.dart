/// Options AI Trader core. See HANDOFF.md and docs/ENGINES.md at the repo's
/// `rebuild/` folder for architecture and engine documentation.
library;

export 'src/models.dart';
export 'src/options_math.dart';

export 'src/brokers/broker_adapter.dart';
export 'src/brokers/live_guard.dart';
export 'src/brokers/broker_registry.dart';
export 'src/brokers/synthetic_market.dart';
export 'src/brokers/simulator_broker.dart';
export 'src/brokers/alpaca_adapter.dart';
export 'src/brokers/tradestation_adapter.dart';
export 'src/brokers/ibkr_adapter.dart';

export 'src/market/market_calendar.dart';
export 'src/analysis/signal.dart';
export 'src/analysis/geometry.dart';
export 'src/analysis/indicators.dart';
export 'src/analysis/pivots.dart';
export 'src/analysis/indicator_engines.dart';
export 'src/analysis/harmonic_engine.dart';
export 'src/analysis/elliott_engine.dart';
export 'src/analysis/classical_engine.dart';
export 'src/analysis/analyzer.dart';
export 'src/analysis/chart_analysis.dart';

export 'src/trading/account.dart';
export 'src/trading/account_state.dart';
export 'src/trading/direction_lock.dart';
export 'src/trading/risk.dart';
export 'src/trading/decision_engine.dart';
export 'src/trading/journal.dart';
export 'src/trading/cycle_record.dart';
export 'src/trading/report.dart';
export 'src/analysis/volatility.dart';
export 'src/trading/trading_engine.dart';
export 'src/strategies/common.dart';
export 'src/strategies/mtf_rsi.dart';
export 'src/strategies/mtf_elliott.dart';
