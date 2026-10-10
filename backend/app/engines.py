"""Pure quantitative analysis. Outputs are proposals, never broker instructions."""
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from math import isfinite, sqrt
from typing import Callable, Iterable


def aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Timezone-aware timestamps required")


@dataclass(frozen=True)
class Bar:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    completed: bool = True

    def __post_init__(self):
        aware(self.timestamp)
        if not isinstance(self.completed, bool):
            raise ValueError("Completed-bar flag must be boolean")
        if not all(isfinite(v) for v in (self.open, self.high, self.low, self.close, self.volume)):
            raise ValueError("Non-finite bar")
        if self.low <= 0 or not self.low <= self.open <= self.high or not self.low <= self.close <= self.high or self.volume < 0:
            raise ValueError("Invalid OHLCV")


@dataclass(frozen=True)
class OptionQuote:
    symbol: str
    expiry: date
    right: str
    strike: float
    bid: float
    ask: float
    delta: float
    iv: float
    open_interest: int
    timestamp: datetime
    multiplier: int = 100

    def __post_init__(self):
        aware(self.timestamp)
        if not self.symbol or self.right not in ("CALL", "PUT"):
            raise ValueError("Invalid option identity")
        if not all(isfinite(v) for v in (self.strike, self.bid, self.ask, self.delta, self.iv)):
            raise ValueError("Non-finite option quote")
        if self.strike <= 0 or not 0 <= self.bid <= self.ask or self.ask <= 0 or self.iv < 0 or self.open_interest < 0 or self.multiplier != 100:
            raise ValueError("Invalid quote; V1 supports standard 100-share options")
        if not ((self.right == "CALL" and 0 <= self.delta <= 1) or (self.right == "PUT" and -1 <= self.delta <= 0)):
            raise ValueError("Invalid delta sign")

    @property
    def key(self):
        return (self.symbol, self.expiry, self.right, self.strike)


@dataclass(frozen=True)
class Signal:
    strategy: str
    right: str
    score: float
    reason: str
    timestamp: datetime

    def __post_init__(self):
        aware(self.timestamp)
        if not self.strategy or self.right not in ("CALL", "PUT") or not isfinite(self.score) or not 0 <= self.score <= 1 or not self.reason:
            raise ValueError("Invalid quantitative signal")


@dataclass(frozen=True)
class Analysis:
    regime: str
    atr: float
    realized_volatility: float
    signals: tuple[Signal, ...]
    explanation: str
    ai_status: str


@dataclass(frozen=True)
class VolatilityAssessment:
    realized_per_bar: float
    average_implied: float | None
    wide_spread_count: int
    quote_count: int


def validate_bars(bars: Iterable[Bar]) -> tuple[Bar, ...]:
    result = tuple(bars)
    if any(not bar.completed for bar in result):
        raise ValueError("Incomplete bar cannot influence a signal")
    if any(a.timestamp >= b.timestamp for a, b in zip(result, result[1:])):
        raise ValueError("Bars must be unique and strictly chronological")
    return result


class TechnicalAnalysisEngine:
    @staticmethod
    def indicators(bars: Iterable[Bar]):
        bars = validate_bars(bars)
        if len(bars) < 21:
            raise ValueError("At least 21 completed bars required")
        closes = [bar.close for bar in bars]
        sma20 = sum(closes[-20:]) / 20
        prior_sma20 = sum(closes[-21:-1]) / 20
        ranges = [max(b.high - b.low, abs(b.high - a.close), abs(b.low - a.close)) for a, b in zip(bars[-15:-1], bars[-14:])]
        returns = [b / a - 1 for a, b in zip(closes[-21:-1], closes[-20:])]
        mean = sum(returns) / len(returns)
        # Per-bar dispersion: intentionally no assumed daily/intraday annualizer.
        volatility = sqrt(sum((r - mean) ** 2 for r in returns) / len(returns))
        return sma20, prior_sma20, sum(ranges) / len(ranges), volatility


class MarketRegimeDetection:
    @staticmethod
    def classify(close: float, sma: float, previous_sma: float, atr: float):
        if atr / close >= 0.06:
            return "HIGH_VOLATILITY"
        if close > sma and sma > previous_sma:
            return "UPTREND"
        if close < sma and sma < previous_sma:
            return "DOWNTREND"
        return "RANGE"


