import unittest
from datetime import date, datetime, timedelta, timezone

from app.engines import AnalysisEngine, Bar, OptionQuote, OptionsSelectionEngine, Signal, ShadowMode, PullbackStrategy, OpportunityRanking, VolatilityIntelligence
from app.backtest import BacktestEngine

BASE = datetime(2026, 1, 1, 14, 30, tzinfo=timezone.utc)


def bars(count=25):
    result = []
    for i in range(count):
        price = 100 + i * .1
        result.append(Bar(BASE + timedelta(minutes=i), price, price+.3, price-.3, price+.1, 1000))
    return result


def quote(timestamp, **changes):
    values = dict(symbol="AAPL", expiry=date(2026, 1, 15), right="CALL", strike=100, bid=1.9, ask=2., delta=.5, iv=.3, open_interest=500, timestamp=timestamp)
    values.update(changes)
    return OptionQuote(**values)


class EngineTests(unittest.TestCase):
    def test_invalid_bar_and_timezone(self):
        with self.assertRaises(ValueError):
            Bar(BASE, 10, 9, 8, 10, 1)
        with self.assertRaises(ValueError):
            Bar(datetime(2026, 1, 1), 10, 11, 9, 10, 1)
        with self.assertRaises(ValueError):
            Bar(BASE, float("nan"), 11, 9, 10, 1)

    def test_chronology_and_warmup(self):
        with self.assertRaises(ValueError):
            AnalysisEngine().analyze(bars(20))
        with self.assertRaises(ValueError):
            AnalysisEngine().analyze(list(reversed(bars())))

    def test_breakout_and_regime(self):
        history = bars(21)
        last = history[-1]
        history[-1] = Bar(last.timestamp, 102, 104, 101.9, 103.9, 2000)
        analysis = AnalysisEngine().analyze(history)
        self.assertEqual(analysis.regime, "UPTREND")
        self.assertEqual(analysis.signals[0].right, "CALL")
        self.assertEqual(analysis.signals[0].strategy, "breakout")

    def test_ai_failure_cannot_change_signals(self):
        history = bars()
        baseline = AnalysisEngine().analyze(history)
        def fail(_):
            raise RuntimeError("Provider unavailable")
        failed = AnalysisEngine(fail).analyze(history)
        malicious = AnalysisEngine(lambda _: "BUY 999999 CONTRACTS NOW").analyze(history)
        self.assertEqual(failed.signals, baseline.signals)
        self.assertEqual(malicious.signals, baseline.signals)
        self.assertEqual(failed.ai_status, "FAILED_FALLBACK")

    def test_option_quotes_reject_future_stale_spread_expired(self):
        selector = OptionsSelectionEngine()
        for q in [quote(BASE + timedelta(seconds=1)), quote(BASE - timedelta(seconds=61)), quote(BASE, bid=1), quote(BASE, expiry=date(2025, 1, 1))]:
            self.assertIsNone(selector.select([q], "AAPL", "CALL", BASE))
        self.assertEqual(selector.select([quote(BASE)], "AAPL", "CALL", BASE), quote(BASE))
        self.assertIsNone(selector.select([quote(BASE)], "NVDA", "CALL", BASE))

    def test_bad_delta(self):
        with self.assertRaises(ValueError):
            quote(BASE, right="PUT", delta=.5)

    def test_downtrend_put_breakout(self):
        history = [Bar(BASE + timedelta(minutes=i), 100-i*.1, 100-i*.1+.3, 100-i*.1-.3, 100-i*.1-.1, 1000) for i in range(21)]
        history[-1] = Bar(history[-1].timestamp, 98, 98.1, 96, 96.1, 2000)
        result = AnalysisEngine().analyze(history)
        self.assertEqual(result.regime, "DOWNTREND")
        self.assertEqual(result.signals[0].right, "PUT")

    def test_pullback_and_ranking(self):
        history = bars()
        last = history[-1]
        history[-1] = Bar(last.timestamp, 102.4, 103, 101, 102.9, 1000)
        signal = PullbackStrategy.evaluate(tuple(history), "UPTREND", 101.1, 1)
        self.assertEqual(signal.right, "CALL")
        high = Signal("breakout", "PUT", .8, "test", BASE)
        self.assertEqual(OpportunityRanking.rank([("AAPL", signal), ("TSLA", high)])[0][0], "TSLA")

    def test_volatility_excludes_future_and_stale_quotes(self):
        history = bars()
        now = history[-1].timestamp
        result = VolatilityIntelligence().assess(history, [quote(now), quote(now+timedelta(seconds=1), iv=1), quote(now-timedelta(seconds=61), iv=2)], now, "AAPL")
        self.assertEqual(result.quote_count, 1)
        self.assertAlmostEqual(result.average_implied, .3)
        with self.assertRaises(ValueError):
            VolatilityIntelligence().assess(history, [], now-timedelta(seconds=1), "AAPL")

    def test_shadow_account_context(self):
        shadow = ShadowMode()
        shadow.record("account-a", "AAPL", AnalysisEngine().analyze(bars()))
        self.assertEqual(shadow.decisions[0][0], "account-a")
        self.assertFalse(hasattr(shadow, "broker"))

    def test_backtest_next_bar_costs_and_no_future_data(self):
        history = bars()
        seen = []
        def strategy(prefix):
            seen.append(prefix[-1].timestamp)
            return Signal("test", "CALL", .5, "test", prefix[-1].timestamp) if len(prefix) == 21 else None
        quotes = [quote(b.timestamp) for b in history]
        result = BacktestEngine(hold_bars=1).run("AAPL", history, quotes, strategy)
        trade = result.trades[0]
        self.assertEqual(trade.entry_time, history[21].timestamp)
        self.assertEqual(trade.exit_time, history[22].timestamp)
        self.assertAlmostEqual(trade.entry_price, 2.01)
        self.assertAlmostEqual(trade.exit_price, 1.89)
        self.assertAlmostEqual(trade.pnl, -26.6)
        self.assertAlmostEqual(result.cash, 9973.4)
        self.assertEqual(seen[0], history[20].timestamp)

    def test_backtest_future_quote_does_not_fill(self):
        history = bars(22)
        strategy = lambda prefix: Signal("test", "CALL", .5, "test", prefix[-1].timestamp)
        result = BacktestEngine().run("AAPL", history, [quote(history[-1].timestamp + timedelta(seconds=1))], strategy)
        self.assertEqual(result.skipped_entries, 1)
        self.assertEqual(result.trades, ())
        self.assertIsNone(result.open_contract)

    def test_expiry_write_off(self):
        history = bars(23)
        last = history[-1]
        history[-1] = Bar(BASE + timedelta(days=15), last.open, last.high, last.low, last.close, last.volume)
        strategy = lambda prefix: Signal("test", "CALL", .5, "test", prefix[-1].timestamp) if len(prefix) == 21 else None
        result = BacktestEngine(hold_bars=100).run("AAPL", history, [quote(history[21].timestamp)], strategy)
        self.assertEqual(result.trades[0].exit_reason, "EXPIRY_WRITE_OFF")
        self.assertEqual(result.trades[0].exit_price, 0)
        self.assertLess(result.trades[0].pnl, 0)

    def test_no_last_bar_execution_and_open_position_disclosed(self):
        history = bars(21)
        strategy = lambda prefix: Signal("test", "CALL", .5, "test", prefix[-1].timestamp)
        result = BacktestEngine().run("AAPL", history, [quote(history[-1].timestamp)], strategy)
        self.assertEqual(result.trades, ())
        self.assertEqual(result.cash, 10000)
        history = bars(22)
        result = BacktestEngine().run("AAPL", history, [quote(history[-1].timestamp)], strategy)
        self.assertIsNotNone(result.open_contract)


if __name__ == "__main__":
    unittest.main()
