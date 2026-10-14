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