class BreakoutStrategy:
    @staticmethod
    def evaluate(bars: tuple[Bar, ...], regime: str):
        bars = validate_bars(bars)
        if len(bars) < 21:
            raise ValueError("At least 21 completed bars required")
        last, prior = bars[-1], bars[-21:-1]
        avg_volume = sum(b.volume for b in prior) / len(prior)
        if avg_volume <= 0 or last.volume < avg_volume * 1.2:
            return None
        if regime == "UPTREND" and last.close > max(b.high for b in prior):
            return Signal("breakout", "CALL", 0.8, "Close exceeds prior 20-bar high; volume >= 1.2x prior average", last.timestamp)
        if regime == "DOWNTREND" and last.close < min(b.low for b in prior):
            return Signal("breakout", "PUT", 0.8, "Close below prior 20-bar low; volume >= 1.2x prior average", last.timestamp)
        return None


class PullbackStrategy:
    @staticmethod
    def evaluate(bars: tuple[Bar, ...], regime: str, sma: float, atr: float):
        bars = validate_bars(bars)
        if len(bars) < 21 or not all(isfinite(v) for v in (sma, atr)):
            raise ValueError("Invalid pullback inputs")
        last, previous = bars[-1], bars[-2]
        if atr <= 0:
            return None
        if regime == "UPTREND" and abs(last.low - sma) <= atr * .5 and last.close > sma and last.close > previous.close:
            return Signal("pullback", "CALL", .6, "Uptrend bounce near 20-bar average", last.timestamp)
        if regime == "DOWNTREND" and abs(last.high - sma) <= atr * .5 and last.close < sma and last.close < previous.close:
            return Signal("pullback", "PUT", .6, "Downtrend rejection near 20-bar average", last.timestamp)
        return None


class AnalysisEngine:
    def __init__(self, explainer: Callable[[dict], str] | None = None):
        self.explainer = explainer

    def analyze(self, bars: Iterable[Bar]) -> Analysis:
        bars = validate_bars(bars)
        sma, prior_sma, atr, vol = TechnicalAnalysisEngine.indicators(bars)
        regime = MarketRegimeDetection.classify(bars[-1].close, sma, prior_sma, atr)
        signals = tuple(s for s in (BreakoutStrategy.evaluate(bars, regime), PullbackStrategy.evaluate(bars, regime, sma, atr)) if s)
        explanation = "; ".join(s.reason for s in signals) or "No quantitative entry rule passed"
        status = "DISABLED"
        if self.explainer is not None:
            try:
                narrative = self.explainer({"regime": regime, "atr": atr, "volatility": vol, "reasons": [s.reason for s in signals]})
                if not isinstance(narrative, str) or not narrative.strip() or len(narrative) > 4000:
                    raise ValueError("Invalid explanation")
                explanation = narrative
                status = "EXPLANATION_ONLY"
            except Exception:
                status = "FAILED_FALLBACK"
        return Analysis(regime, atr, vol, signals, explanation, status)


class OptionsSelectionEngine:
    def select(self, quotes: Iterable[OptionQuote], symbol: str, right: str, as_of: datetime,
               min_dte: int = 7, max_dte: int = 45, max_spread_pct: float = .15,
               max_age: timedelta = timedelta(seconds=60)) -> OptionQuote | None:
        aware(as_of)
        if right not in ("CALL", "PUT") or min_dte < 0 or max_dte < min_dte or not 0 <= max_spread_pct <= 1 or max_age.total_seconds() < 0:
            raise ValueError("Invalid option filters")
        candidates = []
        for q in quotes:
            age = as_of - q.timestamp
            dte = (q.expiry - as_of.date()).days
            if q.symbol != symbol or q.right != right or not timedelta(0) <= age <= max_age:
                continue
            if not min_dte <= dte <= max_dte or q.bid <= 0 or q.open_interest < 100 or not .35 <= abs(q.delta) <= .7:
                continue
            mid = (q.bid + q.ask) / 2
            if (q.ask - q.bid) / mid > max_spread_pct:
                continue
            candidates.append(q)
        return min(candidates, key=lambda q: (abs(abs(q.delta) - .5), (q.ask-q.bid)/((q.ask+q.bid)/2), q.expiry, q.strike)) if candidates else None


