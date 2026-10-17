"""Original v2 server transitions for conservative phone protection parity."""
from datetime import datetime, timedelta, timezone
from copy import deepcopy
from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from app.observed_paper import apply, create
from app.observed_option_replay import iso


def generate():
    at = datetime(2026, 10, 13, 15, 1, tzinfo=timezone.utc)
    rows = json.loads((ROOT / 'mobile/test/fixtures/market_strategy_v1.json').read_text())['cases'][2]['bars']
    cases = []
    for name, bid, add, quantity, partial in [
        ('stop_net_boundary', 171, False, 1, 0), ('above_stop', 172, False, 1, 0),
        ('gross_target_is_not_net_profit', 297, False, 1, 0), ('net_target', 299, False, 1, 0),
        ('gross_add_is_not_net_gain', 233, True, 1, 0), ('net_add', 235, True, 1, 0),
        ('below_net_partial', 254, False, 2, 20), ('net_partial', 256, False, 2, 20),
    ]:
        state = create('parity', 'Parity', 10000000, 'fixture', version='observed-paper-ledger-v2')
        contract = 'NVDA261023C00150000'
        config = state['config'] | {'quantity': quantity, 'holdingMode': 'swing', 'partialPercent': partial,
            'addEnabled': add, 'contracts': {'NVDA': {'CALL': contract}}}
        state, _ = apply(state, {'kind': 'CONFIGURE', 'config': config}, iso(at))
        state, _ = apply(state, {'kind': 'ENABLE', 'enabled': True}, iso(at))
        observations = []
        for offset, observed_bid, ask in [(0, 200, 210), (60, bid, bid + 10)]:
            now = at + timedelta(seconds=offset)
            bars = deepcopy(rows)
            for bar in bars:
                bar['at'] = iso(datetime.fromisoformat(bar['at']) + timedelta(minutes=1, seconds=offset))
            observation = {'source': 'fixture', 'capturedAt': iso(now), 'stockFeed': 'iex', 'bars': {'NVDA': bars},
                'quotes': [{'contract': contract, 'feed': 'opra', 'at': iso(now), 'bid': observed_bid, 'ask': ask, 'bidSize': 40, 'askSize': 40}]}
            state, facts = apply(state, {'kind': 'CYCLE', 'observation': observation}, iso(now))
            observations.append(observation)
        position = state['positions'].get('NVDA')
        cases.append({'name': name, 'config': config, 'observations': observations,
            'expected': {'cash': state['cash'], 'fees': state['fees'],
                'quantity': position['quantity'] if position else 0, 'basis': position['cost'] if position else 0,
                'fillSides': [f['side'] for f in facts['fills']],
                'fillQuantities': [f['execution']['quantity'] for f in facts['fills']]}})
    return {'contract': 'net-liquidation-protection-parity-v1', 'source': 'synthetic_fixture',
            'serverLedger': 'observed-paper-ledger-v2', 'cases': cases}


if __name__ == '__main__':
    (ROOT / 'mobile/test/fixtures/net_protection_v1.json').write_text(json.dumps(generate(), indent=2) + '\n')
