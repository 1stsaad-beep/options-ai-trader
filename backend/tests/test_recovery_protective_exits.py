"""Optional scenario research must not strand validated owned Mock exits."""
from dataclasses import replace
from datetime import timedelta

import pytest

from app.automation import fixture_quotes, run_account
from test_rc2_safety import DurableWorld


@pytest.mark.parametrize('reason,bid,config,seconds', [
    ('STOP_LOSS', .70, {}, 0),
    ('TAKE_PROFIT', 1.50, {}, 0),
    ('TRAILING_STOP', 1.10, {'trailing_stop_pct': 10}, 0),
    ('INTRADAY_EXIT', 1.00, {'intraday_exit_hour_utc': 14}, 0),
    ('SWING_TIME_EXIT', 1.00, {'holding': 'swing', 'swing_max_days': 1}, 86400),
])
def test_protective_exit_survives_optional_scenario_outage(tmp_path, reason, bid, config, seconds):
    world = DurableWorld(tmp_path / 'scenario-outage.db')
    try:
        world.own()
        world.service.configure(world.account, {
            'automation_enabled': True, 'scenario_exit_enabled': True, **config,
        })
        world.time += timedelta(seconds=seconds)
        world.service.reconcile(world.account)
        world.service.mock_market_data(world.account, 'NVDA')
        if reason == 'TRAILING_STOP':
            with world.repo.transaction() as db:
                db.execute('UPDATE position_policies SET high_bid=130 WHERE account_id=?', (world.account,))

        def unavailable(symbol, now):
            raise RuntimeError('optional scenario analysis unavailable')

        owned_contracts = world.service.rows(world.account, 'positions')
        result = run_account(world.service, world.account, feed=unavailable,
            quote_feed=lambda symbol, now: [replace(q, bid=bid, ask=bid+.03)
                for q in fixture_quotes(symbol, now, owned_contracts)])
        assert result['orders_submitted'] == result['fills_applied'] == 1, result
        assert not world.service.rows(world.account, 'positions')
        closes = [o for o in world.service.rows(world.account, 'orders') if o['side'] == 'SELL_TO_CLOSE']
        assert len(closes) == 1 and closes[0]['status'] == 'FILLED'
        assert any(a.get('reason') == reason for a in result['actions'])
        assert len(world.service.rows(world.account, 'orders')) == 2
        before = world.service.performance(world.account)['realized_pnl_cents']
        repeat = run_account(world.service, world.account, feed=unavailable)
        assert repeat['orders_submitted'] == repeat['fills_applied'] == 0
        assert world.service.performance(world.account)['realized_pnl_cents'] == before
    finally:
        world.repo.close()


def test_scenario_outage_without_exit_signal_cannot_fabricate_a_close(tmp_path):
    world = DurableWorld(tmp_path / 'no-exit.db')
    try:
        world.own()
        world.service.configure(world.account, {'automation_enabled': True, 'scenario_exit_enabled': True})
        before = world.service.rows(world.account, 'positions')

        def unavailable(symbol, now):
            raise RuntimeError('optional scenario analysis unavailable')

        result = run_account(world.service, world.account, feed=unavailable)
        assert result['orders_submitted'] == result['fills_applied'] == 0
        assert result['blocked_reasons']
        assert world.service.rows(world.account, 'positions') == before
        assert len(world.service.rows(world.account, 'orders')) == 1
    finally:
        world.repo.close()