class VolatilityIntelligence:
    def assess(self, bars: Iterable[Bar], quotes: Iterable[OptionQuote], as_of: datetime,
               symbol: str, max_age: timedelta = timedelta(seconds=60)) -> VolatilityAssessment:
        aware(as_of)
        if max_age.total_seconds() < 0:
            raise ValueError("Invalid quote age")
        bars = validate_bars(bars)
        if bars and bars[-1].timestamp > as_of:
            raise ValueError("Future bar in volatility assessment")
        volatility = TechnicalAnalysisEngine.indicators(bars)[3]
        valid = [q for q in quotes if q.symbol == symbol and q.expiry >= as_of.date() and timedelta(0) <= as_of-q.timestamp <= max_age]
        implied = sum(q.iv for q in valid) / len(valid) if valid else None
        wide = sum((q.ask-q.bid)/((q.ask+q.bid)/2) > .15 for q in valid)
        # IV is typically annualized; per-bar realized dispersion is not a directly comparable ratio.
        return VolatilityAssessment(volatility, implied, wide, len(valid))


class OpportunityRanking:
    @staticmethod
    def rank(opportunities: Iterable[tuple[str, Signal]]):
        opportunities = list(opportunities)
        if any(not symbol or not isfinite(s.score) or not 0 <= s.score <= 1 for symbol, s in opportunities):
            raise ValueError("Invalid opportunity score")
        return sorted(opportunities, key=lambda item: (-item[1].score, item[0], item[1].strategy))


class HybridAIAnalysisEngine(AnalysisEngine):
    """Quantitative signal authority with optional untrusted narrative only."""


class OpportunityRadar:
    def scan(self, symbol_bars: dict[str, Iterable[Bar]]):
        result = []
        for symbol, bars in sorted(symbol_bars.items()):
            analysis = AnalysisEngine().analyze(bars)
            result.extend((symbol, signal) for signal in analysis.signals)
        return OpportunityRanking.rank(result)


class ShadowMode:
    """Only records proposed analyses; deliberately has no broker reference."""
    def __init__(self):
        self.decisions = []

    def record(self, account_id: str, symbol: str, analysis: Analysis):
        if not account_id or not symbol:
            raise ValueError("Account and symbol required")
        self.decisions.append((account_id, symbol, analysis))


class MarketDataUnavailable(ValueError):
    """Fail-closed entry analysis; never authorizes risk or position actions."""


class AnalysisPipeline:
    """Feed validation separate from pure historical quantitative engines.

    Timestamps represent completed interval ends. Adapters must establish this
    convention before constructing Bar(completed=True).
    """
    def __init__(self, engine: AnalysisEngine | None = None,
                 max_age: timedelta = timedelta(minutes=3),
                 max_gap: timedelta = timedelta(minutes=5)):
        if max_age.total_seconds() < 0 or max_gap.total_seconds() <= 0:
            raise ValueError("Invalid market-data limits")
        self.engine = engine or HybridAIAnalysisEngine()
        self.max_age, self.max_gap = max_age, max_gap

    def analyze(self, bars: Iterable[Bar], as_of: datetime, available: bool = True):
        aware(as_of)
        if available is not True:
            raise MarketDataUnavailable("Market feed unavailable")
        bars = validate_bars(bars)
        if len(bars) < 21:
            raise MarketDataUnavailable("Insufficient completed market bars")
        if not timedelta(0) <= as_of - bars[-1].timestamp <= self.max_age:
            raise MarketDataUnavailable("Future or stale completed market bars")
        if any(b.timestamp-a.timestamp > self.max_gap for a, b in zip(bars[-21:-1], bars[-20:])):
            raise MarketDataUnavailable("Recent market-bar gap exceeds configured feed limit")
        return self.engine.analyze(bars)


def analyze_snapshot(symbol: str, bars: Iterable[Bar], as_of: datetime,
                     quotes: Iterable[OptionQuote] = (), available: bool = True) -> dict:
    """Serializable proposal-only interface for API/worker and offline callers."""
    if not isinstance(symbol, str) or not symbol or len(symbol) > 15:
        raise ValueError("Invalid analysis symbol")
    bars, quotes = tuple(bars), tuple(quotes)
    analysis = AnalysisPipeline().analyze(bars, as_of, available)
    result = asdict(analysis)
    result["signals"] = []
    for signal in analysis.signals:
        proposal = asdict(signal)
        proposal["timestamp"] = signal.timestamp.isoformat()
        quote = OptionsSelectionEngine().select(quotes, symbol, signal.right, as_of)
        proposal["option"] = None if quote is None else {
            **asdict(quote), "expiry": quote.expiry.isoformat(), "timestamp": quote.timestamp.isoformat()}
        proposal["missed_reason"] = "No eligible fresh option quote" if quote is None else None
        result["signals"].append(proposal)
    result.update(symbol=symbol, as_of=as_of.isoformat(), actionable=False,
                  execution_authority=False, source="caller_supplied_unverified")
    return result
