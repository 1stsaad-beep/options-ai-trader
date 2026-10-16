from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path

import pytest

from app.engines import Bar
from app.market_strategy import analyze, greater, VERSION, STRATEGIES
from app.strategy_replay import compare_strategies

FIXTURE = json.loads((Path(__file__).parents[2] / 'mobile/test/fixtures/market_strategy_v1.json').read_text())


@pytest.mark.parametrize('case', FIXTURE['cases'], ids=lambda c:c['name'])
def test_shared_strategies_on_every_original_prefix(case):
    assert FIXTURE['contract'] == VERSION
    bars = [Bar(datetime.fromisoformat(b['at']), *(b[k] for k in ('o','h','l','c','v'))) for b in case['bars']]
    for end, expected in enumerate(case['prefixes'], 1):
        assert {strategy: analyze(bars[:end], strategy) for strategy in STRATEGIES} == expected
    assert analyze(bars, 'missing')['reason'] == 'UNSUPPORTED_STRATEGY'


def test_fixture_reaches_every_direction_and_real_structure_branch():
    for strategy in STRATEGIES:
        assert {c['prefixes'][-1][strategy]['direction'] for c in FIXTURE['cases']} >= {'WAIT','CALL','PUT'}
    for case in FIXTURE['cases']:
        for signals in case['prefixes']:
            for strategy, result in signals.items():
                assert not result['confirmedReverse'] or strategy in ('confluence','divergence')
                assert not result['confirmedReverse'] or result['reason'] == 'DIVERGENCE_AND_STRUCTURE_BREAK'
    assert not greater(100 + 1e-8, 100)
    assert greater(100 + 1e-6, 100)


def query():
    return {'account':'mp-fixture','symbol':'NVDA','source':'fixture','capturedAt':'2026-10-13T15:30:00.000Z',
            'bars':deepcopy(FIXTURE['cases'][0]['bars']), 'cursor':40}


def test_comparison_uses_prefix_and_does_not_invent_history_or_modify_input():
    value = query(); original = deepcopy(value)
    first = compare_strategies(value)
    assert value == original
    assert first['status'] == 'COMPARED'
    assert first['prefixCount'] == 41
    assert first['signals'] == FIXTURE['cases'][0]['prefixes'][40]
    assert not first['executionAllowed'] and not first['externalOrder']
    assert not first['historicalAvailabilityVerified'] and first['pnlCents'] is None
    # Later observed candles cannot influence a selected earlier cursor.
    value['bars'][-1].update(o=1000, h=1001, l=999, c=1000)
    assert compare_strategies(value) == first
    value['cursor'] = 0
    assert all(s['direction'] == 'WAIT' for s in compare_strategies(value)['signals'].values())


@pytest.mark.parametrize('mutation', [
    lambda q:q.update(cursor=True), lambda q:q.update(cursor=-1), lambda q:q.update(cursor=1000),
    lambda q:q.update(bars=[]), lambda q:q.update(bars=q['bars']*30), lambda q:q.update(source='indicative'),
    lambda q:q.update(account=' '), lambda q:q.update(symbol='../NVDA'), lambda q:q.update(executionAllowed=True),
    lambda q:q.update(capturedAt='2026-10-13T14:00:00Z'), lambda q:q.update(capturedAt='2026-02-30T15:30:00Z'),
    lambda q:q['bars'][0].update(c=True), lambda q:q['bars'][0].update(c=1e300),
    lambda q:q['bars'][0].update(c=500), lambda q:q['bars'][0].update(v=-1),
    lambda q:q['bars'][0].update(at=q['bars'][1]['at']), lambda q:q['bars'][0].update(at='2026-10-13T14:00:00'),
    lambda q:q['bars'][0].update(at='2026-10-13T14:00:00.000001Z'), lambda q:q['bars'][0].update(assumed=True),
])
def test_invalid_source_has_no_signal_or_fill(mutation):
    value = query(); mutation(value)
    result = compare_strategies(value)
    assert result['status'] == 'INVALID_OBSERVED_SOURCE'
    assert 'signals' not in result and result['pnlCents'] is None and result['executionAllowed'] is False


def test_authenticated_comparison_is_read_only_without_network_or_execution(monkeypatch):
    from fastapi.testclient import TestClient
    from unittest.mock import Mock
    from app.main import create_app
    from app.repository import Repository
    from app.service import TradingService
    from test_alpaca_market_api import TOKEN, HEADERS
    repo = Repository(); provider = Mock(side_effect=AssertionError('No provider'))
    for method in ('submit','fill','settle_paper','record_option_mark'):
        monkeypatch.setattr(TradingService, method, Mock(side_effect=AssertionError('No execution')))
    try:
        with TestClient(create_app(repo, TOKEN, provider)) as client:
            before = list(repo.connection.iterdump())
            route = '/api/research/strategy-comparison'
            assert client.post(route, json=query()).status_code == 401
            response = client.post(route, headers=HEADERS, json=query())
            assert response.status_code == 200 and response.headers['cache-control'] == 'no-store'
            assert response.json() == {'provenance':'client_supplied_unverified','persisted':False,'result':compare_strategies(query())}
            assert client.post(route, headers=HEADERS, json={'oversize':'x'*131072}).status_code == 413
            assert list(repo.connection.iterdump()) == before and not provider.mock_calls
    finally:
        repo.close()
