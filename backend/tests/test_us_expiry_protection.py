"""US-calendar expiry reduces owned risk without inventing settlement or flatness.

All accounts, quotes and fills are isolated synthetic ledger transactions.
"""
from dataclasses import replace
from datetime import datetime, timedelta
import json

import pytest

from app.automation import fixture_quotes, run_account
from app.lifecycle import advance_reversal, request_reversal
from app.service import Rejected
from test_rc2_safety import DurableWorld


POLICY = 'us_equity_options_2026_2027'
CASES = [
    ('regular_dst', '2026-10-08T14:00:00+00:00', '2026-10-09', '2026-10-09T20:00:00+00:00'),
    ('regular_standard', '2026-11-05T15:00:00+00:00', '2026-11-06', '2026-11-06T21:00:00+00:00'),
    ('early_close', '2026-11-25T15:00:00+00:00', '2026-11-27', '2026-11-27T18:00:00+00:00'),
    ('holiday_expiry', '2026-04-01T14:00:00+00:00', '2026-04-03', '2026-04-02T20:00:00+00:00'),
    ('holiday_early_close', '2026-12-23T15:00:00+00:00', '2026-12-25', '2026-12-24T18:00:00+00:00'),
]


@pytest.fixture
def world(tmp_path):
    w = DurableWorld(tmp_path / 'us-expiry.db')
    w.service.configure(w.account, {'session_policy': POLICY})
    yield w
    w.repo.close()


def at(w, stamp):
    w.time = datetime.fromisoformat(stamp) if isinstance(stamp, str) else stamp
    w.service.reconcile(w.account)
    w.service.mock_market_data(w.account, 'NVDA')


def mark(w, position, bid=100):
    with w.repo.transaction() as db:
        w.service.record_option_mark(db, w.account, position['symbol'], position['right_kind'],
            position['expiry'], position['strike'], bid, bid+5, w.time)


def own(w, seed, expiry, right='CALL', quantity=1):
    at(w, seed)
    order = w.service.submit(w.account, w.request(right=right, expiry=expiry, quantity=quantity))
    w.service.fill(w.account, order['id'], 'owned-before-expiry', quantity, 105)
    position = w.service.rows(w.account, 'positions')[0]
    mark(w, position)
    return position


def close_request(w, position, key='expiry-close', quantity=None):
    return w.request(key=key, right=position['right_kind'], expiry=position['expiry'],
                     side='SELL_TO_CLOSE', quantity=quantity or position['quantity'], limit_cents=100)


def review_events(w):
    return [row for row in w.service.rows(w.account, 'audit')
            if row['event'] == 'MOCK_EXPIRY_REVIEW_REQUIRED']


@pytest.mark.parametrize('name,seed,expiry,cutoff', CASES, ids=[row[0] for row in CASES])
@pytest.mark.parametrize('right', ['CALL', 'PUT'])
def test_final_session_allows_owned_reduction_and_blocks_new_buy(world, name, seed, expiry, cutoff, right):
    w = world
    position = own(w, seed, expiry, right)
    close_time = datetime.fromisoformat(cutoff)
    at(w, close_time-timedelta(hours=1))
    mark(w, position)
    assert w.service.expire(w.account) == 0
    assert w.service.rows(w.account, 'positions') == [position]
    with pytest.raises(Rejected):
        w.service.submit(w.account, w.request(key='final-session-buy', right=right, expiry=expiry))
    order = w.service.submit(w.account, close_request(w, position))
    at(w, close_time-timedelta(microseconds=1))
    assert w.service.fill(w.account, order['id'], 'last-session-owned-close', 1, 100)['status'] == 'FILLED'
    assert not w.service.rows(w.account, 'positions')
    assert not review_events(w)


