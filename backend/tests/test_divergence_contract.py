from datetime import datetime
import importlib.util
import json
from pathlib import Path

import pytest

from app.engines import Bar
from app.intelligence.divergence import DIVERGENCE_CONTRACT_VERSION, divergences

ROOT=Path(__file__).parents[2]
spec=importlib.util.spec_from_file_location('divergence_authoring',ROOT/'scripts/generate_divergence_parity_fixture.py')
helpers=importlib.util.module_from_spec(spec);spec.loader.exec_module(helpers)
FIXTURE=json.loads((ROOT/'mobile/test/fixtures/divergence_contract_v1.json').read_text())


@pytest.mark.parametrize('case',FIXTURE['cases'],ids=lambda c:c['name'])
def test_checked_in_confirmed_divergence_contract(case):
    assert FIXTURE['contract']==DIVERGENCE_CONTRACT_VERSION
    actual=helpers.portable(divergences(helpers.points(case['points']),case['oscillator'],name=case['indicator']))
    assert actual==case['expected']


@pytest.mark.parametrize('case',FIXTURE['bars'],ids=lambda c:c['name'])
def test_completed_bar_sources_preserve_every_confirmed_prefix(case):
    bars=[Bar(datetime.fromisoformat(b['at']),b['o'],b['h'],b['l'],b['c'],b['v']) for b in case['bars']]
    assert helpers.from_bars(bars)==case['expected']
    for end in range(1,len(bars)+1):
        assert helpers.from_bars(bars[:end])==[d for d in case['expected'] if d['to'][1]<end]


def test_fixture_checks_all_four_labels_epsilon_distance_and_all_pairs():
    assert {d['kind'] for c in FIXTURE['cases'] for d in c['expected']}=={
        'REGULAR_BULLISH','HIDDEN_BULLISH','REGULAR_BEARISH','HIDDEN_BEARISH'}
    cases={c['name']:c for c in FIXTURE['cases']}
    assert not cases['distance:2']['expected'] and not cases['distance:61']['expected']
    assert cases['distance:3']['expected'] and cases['distance:60']['expected']
    all_pairs=cases['all-adjacent-same-kind-pairs']['expected']
    assert [d['to'][0] for d in all_pairs]==[13,23,18]
