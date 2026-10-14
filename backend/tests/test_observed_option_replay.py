import copy
import json
from pathlib import Path

import pytest
from app.observed_option_replay import replay_option

FIXTURES = json.loads((Path(__file__).parents[2] / 'mobile/test/fixtures/observed_option_replay_v1.json').read_text())['cases']


@pytest.mark.parametrize('case', FIXTURES, ids=lambda c:c['name'])
def test_shared_observed_option_contract(case):
    before = copy.deepcopy(case['query'])
    assert replay_option(case['query']) == case['expected']
    assert case['query'] == before


def test_future_extension_never_rewrites_known_horizon():
    q = copy.deepcopy(FIXTURES[0]['query'])
    original = replay_option(q)
    later = copy.deepcopy(q['observations'][0])
    later['capturedAt'] = later['quote']['at'] = '2026-10-13T15:07:00.000Z'
    later['quote'].update(bid=1000, ask=1100)
    q['observations'].append(later)
    assert replay_option(q) == original


def test_invalid_non_objects_and_explicit_nulls_are_classified():
    assert replay_option(None)['status'] == 'INVALID_QUERY'
    for field in ('horizonSeconds', 'slippageCents', 'feePerContractCents'):
        q = copy.deepcopy(FIXTURES[0]['query']); q[field] = None
        assert replay_option(q)['status'] == 'INVALID_QUERY'


def test_latest_known_quote_wins_without_future_peeking():
    q = copy.deepcopy(FIXTURES[0]['query'])
    old = copy.deepcopy(q['observations'][0])
    old['capturedAt'] = old['quote']['at'] = '2026-10-13T15:05:40.000Z'
    old['quote'].update(bid=1000, ask=1100)
    q['observations'].insert(0, old)
    assert replay_option(q)['pnlCents'] == 7740


def test_authenticated_portable_replay_never_reads_provider_or_writes_ledger(monkeypatch):
    from fastapi.testclient import TestClient
    from unittest.mock import Mock
    from app.main import create_app
    from app.repository import Repository
    from app.service import TradingService
    from test_alpaca_market_api import TOKEN, HEADERS
    repo = Repository()
    provider = Mock(side_effect=AssertionError('No provider access'))
    for method in ('submit', 'fill', 'settle_paper', 'record_option_mark'):
        monkeypatch.setattr(TradingService, method, Mock(side_effect=AssertionError('No execution')))
    try:
        with TestClient(create_app(repo, TOKEN, provider)) as client:
            before = list(repo.connection.iterdump())
            path = '/api/research/observed-option-replay'
            assert client.post(path, json=FIXTURES[0]['query']).status_code == 401
            response = client.post(path, headers=HEADERS, json=FIXTURES[0]['query'])
            assert response.status_code == 200
            assert response.json() == {'provenance':'client_supplied_unverified',
                                      'persisted':False, 'result':FIXTURES[0]['expected']}
            assert response.headers['cache-control'] == 'no-store'
            invalid = client.post(path, headers=HEADERS, json={'executionAllowed':True})
            assert invalid.json()['result']['status'] == 'INVALID_QUERY'
            assert client.post(path, headers=HEADERS, json={'oversize':'x'*131072}).status_code == 413
            assert list(repo.connection.iterdump()) == before
            assert not provider.mock_calls
    finally:
        repo.close()
