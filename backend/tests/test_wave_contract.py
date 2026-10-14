"""Stored cross-runtime wave geometry/causality with independent hand assertions."""
import importlib.util
import json
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('wave_fixture',ROOT/'scripts/generate_wave_parity_fixture.py')
fixture=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixture)
DATA=json.loads((ROOT/'mobile/test/fixtures/wave_contract_v1.json').read_text())

@pytest.mark.parametrize('case',DATA['cases'],ids=lambda c:c['name'])
def test_stored_wave_events_match_every_original_prefix(case):
    assert fixture.trace(case['bars'])==case['steps']

def test_hand_expected_confirmation_invalidation_and_no_plateau_pivot():
    by_name={c['name']:c for c in DATA['cases']}
    events=[e for step in by_name['bullish_invalidation']['steps'] for e in step['events']]
    third=next(e for e in events if e['event']=='DETECTED' and e['scenario']['kind']=='third' and e['scenario']['degree']=='main' and e['scenario']['points'][0][0]==4)
    assert third['tick']==37 and third['scenario']['observed_at']==37
    assert [p[0] for p in third['scenario']['points']]==[4,14,24,34]
    assert any(e['event']=='INVALIDATED' and e['scenario']==third['scenario'] for e in events)
    assert not any(step['events'] for step in by_name['flat_no_pivot']['steps'])
    nested=[e for step in by_name['nested_parent_confirmation']['steps'] for e in step['events'] if e['scenario']['kind']=='third_of_third']
    assert nested and all(e['tick']>=max(p[1] for p in e['scenario']['parentPoints']) for e in nested)
    for name,index in [('equal_extrema_rejected',14),('outside_bar_unordered',24)]:
        assert not any(p[0]==index for step in by_name[name]['steps'] for e in step['events'] for p in e['scenario']['points'])
