"""Calendar policy is enforced by real ledger acceptance and fill transactions."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from app.automation import fixture_quotes, run_account
from app.service import Rejected
from test_rc2_safety import DurableWorld

POLICY = 'us_equity_options_2026_2027'


@pytest.fixture
def world(tmp_path):
    w = DurableWorld(tmp_path / 'session.db')
    w.service.configure(w.account, {'session_policy': POLICY})
    yield w
    w.repo.close()


def at(w, stamp):
    w.time = datetime.fromisoformat(stamp)
    w.service.reconcile(w.account)
    w.service.mock_market_data(w.account, 'NVDA')


def cycle(w, bid=1.0, failing_analysis=False):
    # Pre-read to avoid a nested transaction inside the bound quote callback.
    contracts = w.service.rows(w.account, 'positions') + w.service.rows(w.account, 'orders')
    def bars(symbol, now):
        if failing_analysis:
            raise RuntimeError('Optional analysis failed')
        return w.bars('CALL')
    return run_account(w.service, w.account, feed=bars,
        quote_feed=lambda symbol, now: [replace(q, bid=bid, ask=bid+.03)
                                       for q in fixture_quotes(symbol, now, contracts)])


@pytest.mark.parametrize('stamp', ['2026-10-09T13:29:59+00:00',
    '2026-10-09T19:45:00+00:00', '2026-10-10T14:00:00+00:00',
    '2026-11-26T15:00:00+00:00', '2026-11-27T17:45:00+00:00',
    '2028-01-03T15:00:00+00:00'])
def test_acceptance_blocks_closed_or_unsupported_sessions(world, stamp):
    at(world, stamp)
    with pytest.raises(Rejected, match='Market session'):
        world.service.submit(world.account, world.request())
    assert world.service.rows(world.account, 'orders') == []
    assert not world.service.status(world.account)['new_entries_allowed']


def test_cutoff_rechecks_fill_preserves_prior_receipt_and_accounts(world):
    w = world
    at(w, '2026-10-09T19:44:50+00:00')
    order = w.service.submit(w.account, w.request(quantity=2))
    w.service.fill(w.account, order['id'], 'first', 1, 105)
    other = w.service.create_account('24x7 independent', 3_000_000)['id']
    w.service.watch(other, 'NVDA', True)
    at(w, '2026-10-09T19:45:00+00:00')
    assert w.service.fill(w.account, order['id'], 'first', 1, 105)['filled'] == 1
    with pytest.raises(Rejected, match='session'):
        w.service.fill(w.account, order['id'], 'second', 1, 105)
    assert w.service.submit(w.account, w.request(quantity=2))['id'] == order['id']
    w.mark()
    independent = w.service.submit(other, w.request(key='other'))
    assert w.service.fill(other, independent['id'], 'other-fill', 1, 105)['status'] == 'FILLED'


@pytest.mark.parametrize('stamp', ['2026-10-09T19:45:00+00:00', '2026-11-27T17:45:00+00:00'])
def test_intraday_close_uses_calendar_not_fixed_utc_hour(world, stamp):
    w = world
    close = datetime.fromisoformat(stamp)
    at(w, (close-timedelta(minutes=1)).isoformat())
    w.own()
    w.service.configure(w.account, {'automation_enabled': True, 'scenario_exit_enabled': True})
    at(w, stamp)
    result = cycle(w, failing_analysis=True)
    assert result['session']['status'] == 'EXIT_WINDOW'
    assert result['fills_applied'] == 1
    assert any(a.get('reason') == 'INTRADAY_EXIT' for a in result['actions'])
    assert not w.service.rows(w.account, 'positions')


def test_owned_stop_after_close_is_durable_without_fabricated_fill(world):
    w = world
    w.own()
    w.service.configure(w.account, {'automation_enabled': True, 'holding': 'swing', 'scenario_exit_enabled': True})
    at(w, '2026-10-09T20:00:00+00:00')
    result = cycle(w, bid=.7, failing_analysis=True)
    closes = [o for o in w.service.rows(w.account, 'orders') if o['side'] == 'SELL_TO_CLOSE']
    assert len(closes) == 1 and closes[0]['filled'] == 0
    assert result['fills_applied'] == 0 and result['blocked_reasons']
    assert cycle(w, bid=.7)['orders_submitted'] == 0
    at(w, '2026-10-12T13:30:00+00:00')
    result = cycle(w, bid=.7, failing_analysis=True)
    assert result['fills_applied'] == 1
    assert not w.service.rows(w.account, 'positions')


@pytest.mark.parametrize('partial', [False, True])
def test_prior_session_buy_never_fills_on_next_open(world, partial):
    w = world
    order = w.service.submit(w.account, w.request(quantity=2))
    if partial:
        w.service.fill(w.account, order['id'], 'first', 1, 105)
    at(w, '2026-10-12T13:30:00+00:00')  # No cutoff cycle ran while stopped.
    with pytest.raises(Rejected, match='prior-session'):
        w.service.fill(w.account, order['id'], 'overnight', 1, 105)
    w.service.configure(w.account, {'automation_enabled': True, 'strategies': []})
    result = cycle(w)
    assert next(o for o in w.service.rows(w.account, 'orders') if o['id'] == order['id'])['status'] == 'CANCELLED'
    assert any(a.get('reason') == 'SESSION_ENTRY_WINDOW_ENDED' for a in result['actions'])
    assert not w.service.rows(w.account, 'positions')  # Carried intraday remainder exits.


def test_calendar_failure_preserves_protective_intent_and_never_fills(world, monkeypatch):
    w = world
    w.own()
    w.service.configure(w.account, {'automation_enabled': True, 'scenario_exit_enabled': True})
    def unavailable(*args, **kwargs):
        raise RuntimeError('calendar damaged')
    monkeypatch.setattr('app.market_sessions.evaluate_session', unavailable)
    result = cycle(w, bid=.7, failing_analysis=True)
    assert result['session']['status'] == 'CALENDAR_UNAVAILABLE'
    closes = [o for o in w.service.rows(w.account, 'orders') if o['side'] == 'SELL_TO_CLOSE']
    assert len(closes) == 1 and closes[0]['filled'] == 0
    assert result['fills_applied'] == 0
    assert any(a.get('reason') == 'STOP_LOSS' for a in result['actions'])


@pytest.mark.parametrize('old,new', [('CALL', 'PUT'), ('PUT', 'CALL')])
def test_pending_reversal_cannot_enter_after_cutoff(world, old, new):
    w = world
    at(w, '2026-10-09T19:44:59+00:00')
    w.own(old)
    w.service.configure(w.account, {'automation_enabled': True, 'reversal_enabled': True})
    run_account(w.service, w.account, feed=lambda symbol, now: w.bars(new))
    target = next(o for o in w.service.rows(w.account, 'orders') if o['side'] == 'BUY' and o['right_kind'] == new)
    assert target['status'] == 'PENDING'
    at(w, '2026-10-09T19:45:00+00:00')
    with pytest.raises(Rejected, match='session'):
        w.service.fill(w.account, target['id'], 'late-reverse', 1, 105)
    result = run_account(w.service, w.account, feed=lambda symbol, now: w.bars(new))
    assert result['fills_applied'] == 0
    assert next(o for o in w.service.rows(w.account, 'orders') if o['id'] == target['id'])['status'] == 'CANCELLED'
    assert not w.service.rows(w.account, 'positions')


@pytest.mark.parametrize('changes', [{'session_policy': 'guess'}, {'session_exit_buffer_minutes': True},
                                  {'session_exit_buffer_minutes': 0}, {'session_exit_buffer_minutes': 121}])
def test_session_configuration_rejects_ambiguous_values(world, changes):
    with pytest.raises(Rejected):
        world.service.configure(world.account, changes)
