import json
from pathlib import Path
import pytest
from app.option_greeks import provider_greeks, quality
from app.market_data import MarketDataError
from test_alpaca_market_data import adapter, chain

CASES=json.loads((Path(__file__).parents[2]/'mobile/test/fixtures/option_greeks_quality_v1.json').read_text())['cases']


@pytest.mark.parametrize('case',CASES,ids=lambda c:c['name'])
def test_shared_provider_value_contract(case):
    if not case['valid']:
        with pytest.raises(ValueError):provider_greeks(case['raw'],case['right'])
    else:
        values=provider_greeks(case['raw'],case['right']); report=quality(values)
        assert report['valuesStatus']==case['status']
        assert not report['freshnessVerified'] and not report['entryEligible']
        assert 'GREEKS_PROVIDER_TIME_UNAVAILABLE' in report['reasons']


@pytest.mark.parametrize('bad',[float('nan'),float('inf'),float('-inf'),10**400],ids=['nan','infinity','negative_infinity','oversized_integer'])
def test_nonfinite_provider_sensitivities_are_rejected(bad):
    with pytest.raises(ValueError):provider_greeks({'theta':bad},'C')


def test_adapter_rejects_wrong_call_sign_and_never_promotes_timestamp():
    provider,_,_=adapter(chain({'greeks':{'delta':-.5}}))
    with pytest.raises(MarketDataError,match='INVALID_PROVIDER_GREEKS'):provider.option_chain('AAPL')
    provider,_,_=adapter(chain({'greeks':{'delta':.5,'timestamp':'2026-10-12T15:00:00Z'}}))
    row=provider.option_chain('AAPL')['data']['contracts'][0]
    assert row['greeks_timestamp'] is None and row['greeks_quality']==quality(row['greeks'])
    assert not row['greeks_quality']['entryEligible']
