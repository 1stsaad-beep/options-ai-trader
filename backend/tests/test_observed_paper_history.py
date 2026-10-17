from copy import deepcopy
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.observed_paper_store import ObservedPaperStore, LedgerConflict
from test_observed_paper import stored, observation
from test_observed_paper_valuation import opened
from test_alpaca_market_api import TOKEN, HEADERS


def test_original_event_values_are_causal_and_stable_after_later_prices(tmp_path):
    repo, store, clock = opened(tmp_path)
    initial = store.valuation_history('a')
    point = initial['points'][-1]
    assert point['liquidationEquityCents'] == 997480
    assert point['prefix'] == {'eventSamples':4, 'incompleteSamples':0, 'complete':True,
        'maximumSampledDrawdownCents':2520}
    assert point['totalPnlCents'] == -2520 and point['feesCents'] == 210
    assert initial['throughEventHash'] == point['eventHash'] and initial['sharpe'] is None
    store.command('a','later',{'kind':'CYCLE','observation':observation(clock.step(),bid=70,ask=74)},
        expected_version=3,lease=store.acquire('valuation'))
    # A later stop must not leak into the earlier point or its drawdown prefix.
    assert store.valuation_history('a',through=3) == initial
    after = store.valuation_history('a')
    assert after['points'][:4] == initial['points']
    assert after['points'][-1]['status'] == 'CASH_ONLY'
    assert after['points'][-1]['liquidationEquityCents'] == store.snapshot('a')['state']['cash']
    assert after['points'][-1]['prefix']['maximumSampledDrawdownCents'] == 11520
    assert not after['hasMore'] and not after['executionAllowed']
    repo.close()


def test_stale_gap_is_not_interpolated_and_never_erased_by_new_cash_sample(tmp_path):
    repo, store, clock = opened(tmp_path)
    clock.step(31)
    store.command('a','stop',{'kind':'ENABLE','enabled':False})
    store.command('a','close',{'kind':'REQUEST_CLOSE','symbol':'NVDA'})
    store.command('a','finish',{'kind':'CYCLE','observation':observation(clock.step(),bid=110,ask=115,bars=False)},
        expected_version=5,lease=store.acquire('valuation'))
    points = store.valuation_history('a')['points']
    assert points[4]['liquidationEquityCents'] is None
    assert points[4]['incompleteReasons'] == ['QUALIFIED_ORIGINAL_QUOTE_UNAVAILABLE']
    assert points[-1]['complete'] and points[-1]['status'] == 'CASH_ONLY'
    assert points[-1]['prefix'] == {'complete':False, 'eventSamples':7, 'incompleteSamples':2,
        'maximumSampledDrawdownCents':None}
    repo.close()


def test_liquidity_gap_and_partial_close_authority_match_current_valuation(tmp_path):
    repo, store, clock = opened(tmp_path,size=12)
    assert store.valuation_history('a')['points'][-1]['incompleteReasons'] == ['INSUFFICIENT_REMAINING_LIQUIDITY']
    store.command('a','close',{'kind':'REQUEST_CLOSE','symbol':'NVDA'})
    store.command('a','stop',{'kind':'ENABLE','enabled':False})
    store.command('a','partial',{'kind':'CYCLE','observation':observation(clock.step(),bid=110,ask=115,size=4)},
        expected_version=5,lease=store.acquire('valuation'))
    last = store.valuation_history('a')['points'][-1]; current = store.valuation('a')
    for key in ('status','complete','cashCents','ownedBasisCents','liquidationEquityCents','unrealizedPnlCents','totalPnlCents'):
        assert last[key] == current[key]
    assert last['ownedBasisCents'] == 21340 and last['liquidationEquityCents'] is None
    repo.close()


def test_pagination_anchors_immutable_end_with_equal_timestamps_and_restart(tmp_path):
    repo, store, clock = opened(tmp_path)
    expected = store.valuation_history('a'); first = store.valuation_history('a',limit=2)
    store.command('a','stop',{'kind':'ENABLE','enabled':False})
    second = ObservedPaperStore(repo,clock).valuation_history('a',after=first['nextAfter'],limit=2,through=first['throughVersion'])
    assert first['points']+second['points'] == expected['points']
    assert first['hasMore'] and not second['hasMore']
    assert second['throughEventHash'] == first['throughEventHash']
    assert store.valuation_history('a',after=3,through=3)['points'] == []
    repo.close()


@pytest.mark.parametrize('kwargs',[{'after':True},{'after':-2},{'limit':0},{'limit':101},{'limit':False},
    {'through':False},{'through':-1},{'through':99},{'after':99}])
def test_cursor_limits(tmp_path,kwargs):
    repo, store, _ = stored(tmp_path)
    with pytest.raises(ValueError): store.valuation_history('a',**kwargs)
    repo.close()


def test_warm_cache_does_not_hide_corrupted_financial_state(tmp_path):
    repo, store, _ = opened(tmp_path)
    before = deepcopy(store.snapshot('a'))
    with repo.transaction() as db:
        db.execute('UPDATE observed_paper_accounts SET version=version+1 WHERE id=?',('a',))
    with pytest.raises(LedgerConflict): store.valuation_history('a')
    with repo.transaction() as db:
        db.execute('UPDATE observed_paper_accounts SET version=? WHERE id=?',(before['version'],'a'))
    assert store.snapshot('a',full=True) == before
    repo.close()


def test_history_route_auth_read_only_and_bounds(tmp_path):
    repo, store, _ = opened(tmp_path); before = store.snapshot('a',full=True)
    with TestClient(create_app(repo,TOKEN)) as client:
        path='/api/observed-paper/accounts/a/valuation-history'
        assert client.get(path).status_code == 401
        result=client.get(path+'?limit=2',headers=HEADERS)
        assert result.status_code == 200 and len(result.json()['points']) == 2
        assert client.get(path+'?limit=101',headers=HEADERS).status_code == 422
        assert client.get(path+'?through=99',headers=HEADERS).status_code == 422
        assert client.get(path.replace('/a/','/missing/'),headers=HEADERS).status_code == 409
        assert store.snapshot('a',full=True) == before


def test_saved_history_fixture_is_actual_sql_replay():
    import json
    import sys
    from pathlib import Path
    root=Path(__file__).parents[2]
    sys.path.insert(0,str(root/'scripts'))
    from generate_observed_history_fixture import generate
    assert generate()==json.loads((root/'mobile/test/fixtures/observed_history_v1.json').read_text())
