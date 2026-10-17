from copy import deepcopy
from datetime import timedelta
import json
import pytest

from app.observed_paper_valuation import summarize
from test_observed_paper import stored, observation


def opened(tmp_path, size=40):
    repo, store, clock = stored(tmp_path)
    lease = store.acquire('valuation')
    store.command('a', 'open', {'kind': 'CYCLE', 'observation': observation(size=size)}, expected_version=2, lease=lease)
    return repo, store, clock


def test_current_model_uses_original_quote_both_fee_sides_and_leaves_ledger_unchanged(tmp_path):
    repo, store, clock = opened(tmp_path)
    before = store.snapshot('a', full=True)
    report = store.valuation('a')
    assert report['status'] == 'OBSERVED_MODEL' and report['complete']
    assert report['ownedBasisCents'] == 32010  # (106 * 100 + 70) * 3
    assert report['options'][0]['valueCents'] == 29490  # (99 * 100 - 70) * 3
    assert report['unrealizedPnlCents'] == -2520 and report['liquidationEquityCents'] == 997480
    assert report['totalPnlCents'] == -2520 and not report['executionAllowed']
    assert (report['version'], report['eventHash']) == (before['version'], before['eventHash'])
    assert store.snapshot('a', full=True) == before
    assert store.valuation('a') == report  # valuation consumes no liquidity
    clock.step(31)
    stale = store.valuation('a')
    assert stale['status'] == 'INCOMPLETE' and stale['liquidationEquityCents'] is None
    assert stale['options'][0]['quote'] is None and stale['unrealizedPnlCents'] is None
    repo.close()


@pytest.mark.parametrize('size,remaining', [(12,0),(16,1)])
def test_used_displayed_size_cannot_be_reused_as_full_liquidation(tmp_path,size,remaining):
    repo, store, _ = opened(tmp_path, size=size)
    report = store.valuation('a')
    assert report['options'][0]['quantity'] == 3
    assert report['options'][0]['modeledAvailableQuantity'] == remaining
    assert report['options'][0]['status'] == 'INSUFFICIENT_REMAINING_LIQUIDITY'
    assert report['liquidationEquityCents'] is None and report['options'][0]['valueCents'] is None
    repo.close()


def test_stopped_partial_close_uses_newer_fill_authority_not_old_liquidity(tmp_path):
    repo, store, clock = opened(tmp_path)
    store.command('a', 'close', {'kind':'REQUEST_CLOSE', 'symbol':'NVDA'})
    store.command('a', 'stop', {'kind':'ENABLE', 'enabled':False})
    obs = observation(clock.step(), bid=110, ask=115, size=4)
    store.command('a', 'partial', {'kind':'CYCLE', 'observation':obs}, expected_version=5, lease=store.acquire('valuation'))
    report = store.valuation('a'); leg = report['options'][0]
    assert leg['quantity'] == 2 and leg['quote'] == obs['quotes'][0]
    assert leg['modeledAvailableQuantity'] == 0 and not report['complete']
    repo.close()


def test_freshness_exact_microsecond_boundary(tmp_path):
    repo, store, clock = opened(tmp_path)
    clock.step(30)
    assert store.valuation('a')['complete']
    clock.value += timedelta(microseconds=1)
    assert not store.valuation('a')['complete']
    repo.close()


@pytest.mark.parametrize('changed', ['source', 'identity', 'future_capture', 'indicative', 'future_quote', 'expired_session'])
def test_no_mismatched_future_or_non_opra_valuation(tmp_path, changed):
    repo, store, clock = opened(tmp_path)
    state = store.snapshot('a')['state']
    with repo.transaction() as db:
        rows = [dict(r) for r in db.stream('SELECT payload FROM observed_paper_events WHERE account_id=? ORDER BY sequence DESC', ('a',))]
    command = json.loads(rows[0]['payload']); obs = command['command']['observation']
    if changed == 'source': obs['source'] = 'alpaca'
    if changed == 'identity': obs['quotes'][0]['bid'] += 1
    if changed == 'future_capture': obs['capturedAt'] = '2026-10-13T15:01:00Z'
    if changed == 'indicative': obs['quotes'][0]['feed'] = 'indicative'
    if changed == 'future_quote': obs['quotes'][0]['at'] = '2026-10-13T15:01:00Z'
    if changed == 'expired_session': clock.step(6*3600)
    rows[0]['payload'] = json.dumps(command)
    report = summarize(iter(rows), state, clock())
    assert report['status'] == 'INCOMPLETE' and report['liquidationEquityCents'] is None
    repo.close()


def test_cash_only_needs_no_quotes_but_future_state_is_rejected(tmp_path):
    repo, store, clock = stored(tmp_path)
    report = store.valuation('a')
    assert report['status'] == 'CASH_ONLY' and report['liquidationEquityCents'] == 1000000
    assert report['totalPnlCents'] == report['unrealizedPnlCents'] == 0
    clock.value -= timedelta(seconds=1)
    with pytest.raises(ValueError, match='clock'): store.valuation('a')
    repo.close()


def test_unpriced_delivery_never_uses_option_quote_or_cost_basis_as_stock_price(tmp_path):
    repo, store, clock = opened(tmp_path)
    state = deepcopy(store.snapshot('a')['state'])
    state['deliveries'] = {'NVDA': {'quantity': 100, 'cost': 1500000}}
    state['positions'] = {}; state['cash'] = 100
    report = summarize(iter(()), state, clock())
    assert report['status'] == 'INCOMPLETE' and report['liquidationEquityCents'] is None
    assert report['deliveries'][0]['valueCents'] is None
    repo.close()


def test_api_authentication_read_only_and_no_public_quote_injection(tmp_path):
    from fastapi.testclient import TestClient
    from app.main import create_app
    from test_alpaca_market_api import TOKEN, HEADERS
    repo, store, _ = opened(tmp_path)
    with TestClient(create_app(repo, TOKEN)) as client:
        path = '/api/observed-paper/accounts/a/valuation'
        assert client.get(path).status_code == 401
        result = client.get(path, headers=HEADERS).json()
        assert result['account'] == 'a' and result['source'] == 'fixture'
        assert result['liquidationEquityCents'] is None  # real server clock is later than fixture
        assert client.post(path, headers=HEADERS, json={'quote': observation()['quotes'][0]}).status_code == 405
        assert client.get('/api/observed-paper/accounts/missing/valuation', headers=HEADERS).status_code == 409
    assert store.snapshot('a', full=True)['version'] == 3
    repo.close()


def test_saved_phone_fixture_reproduces_original_sql_values():
    import sys
    from pathlib import Path
    root = Path(__file__).parents[2]; sys.path.insert(0, str(root/'scripts'))
    from generate_observed_valuation_fixture import generate
    assert generate() == json.loads((root/'mobile/test/fixtures/observed_valuation_v1.json').read_text())
