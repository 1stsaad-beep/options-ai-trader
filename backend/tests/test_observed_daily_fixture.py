import json
from pathlib import Path
import sys


def test_phone_daily_fixture_reproduces_actual_verified_sql_reports():
    root = Path(__file__).parents[2]
    sys.path.insert(0, str(root/'scripts'))
    from generate_observed_daily_fixture import generate
    result = generate()
    assert result == json.loads((root/'mobile/test/fixtures/observed_daily_v1.json').read_text())
    cases = {c['name']: c['report'] for c in result['cases']}
    assert cases['complete']['performance']['sharpe'] is not None
    assert cases['gap']['performance']['sharpe'] is None
    assert cases['liquidity']['performance']['sharpe'] is None
