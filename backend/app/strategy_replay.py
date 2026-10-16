"""Read-only alternative signals on a bounded, client-supplied observed window."""
from datetime import timedelta
from math import isfinite
import re

from .engines import Bar
from .market_strategy import STRATEGIES, VERSION as STRATEGY_VERSION, analyze
from .observed_option_replay import iso
from .paper_settlement import stamp

VERSION = 'observed-strategy-comparison-v1'


def compare_strategies(query):
    base = {'version': VERSION, 'strategyContract': STRATEGY_VERSION,
            'counterfactual': True, 'executionAllowed': False, 'externalOrder': False,
            'pnlCents': None, 'historicalAvailabilityVerified': False}
    try:
        if not isinstance(query, dict) or set(query) != {'account', 'symbol', 'source', 'capturedAt', 'bars', 'cursor'}:
            raise ValueError()
        if (not isinstance(query['account'], str) or not 1 <= len(query['account']) <= 120
                or query['account'].strip() != query['account']
                or not isinstance(query['symbol'], str) or not re.fullmatch(r'[A-Z][A-Z0-9.]{0,9}', query['symbol'])
                or query['source'] not in ('alpaca', 'fixture')):
            raise ValueError()
        raw, cursor = query['bars'], query['cursor']
        if not isinstance(raw, list) or not 1 <= len(raw) <= 1000 or type(cursor) is not int or not 0 <= cursor < len(raw):
            raise ValueError()
        captured = stamp(query['capturedAt'])
        bars = []
        for row in raw:
            if not isinstance(row, dict) or set(row) != {'at', 'o', 'h', 'l', 'c', 'v'}:
                raise ValueError()
            at = stamp(row['at'])
            if at.second or at.microsecond or at + timedelta(minutes=1) > captured:
                raise ValueError()
            values = [row[key] for key in ('o', 'h', 'l', 'c', 'v')]
            if any(type(v) not in (int, float) or not isfinite(v) or abs(v) > 1e12 for v in values):
                raise ValueError()
            if bars and at <= bars[-1].timestamp:
                raise ValueError()
            bars.append(Bar(at, *values))
        prefix = bars[:cursor + 1]
        return base | {'status': 'COMPARED', 'account': query['account'], 'symbol': query['symbol'],
                       'source': query['source'], 'capturedAt': iso(captured), 'prefixCount': len(prefix),
                       'prefixEndsAt': iso(prefix[-1].timestamp + timedelta(minutes=1)),
                       'signals': {strategy: analyze(prefix, strategy) for strategy in STRATEGIES}}
    except (ValueError, TypeError, KeyError, OverflowError, AttributeError):
        return base | {'status': 'INVALID_OBSERVED_SOURCE'}
