"""Replaceable market-data boundary. No broker/execution imports or capabilities.

All results are observations, never permission to fill. This first Basic adapter
deliberately has no stream subscriptions, avoiding the shared account's stream
connection limit. It shares bounded REST caching/rate budget across local accounts.
"""
from collections import OrderedDict, deque
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import http.client
import json
import math
import os
import re
import ssl
import threading
import time
from typing import Protocol
from urllib.parse import urlencode
from zoneinfo import ZoneInfo
from .option_greeks import provider_greeks, quality as greeks_quality
from .option_eligibility import qualify as qualify_option

UTC = timezone.utc
DATA_HOST = 'data.alpaca.markets'
MODE = 'real_market_virtual'
USAGE = 'Subject to Alpaca and exchange agreements; this adapter grants no redistribution rights'
TERMS_URL = 'https://alpaca.markets/disclosures'
INDICATIVE_REASON = 'INDICATIVE_OPTIONS_NOT_EXECUTABLE'
TIMEFRAMES = {'1Min': 60, '5Min': 300, '15Min': 900, '1Hour': 3600, '1Day': 86400}
STOCK = re.compile(r'[A-Z][A-Z0-9.]{0,9}')
OPTION = re.compile(r'([A-Z][A-Z0-9.]{0,9})(\d{6})([CP])(\d{8})')


class MarketDataError(RuntimeError):
    """Only a fixed diagnostic code crosses the boundary, never provider bodies."""
    def __init__(self, code):
        self.code = code
        super().__init__(code)


class MarketDataProvider(Protocol):
    def status(self) -> dict: ...
    def stock_snapshot(self, symbol: str) -> dict: ...
    def stock_bars(self, symbol: str, start: datetime, end: datetime, timeframe: str) -> dict: ...
    def option_chain(self, symbol: str) -> dict: ...
    def option_bars(self, symbol: str, start: datetime, end: datetime, timeframe: str) -> dict: ...


def symbol(value, *, option=False):
    if not isinstance(value, str) or not (OPTION if option else STOCK).fullmatch(value):
        raise MarketDataError('INVALID_SYMBOL')
    if option:
        match = OPTION.fullmatch(value)
        try:
            datetime.strptime(match[2], '%y%m%d')
        except ValueError:
            raise MarketDataError('INVALID_OPTION_DATE') from None
    return value


def timestamp(value):
    try:
        result = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace('Z', '+00:00'))
        if result.tzinfo is None or result.utcoffset() is None:
            raise ValueError()
        return result.astimezone(UTC)
    except (ValueError, TypeError, AttributeError, OverflowError):
        raise MarketDataError('INVALID_TIMESTAMP') from None


def number(value, *, signed=False):
    try:
        finite=type(value) in (int,float) and math.isfinite(value)
    except OverflowError:
        finite=False
    if not finite or (not signed and value < 0):
        raise MarketDataError('INVALID_PROVIDER_NUMBER')
    return value


@dataclass(frozen=True)
class DataCredentials:
    key_id: str = field(repr=False)
    secret_key: str = field(repr=False)

    def __post_init__(self):
        if any(not isinstance(v, str) or not 1 <= len(v) <= 256 or not v.isascii()
               or any(ord(c) <= 32 or ord(c) == 127 for c in v)
               for v in (self.key_id, self.secret_key)):
            raise MarketDataError('INVALID_DATA_CREDENTIALS')


@dataclass(frozen=True)
class DataResponse:
    status: int
    headers: dict
    body: dict


class DataTransport(Protocol):
    def get(self, path: str, params: dict) -> DataResponse: ...


def allowed_query(path, params, *, observed_options=False):
    """Reject arbitrary paths/queries before credentials can enter a request."""
    if observed_options and path == '/v1beta1/options/quotes/latest':
        symbols = params.get('symbols')
        return (set(params) == {'symbols','feed'} and params['feed']=='opra'
                and isinstance(symbols,str) and 1 <= len(symbols.split(',')) <= 30
                and all(OPTION.fullmatch(s) for s in symbols.split(',')))
    if path in ('/v2/stocks/quotes/latest', '/v2/stocks/trades/latest'):
        return set(params) <= {'symbols', 'feed'} and params.get('feed') == 'iex'
    if path == '/v2/stocks/bars':
        return set(params) <= {'symbols', 'feed', 'start', 'end', 'timeframe', 'limit', 'sort', 'adjustment', 'asof', 'page_token'} and params.get('feed') == 'iex'
    if path == '/v1beta1/options/bars':
        return set(params) <= {'symbols', 'start', 'end', 'timeframe', 'limit', 'sort', 'page_token'}
    prefix = '/v1beta1/options/snapshots/'
    return (path.startswith(prefix) and STOCK.fullmatch(path[len(prefix):]) is not None
            and set(params) <= {'feed', 'limit', 'page_token'} and params.get('feed') == 'indicative')


