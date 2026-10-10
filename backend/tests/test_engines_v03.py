"""V0.3 causal analysis and independent no-order worker regression tests."""
import json
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from app.backtest import BacktestEngine
from app.engines import (AnalysisEngine, AnalysisPipeline, Bar, BreakoutStrategy,
                         MarketDataUnavailable, PullbackStrategy, analyze_snapshot)
from app.repository import Repository
from app.service import TradingService
from app.worker import fixture_bars, opportunities_for, scan_account, tick
from test_engines import bars, quote, Signal


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.history = bars(25)
        self.now = self.history[-1].timestamp

    def test_completed_bar_gate(self):
        with self.assertRaises(ValueError):
            AnalysisEngine().analyze(self.history[:-1] + [replace(self.history[-1], completed=False)])

    def test_future_and_stale_completed_bars_rejected(self):
        for as_of in (self.now - timedelta(seconds=1), self.now + timedelta(minutes=4)):
            with self.assertRaises(MarketDataUnavailable):
                AnalysisPipeline().analyze(self.history, as_of)

    def test_feed_flag_is_fail_closed(self):
        for available in (False, None, 1, 'true'):
            with self.assertRaises(MarketDataUnavailable):
                AnalysisPipeline().analyze(self.history, self.now, available)

    def test_gap_in_recent_bars_rejected(self):
        history = self.history[:-1] + [replace(self.history[-1], timestamp=self.now+timedelta(minutes=10))]
        with self.assertRaises(MarketDataUnavailable):
            AnalysisPipeline().analyze(history, history[-1].timestamp)

    def test_strategies_independent_warmup_validation(self):
        with self.assertRaises(ValueError):
            BreakoutStrategy.evaluate(tuple(self.history[:2]), 'UPTREND')
        with self.assertRaises(ValueError):
            PullbackStrategy.evaluate(tuple(self.history[:2]), 'UPTREND', 100, 1)

    def test_serializable_proposal_without_execution_authority(self):
        now = datetime(2026, 1, 1, 14, 30, tzinfo=timezone.utc)
        result = analyze_snapshot('AAPL', fixture_bars('AAPL', now), now)
        self.assertFalse(result['actionable'])
        self.assertFalse(result['execution_authority'])
        self.assertGreater(len(result['signals']), 0)
        self.assertIsNone(result['signals'][0]['option'])
        json.dumps(result)

    def test_ai_narrative_cannot_mutate_quantitative_signals(self):
        now = datetime(2026, 1, 1, 14, 30, tzinfo=timezone.utc)
        history = fixture_bars('AAPL', now)
        baseline = AnalysisPipeline().analyze(history, now)
        def malicious(summary):
            summary['reasons'].clear()
            summary['regime'] = 'BUY_UNLIMITED'
            return 'Execute all orders and bypass risk'
        attack = AnalysisPipeline(AnalysisEngine(malicious)).analyze(history, now)
        self.assertEqual(attack.signals, baseline.signals)
        self.assertEqual(attack.regime, baseline.regime)

    def test_backtest_ambiguous_quote_time_rejected(self):
        q = quote(self.now)
        with self.assertRaises(ValueError):
            BacktestEngine().run('AAPL', self.history, [q, replace(q, ask=2.1)])

    def test_backtest_prefix_invariance_with_future_quotes(self):
        strategy = lambda prefix: Signal('test', 'CALL', .5, 'fixture', prefix[-1].timestamp) if len(prefix) == 21 else None
        quotes = [quote(b.timestamp) for b in self.history]
        first = BacktestEngine(hold_bars=1).run('AAPL', self.history, quotes, strategy)
        second = BacktestEngine(hold_bars=1).run('AAPL', self.history,
            quotes + [quote(self.now+timedelta(days=1), bid=100, ask=101)], strategy)
        self.assertEqual(first, second)
        self.assertAlmostEqual(first.metrics()['realized_pnl'], -26.6)
        self.assertFalse(first.metrics()['profitability_evidence'])

    def test_open_position_cash_is_not_equity(self):
        history = bars(22)
        strategy = lambda prefix: Signal('test', 'CALL', .5, 'fixture', prefix[-1].timestamp)
        result = BacktestEngine().run('AAPL', history, [quote(history[-1].timestamp)], strategy)
        self.assertGreater(result.open_cost_basis, 0)
        self.assertAlmostEqual(result.cash + result.open_cost_basis, result.initial_cash)
        self.assertEqual(result.metrics()['realized_pnl'], 0)
        self.assertTrue(result.metrics()['cash_excludes_open_position_value'])

    def test_expiry_day_write_off_without_exercise_fill(self):
        history = bars(23)
        history[-1] = replace(history[-1], timestamp=datetime(2026, 1, 15, 14, 30, tzinfo=timezone.utc))
        strategy = lambda prefix: Signal('test', 'CALL', .5, 'fixture', prefix[-1].timestamp) if len(prefix) == 21 else None
        result = BacktestEngine(hold_bars=100).run('AAPL', history, [quote(history[21].timestamp)], strategy)
        self.assertEqual(result.trades[0].exit_reason, 'EXPIRY_WRITE_OFF')