@pytest.mark.parametrize('right', ['CALL', 'PUT'])
def test_partial_close_cutoff_retains_cost_and_replays_receipt_after_restart(world, right):
    w = world
    position = own(w, CASES[0][1], CASES[0][2], right, 2)
    at(w, '2026-10-09T19:59:59+00:00')
    order = w.service.submit(w.account, close_request(w, position))
    w.service.fill(w.account, order['id'], 'pre-cutoff-partial', 1, 100)
    remainder = w.service.rows(w.account, 'positions')[0]
    realized = w.service.performance(w.account)['realized_pnl_cents']
    with w.repo.transaction() as db:
        policy = db.one('SELECT * FROM position_policies WHERE account_id=?', (w.account,))
    assert remainder['quantity'] == 1 and remainder['cost'] == 10565
    at(w, '2026-10-09T20:00:00+00:00')
    assert w.service.expire(w.account) == 0
    assert w.service.expire(w.account) == 0
    assert len(review_events(w)) == 1
    with pytest.raises(Rejected):
        w.service.fill(w.account, order['id'], 'new-late-fill', 1, 100)
    w.reopen()
    assert w.service.fill(w.account, order['id'], 'pre-cutoff-partial', 1, 100)['filled'] == 1
    assert w.service.submit(w.account, close_request(w, position))['id'] == order['id']
    at(w, '2026-10-12T14:00:00+00:00')
    assert w.service.expire(w.account) == 0
    mark(w, remainder, bid=150)  # Fresh synthetic prices do not resolve expiry.
    assert w.service.rows(w.account, 'positions') == [remainder]
    with w.repo.transaction() as db:
        assert db.one('SELECT * FROM position_policies WHERE account_id=?', (w.account,)) == policy
    performance = w.service.performance(w.account)
    assert performance['realized_pnl_cents'] == realized
    assert performance['open_premium_cents'] == remainder['cost']
    assert performance['valuation_complete'] is False
    assert performance['unrealized_pnl_cents'] is None
    assert len(w.service.status(w.account)['expiration_reviews']) == 1
    assert len(review_events(w)) == 1
    with pytest.raises(Rejected):
        w.service.submit(w.account, w.request(key='opposite-after-expiry', right='PUT' if right == 'CALL' else 'CALL'))
    w.service.watch(w.account, 'AAPL', True)
    with pytest.raises(Rejected):
        w.service.submit(w.account, w.request(key='other-symbol-after-expiry', symbol='AAPL', strike_cents=20000))
    with pytest.raises(Rejected):
        w.service.submit(w.account, close_request(w, remainder, key='new-expired-close'))


def test_global_expire_retains_us_exposure_and_preserves_legacy_writeoff(world):
    w = world
    position = own(w, CASES[0][1], CASES[0][2])
    other = w.service.create_account('legacy-24x7', 3_000_000)['id']
    w.service.watch(other, 'NVDA', True)
    legacy = w.service.submit(other, w.request(key='legacy-entry', expiry=position['expiry']))
    w.service.fill(other, legacy['id'], 'legacy-owned', 1, 105)
    at(w, '2026-10-09T20:00:00+00:00')
    w.service.reconcile(other)
    assert w.service.expire() == 1
    assert w.service.expire() == 0
    assert w.service.rows(w.account, 'positions') == [position]
    assert not w.service.rows(other, 'positions')
    assert w.service.performance(w.account)['realized_pnl_cents'] == 0
    assert w.service.performance(other)['realized_pnl_cents'] == -10500
    assert len(review_events(w)) == 1
    assert w.service.reconcile(w.account)['resubmitted'] == 0


@pytest.mark.parametrize('right,target', [('CALL', 'PUT'), ('PUT', 'CALL')])
def test_expiry_never_infers_flatness_for_waiting_reversal(world, right, target):
    w = world
    position = own(w, CASES[0][1], CASES[0][2], right, 2)
    at(w, '2026-10-09T19:59:30+00:00')
    mark(w, position)
    quotes = fixture_quotes('NVDA', w.time, [position])
    intent = request_reversal(w.service, w.account, 'expiry-reversal', 'NVDA', target, w.bars(target), quotes)
    close_id = json.loads(intent['payload'])['close_order_ids'][0]
    w.service.fill(w.account, close_id, 'partial-reversal-close', 1, 100)
    at(w, '2026-10-09T20:00:00+00:00')
    assert w.service.expire(w.account) == 0
    current = advance_reversal(w.service, w.account, intent['id'], w.bars(target), fixture_quotes('NVDA', w.time))
    assert current['state'] == 'WAIT_FLAT'
    assert current['order_id'] is None
    assert w.service.rows(w.account, 'positions')[0]['quantity'] == 1
    assert not any(o['side'] == 'BUY' and o['right_kind'] == target
                   for o in w.service.rows(w.account, 'orders'))


@pytest.mark.parametrize('state', ['owned', 'pending', 'active_intent'])
def test_policy_change_cannot_reinterpret_outstanding_expiry_authority(world, state):
    w = world
    at(w, CASES[0][1])
    if state == 'pending':
        w.service.submit(w.account, w.request())
    else:
        w.own()
        if state == 'active_intent':
            intent = request_reversal(w.service, w.account, 'flat-locked', 'NVDA', 'PUT', w.bars('PUT'), w.quotes())
            close_id = json.loads(intent['payload'])['close_order_ids'][0]
            w.service.fill(w.account, close_id, 'old-direction-flat', 1, 100)
            assert not w.service.rows(w.account, 'positions')
            assert all(order['status'] == 'FILLED' for order in w.service.rows(w.account, 'orders'))
    with pytest.raises(Rejected):
        w.service.configure(w.account, {'session_policy': 'synthetic_24x7'})
    with w.repo.transaction() as db:
        assert w.service.account(db, w.account)['config']['session_policy'] == POLICY


