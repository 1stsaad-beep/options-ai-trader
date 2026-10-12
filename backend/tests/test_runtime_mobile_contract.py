"""Cache-only phone contract, prices, pagination and old immutable events."""
from datetime import timedelta
import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from app import market_runtime as rt, market_data_journal as journal
from app.main import create_app
from app.market_data import DisabledMarketData
from test_market_runtime import setup, enable, collect_cycle  # noqa: F401
from test_alpaca_market_api import TOKEN, HEADERS


def test_status_prices_use_original_timestamps_and_current_staleness(setup):
    c, wire, clock = setup
    a = enable(c.service)
    collect_cycle(c)
    before = len(wire.calls)
    first = rt.status(c.service, a)
    price = next(i for i in first['latest'] if i['kind'] == 'stock_snapshot')
    assert price['price'] == 130 and price['market_time'] == clock.now().isoformat()
    assert price['feed'] == 'iex' and len(price['sha256']) == 64
    clock.advance(90)
    second = next(i for i in rt.status(c.service, a)['latest'] if i['kind'] == 'stock_snapshot')
    assert second['price'] == price['price'] and second['market_time'] == price['market_time']
    assert second['state_now'] == 'STALE_OR_FUTURE_DATA'
    assert len(wire.calls) == before


def test_event_pagination_covers_equal_timestamps_and_binds_account(setup):
    c, _, clock = setup
    a, b = enable(c.service), enable(c.service, 'B')
    with c.repo.transaction() as db:
        for n in range(125):
            rt.event_in(db, a, 'paging:'+str(n), clock.now(), 'TEST_EVENT', {'n': n})
    seen, cursor = [], None
    while True:
        page = rt.events(c.service, a, limit=17, before=cursor)
        seen += [r['id'] for r in page['items']]
        cursor = page['next_before']
        if not cursor:
            break
        with pytest.raises(journal.JournalError, match='CURSOR'):
            rt.events(c.service, b, before=cursor)
    assert len(seen) == len(set(seen)) == 126


@pytest.mark.parametrize('cursor', ['garbage', 'A'*1025, 'e30=', 'bnVsbA=='])
def test_malformed_cursor_is_safe_422(setup, cursor):
    c, _, _ = setup
    a = enable(c.service)
    with pytest.raises(journal.JournalError):
        rt.events(c.service, a, before=cursor)


def test_runtime_read_and_control_http_never_queries_provider_or_demo(setup):
    c, wire, clock = setup
    a, b = enable(c.service), enable(c.service, 'B')
    collect_cycle(c)
    calls = len(wire.calls)
    with TestClient(create_app(c.repo, TOKEN, DisabledMarketData())) as client:
        client.app.state.service.now = clock.now
        prefix = f'/api/accounts/{a}/market-runtime'
        status = client.get(prefix+'/status', headers=HEADERS).json()
        assert status['server_time'] and status['archive']['segments'] == 1
        response = client.put(prefix+'/config', headers=HEADERS, json={'expected_version': 1,
            'enabled': False,'strategies': {'breakout': False, 'pullback': False}})
        assert response.json()['account_id'] == a
        assert rt.status(c.service, b)['config']['enabled']
        event = client.get(prefix+'/events?limit=1', headers=HEADERS).json()
        assert event['next_before']
        ack = client.post(prefix+'/events/'+event['items'][0]['id']+'/ack', headers=HEADERS).json()
        assert ack['account_id'] == a and ack['acknowledged']
    assert len(wire.calls) == calls and c.service.rows(a, 'orders') == []


def test_saved_flutter_fixture_is_real_backend_shape():
    raw = json.loads((Path(__file__).resolve().parents[2]/'mobile/test/fixtures/market_runtime_v1.json').read_text())
    assert raw['fixture_source'] == 'offline_runtime_mock_no_account_connection'
    for key in ('status', 'events', 'second_status', 'second_events'):
        value = raw[key]
        assert all(value[k] == v for k,v in rt.AUTHORITY.items())
        assert value['account_id'] == ('account-two' if key.startswith('second') else 'account-one')
    for item in raw['events']['items']:
        original = {k:v for k,v in item.items() if k not in ('sha256','acknowledged_at')}
        from hashlib import sha256
        assert sha256(journal.canonical(original).encode()).hexdigest() == item['sha256']
