"""Disabled quantitative policies cannot acquire more Mock inventory."""
from datetime import timedelta

import pytest

from app.automation import run_account
from app.lifecycle import advance_reversal, request_reversal, request_scaling
from app.service import Rejected
from test_rc2_safety import DurableWorld


@pytest.fixture
def world(tmp_path):
    value = DurableWorld(tmp_path / 'entry-permissions.db')
    yield value
    value.repo.close()


def cycle(world, right):
    world.time += timedelta(seconds=1)
    world.service.reconcile(world.account)
    world.service.mock_market_data(world.account, 'NVDA')
    return run_account(world.service, world.account, feed=lambda symbol, now: world.bars(right))


@pytest.mark.parametrize('old_right,new_right', [('CALL', 'PUT'), ('PUT', 'CALL')])
@pytest.mark.parametrize('disabled', [{'reversal_enabled': False}, {'strategies': []}])
@pytest.mark.parametrize('partial', [False, True])
def test_disabled_policy_blocks_reversal_fill_and_preserves_receipts(world, old_right, new_right, disabled, partial):
    world.own(old_right)
    world.service.configure(world.account, {'automation_enabled': True,
        'reversal_enabled': True, 'auto_quantity': 2})
    cycle(world, new_right)
    target = next(o for o in world.service.rows(world.account, 'orders')
                  if o['side'] == 'BUY' and o['right_kind'] == new_right)
    assert target['status'] == 'PENDING'
    if partial:
        cycle(world, new_right)
        with world.repo.transaction() as db:
            receipt = db.one('SELECT * FROM fills WHERE order_id=?', (target['id'],))
    world.service.configure(world.account, disabled)
    before = world.service.rows(world.account, 'positions')
    with pytest.raises(Rejected, match='disabled'):
        world.service.fill(world.account, target['id'], 'new-unapproved-fill', 1, 105)
    assert cycle(world, new_right)['fills_applied'] == 0
    assert world.service.rows(world.account, 'positions') == before
    if partial:
        world.reopen()
        restored = world.service.fill(world.account, target['id'], receipt['id'],
                                     receipt['quantity'], receipt['price_cents'])
        assert restored['filled'] == 1
        assert world.service.rows(world.account, 'positions') == before


def test_disabled_strategy_blocks_ordinary_automatic_remainder_not_manual_account(world):
    world.service.configure(world.account, {'automation_enabled': True, 'auto_quantity': 2})
    cycle(world, 'CALL')
    order = world.service.rows(world.account, 'orders')[0]
    assert order['filled'] == 1
    other = world.service.create_account('independent-manual', 3_000_000)['id']
    world.service.watch(other, 'NVDA', True)
    manual = world.service.submit(other, world.request(key='manual', right='PUT'))
    world.service.configure(world.account, {'strategies': []})
    with pytest.raises(Rejected, match='disabled'):
        world.service.fill(world.account, order['id'], 'disabled-entry', 1, 105)
    assert cycle(world, 'CALL')['fills_applied'] == 0
    assert world.service.fill(other, manual['id'], 'manual-fill', 1, 105)['status'] == 'FILLED'


def test_disabled_strategy_blocks_scaling_but_owned_close_still_works(world):
    from dataclasses import replace
    world.own()
    world.service.configure(world.account, {'scaling_enabled': True})
    quotes = [replace(q, bid=1.4, ask=1.45) for q in world.quotes()]
    intent = request_scaling(world.service, world.account, 'scale', 'NVDA', 'CALL', world.bars('CALL'), quotes)
    world.service.configure(world.account, {'strategies': []})
    with pytest.raises(Rejected, match='disabled'):
        world.service.fill(world.account, intent['order_id'], 'disabled-scale', 1, 145)
    close = world.service.submit(world.account, world.request(key='owned-close', side='SELL_TO_CLOSE', limit_cents=100))
    assert world.service.fill(world.account, close['id'], 'close-fill', 1, 100)['status'] == 'FILLED'
    assert not world.service.rows(world.account, 'positions')


