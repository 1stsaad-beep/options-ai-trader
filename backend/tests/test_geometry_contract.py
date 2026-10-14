from datetime import datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path

from app.engines import Bar
from app.intelligence.harmonics import GEOMETRY_CONTRACT_VERSION
from app.intelligence.pivots import Pivot, confirmed_pivots

ROOT=Path(__file__).parents[2]
spec=importlib.util.spec_from_file_location('geometry_authoring',ROOT/'scripts/generate_geometry_parity_fixture.py')
helpers=importlib.util.module_from_spec(spec);spec.loader.exec_module(helpers)


def test_checked_in_geometry_matches_server_detector_without_regeneration():
    fixture=json.loads((ROOT/'mobile/test/fixtures/geometry_contract_v1.json').read_text())
    assert fixture['contract']==GEOMETRY_CONTRACT_VERSION
    start=datetime(2026,10,13,14,tzinfo=timezone.utc)
    for group in ('harmonics','classical'):
        for case in fixture[group]:
            ps=[Pivot(i,price,'HIGH' if high else 'LOW',start+timedelta(minutes=i),
                start+timedelta(minutes=at),at) for i,at,price,high in case['points']]
            actual=(helpers.portable_harmonics(ps) if group=='harmonics' else helpers.portable_classic(ps,case['close']))
            assert actual==case['expected'],case['name']
    for case in fixture['bars']:
        bars=[Bar(datetime.fromisoformat(b['at']),b['o'],b['h'],b['l'],b['c'],b['v']) for b in case['bars']]
        assert helpers.portable_points(confirmed_pivots(bars,left=3,right=3))==case['expected']


def test_fixture_contains_all_named_mirrors_and_butterfly_extension():
    fixture=json.loads((ROOT/'mobile/test/fixtures/geometry_contract_v1.json').read_text())
    for name in ('GARTLEY','BAT','BUTTERFLY','CRAB','CYPHER','BUTTERFLY_EXTENSION_RANGE'):
        for direction in ('BULLISH','BEARISH'):
            c=next(c for c in fixture['harmonics'] if c['name']==name+'_'+direction)
            assert any(h['kind']==name.replace('_EXTENSION_RANGE','') and h['direction']==direction for h in c['expected'])
