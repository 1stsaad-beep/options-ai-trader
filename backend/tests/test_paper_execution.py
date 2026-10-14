from copy import deepcopy
from datetime import datetime
from pathlib import Path
import json
import pytest
from app.paper_execution import project_execution
from app.observed_option_replay import replay_option

CASES=json.loads((Path(__file__).parents[2]/'mobile/test/fixtures/paper_execution_v2.json').read_text())['cases']
@pytest.mark.parametrize('c',CASES,ids=lambda c:c['name'])
def test_hand_expected_execution_contract(c):
    before=deepcopy(c)
    assert project_execution(c['quote'],c['side'],c['requested'],c['consumed'],datetime.fromisoformat(c['at']))==c['expected']
    assert c==before


def test_replay_prices_new_entry_at_actual_adverse_fill_and_rejects_policy_tampering():
    cases=json.loads((Path(__file__).parents[2]/'mobile/test/fixtures/observed_option_replay_v1.json').read_text())['cases']
    query=deepcopy(cases[0]['query']);entry=query['entry'];fill=entry['fill']
    original=replay_option(query)
    model=project_execution(entry['quote'],'BUY',fill['quantity'],0,datetime.fromisoformat(entry['at']))
    assert model['quantity']==fill['quantity']
    fill.update(execution=model,price=model['priceCents'],fee=model['feeCents'])
    updated=replay_option(query)
    assert updated['status']=='OBSERVED_COUNTERFACTUAL'
    assert updated['pnlCents']==original['pnlCents']-105*fill['quantity']
    query['entry']['fill']['execution']['policy']['adverseSlippageCents']=0
    assert replay_option(query)['status']=='INVALID_ORIGINAL_RECEIPT'