def test_explicit_manual_reversal_preserves_existing_opt_in_semantics(world):
    import json
    world.own()
    intent = request_reversal(world.service, world.account, 'manual-reversal', 'NVDA', 'PUT', world.bars('PUT'), world.quotes())
    close_id = json.loads(intent['payload'])['close_order_ids'][0]
    world.service.fill(world.account, close_id, 'manual-close', 1, 100)
    advanced = advance_reversal(world.service, world.account, intent['id'], world.bars('PUT'), world.quotes())
    assert world.service.fill(world.account, advanced['order_id'], 'manual-reversal-fill', 1, 105)['status'] == 'FILLED'


def test_legacy_automatic_order_without_strategy_evidence_cannot_add_inventory(world):
    from copy import copy
    internal = copy(world.service)
    internal._automation_authorized = True
    order = internal.submit(world.account, world.request(key='auto-e:legacy-missing-evidence'))
    with pytest.raises(Rejected, match='authorization evidence'):
        world.service.fill(world.account, order['id'], 'unknown-strategy', 1, 105)
    assert not world.service.rows(world.account, 'positions')
    assert world.service.cancel(world.account, order['id'])['status'] == 'CANCELLED'


@pytest.mark.parametrize('key', ['auto-e', 'v1-r', 'v1-s'])
def test_manual_keys_without_reserved_colon_remain_manual(world, key):
    world.service.configure(world.account, {'strategies': []})
    order = world.service.submit(world.account, world.request(key=key))
    assert world.service.fill(world.account, order['id'], 'manual-key-fill', 1, 105)['status'] == 'FILLED'


def test_legacy_explicit_quantitative_strategy_evidence_remains_usable(world):
    from copy import copy
    world.service.configure(world.account, {'automation_enabled': True})
    internal = copy(world.service)
    internal._automation_authorized = True
    internal._decision_context = {'reason': 'breakout',
                                  'strategy_source': 'completed_bar_quantitative_worker'}
    order = internal.submit(world.account, world.request(key='auto-e:legacy-strategy'))
    assert world.service.fill(world.account, order['id'], 'legacy-fill', 1, 105)['status'] == 'FILLED'


@pytest.mark.parametrize('origin', ['automatic', 'manual', 'legacy_unknown'])
def test_scaling_fill_respects_saved_automatic_origin(world, origin):
    from dataclasses import replace
    world.own()
    world.service.configure(world.account, {'automation_enabled': True,
        'scaling_enabled': True, 'take_profit_pct': 500})
    quotes = [replace(q, bid=1.4, ask=1.45) for q in world.quotes()]
    if origin == 'legacy_unknown':
        # Create an immutable receipt in the actual prior schema, which lacked
        # caller origin. No stored decision or fill is subsequently rewritten.
        save = world.service.decision
        def legacy_decision(db, account_id, action, facts, order_id=None, intent_id=None):
            return save(db, account_id, action,
                {key: value for key, value in facts.items() if key != 'automatic_authority'}, order_id, intent_id)
        world.service.decision = legacy_decision
    if origin == 'automatic':
        run_account(world.service, world.account, quote_feed=lambda symbol, now: quotes)
        intent = world.service.rows(world.account, 'lifecycle_intents')[0]
    else:
        intent = request_scaling(world.service, world.account, 'scale-origin', 'NVDA', 'CALL', world.bars('CALL'), quotes)
    world.service.configure(world.account, {'automation_enabled': False})
    if origin == 'manual':
        assert world.service.fill(world.account, intent['order_id'], 'explicit-scale', 1, 145)['status'] == 'FILLED'
    else:
        with pytest.raises(Rejected, match='disabled'):
            world.service.fill(world.account, intent['order_id'], 'disabled-worker-scale', 1, 145)
        assert world.service.rows(world.account, 'positions')[0]['quantity'] == 1
