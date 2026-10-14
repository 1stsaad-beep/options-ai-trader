"""Pure, explicitly virtual settlement arithmetic; never a broker instruction.

Standard long equity options deliver stock. Missing cash/shares, unknown terms,
assignment to a long holder, and inferred cash settlement are rejected. The
caller must persist the returned receipt atomically with the inventory change.
All currency values are integer USD cents; OCC strikes must be exact cents.
"""
from datetime import datetime, timezone
import re

from .option_expiration import evaluate_expiration

VERSION = 'paper-equity-delivery-v1'
MAX = 9007199254740991
PATTERN = re.compile(r'^([A-Z]{1,6})(\d{2})(\d{2})(\d{2})([CP])(\d{8})$')


def integer(value, minimum=0):
    if type(value) is not int or not minimum <= value <= MAX:
        raise ValueError('Invalid integer amount')
    return value


def stamp(value):
    if not isinstance(value, str):
        raise ValueError('Explicit timestamp required')
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError('Timezone required')
    return result.astimezone(timezone.utc)


def project(position, delivery, cash, request, now):
    """Return deterministic deltas. Does not change any caller-owned object.

    A receipt is an explicit paper observation, not proof of broker settlement.
    Late recording is allowed, but the effective event may not precede ownership
    or exceed the known exercise cutoff. Worthless expiry needs an explicit
    at-cutoff underlying observation; no zero-price fallback exists.
    """
    allowed = {'id', 'action', 'contract', 'quantity', 'feeCents', 'underlyingCents',
               'effectiveAt', 'recordedAt', 'source', 'reference'}
    if not isinstance(request, dict) or set(request) != allowed:
        raise ValueError('Strict settlement receipt required')
    if request['source'] not in ('manual_paper', 'fixture'):
        raise ValueError('Paper-only receipt source required')
    for key in ('id', 'reference'):
        if not isinstance(request[key], str) or not 1 <= len(request[key].strip()) <= 120:
            raise ValueError('Receipt identity/reference required')
    match = PATTERN.fullmatch(request['contract']) if isinstance(request['contract'], str) else None
    if not match or int(match[6]) <= 0 or int(match[6]) % 10:
        raise ValueError('Standard whole-cent OCC contract required')
    symbol, right, strike = match[1], match[5], int(match[6]) // 10
    expiry = datetime(2000 + int(match[2]), int(match[3]), int(match[4]), tzinfo=timezone.utc).date()
    effective, recorded = stamp(request['effectiveAt']), stamp(request['recordedAt'])
    if now.tzinfo is None or not effective <= recorded <= now:
        raise ValueError('Receipt chronology invalid')
    qty, fee, spot = integer(request['quantity'], 1), integer(request['feeCents']), integer(request['underlyingCents'], 1)
    integer(cash)
    delivery = delivery or {'quantity': 0, 'cost': 0}
    stock_qty, stock_cost = integer(delivery['quantity']), integer(delivery['cost'])
    if (stock_qty == 0) != (stock_cost == 0):
        raise ValueError('Delivery inventory inconsistent')
    action = request['action']
    removed_cost = removed_fees = option_qty = stock_delta = basis_delta = cash_delta = pnl = 0
    if action == 'SELL_DELIVERY':
        if qty > stock_qty:
            raise ValueError('Owned delivered shares required; short stock prohibited')
        basis_delta = -(stock_cost * qty // stock_qty)
        stock_delta = -qty
        cash_delta = spot * qty - fee
        pnl = cash_delta + basis_delta
    elif action in ('EXERCISE', 'EXPIRE_WORTHLESS'):
        if not position or position['contract'] != request['contract'] or qty > integer(position['quantity'], 1):
            raise ValueError('Owned option quantity required')
        if effective < stamp(position['opened']):
            raise ValueError('Receipt predates ownership')
        expiry_facts = evaluate_expiration(expiry, effective)
        cutoff_text = expiry_facts.get('cutoff_at')
        if cutoff_text is None:
            raise ValueError('Known contract calendar required')
        cutoff = stamp(cutoff_text)
        option_qty = qty
        removed_cost = integer(position['cost'], 1) * qty // position['quantity']
        removed_fees = integer(position.get('entryFees', 0)) * qty // position['quantity']
        if action == 'EXPIRE_WORTHLESS':
            if effective != cutoff or (spot > strike if right == 'C' else spot < strike):
                raise ValueError('Explicit non-ITM expiry observation at cutoff required')
            cash_delta = -fee
            pnl = -removed_cost - removed_fees - fee
        else:
            if effective > cutoff:
                raise ValueError('Exercise after cutoff prohibited')
            shares = qty * 100
            if right == 'C':
                cash_delta = -strike * shares - fee
                stock_delta = shares
                basis_delta = strike * shares + removed_cost + removed_fees + fee
            else:
                if shares > stock_qty:
                    raise ValueError('Put exercise requires owned underlying shares; no short delivery')
                stock_delta = -shares
                basis_delta = -(stock_cost * shares // stock_qty)
                cash_delta = strike * shares - fee
                pnl = cash_delta + basis_delta - removed_cost - removed_fees
    else:
        raise ValueError('Long-only equity options cannot receive assignment or cash settlement')
    integer(cash + cash_delta)
    integer(stock_qty + stock_delta)
    integer(stock_cost + basis_delta)
    for value in (cash_delta, basis_delta, pnl, removed_cost, removed_fees):
        if abs(value) > MAX:
            raise ValueError('Settlement arithmetic overflow')
    return {'version': VERSION, 'symbol': symbol, 'cashDelta': cash_delta,
            'optionQuantity': option_qty, 'removedCost': removed_cost, 'removedEntryFees': removed_fees,
            'shareDelta': stock_delta, 'shareBasisDelta': basis_delta, 'realizedPnl': pnl,
            'feeCents': fee, 'externalOrder': False, 'source': 'paper_receipt'}