def test_calendar_failure_does_not_erase_owned_expiry_or_authorize_fill(world, monkeypatch):
    w = world
    position = own(w, CASES[0][1], CASES[0][2])
    order = w.service.submit(w.account, close_request(w, position))
    at(w, '2026-10-09T15:00:00+00:00')
    def unavailable(*args, **kwargs):
        raise RuntimeError('calendar unavailable')
    monkeypatch.setattr('app.market_sessions.evaluate_session', unavailable)
    assert w.service.expire(w.account) == 0
    assert w.service.rows(w.account, 'positions') == [position]
    with pytest.raises(Rejected):
        w.service.fill(w.account, order['id'], 'calendar-unknown-close', 1, 100)
    assert w.service.rows(w.account, 'positions') == [position]


def test_automation_protects_holiday_expiry_on_last_session_despite_optional_outage(world):
    w = world
    position = own(w, CASES[3][1], CASES[3][2])
    at(w, '2026-04-02T14:00:00+00:00')
    w.service.configure(w.account, {'automation_enabled': True, 'scenario_exit_enabled': True,
        'holding': 'swing', 'expiry_exit_days': 0, 'strategies': []})
    def unavailable(symbol, now):
        raise RuntimeError('optional analysis unavailable')
    result = run_account(w.service, w.account, feed=unavailable,
        quote_feed=lambda symbol, now: [replace(q, bid=1.0, ask=1.03)
            for q in fixture_quotes(symbol, now, [position])])
    assert result['fills_applied'] == 1
    assert any(action.get('reason') == 'EXPIRY_PROTECTION' for action in result['actions'])
    assert not w.service.rows(w.account, 'positions')
    assert not review_events(w)


def test_missed_expire_tick_blocks_global_new_risk_but_allows_other_owned_close(world):
    w = world
    expired = own(w, CASES[0][1], CASES[0][2])
    w.service.watch(w.account, 'AAPL', True)
    request = w.request(key='valid-aapl', symbol='AAPL', strike_cents=20000)
    order = w.service.submit(w.account, request)
    w.service.fill(w.account, order['id'], 'valid-aapl-owned', 1, 105)
    valid = next(p for p in w.service.rows(w.account, 'positions') if p['symbol'] == 'AAPL')
    at(w, '2026-10-12T14:00:00+00:00')
    w.service.mock_market_data(w.account, 'AAPL')
    mark(w, expired, bid=150)
    mark(w, valid)
    # No expire()/worker tick ran. Safety derives uncertainty from retained
    # contracts rather than relying on a previously written review event.
    assert not review_events(w)
    assert len(w.service.status(w.account)['expiration_reviews']) == 1
    assert w.service.performance(w.account)['valuation_complete'] is False
    other = w.service.create_account('new-risk-account', 3_000_000)['id']
    w.service.watch(other, 'TSLA', True)
    with pytest.raises(Rejected):
        w.service.submit(other, w.request(key='global-risk', symbol='TSLA', strike_cents=25000))
    close = w.service.submit(w.account, request | {'request_key': 'valid-aapl-close',
        'side': 'SELL_TO_CLOSE', 'limit_cents': 100})
    assert w.service.fill(w.account, close['id'], 'valid-reduction', 1, 100)['status'] == 'FILLED'
    assert w.service.rows(w.account, 'positions') == [expired]


def test_expired_fixture_quote_cannot_refresh_mark_or_create_opposite_inventory(world):
    w = world
    position = own(w, CASES[0][1], CASES[0][2])
    with w.repo.transaction() as db:
        original_mark = db.one('SELECT * FROM option_marks WHERE account_id=? AND expiry=?',
                               (w.account, position['expiry']))
    at(w, '2026-10-12T14:00:00+00:00')
    w.service.configure(w.account, {'automation_enabled': True, 'reversal_enabled': True})
    result = run_account(w.service, w.account, feed=lambda symbol, now: w.bars('PUT'),
        quote_feed=lambda symbol, now: [replace(q, bid=1.5, ask=1.53)
            for q in fixture_quotes(symbol, now, [position])])
    assert result['fills_applied'] == result['orders_submitted'] == 0
    assert w.service.rows(w.account, 'positions') == [position]
    with w.repo.transaction() as db:
        assert db.one('SELECT * FROM option_marks WHERE account_id=? AND expiry=?',
                      (w.account, position['expiry'])) == original_mark
    assert w.service.performance(w.account)['valuation_complete'] is False
