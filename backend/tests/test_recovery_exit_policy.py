"""Partial reductions retain their accepted size across real Mock transactions."""
from dataclasses import replace
from datetime import timedelta

import pytest

from app.automation import fixture_quotes, run_account
from test_rc2_safety import DurableWorld


@pytest.fixture
def world(tmp_path):
    value = DurableWorld(tmp_path / 'exit-policy.db')
    yield value
    value.repo.close()


def cycle(world, right, bid=1.2, feed=None, advance=True):
    if advance:
        world.time += timedelta(seconds=1)
    world.service.reconcile(world.account)
    world.service.mock_market_data(world.account, 'NVDA')
    return run_account(world.service, world.account,
        feed=feed or (lambda symbol, now: world.bars(right)),
        quote_feed=lambda symbol, now: [replace(q, bid=bid, ask=bid+.03)
                                       for q in fixture_quotes(symbol, now)])


@pytest.mark.parametrize('right', ['CALL', 'PUT'])
@pytest.mark.parametrize('resume', ['same_price', 'reprice', 'restart'])
def test_partial_profit_preserves_intended_remainder(world, right, resume):
    world.own(right, quantity=4)
    world.service.configure(world.account, {'automation_enabled': True,
        'partial_profit_pct': 10, 'partial_exit_pct': 50, 'take_profit_pct': 500})
    first = cycle(world, right)
    assert first['fills_applied'] == 1
    assert world.service.rows(world.account, 'positions')[0]['quantity'] == 3
    assert cycle(world, right, advance=False)['fills_applied'] == 0
    if resume == 'restart':
        world.reopen()
    bid = 1.1 if resume == 'reprice' else 1.2
    cycle(world, right, bid)
    cycle(world, right, bid)
    positions = world.service.rows(world.account, 'positions')
    assert len(positions) == 1 and positions[0]['quantity'] == 2
    closes = [o for o in world.service.rows(world.account, 'orders') if o['side'] == 'SELL_TO_CLOSE']
    assert sum(o['filled'] for o in closes) == 2
    assert all(o['status'] in ('FILLED', 'CANCELLED') for o in closes)
    assert world.service.reconcile(world.account)['resubmitted'] == 0


@pytest.mark.parametrize('right', ['CALL', 'PUT'])
@pytest.mark.parametrize('error', [RuntimeError('optional scenario unavailable'), ValueError('research provenance unavailable')])
def test_partial_profit_survives_scenario_outage_but_real_invalidation_takes_priority(world, right, error):
    world.own(right, quantity=4)
    world.service.configure(world.account, {'automation_enabled': True,
        'partial_profit_pct': 10, 'take_profit_pct': 500, 'scenario_exit_enabled': True})
    def unavailable(symbol, now):
        raise error
    result = cycle(world, right, feed=unavailable)
    assert any(action.get('reason') == 'PARTIAL_PROFIT' for action in result['actions'])
    assert result['blocked_reasons']
    cycle(world, right, feed=unavailable)
    assert world.service.rows(world.account, 'positions')[0]['quantity'] == 2
    opposite = 'PUT' if right == 'CALL' else 'CALL'
    result = cycle(world, right, feed=lambda symbol, now: world.bars(opposite))
    assert any(action.get('reason') == 'SCENARIO_INVALIDATED' for action in result['actions'])
    cycle(world, right, feed=unavailable)
    assert not world.service.rows(world.account, 'positions')


@pytest.mark.parametrize('right', ['CALL', 'PUT'])
def test_stop_loss_can_supersede_a_partially_filled_partial_exit(world, right):
    world.own(right, quantity=4)
    world.service.configure(world.account, {'automation_enabled': True,
        'partial_profit_pct': 10, 'take_profit_pct': 500})
    cycle(world, right)
    stopped = cycle(world, right, .7)
    assert any(action.get('reason') == 'STOP_LOSS' for action in stopped['actions'])
    cycle(world, right, .7)
    cycle(world, right, .7)
    assert not world.service.rows(world.account, 'positions')
    assert sum(o['filled'] for o in world.service.rows(world.account, 'orders')
               if o['side'] == 'SELL_TO_CLOSE') == 4
