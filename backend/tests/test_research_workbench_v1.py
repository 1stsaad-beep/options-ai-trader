"""The research workbench is useful evidence, never an order entry surface."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json

from fastapi.testclient import TestClient
import pytest

from app.main import create_app
from app.repository import Repository
from app.research import DecisionMemory, MomentumCandidate, StrategyTournament
from app.research_workbench import (
    _contract, fixture_quotes, inspect_workbench, replay_workbench, snapshot_workbench, capture_workbench_observation,
)
from app.service import Rejected, TradingService


NOW = datetime(2026, 10, 9, 14, 0, 35, tzinfo=timezone.utc)


@pytest.fixture
def world(tmp_path):
    repo = Repository('sqlite:///' + str(tmp_path / 'research.db'))
    clock = [NOW]
    service = TradingService(repo, now=lambda: clock[0], today=lambda: clock[0].date())
    first = service.create_account('Research A')['id']
    second = service.create_account('Research B')['id']
    service.watch(first, 'NVDA', True)
    service.watch(second, 'NVDA', True)
    yield service, first, second, clock
    repo.close()


def test_workbench_orchestrates_all_research_engines_without_mutation(world, monkeypatch):
    service, first, _, _ = world
    before = {table: service.rows(first, table) for table in ('orders', 'positions', 'decision_snapshots', 'audit')}
    for name in ('submit', 'fill', 'reconcile', 'configure', 'mock_market_data'):
        monkeypatch.setattr(service, name, lambda *args, **kwargs: pytest.fail('Research reached execution/state mutation'))
    result = inspect_workbench(service, first, 'NVDA')
    assert result == inspect_workbench(service, first, 'NVDA')
    assert result['account_id'] == first
    assert result['symbol'] == 'NVDA'
    assert not result['execution_authority'] and not result['external_connections']
    assert result['mode'] == 'SHADOW' and result['source'] == 'synthetic_fixture'
    assert not result['profitability_evidence']
    assert set(result['modules']) == {
        'scenario_battle', 'entry_timing', 'option_twin', 'liquidity_trap',
        'correlation_guard', 'strategy_tournament', 'safety_supervisor'}
    assert len(result['modules']['entry_timing']['methods']) == 3
    assert len(result['modules']['option_twin']['scenarios']) == 3
    assert result['modules']['strategy_tournament']['status'] == 'EVALUATED'
    assert len(result['modules']['strategy_tournament']['folds']) > 0
    assert json.loads(result['decision']['evidence_json'])['execution_authority'] is False
    assert {table: service.rows(first, table) for table in before} == before
    assert json.loads(json.dumps(result, allow_nan=False)) == result


@pytest.mark.parametrize('symbol', ['AAPL', 'INVALID', 'nvda'])
def test_requires_enabled_qualified_account_watch_symbol(world, symbol):
    service, first, _, _ = world
    with pytest.raises(Rejected, match='enabled, qualified'):
        inspect_workbench(service, first, symbol)


def test_disabled_or_unknown_account_cannot_create_research_snapshot(world):
    service, first, _, _ = world
    service.watch(first, 'NVDA', False)
    with pytest.raises(Rejected):
        snapshot_workbench(service, first, 'NVDA')
    with pytest.raises(Rejected, match='Unknown account'):
        inspect_workbench(service, 'not-an-account', 'NVDA')
    assert service.rows(first, 'decision_snapshots') == []


def test_snapshot_survives_restart_and_preserves_decision_reasons(world):
    service, first, second, clock = world
    original = snapshot_workbench(service, first, 'NVDA')
    identifier = original['snapshot_id']
    before = deepcopy(service.rows(first, 'decision_snapshots'))
    pending = replay_workbench(service, first, 'NVDA', identifier)
    assert pending['counterfactual']['status'] == 'INSUFFICIENT_OBSERVED_OUTCOME'
    assert pending['counterfactual']['pnl'] is None
    clock[0] += timedelta(minutes=1)
    capture_workbench_observation(service, first, 'NVDA', identifier)
    clock[0] += timedelta(minutes=1)
    capture_workbench_observation(service, first, 'NVDA', identifier)
    restarted = TradingService(service.repo, now=lambda: clock[0], today=lambda: clock[0].date())
    service.watch(first, 'NVDA', False)  # Historical evidence remains readable after monitoring stops.
    replay = replay_workbench(restarted, first, 'NVDA', identifier)
    assert replay['counterfactual']['status'] == 'REPLAYED'
    assert replay['original_decision'] == original['workbench']['decision']
    assert replay['counterfactual']['decision_reasons'] == original['workbench']['decision']['reasons']
    assert replay['counterfactual']['commissions'] == pytest.approx(1.3)
    assert service.rows(first, 'decision_snapshots') == before
    assert service.rows(first, 'orders') == []
    assert service.rows(second, 'decision_snapshots') == []


def test_cross_account_or_symbol_replay_is_rejected(world):
    service, first, second, _ = world
    identifier = snapshot_workbench(service, first, 'NVDA')['snapshot_id']
    for account, symbol, key in ((second, 'NVDA', identifier), (first, 'AAPL', identifier),
                                  (first, 'NVDA', 'nonexistent')):
        with pytest.raises(Rejected):
            replay_workbench(service, account, symbol, key)


def test_replay_does_not_use_future_quotes_or_reprice_original_costs(world):
    service, first, _, clock = world
    original = snapshot_workbench(service, first, 'NVDA')
    clock[0] = NOW.replace(second=0) + timedelta(minutes=1)
    capture_workbench_observation(service, first, 'NVDA', original['snapshot_id'])
    result = replay_workbench(service, first, 'NVDA', original['snapshot_id'])
    assert result['counterfactual']['status'] == 'INSUFFICIENT_OBSERVED_OUTCOME'
    clock[0] += timedelta(minutes=1)
    capture_workbench_observation(service, first, 'NVDA', original['snapshot_id'])
    first_replay = replay_workbench(service, first, 'NVDA', original['snapshot_id'])
    service.configure(first, {'commission_cents': 900})
    clock[0] += timedelta(days=300)
    assert replay_workbench(service, first, 'NVDA', original['snapshot_id']) == first_replay
    assert first_replay['counterfactual']['entry_at'] > original['workbench']['decision']['decided_at']


def test_new_future_observations_never_change_completed_research_folds():
    contract = _contract('NVDA', 'CALL', NOW)
    end = contract.observed_at
    original = fixture_quotes(contract, end)
    extended = fixture_quotes(contract, end + timedelta(minutes=24), count=174)
    assert extended[:150] == original
    candidates = [MomentumCandidate('fast', 3, .002), MomentumCandidate('slow', 8, .004)]
    earlier = StrategyTournament().walk_forward(original, candidates, test_size=12, purge=2)
    later = StrategyTournament().walk_forward(extended, candidates, test_size=12, purge=2)
    assert later['folds'][:len(earlier['folds'])] == earlier['folds']
    for fold in earlier['folds']:
        assert fold['selection_at'] < fold['test_start']
        for trade in fold['testing']['trades']:
            assert trade['decision_at'] < trade['entry_at'] < trade['exit_at']


def test_workbench_tournament_preserves_completed_folds_when_future_is_appended(world):
    service, first, _, clock = world
    earlier = inspect_workbench(service, first, 'NVDA')['modules']['strategy_tournament']
    clock[0] += timedelta(hours=2)
    later = inspect_workbench(service, first, 'NVDA')['modules']['strategy_tournament']
    assert later['session_id'] == earlier['session_id']
    assert later['fixed_contract'] == earlier['fixed_contract']
    assert later['folds'][:len(earlier['folds'])] == earlier['folds']
    assert earlier['fixed_contract']['known_at'] < earlier['folds'][0]['train_start']
    assert not earlier['contract_selection_uses_end_of_sample_data']


def test_workbench_tournament_reports_insufficient_prefix_without_fabricating_results(world):
    service, first, _, clock = world
    clock[0] = NOW.replace(hour=1)
    result = inspect_workbench(service, first, 'NVDA')['modules']['strategy_tournament']
    assert result['status'] == 'INSUFFICIENT_SESSION_HISTORY'
    assert result['out_of_sample_pnl'] is None
    assert result['folds'] == []


def test_stale_or_unknown_state_stays_blocked_even_with_synthetic_research(world):
    service, first, _, clock = world
    service.disconnect(first)
    result = inspect_workbench(service, first, 'NVDA')
    safety = result['modules']['safety_supervisor']
    assert not safety['new_entry_gate_passes']
    assert {'ACCOUNT_KNOWN', 'BALANCES_FRESH', 'ORDERS_RECONCILED'} <= set(safety['hard_failures'])
    assert not service.list_accounts()[0]['state_known']
    clock[0] += timedelta(minutes=3)
    later = inspect_workbench(service, first, 'NVDA')
    assert 'MARKET_FRESH' in later['modules']['safety_supervisor']['hard_failures']
    assert not later['modules']['safety_supervisor']['trust']['may_override_hard_gate']


def test_emergency_stop_is_observed_without_unlocking_or_mutating_orders(world):
    service, first, _, _ = world
    service.stop(first)
    result = inspect_workbench(service, first, 'NVDA')
    assert 'EMERGENCY_STOP' in result['modules']['safety_supervisor']['hard_failures']
    assert not result['modules']['safety_supervisor']['new_entry_gate_passes']
    assert service.status(first)['stopped']


def test_account_exposure_projection_counts_owned_and_pending_without_leaking(world):
    service, first, second, _ = world
    service.configure(first, {'commission_cents': 50})
    request = dict(request_key='example', symbol='NVDA', right='CALL', expiry='2026-11-20',
                   strike_cents=15000, side='BUY', quantity=2, limit_cents=50)
    order = service.submit(first, request)
    service.fill(first, order['id'], 'partial', 1, 50)
    first_projection = inspect_workbench(service, first, 'NVDA')['modules']['correlation_guard']
    second_projection = inspect_workbench(service, second, 'NVDA')['modules']['correlation_guard']
    assert first_projection['exposures'] == {'NVDA': 101.0}
    assert first_projection['exposure_basis'] == 'owned_and_pending_premium_proxy'
    assert first_projection['exposure_input_must_include_pending_orders']
    assert second_projection['exposures'] == {}
    assert not first_projection['actual_delta_or_portfolio_var']


def journal():
    memory = DecisionMemory()
    for account, key, minute in [('a', 'one', 0), ('b', 'one', 0), ('a', 'two', 1)]:
        stamp = NOW + timedelta(minutes=minute)
        memory.record(account, key, stamp, stamp, 'synthetic-contract', ['KNOWN_QUANTITATIVE_REASON'], {'price': 5})
    return memory


def test_decision_memory_export_restore_checks_chain_and_account_separation():
    memory = journal()
    state = memory.to_state()
    restored = DecisionMemory.from_state(json.loads(json.dumps(state)))
    assert restored.observations('a') == memory.observations('a')
    assert restored.observations('b') == memory.observations('b')
    assert len(restored.observations('a')) == 2
    assert restored.observations('unknown') == ()
    state['records'][0]['reasons'].append('EDITED_OUTSIDE_MEMORY')
    assert restored.observations('a')[0].reasons == ('KNOWN_QUANTITATIVE_REASON',)


@pytest.mark.parametrize('field,value', [
    ('digest', '0' * 64), ('previous_digest', 'forged'), ('evidence_json', '{"price":6}'),
    ('account_id', 'b'), ('reasons', ['POST_HOC_REASON']),
    ('observed_at', (NOW + timedelta(days=1)).isoformat()), ('reasons', 'invalid'),
])
def test_decision_memory_rejects_tampering(field, value):
    state = journal().to_state()
    state['records'][0][field] = value
    with pytest.raises(ValueError):
        DecisionMemory.from_state(state)


@pytest.mark.parametrize('mutation', ['duplicate', 'reordered', 'unknown_field', 'boolean_version'])
def test_decision_memory_rejects_invalid_serialized_history(mutation):
    state = journal().to_state()
    if mutation == 'duplicate':
        state['records'].append(deepcopy(state['records'][0]))
    elif mutation == 'reordered':
        state['records'][0], state['records'][1] = state['records'][1], state['records'][0]
    elif mutation == 'unknown_field':
        state['records'][0]['execute'] = True
    else:
        state['schema_version'] = True
    with pytest.raises(ValueError):
        DecisionMemory.from_state(state)


def test_api_authentication_strict_body_and_account_scoping(world):
    service, first, second, clock = world
    token = 'test-token-at-least-32-characters-long'
    app = create_app(service.repo, token)
    headers = {'Authorization': 'Bearer ' + token}
    prefix = f'/api/accounts/{first}/research/NVDA'
    with TestClient(app) as client:
        app.state.service.now = lambda: clock[0]
        for route in (prefix, prefix + '/snapshots/unknown/replay'):
            assert client.get(route).status_code == 401
        assert client.post(prefix + '/snapshot', json={}).status_code == 401
        assert client.get(prefix, headers=headers).status_code == 200
        assert client.post(prefix + '/snapshot', json={'execute': True}, headers=headers).status_code == 422
        assert client.post(prefix + '/snapshot', json={'reason': 'AI says buy'}, headers=headers).status_code == 422
        saved = client.post(prefix + '/snapshot', json={}, headers=headers)
        assert saved.status_code == 200, saved.text
        identifier = saved.json()['snapshot_id']
        assert client.get(prefix + f'/snapshots/{identifier}/replay', headers=headers).status_code == 200
        assert client.get(f'/api/accounts/{second}/research/NVDA/snapshots/{identifier}/replay', headers=headers).status_code == 409
        assert service.rows(first, 'orders') == []
