"""Offline contract/transport tests; no user keys or financial network access."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from unittest.mock import Mock, patch
import pytest
from app.market_data import (AlpacaBasicData, AlpacaDataTransport, DataCredentials,
    DataResponse, DisabledMarketData, MarketDataError, from_environment, timestamp)

NOW = datetime(2026, 10, 12, 15, 0, tzinfo=timezone.utc)
CONTRACT = 'AAPL261016C00200000'


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('Unexpected network access in isolated market-data tests')
    monkeypatch.setattr('socket.create_connection', forbidden)


class Clock:
    def __init__(self):
        self.elapsed = 0
    def now(self):
        return NOW + timedelta(seconds=self.elapsed)
    def mono(self):
        return self.elapsed
    def advance(self, seconds):
        self.elapsed += seconds


class Responses:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []
    def get(self, path, params):
        self.calls.append((path, deepcopy(params)))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def ok(body, headers=None):
    return DataResponse(200, headers or {}, body)


def adapter(*responses, **kwargs):
    clock, transport = Clock(), Responses(*responses)
    client = AlpacaBasicData(transport, now=clock.now, monotonic=clock.mono, sleep=clock.advance, **kwargs)
    return client, transport, clock


def quote(**changes):
    return dict(t=NOW.isoformat(), bp=199.8, ap=200.1, bs=10, **{'as': 12}) | changes


def trade(**changes):
    return dict(t=NOW.isoformat(), p=200, s=20) | changes


def stock_responses(q=None, t=None):
    return ok({'quotes': {'AAPL': quote() if q is None else q}}), ok({'trades': {'AAPL': trade() if t is None else t}})


def chain(raw=None, contract=CONTRACT, token=None):
    return ok({'snapshots': {contract: raw if raw is not None else {'latestQuote': quote(), 'latestTrade': trade(t=(NOW-timedelta(minutes=15)).isoformat())}}, 'next_page_token': token})


def bar(at='2026-10-12T14:00:00Z', **changes):
    return dict(t=at, o=100, h=102, l=99, c=101, v=20) | changes


def test_disabled_default_and_does_not_discover_other_app_credentials(monkeypatch):
    monkeypatch.delenv('OAT_ALPACA_DATA_APPROVAL', raising=False)
    monkeypatch.setenv('APCA_API_KEY_ID', 'other-app-value-not-to-use')
    monkeypatch.setenv('APCA_API_SECRET_KEY', 'other-app-value-not-to-use')
    provider = from_environment()
    assert isinstance(provider, DisabledMarketData)
    assert provider.status()['connection_enabled'] is False
    for method, args in [('stock_snapshot', ('AAPL',)), ('option_chain', ('AAPL',)),
                         ('stock_bars', ('AAPL', NOW, NOW, '1Day')),
                         ('option_bars', (CONTRACT, NOW, NOW, '1Day'))]:
        with pytest.raises(MarketDataError, match='DATA_CONNECTION_NOT_APPROVED'):
            getattr(provider, method)(*args)


def test_configured_transport_remains_offline_and_has_no_order_capability(monkeypatch):
    monkeypatch.setenv('OAT_ALPACA_DATA_APPROVAL', 'read_only_approved')
    monkeypatch.setenv('OAT_ALPACA_DATA_KEY_ID', 'unit-test-key')
    monkeypatch.setenv('OAT_ALPACA_DATA_SECRET_KEY', 'unit-test-secret')
    provider = from_environment()
    assert provider.status()['requests'] == 0
    assert provider.status()['external_orders_enabled'] is False
    assert provider.status()['stream_subscriptions'] == 0
    for method in ('submit', 'order', 'cancel', 'buy', 'sell', 'connect_ibkr'):
        assert not hasattr(provider, method)
        assert not hasattr(provider._transport, method)
    assert 'unit-test' not in repr(provider._transport._credentials)


@pytest.mark.parametrize('path', ['/v2/orders', '/v2/account', '/v2/options/contracts',
    'https://paper-api.alpaca.markets/v2/orders', '//api.alpaca.markets/v2/orders',
    '/v1beta1/options/snapshots/../orders', '/v2/stocks/quotes/latest?feed=sip'])
def test_trading_and_injected_routes_rejected_before_network(path):
    transport = AlpacaDataTransport(DataCredentials('test-id', 'test-secret'))
    with pytest.raises(MarketDataError, match='DATA_ROUTE_FORBIDDEN'):
        transport.get(path, {})


def test_transport_get_fixed_host_tls_no_redirect_and_no_provider_body_disclosure():
    response = Mock(status=302)
    response.getheaders.return_value = [('Location', 'https://api.alpaca.markets/v2/orders')]
    connection = Mock()
    connection.getresponse.return_value = response
    with patch('app.market_data.http.client.HTTPSConnection', return_value=connection) as create:
        client = AlpacaDataTransport(DataCredentials('test-id', 'test-secret'))
        result = client.get('/v2/stocks/quotes/latest', {'feed': 'iex', 'symbols': 'AAPL'})
    assert create.call_args.args == ('data.alpaca.markets', 443)
    assert create.call_args.kwargs['context'].check_hostname
    assert connection.request.call_args.args[0] == 'GET'
    assert result.body == {} and result.headers == {} and result.status == 302
    response.read.assert_not_called()
    connection.close.assert_called_once()


@pytest.mark.parametrize('body', [b'{"data":NaN}', b'[]', b'invalid', b'x'*(4*1024*1024+1)], ids=['nan', 'array', 'invalid-json', 'oversized'])
def test_invalid_or_oversized_json_rejected(body):
    response = Mock(status=200)
    response.getheaders.return_value = []
    response.read.return_value = body
    connection = Mock(); connection.getresponse.return_value = response
    with patch('app.market_data.http.client.HTTPSConnection', return_value=connection):
        with pytest.raises(MarketDataError):
            AlpacaDataTransport(DataCredentials('x', 'y')).get('/v2/stocks/quotes/latest', {'feed': 'iex'})
    connection.close.assert_called_once()


def test_current_iex_price_provenance_and_shared_cache_cannot_be_mutated():
    client, transport, clock = adapter(*stock_responses())
    first = client.stock_snapshot('AAPL')
    assert first['data']['price'] == 200
    assert first['feed'] == 'iex' and first['nominal_delay_seconds'] == 0
    assert not first['virtual_fills_enabled'] and not first['cached']
    first['data']['quote']['bp'] = 1
    clock.advance(10)
    second = client.stock_snapshot('AAPL')
    assert second['cached'] and second['data']['quote']['bp'] == 199.8
    assert second['data']['quote']['age_seconds'] == 10
    assert second['captured_at'] == first['captured_at']
    assert len(transport.calls) == 2


def test_concurrent_identical_requests_issue_once_without_subscriptions():
    client, transport, _ = adapter(*stock_responses())
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: client.stock_snapshot('AAPL'), range(20)))
    assert len(transport.calls) == 2
    assert all(r['data']['price'] == 200 for r in results)
    assert client.status()['stream_subscriptions'] == 0


def test_stale_values_are_labeled_and_missing_values_not_fabricated():
    client, _, _ = adapter(*stock_responses(q=quote(t=(NOW-timedelta(hours=4)).isoformat())))
    assert not client.stock_snapshot('AAPL')['data']['quote']['fresh']
    client, _, _ = adapter(ok({'quotes': {}}), ok({'trades': {}}))
    data = client.stock_snapshot('AAPL')['data']
    assert data['price'] is None and data['quote'] is None and data['trade'] is None
    assert data['availability'] == 'NO_DATA'


@pytest.mark.parametrize('changes,code', [({'bp': float('nan')}, 'INVALID_PROVIDER_NUMBER'),
    ({'bp': True}, 'INVALID_PROVIDER_NUMBER'), ({'bp': -1}, 'INVALID_PROVIDER_NUMBER'),
    ({'bp': 300}, 'CROSSED_PROVIDER_QUOTE'),
    ({'t': (NOW+timedelta(seconds=1)).isoformat()}, 'FUTURE_PROVIDER_TIMESTAMP'),
    ({'t': '2026-10-12T15:00:00'}, 'INVALID_TIMESTAMP')])
def test_bad_quotes_fail_closed(changes, code):
    client, _, _ = adapter(*stock_responses(q=quote(**changes)))
    with pytest.raises(MarketDataError, match=code):
        client.stock_snapshot('AAPL')


def test_expired_cache_outage_never_falls_back_to_price_or_fixture():
    client, transport, clock = adapter(*stock_responses(), DataResponse(503, {}, {}), DataResponse(503, {}, {}))
    client.stock_snapshot('AAPL'); clock.advance(31)
    with pytest.raises(MarketDataError, match='UPSTREAM_UNAVAILABLE'):
        client.stock_snapshot('AAPL')
    assert len(transport.calls) == 4 and client.status()['retries'] == 1
    with pytest.raises(MarketDataError, match='RATE_LIMITED'):
        client.stock_snapshot('AAPL')


def test_reconnect_after_transient_failure_is_bounded_and_recovers():
    client, transport, _ = adapter(MarketDataError('DATA_CONNECTION_UNAVAILABLE'), *stock_responses())
    assert client.stock_snapshot('AAPL')['data']['price'] == 200
    assert len(transport.calls) == 3 and client.status()['retries'] == 1


@pytest.mark.parametrize('status', [401, 403])
def test_credential_entitlement_denials_stop_retries_and_cache(status):
    client, transport, _ = adapter(DataResponse(status, {}, {'message': 'DO_NOT_LEAK_TEST_SECRET'}))
    for _ in range(2):
        with pytest.raises(MarketDataError, match='AUTH_OR_ENTITLEMENT_DENIED') as error:
            client.stock_snapshot('AAPL')
        assert 'DO_NOT_LEAK' not in str(error.value)
    assert len(transport.calls) == 1


@pytest.mark.parametrize('headers', [
    {'Retry-After': '120', 'X-RateLimit-Limit': '200', 'X-RateLimit-Remaining': '0'},
    {'Retry-After': 'Mon, 12 Oct 2026 15:02:00 GMT'},
    {'X-RateLimit-Reset': str(int(NOW.timestamp())+120)},
])
def test_provider_rate_limit_honored_without_blocking_sleep(headers):
    client, transport, clock = adapter(DataResponse(429, headers, {}), *stock_responses())
    with pytest.raises(MarketDataError, match='RATE_LIMITED'):
        client.stock_snapshot('AAPL')
    clock.advance(119)
    with pytest.raises(MarketDataError, match='RATE_LIMITED'):
        client.stock_snapshot('AAPL')
    assert len(transport.calls) == 1
    clock.advance(1)
    assert client.stock_snapshot('AAPL')['data']['price'] == 200


def test_local_budget_is_shared_and_resets():
    client, transport, clock = adapter(*stock_responses(), requests_per_minute=1)
    with pytest.raises(MarketDataError, match='RATE_LIMITED'):
        client.stock_snapshot('AAPL')
    assert len(transport.calls) == 1
    clock.advance(60)
    # Query just the previously blocked second leg: budget now permits it.
    client._request('/v2/stocks/trades/latest', {'symbols': 'AAPL', 'feed': 'iex'})
    assert len(transport.calls) == 2


def test_success_with_zero_remaining_gates_next_request():
    client, transport, _ = adapter(ok({'quotes': {}}, {'X-RateLimit-Remaining': '0'}))
    with pytest.raises(MarketDataError, match='RATE_LIMITED'):
        client.stock_snapshot('AAPL')
    assert len(transport.calls) == 1


def test_basic_options_are_explicitly_modified_with_unknown_greeks():
    client, transport, _ = adapter(chain())
    result = client.option_chain('AAPL')
    item = result['data']['contracts'][0]
    assert item['greeks'] is None and item['implied_volatility'] is None
    assert result['feed'] == 'indicative' and result['nominal_delay_seconds'] is None
    assert result['data']['trade_delay_seconds'] == 900
    assert result['data']['quote_delay_seconds'] is None
    assert not result['virtual_fills_enabled']
    assert result['execution_block_reason'] == 'INDICATIVE_OPTIONS_NOT_EXECUTABLE'
    assert transport.calls[0][1]['feed'] == 'indicative'


def test_only_provider_greeks_preserved_and_no_freshness_invented():
    client, _, _ = adapter(chain({'greeks': {'delta': -.32}, 'impliedVolatility': .4}, contract='AAPL261016P00200000'))
    result = client.option_chain('AAPL')['data']['contracts'][0]
    assert result['greeks']['delta'] == -.32 and result['greeks']['gamma'] is None
    assert result['greeks_timestamp'] is None and not result['greeks_freshness_verified']
    assert result['quote'] is None and result['trade'] is None


def test_chain_pagination_and_truncation_are_honest():
    client, transport, _ = adapter(chain(token='next'), chain(contract='AAPL261016P00200000'))
    result = client.option_chain('AAPL')
    assert len(result['data']['contracts']) == 2 and result['complete']
    assert transport.calls[1][1]['page_token'] == 'next'
    client, _, _ = adapter(chain(token='more'), max_pages=1)
    assert not client.option_chain('AAPL')['complete']


def test_repeated_page_tokens_and_wrong_underlying_fail():
    client, _, _ = adapter(chain(token='same'), chain(contract='AAPL261016P00200000', token='same'))
    with pytest.raises(MarketDataError, match='INVALID_PAGINATION'):
        client.option_chain('AAPL')
    client, _, _ = adapter(chain(contract='TSLA261016C00200000'))
    with pytest.raises(MarketDataError, match='SYMBOL_MISMATCH'):
        client.option_chain('AAPL')


def test_documented_historical_iex_example_without_generated_prices():
    fixture = json.loads((Path(__file__).parent/'fixtures/alpaca_iex_aapl_20230929.json').read_text())
    assert fixture['provenance']['account_fetched'] is False
    raw = fixture['response']
    client, transport, _ = adapter(ok({'bars': {raw['symbol']: raw['bars']}, 'next_page_token': None}))
    result = client.stock_bars('AAPL', timestamp('2023-09-29T00:00:00Z'), timestamp('2023-09-30T05:00:00Z'))
    assert result['data']['bars'][0]['c'] == 171.29
    assert result['data']['bars'][0]['v'] == 923134
    assert transport.calls[0][1]['adjustment'] == 'raw' and transport.calls[0][1]['asof'] == '-'
    assert result['point_in_time_backtest_verified'] is False


def test_history_excludes_unclosed_bar_at_decision_cutoff():
    client, _, _ = adapter(ok({'bars': {'AAPL': [bar(), bar('2026-10-12T14:01:00Z')]}}))
    result = client.stock_bars('AAPL', timestamp('2026-10-12T14:00:00Z'), timestamp('2026-10-12T14:01:30Z'), '1Min')
    assert len(result['data']['bars']) == 1 and result['data']['incomplete_bars_excluded'] == 1


@pytest.mark.parametrize('date,expected', [('2026-03-08T05:00:00Z','2026-03-09T04:00:00+00:00'),
                                        ('2026-11-01T04:00:00Z','2026-11-02T05:00:00+00:00')])
def test_daily_completion_uses_new_york_dst(date, expected):
    client, _, clock = adapter(ok({'bars': {'AAPL': [bar(date)]}}))
    clock.advance(40*86400)
    result = client.stock_bars('AAPL', timestamp(date), timestamp(expected), '1Day')
    assert result['data']['bars'][0]['closed_at'] == expected


@pytest.mark.parametrize('rows,code', [([bar(),bar()], 'INVALID_BAR_ORDER'),
    ([bar('2026-10-12T16:00:00Z')], 'INVALID_BAR_ORDER'),
    ([bar(l=103)], 'INVALID_OHLC'), ([bar(v=-1)], 'INVALID_PROVIDER_NUMBER')])
def test_corrupt_historical_bars_rejected(rows, code):
    client, _, _ = adapter(ok({'bars': {'AAPL': rows}}))
    with pytest.raises(MarketDataError, match=code):
        client.stock_bars('AAPL', NOW-timedelta(hours=2), NOW, '1Min')


def test_options_history_uses_delayed_entitlement_without_unsupported_feed_parameter():
    client, transport, _ = adapter(ok({'bars': {CONTRACT: [bar()]}}))
    result = client.option_bars(CONTRACT, NOW-timedelta(hours=2), NOW-timedelta(minutes=15), '1Min')
    assert result['nominal_delay_seconds'] == 900
    assert 'feed' not in transport.calls[0][1]
    assert not result['virtual_fills_enabled']


@pytest.mark.parametrize('start,end', [(NOW-timedelta(hours=1), NOW),
    (timestamp('2024-01-31T00:00:00Z'), NOW-timedelta(hours=1)), (NOW, NOW-timedelta(hours=1))])
def test_unentitled_option_history_range_rejected_before_request(start, end):
    client, transport, _ = adapter()
    with pytest.raises(MarketDataError, match='HISTORY_RANGE'):
        client.option_bars(CONTRACT, start, end, '1Min')
    assert not transport.calls


@pytest.mark.parametrize('ticker', ['../orders','AAPL?feed=sip','aapl','AAPL,MSFT','https://example.org','',None])
def test_bad_symbols_do_not_reach_transport(ticker):
    client, transport, _ = adapter()
    with pytest.raises(MarketDataError, match='INVALID_SYMBOL'):
        client.stock_snapshot(ticker)
    assert not transport.calls


@pytest.mark.parametrize('kind',['quote','trade','implied_volatility'])
def test_oversized_provider_integer_has_fixed_numeric_diagnostic(kind):
    huge=10**400
    if kind=='implied_volatility':
        client,_,_=adapter(chain({'impliedVolatility':huge}))
        operation=lambda:client.option_chain('AAPL')
    else:
        q=quote(bp=huge) if kind=='quote' else quote()
        t=trade(p=huge) if kind=='trade' else trade()
        client,_,_=adapter(*stock_responses(q,t))
        operation=lambda:client.stock_snapshot('AAPL')
    with pytest.raises(MarketDataError,match='^INVALID_PROVIDER_NUMBER$'):operation()
