"""Actual quantitative fixture -> risk -> durable Mock lifecycle regressions."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from app.automation import fixture_quotes, run_account
from app.repository import Repository
from app.service import Rejected, TradingService
from app.worker import fixture_bars, tick


class World:
    def __init__(self, repo=None):
        self.time = datetime(2026, 10, 9, 14, 0, tzinfo=timezone.utc)
        self.repo = repo or Repository()
        self.service = TradingService(self.repo, now=lambda: self.time, today=lambda: self.time.date())
        self.account = self.service.create_account('automation', 3000000)['id']
        self.service.watch(self.account, 'NVDA', True)

    def enable(self, **extra):
        self.service.configure(self.account, {'automation_enabled': True, **extra})

    def run(self, **kwargs):
        return run_account(self.service, self.account, **kwargs)

    def advance(self, seconds=1):
        self.time += timedelta(seconds=seconds)

    def orders(self):
        return self.service.rows(self.account, 'orders')

    def positions(self):
        return self.service.rows(self.account, 'positions')

    def quotes(self, bid=1.0, ask=1.05, timestamp=None):
        return lambda symbol, now: [replace(q, bid=bid, ask=ask, timestamp=timestamp or now) for q in fixture_quotes(symbol, now)]


@pytest.fixture
def world():
    w = World()
    yield w
    w.repo.close()


def test_automatic_mode_is_explicit_and_shadow_worker_stays_nonexecuting(world):
    assert world.run()['blocked_reasons']
    world.enable()
    assert tick(world.service, world.time)['orders_submitted'] == 0
    assert not world.orders()
    result = tick(world.service, world.time, execute_mock=True)
    assert result['orders_submitted'] == 1
    assert world.orders()[0]['status'] == 'FILLED'


def test_actual_quantitative_breakout_enters_single_call_with_risk_admission(world):
    world.enable()
    result = world.run()
    assert not result['blocked_reasons']
    assert result['orders_submitted'] == result['fills_applied'] == 1
    order = world.orders()[0]
    assert (order['right_kind'], order['side'], order['quantity']) == ('CALL', 'BUY', 1)
    assert world.positions()[0]['cost'] == 10500
    assert all(row['source'] == 'synthetic_mock' for row in [result])


def test_automatic_put_uses_quantitative_downtrend_signal(world):
    world.enable()
    def downward(symbol, now):
        bars = fixture_bars(symbol, now)
        return [replace(b, open=300-b.open, high=300-b.low, low=300-b.high, close=300-b.close) for b in bars]
    assert world.run(feed=downward)['orders_submitted'] == 1
    assert world.orders()[0]['right_kind'] == 'PUT'


def test_take_profit_closes_owned_contract_and_same_day_never_reenters(world):
    world.enable()
    world.run()
    world.advance()
    result = world.run(quote_feed=world.quotes(1.40, 1.45))
    assert result['orders_submitted'] == result['fills_applied'] == 1
    assert not world.positions()
    assert any(a.get('reason') == 'TAKE_PROFIT' for a in result['actions'])
    assert world.service.performance(world.account)['realized_pnl_cents'] == 3500
    world.advance()
    assert world.run()['orders_submitted'] == 0
    assert len(world.orders()) == 2


def test_stop_loss_cancels_partial_entry_remainder_before_owned_exit(world):
    world.enable(auto_quantity=3, auto_fill_chunk=1)
    world.run()
    assert world.orders()[0]['status'] == 'PARTIAL'
    world.advance()
    result = world.run(quote_feed=world.quotes(.70, .73))
    assert not world.positions()
    buys = [o for o in world.orders() if o['side'] == 'BUY']
    closes = [o for o in world.orders() if o['side'] == 'SELL_TO_CLOSE']
    assert buys[0]['status'] == 'CANCELLED' and buys[0]['filled'] == 1
    assert closes[0]['quantity'] == closes[0]['filled'] == 1
    assert [a['type'] for a in result['actions']] == ['CANCEL', 'ORDER', 'FILL']
    world.advance()
    world.run()
    assert not world.positions()


def test_partial_fills_advance_only_on_new_observation(world):
    world.enable(auto_quantity=3, auto_fill_chunk=1)
    first_quote = world.time
    world.run(quote_feed=world.quotes(timestamp=first_quote))
    world.advance()
    world.run(quote_feed=world.quotes(timestamp=first_quote))
    assert world.orders()[0]['filled'] == 1
    world.run()
    assert world.orders()[0]['filled'] == 2
    world.advance()
    world.run()
    assert world.orders()[0]['filled'] == 3
    assert len(world.orders()) == 1


def test_parallel_repeated_cycles_and_lost_response_do_not_duplicate(world):
    world.enable(auto_quantity=3, auto_fill_chunk=1)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: world.run(), range(8)))
    assert sum(r['orders_submitted'] for r in results) == 1
    assert sum(r['fills_applied'] for r in results) == 1
    # Caller lost the result after commit, then retried unchanged snapshot.
    assert world.run()['orders_submitted'] == 0
    assert world.orders()[0]['filled'] == 1


def test_restart_requires_reconciliation_then_resumes_partial_without_resubmit(tmp_path):
    url = 'sqlite:///' + str(tmp_path/'restart.db')
    first = World(Repository(url))
    first.enable(auto_quantity=2)
    first.run()
    original_id = first.orders()[0]['id']
    account = first.account
    first.repo.close()
    repo = Repository(url)
    time = first.time + timedelta(seconds=1)
    service = TradingService(repo, now=lambda: time, today=lambda: time.date())
    try:
        assert run_account(service, account)['blocked_reasons']
        assert service.rows(account, 'orders')[0]['filled'] == 1
        service.reconcile(account)
        service.mock_market_data(account, 'NVDA')
        run_account(service, account)
        order = service.rows(account, 'orders')[0]
        assert order['id'] == original_id and order['filled'] == 2
        assert len(service.rows(account, 'orders')) == 1
    finally:
        repo.close()


def test_disconnect_and_market_outage_do_not_fill_or_self_restore(world):
    world.enable(auto_quantity=3)
    world.run()
    world.service.disconnect(world.account)
    world.advance()
    assert world.run()['blocked_reasons']
    assert not world.service.status(world.account)['state_known']
    world.service.reconcile(world.account)
    world.service.mock_market_data(world.account, 'NVDA', False)
    assert world.run()['blocked_reasons']
    assert world.orders()[0]['filled'] == 1
    world.service.mock_market_data(world.account, 'NVDA', True)
    world.run()
    assert world.orders()[0]['filled'] == 2


def test_unknown_stale_account_blocks_even_expiry_until_explicit_reconciliation(world):
    world.enable()
    world.run()
    expiry = datetime.fromisoformat(world.orders()[0]['expiry']).replace(tzinfo=timezone.utc)
    world.time = expiry.replace(hour=14)
    assert world.run()['expired_positions'] == 0
    assert world.positions()
    world.service.reconcile(world.account)
    result = world.run()
    assert result['expired_positions'] == 1
    assert not world.positions()
    assert world.service.performance(world.account)['realized_pnl_cents'] == -10500
    assert world.run()['expired_positions'] == 0


def test_risk_limit_prevents_automatic_entry_without_naked_close(world):
    world.enable(auto_quantity=100)
    result = world.run()
    assert result['blocked_reasons'] and not world.orders() and not world.positions()
    assert any('Contract limit' in r for r in result['blocked_reasons'])


def test_disabled_strategy_and_future_bar_cannot_create_entry(world):
    world.enable(strategies=[])
    assert world.run()['orders_submitted'] == 0
    world.service.configure(world.account, {'strategies': ['breakout']})
    assert world.run(feed=lambda s, n: fixture_bars(s, n+timedelta(minutes=10)))['blocked_reasons']
    assert not world.orders()


@pytest.mark.parametrize('offset', [-61, 1])
def test_stale_future_option_quotes_block_automatic_entry(world, offset):
    world.enable()
    result = world.run(quote_feed=world.quotes(timestamp=world.time+timedelta(seconds=offset)))
    assert result['blocked_reasons'] and not world.orders()


def test_ambiguous_duplicate_contract_quotes_fail_closed(world):
    world.enable()
    def duplicate(symbol, now):
        quotes = fixture_quotes(symbol, now)
        return quotes + [replace(quotes[0], ask=1.06)]
    assert world.run(quote_feed=duplicate)['blocked_reasons']
    assert not world.orders()


def test_emergency_stop_preserves_trusted_owned_automatic_exit(world):
    world.enable()
    world.run()
    world.service.stop(world.account)
    world.advance()
    result = world.run(quote_feed=world.quotes(.70, .73))
    assert result['orders_submitted'] == 1
    assert not world.positions()
    assert world.orders()[-1]['side'] == 'SELL_TO_CLOSE'


def test_independent_accounts_and_failure_do_not_block_healthy_worker(world):
    world.enable()
    other = world.service.create_account('second', 3000000)['id']
    world.service.configure(other, {'automation_enabled': True})
    world.service.watch(other, 'AAPL', True)
    world.service.disconnect(world.account)
    result = tick(world.service, world.time, execute_mock=True)
    assert result['orders_submitted'] == 1
    assert not world.orders()
    assert {o['symbol'] for o in world.service.rows(other, 'orders')} == {'AAPL'}


def test_live_and_shadow_automation_are_locked(world):
    with pytest.raises(Rejected):
        world.service.configure(world.account, {'automation_enabled': True, 'mode': 'live'})
    world.enable(mode='shadow')
    assert world.run()['blocked_reasons']
    assert not world.orders()


def test_corrupt_ledger_cycle_rolls_back_and_persists_untrusted_lock(world):
    world.enable()
    world.run()
    with world.repo.transaction() as db:
        db.execute('UPDATE positions SET quantity=99 WHERE account_id=?', (world.account,))
    result = world.run()
    assert result['blocked_reasons']
    assert not world.service.status(world.account)['state_known']
    assert len(world.orders()) == 1


def test_automatic_exit_preserves_partial_closing_order_on_repeated_observation(world):
    world.enable(auto_quantity=3, auto_fill_chunk=3)
    world.run()
    world.service.configure(world.account, {'auto_fill_chunk': 1})
    world.advance()
    world.run(quote_feed=world.quotes(1.40, 1.45))
    assert world.positions()[0]['quantity'] == 2
    world.run(quote_feed=world.quotes(1.40, 1.45))
    assert world.positions()[0]['quantity'] == 2
    world.advance()
    world.run(quote_feed=world.quotes(1.40, 1.45))
    assert world.positions()[0]['quantity'] == 1
    world.advance()
    world.run(quote_feed=world.quotes(1.40, 1.45))
    assert not world.positions()
    assert len(world.orders()) == 2


def test_shadow_worker_never_settles_expired_disconnected_position(world):
    world.enable()
    world.run()
    world.time = datetime.fromisoformat(world.orders()[0]['expiry']).replace(hour=14, tzinfo=timezone.utc)
    world.service.disconnect(world.account)
    result = tick(world.service, world.time)
    assert result['orders_submitted'] == 0
    assert world.positions()
    assert world.service.performance(world.account)['realized_pnl_cents'] == 0


def test_quote_and_market_freshness_rechecked_at_execution_after_slow_feed(world):
    world.enable()
    world.run()
    world.advance()
    def slow_quote(symbol, now):
        snapshot = [replace(q, bid=.70, ask=.73) for q in fixture_quotes(symbol, now)]
        world.advance(61)
        return snapshot
    result = world.run(quote_feed=slow_quote)
    assert result['blocked_reasons']
    assert len(world.orders()) == 1 and world.positions()[0]['quantity'] == 1


def test_malformed_other_account_cannot_prevent_healthy_owned_exit(world):
    world.enable()
    world.run()
    other = world.service.create_account('broken')['id']
    with world.repo.transaction() as db:
        db.execute('UPDATE accounts SET config=? WHERE id=?', ('{broken', other))
    world.advance()
    result = tick(world.service, world.time, execute_mock=True, quote_feed=world.quotes(.70, .73))
    assert not world.positions()
    assert result['orders_submitted'] == 1
    assert any(r['account_id'] == other and r['blocked_reasons'] for r in result['automation'])