class AlpacaDataTransport:
    """GET-only fixed HTTPS host; no redirects, proxies, SDK or trading URL.

    Creating this transport is offline. A separate operator approval flag is
    required by from_environment before production can use credentials.
    """
    def __init__(self, credentials: DataCredentials, *, observed_options=False):
        self._credentials = credentials
        self._observed_options = observed_options is True

    def get(self, path, params):
        if not allowed_query(path, params, observed_options=self._observed_options):
            raise MarketDataError('DATA_ROUTE_FORBIDDEN')
        connection = http.client.HTTPSConnection(DATA_HOST, 443, timeout=8, context=ssl.create_default_context())
        try:
            connection.request('GET', path + '?' + urlencode(params), headers={
                'APCA-API-KEY-ID': self._credentials.key_id,
                'APCA-API-SECRET-KEY': self._credentials.secret_key,
                'Accept': 'application/json',
            })
            response = connection.getresponse()
            headers = {k.lower(): v for k, v in response.getheaders()
                       if k.lower() in ('retry-after', 'x-ratelimit-limit', 'x-ratelimit-remaining', 'x-ratelimit-reset')}
            if response.status != 200:
                return DataResponse(response.status, headers, {})
            body = response.read(4 * 1024 * 1024 + 1)
            if len(body) > 4 * 1024 * 1024:
                raise MarketDataError('DATA_RESPONSE_TOO_LARGE')
            def reject_constant(_):
                raise ValueError()
            value = json.loads(body, parse_constant=reject_constant)
            if not isinstance(value, dict):
                raise ValueError()
            return DataResponse(200, headers, value)
        except (OSError, http.client.HTTPException):
            raise MarketDataError('DATA_CONNECTION_UNAVAILABLE') from None
        except (ValueError, UnicodeError):
            raise MarketDataError('INVALID_PROVIDER_RESPONSE') from None
        finally:
            connection.close()


class DisabledMarketData:
    def status(self):
        return {'provider': 'alpaca', 'mode': MODE, 'connection_enabled': False,
                'connection_state': 'DISABLED_PENDING_SEPARATE_APPROVAL', 'live_enabled': False,
                'external_orders_enabled': False, 'virtual_fills_enabled': False,
                'stock_feed': 'iex', 'option_feed': 'indicative', 'stream_subscriptions': 0}

    def _disabled(self, *args, **kwargs):
        raise MarketDataError('DATA_CONNECTION_NOT_APPROVED')
    stock_snapshot = stock_bars = option_chain = option_bars = _disabled


