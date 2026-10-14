"""Read-only counterfactuals from original option quotes, never stock-price proxies.

The fixed-horizon model uses the latest qualified quote *received by* the horizon.
It does not interpolate, fill missing history, estimate queue priority or create an
execution receipt. Provenance labels are retained, not independently authenticated.
"""
from datetime import date, timedelta, timezone
import re

from .market_sessions import evaluate_session, US_EQUITY_OPTIONS_POLICY
from .option_expiration import evaluate_expiration
from .paper_settlement import stamp

VERSION = 'observed-option-counterfactual-v1'
PATTERN = re.compile(r'^([A-Z]{1,6})(\d{2})(\d{2})(\d{2})([CP])(\d{8})$')
QUOTE_KEYS = {'contract', 'feed', 'at', 'bid', 'ask', 'bidSize', 'askSize'}


def integer(value, minimum=0, maximum=100000000):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError('invalid integer')
    return value


def iso(value):
    precision = 'microseconds' if value.microsecond % 1000 else 'milliseconds'
    return value.astimezone(timezone.utc).isoformat(timespec=precision).replace('+00:00', 'Z')


def read_observation(value):
    if not isinstance(value, dict) or set(value) != {'account', 'source', 'capturedAt', 'quote'}:
        raise ValueError('invalid observation')
    if not isinstance(value['account'], str) or not value['account'].strip() or len(value['account']) > 120:
        raise ValueError('invalid account')
    if value['source'] not in ('fixture', 'alpaca'):
        raise ValueError('unknown source')
    q = value['quote']
    if not isinstance(q, dict) or set(q) != QUOTE_KEYS or not isinstance(q['contract'], str):
        raise ValueError('invalid quote')
    m = PATTERN.fullmatch(q['contract'])
    if not m or int(m[6]) <= 0 or int(m[6]) % 10:
        raise ValueError('nonstandard contract')
    expiry = date(2000 + int(m[2]), int(m[3]), int(m[4]))
    captured, quoted = stamp(value['capturedAt']), stamp(q['at'])
    bid, ask = integer(q['bid'], 1), integer(q['ask'], 1)
    integer(q['bidSize'], 1, 1000000000); integer(q['askSize'], 1, 1000000000)
    if (q['feed'] != 'opra' or ask < bid or (ask - bid) * 5 > ask or
            not 0 <= (captured - quoted).total_seconds() <= 30 or
            not evaluate_session(captured, US_EQUITY_OPTIONS_POLICY).fill_allowed or
            not evaluate_expiration(expiry, captured)['close_fill_allowed']):
        raise ValueError('unqualified quote')
    return captured, quoted, expiry


def replay_option(query):
    """JSON-in/out, bounded integer arithmetic; malformed inputs fail explicitly."""
    base = {'version': VERSION, 'counterfactual': True, 'executionAllowed': False,
            'externalOrder': False, 'pnlCents': None}
    def unavailable(status):
        return base | {'status': status}
    try:
        if not isinstance(query, dict) or set(query) - {'entry', 'observations', 'asOf',
                'horizonSeconds', 'slippageCents', 'feePerContractCents'}:
            raise ValueError()
        as_of = stamp(query['asOf'])
        horizon = integer(query.get('horizonSeconds', 300), 1, 86400)
        slippage = integer(query.get('slippageCents', 0), 0, 10000)
        fee = integer(query.get('feePerContractCents', 65), 0, 10000)
        observations = query['observations']
        if not isinstance(observations, list) or len(observations) > 20000:
            raise ValueError()
    except (KeyError, TypeError, ValueError, OverflowError):
        return unavailable('INVALID_QUERY')
    try:
        e = query['entry']; f = e['fill']; q = e['quote']
        origin = {'account': e['account'], 'source': e['evidence']['source'],
                  'capturedAt': e['at'], 'quote': q}
        entered, _, expiry = read_observation(origin)
        quantity = integer(f['quantity'], 1, 100000)
        entry_fee = integer(f['fee'], 0, 1000000000)
        if (f['side'] != 'BUY' or type(f['price']) is not int or f['price'] != q['ask'] or
                quantity > min(q['bidSize'], q['askSize']) or
                not evaluate_session(entered, US_EQUITY_OPTIONS_POLICY).entry_allowed or
                not evaluate_expiration(expiry, entered)['entry_allowed']):
            raise ValueError()
    except (KeyError, TypeError, ValueError, OverflowError):
        return unavailable('INVALID_ORIGINAL_RECEIPT')
    target = entered + timedelta(seconds=horizon)
    if as_of < target:
        return unavailable('HORIZON_NOT_OBSERVED')
    if (not evaluate_session(target, US_EQUITY_OPTIONS_POLICY).fill_allowed or
            not evaluate_expiration(expiry, target)['close_fill_allowed']):
        return unavailable('HORIZON_OUTSIDE_OPTION_SESSION')
    candidates = []
    try:
        for o in observations:
            captured, quoted, _ = read_observation(o)
            if (o['account'] == origin['account'] and o['source'] == origin['source'] and
                    o['quote']['contract'] == q['contract'] and captured <= target and
                    target - timedelta(seconds=30) <= quoted <= target):
                candidates.append((quoted, captured, o['quote']))
    except (KeyError, TypeError, ValueError, OverflowError):
        return unavailable('INVALID_OBSERVATION')
    if not candidates:
        return unavailable('INSUFFICIENT_OBSERVED_DATA')
    latest = max(c[0] for c in candidates)
    at_latest = sorted((c for c in candidates if c[0] == latest), key=lambda c:c[1])
    exit_quote = at_latest[0][2]
    if any(any(c[2][key] != exit_quote[key] for key in QUOTE_KEYS - {'at'}) for c in at_latest):
        return unavailable('AMBIGUOUS_OBSERVATION')
    if quantity > min(exit_quote['bidSize'], exit_quote['askSize']):
        return unavailable('INSUFFICIENT_OBSERVED_LIQUIDITY')
    price = exit_quote['bid'] - slippage
    if price <= 0:
        return unavailable('NO_POSITIVE_STRESSED_BID')
    entry_cost = q['ask'] * quantity * 100 + entry_fee
    exit_fee = fee * quantity
    proceeds = price * quantity * 100 - exit_fee
    return base | {'status': 'OBSERVED_COUNTERFACTUAL', 'source': origin['source'],
        'account': origin['account'], 'contract': q['contract'], 'quantity': quantity,
        'targetAt': iso(target), 'quoteAt': iso(latest), 'capturedAt': iso(at_latest[0][1]),
        'entryCostCents': entry_cost, 'entryFeeCents': entry_fee,
        'exitBidCents': exit_quote['bid'], 'slippageCents': slippage,
        'exitPriceCents': price, 'exitFeeCents': exit_fee, 'exitProceedsCents': proceeds,
        'pnlCents': proceeds - entry_cost, 'model': 'observed-bid-minus-adverse-cents',
        'queueModeled': False, 'greeksUsedForPricing': False}
