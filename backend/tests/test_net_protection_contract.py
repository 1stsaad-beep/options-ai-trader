import json
from pathlib import Path
import sys

ROOT = Path(__file__).parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
from generate_net_protection_fixture import generate


def test_original_server_v2_receipts_reproduce_mobile_net_protection_cases():
    result = generate()
    assert result == json.loads((ROOT / 'mobile/test/fixtures/net_protection_v1.json').read_text())
    cases = {c['name']: c['expected'] for c in result['cases']}
    assert cases['stop_net_boundary']['cash'] == 9995760
    assert cases['above_stop']['quantity'] == 1
    assert cases['gross_target_is_not_net_profit']['quantity'] == 1
    assert cases['net_target']['cash'] == 10008560
    assert cases['gross_add_is_not_net_gain']['quantity'] == 1
    assert cases['net_add']['quantity'] == 2
    assert cases['below_net_partial']['quantity'] == 2
    assert cases['net_partial']['quantity'] == 1