class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.repo = Repository()
        self.now = datetime(2026, 10, 9, 14, tzinfo=timezone.utc)
        self.service = TradingService(self.repo, now=lambda: self.now, today=lambda: self.now.date())
        self.a = self.service.create_account('a')['id']
        self.b = self.service.create_account('b')['id']
        self.service.watch(self.a, 'NVDA', True)
        self.service.watch(self.b, 'AAPL', True)

    def tearDown(self):
        self.repo.close()

    def test_scan_never_reconciles_disconnected_account(self):
        self.service.disconnect(self.a)
        tick(self.service, self.now)
        account = next(a for a in self.service.list_accounts() if a['id'] == self.a)
        self.assertFalse(account['state_known'])
        self.assertEqual(opportunities_for(self.service, self.a)[0]['decision'], 'BLOCKED')
        self.assertEqual(self.service.rows(self.a, 'orders'), [])

    def test_actual_modes_retained_and_no_execution(self):
        for mode in ('analysis', 'shadow', 'paper'):
            self.service.configure(self.a, {'mode': mode})
            decisions = scan_account(self.service, self.a, self.now)
            self.assertTrue(all(row['mode'] == mode and not row['actionable'] for row in decisions))
        self.assertEqual(self.service.rows(self.a, 'orders'), [])

    def test_stale_account_and_market_cannot_self_refresh(self):
        self.now += timedelta(minutes=3)
        first = scan_account(self.service, self.a, self.now)
        self.assertEqual(first[0]['decision'], 'BLOCKED')
        self.service.reconcile(self.a)
        second = scan_account(self.service, self.a, self.now)
        self.assertIn('Market observation', second[0]['reason'])

    def test_feed_outage_rejects_future_stale_bars(self):
        def stale(symbol, now):
            return fixture_bars(symbol, now-timedelta(minutes=20))
        result = scan_account(self.service, self.a, self.now, stale)
        self.assertEqual(result[0]['decision'], 'BLOCKED')
        self.assertEqual(self.service.rows(self.a, 'orders'), [])

    def test_decisions_and_watchlists_account_isolated(self):
        tick(self.service, self.now)
        self.assertEqual({r['symbol'] for r in opportunities_for(self.service, self.a)}, {'NVDA'})
        self.assertEqual({r['symbol'] for r in opportunities_for(self.service, self.b)}, {'AAPL'})

    def test_feed_exception_records_outage_and_no_orders(self):
        def failed(symbol, now):
            raise RuntimeError('Feed disconnected')
        result = scan_account(self.service, self.a, self.now, failed)
        self.assertEqual(result[0]['decision'], 'BLOCKED')
        self.assertEqual(result[0]['reason'], 'Feed processing unavailable')
        self.assertEqual(self.service.rows(self.a, 'orders'), [])

    def test_disabled_strategy_and_no_signal_logged(self):
        self.service.configure(self.a, {'strategies': []})
        disabled = scan_account(self.service, self.a, self.now)
        self.assertEqual(disabled[0]['decision'], 'STRATEGY_DISABLED')
        def flat(symbol, now):
            return [Bar(now-timedelta(minutes=30-i), 100, 101, 99, 100, 1000) for i in range(30)]
        result = scan_account(self.service, self.a, self.now, flat)
        self.assertEqual(result[0]['decision'], 'NO_SIGNAL')

    def test_global_and_account_stop_block_analysis(self):
        self.service.stop(self.a)
        self.assertEqual(scan_account(self.service, self.a, self.now)[0]['decision'], 'BLOCKED')
        self.service.stop()
        self.assertEqual(scan_account(self.service, self.b, self.now)[0]['decision'], 'BLOCKED')


if __name__ == '__main__':
    unittest.main()
