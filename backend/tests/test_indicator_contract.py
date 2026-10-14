from datetime import datetime
import json
from pathlib import Path

from app.engines import Bar
from app.intelligence.indicators import INDICATOR_CONTRACT_VERSION, indicator_series


def test_shared_indicator_fixture_matches_original_server_contract():
    fixture=json.loads((Path(__file__).parents[2]/'mobile/test/fixtures/indicator_contract_v1.json').read_text())
    assert fixture['contract']==INDICATOR_CONTRACT_VERSION
    for case in fixture['cases']:
        bars=[Bar(datetime.fromisoformat(b['at']),b['o'],b['h'],b['l'],b['c'],b['v']) for b in case['bars']]
        assert indicator_series(bars)==case['expected']