class AlpacaBasicData:
    def __init__(self, transport: DataTransport, *, now=None, monotonic=None, sleep=None, requests_per_minute=30, max_pages=5):
        if type(requests_per_minute) is not int or not 1 <= requests_per_minute <= 200:
            raise MarketDataError('INVALID_RATE_BUDGET')
        if type(max_pages) is not int or not 1 <= max_pages <= 10:
            raise MarketDataError('INVALID_PAGE_BUDGET')
        self._transport = transport
        self._now = now or (lambda: datetime.now(UTC))
        self._monotonic = monotonic or time.monotonic
        self._sleep = sleep or time.sleep
        self._budget, self._max_pages = requests_per_minute, max_pages
        self._lock = threading.RLock()
        self._cache, self._calls = OrderedDict(), deque()
        self._cooldown, self._blocked = 0.0, None
        self._metrics = {'requests': 0, 'cache_hits': 0, 'retries': 0, 'rate_limited': 0,
                         'errors': 0, 'provider_limit': None, 'provider_remaining': None}

    def status(self):
        with self._lock:
            return {'provider': 'alpaca', 'mode': MODE, 'connection_enabled': True,
                    'connection_state': self._blocked or ('COOLDOWN' if self._monotonic() < self._cooldown else 'READY_NOT_VERIFIED'),
                    'live_enabled': False, 'external_orders_enabled': False, 'virtual_fills_enabled': False,
                    'stock_feed': 'iex', 'option_feed': 'indicative', 'stream_subscriptions': 0,
                    'requests_per_minute': self._budget, 'cache_entries': len(self._cache), **self._metrics}

    def _request(self, path, params, ttl=30):
        if not allowed_query(path, params):
            raise MarketDataError('DATA_ROUTE_FORBIDDEN')
        key = (path, tuple(sorted(params.items())))
        # Serialize fetch+cache population: identical concurrent reads issue once.
        # No database lock is held by callers during this bounded network section.
        with self._lock:
            now = self._monotonic()
            if self._blocked:
                raise MarketDataError(self._blocked)
            cached = self._cache.get(key)
            if cached and now < cached[0]:
                self._cache.move_to_end(key)
                self._metrics['cache_hits'] += 1
                return deepcopy(cached[1]), cached[2], True
            for attempt in range(2):
                now = self._monotonic()
                while self._calls and now - self._calls[0] >= 60:
                    self._calls.popleft()
                if now < self._cooldown or len(self._calls) >= self._budget:
                    self._metrics['rate_limited'] += 1
                    raise MarketDataError('DATA_RATE_LIMITED')
                self._calls.append(now)
                self._metrics['requests'] += 1
                try:
                    response = self._transport.get(path, params)
                except MarketDataError as exc:
                    if exc.code != 'DATA_CONNECTION_UNAVAILABLE':
                        raise
                    response = DataResponse(503, {}, {})
                headers = {k.lower(): str(v) for k, v in response.headers.items()}
                for header, metric in [('x-ratelimit-limit', 'provider_limit'), ('x-ratelimit-remaining', 'provider_remaining')]:
                    value = headers.get(header, '')
                    if value.isdigit() and len(value) <= 9:
                        self._metrics[metric] = int(value)
                if response.status == 429 or headers.get('x-ratelimit-remaining') == '0':
                    retry = 60.0
                    try:
                        # HTTP Retry-After can also be an RFC date.
                        raw = headers.get('retry-after')
                        if raw is not None:
                            from email.utils import parsedate_to_datetime
                            retry = float(raw) if raw.isdigit() else (parsedate_to_datetime(raw) - self._now()).total_seconds()
                        reset = float(headers.get('x-ratelimit-reset', '0')) - self._now().timestamp()
                        retry = max(retry, reset, 1)
                        if not math.isfinite(retry):
                            retry = 60
                    except (ValueError, TypeError, OverflowError):
                        retry = 60
                    self._cooldown = self._monotonic() + min(max(retry, 1), 86400)
                if response.status == 200:
                    if not isinstance(response.body, dict):
                        raise MarketDataError('INVALID_PROVIDER_RESPONSE')
                    captured = timestamp(self._now()).isoformat()
                    self._cache[key] = (self._monotonic() + ttl, deepcopy(response.body), captured)
                    self._cache.move_to_end(key)
                    while len(self._cache) > 128:
                        self._cache.popitem(last=False)
                    return deepcopy(response.body), captured, False
                self._metrics['errors'] += 1
                if response.status in (401, 403):
                    self._blocked = 'DATA_AUTH_OR_ENTITLEMENT_DENIED'
                    raise MarketDataError(self._blocked)
                if response.status == 429:
                    self._metrics['rate_limited'] += 1
                    raise MarketDataError('DATA_RATE_LIMITED')
                if response.status >= 500 and attempt == 0:
                    self._metrics['retries'] += 1
                    self._sleep(0.25)
                    continue
                if response.status >= 500:
                    self._cooldown = self._monotonic() + 5
                raise MarketDataError('DATA_UPSTREAM_UNAVAILABLE' if response.status >= 500 else 'DATA_REQUEST_DENIED')

    def _envelope(self, feed, data, captures, cache_flags, *, delay=0, complete=True, reason='MARKET_DATA_OBSERVATION_ONLY'):
        return {'schema_version': 1, 'provider': 'alpaca', 'mode': MODE, 'feed': feed,
                'nominal_delay_seconds': delay, 'captured_at': min(captures),
                'last_page_captured_at': max(captures), 'served_at': timestamp(self._now()).isoformat(),
                'cached': all(cache_flags), 'complete': complete, 'data': data,
                'virtual_fills_enabled': False, 'execution_block_reason': reason,
                'external_orders_enabled': False, 'usage': USAGE, 'usage_url': TERMS_URL,
                'point_in_time_backtest_verified': False}

    def _event(self, value, kind):
        if value is None:
            return None
        if not isinstance(value, dict):
            raise MarketDataError('INVALID_PROVIDER_RESPONSE')
        observed = timestamp(value.get('t'))
        age = (timestamp(self._now()) - observed).total_seconds()
        if age < 0:
            raise MarketDataError('FUTURE_PROVIDER_TIMESTAMP')
        fields = ('bp', 'ap', 'bs', 'as') if kind == 'quote' else ('p', 's')
        result = {k: number(value[k]) if value.get(k) is not None else None for k in fields}
        if kind == 'quote' and result['bp'] is not None and result['ap'] is not None and result['bp'] > result['ap']:
            raise MarketDataError('CROSSED_PROVIDER_QUOTE')
        return {'timestamp': observed.isoformat(), 'age_seconds': age,
                'fresh': age <= 60, **result}

    def stock_snapshot(self, ticker):
        ticker = symbol(ticker)
        quotes, qt, qc = self._request('/v2/stocks/quotes/latest', {'symbols': ticker, 'feed': 'iex'})
        trades, tt, tc = self._request('/v2/stocks/trades/latest', {'symbols': ticker, 'feed': 'iex'})
        quote = self._mapping(quotes, 'quotes').get(ticker)
        trade = self._mapping(trades, 'trades').get(ticker)
        q, t = self._event(quote, 'quote'), self._event(trade, 'trade')
        return self._envelope('iex', {'symbol': ticker, 'quote': q, 'trade': t,
            'price': t['p'] if t else None, 'price_source': 'latest_iex_trade' if t else None,
            'coverage': 'IEX only; not consolidated NBBO',
            'availability': 'NO_DATA' if q is None and t is None else 'OBSERVED'}, [qt, tt], [qc, tc])

    @staticmethod
    def _mapping(body, field):
        value = body.get(field)
        if not isinstance(value, dict):
            raise MarketDataError('INVALID_PROVIDER_RESPONSE')
        return value

    def _pages(self, path, params, field, ttl):
        pages, captures, cached, seen = [], [], [], set()
        for _ in range(self._max_pages):
            body, captured, hit = self._request(path, params, ttl)
            pages.append(self._mapping(body, field))
            captures.append(captured); cached.append(hit)
            token = body.get('next_page_token')
            if token is None:
                return pages, captures, cached, True
            if not isinstance(token, str) or not 1 <= len(token) <= 4096 or token in seen:
                raise MarketDataError('INVALID_PAGINATION')
            seen.add(token)
            params = {**params, 'page_token': token}
        return pages, captures, cached, False

    def option_chain(self, underlying):
        underlying = symbol(underlying)
        pages, captures, cached, complete = self._pages('/v1beta1/options/snapshots/' + underlying,
            {'feed': 'indicative', 'limit': 100}, 'snapshots', 30)
        result = {}
        for page in pages:
            for contract, raw in page.items():
                symbol(contract, option=True)
                root = OPTION.fullmatch(contract)[1]
                if root != underlying and not re.fullmatch(re.escape(underlying) + r'[1-9]', root):
                    raise MarketDataError('PROVIDER_SYMBOL_MISMATCH')
                if not isinstance(raw, dict) or contract in result:
                    raise MarketDataError('INVALID_PROVIDER_RESPONSE')
                try:
                    greeks = provider_greeks(raw.get('greeks'), OPTION.fullmatch(contract)[3])
                except ValueError:
                    raise MarketDataError('INVALID_PROVIDER_GREEKS') from None
                result[contract] = {'symbol': contract,
                    'quote': self._event(raw.get('latestQuote'), 'quote'),
                    'trade': self._event(raw.get('latestTrade'), 'trade'),
                    'greeks': greeks, 'greeks_source': 'provider' if greeks is not None else None,
                    'greeks_timestamp': None, 'greeks_freshness_verified': False, 'greeks_quality': greeks_quality(greeks),
                    'eligibility': qualify_option(contract, greeks, timestamp(self._now())),
                    'implied_volatility': number(raw['impliedVolatility']) if raw.get('impliedVolatility') is not None else None}
        return self._envelope('indicative', {'symbol': underlying, 'contracts': list(result.values()),
            'quote_quality': 'MODIFIED_INDICATIVE_NOT_OPRA', 'quote_delay_seconds': None,
            'trade_delay_seconds': 900, 'availability': 'OBSERVED' if result else 'NO_DATA'},
            captures, cached, delay=None, complete=complete, reason=INDICATIVE_REASON)

    def stock_bars(self, ticker, start, end, timeframe='1Day'):
        return self._bars(ticker, start, end, timeframe, option=False)

    def option_bars(self, contract, start, end, timeframe='1Day'):
        return self._bars(contract, start, end, timeframe, option=True)

    def _bars(self, ticker, start, end, timeframe, *, option):
        ticker = symbol(ticker, option=option)
        start, end = timestamp(start), timestamp(end)
        delay = 900 if option else 0
        earliest = datetime(2024, 2, 1, tzinfo=UTC) if option else datetime(2016, 1, 1, tzinfo=UTC)
        if timeframe not in TIMEFRAMES or start < earliest or start >= end or end > timestamp(self._now()) - timedelta(seconds=delay):
            raise MarketDataError('INVALID_OR_UNENTITLED_HISTORY_RANGE')
        params = {'symbols': ticker, 'start': start.isoformat(), 'end': end.isoformat(),
                  'timeframe': timeframe, 'limit': 1000, 'sort': 'asc'}
        if not option:
            params.update(feed='iex', adjustment='raw', asof='-')
        path = '/v1beta1/options/bars' if option else '/v2/stocks/bars'
        pages, captures, cached, complete = self._pages(path, params, 'bars', 300)
        bars, previous, excluded = [], None, 0
        for page in pages:
            if set(page) - {ticker}:
                raise MarketDataError('PROVIDER_SYMBOL_MISMATCH')
            rows = page.get(ticker, [])
            if rows is None:
                rows = []
            if not isinstance(rows, list):
                raise MarketDataError('INVALID_PROVIDER_RESPONSE')
            for row in rows:
                if not isinstance(row, dict):
                    raise MarketDataError('INVALID_PROVIDER_RESPONSE')
                at = timestamp(row.get('t'))
                if not start <= at <= end or (previous is not None and at <= previous):
                    raise MarketDataError('INVALID_BAR_ORDER_OR_RANGE')
                previous = at
                values = {k: number(row.get(k)) for k in ('o', 'h', 'l', 'c', 'v')}
                if not values['l'] <= min(values['o'], values['c']) <= max(values['o'], values['c']) <= values['h']:
                    raise MarketDataError('INVALID_OHLC')
                if timeframe == '1Day':
                    local = at.astimezone(ZoneInfo('America/New_York'))
                    closed = (local.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)).astimezone(UTC)
                else:
                    closed = at + timedelta(seconds=TIMEFRAMES[timeframe])
                if closed > end:
                    excluded += 1
                    continue
                bars.append({'timestamp': at.isoformat(), 'closed_at': closed.isoformat(), **values})
        return self._envelope('historical_options' if option else 'iex',
            {'symbol': ticker, 'timeframe': timeframe, 'bars': bars, 'incomplete_bars_excluded': excluded,
             'adjustment': 'provider_option_history' if option else 'raw', 'symbol_mapping': False,
             'availability': 'OBSERVED' if bars else 'NO_COMPLETE_BARS'}, captures, cached,
            delay=delay, complete=complete, reason='HISTORICAL_BARS_ARE_NOT_EXECUTABLE_QUOTES')


def from_environment() -> MarketDataProvider:
    """No dotenv, key autodiscovery, other-app settings, or automatic connection."""
    if os.getenv('OAT_ALPACA_DATA_APPROVAL', '') != 'read_only_approved':
        return DisabledMarketData()
    key = os.getenv('OAT_ALPACA_DATA_KEY_ID', '')
    secret = os.getenv('OAT_ALPACA_DATA_SECRET_KEY', '')
    try:
        budget = int(os.getenv('OAT_ALPACA_DATA_REQUESTS_PER_MINUTE', '30'))
    except ValueError:
        raise MarketDataError('INVALID_RATE_BUDGET') from None
    return AlpacaBasicData(AlpacaDataTransport(DataCredentials(key, secret)), requests_per_minute=budget)
