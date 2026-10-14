"""Portable paper share marks, never fills or evidence of broker ownership."""
from datetime import timedelta
import re
from .paper_settlement import integer, stamp

VERSION = 'paper-delivery-valuation-v1'
FIELDS = {'version', 'symbol', 'source', 'feed', 'at', 'capturedAt', 'bidCents', 'askCents'}


def value_deliveries(deliveries, observations, now, source):
    if source not in ('fixture', 'alpaca') or now.tzinfo is None:
        raise ValueError('Explicit observation source and clock required')
    rows, basis, liquidation, exposure, loss = [], 0, 0, 0, 0
    complete = risk_complete = True
    for symbol, position in deliveries.items():
        qty, cost = integer(position['quantity'], 1), integer(position['cost'], 1)
        basis = integer(basis + cost)
        observation = observations.get(symbol)
        status, amount, reserve, pnl = 'MISSING', None, None, None
        try:
            if observation is not None:
                status = 'INVALID'
                if (not isinstance(observation, dict) or set(observation) != FIELDS
                        or observation['version'] != VERSION or observation['symbol'] != symbol
                        or not re.fullmatch(r'[A-Z]{1,6}', symbol)
                        or observation['feed'] not in ('iex', 'sip')):
                    raise ValueError()
                bid, ask = integer(observation['bidCents'], 1), integer(observation['askCents'], 1)
                if ask > 100000000 or bid > ask or (ask - bid) * 5 > ask:
                    raise ValueError()
                at, captured = stamp(observation['at']), stamp(observation['capturedAt'])
                if at > captured:
                    raise ValueError()
                status = 'SOURCE_MISMATCH'
                if observation['source'] != source:
                    raise ValueError()
                status = 'NOT_YET_KNOWN'
                if captured > now:
                    raise ValueError()
                status = 'STALE'
                if now - at > timedelta(seconds=30):
                    raise ValueError()
                status = 'INVALID'
                amount = integer(bid * qty)
                reserve = max(cost, integer(ask * qty))
                integer(liquidation + amount)
                integer(exposure + reserve)
                integer(loss + max(0, cost - amount))
                pnl = amount - cost
                status = 'QUALIFIED' if observation['feed'] == 'sip' else 'IEX_PARTIAL_MARK'
        except (ValueError, TypeError, KeyError, OverflowError):
            amount = reserve = pnl = None
        if amount is None:
            complete = False
        else:
            liquidation += amount
            exposure += reserve
            loss += max(0, -pnl)
        if status != 'QUALIFIED':
            risk_complete = False
        rows.append({'symbol': symbol, 'quantity': qty, 'basisCents': cost,
                     'status': status, 'valueCents': amount, 'unrealizedPnlCents': pnl,
                     'exposureCents': reserve})
    return {'version': VERSION, 'complete': complete, 'riskComplete': risk_complete,
            'basisCents': basis, 'valueCents': liquidation if complete else None,
            'unrealizedPnlCents': liquidation - basis if complete else None,
            'exposureCents': exposure if risk_complete else None,
            'openLossCents': loss if risk_complete else None, 'positions': rows,
            'modeledExitFeeCents': 0, 'externalOrder': False,
            'policy': 'observed_bid_gross_no_guaranteed_fill;iex_display_only;sip_required_for_new_risk'}


def saved_delivery_valuation(db, account_id, now):
    """Read existing account-bound, digest-verified journal; never fetch or write."""
    from decimal import Decimal, InvalidOperation
    from .market_data_journal import _decode, JournalError
    deliveries = {p['symbol']: p for p in db.all(
        'SELECT symbol,quantity,cost FROM paper_delivery_positions WHERE account_id=?', (account_id,))}
    marks = {}
    for symbol in deliveries:
        row = db.one("SELECT * FROM market_data_journal WHERE account_id=? AND symbol=? AND kind='stock_snapshot' ORDER BY sequence DESC LIMIT 1", (account_id, symbol))
        if row is None:
            continue
        marks[symbol] = {}  # Corrupt newest evidence never silently falls back.
        try:
            record = _decode(row)
            observation = record['observation']
            if observation['provider'] != 'alpaca' or observation['data']['symbol'] != symbol or observation['account_id'] != account_id:
                raise ValueError()
            quote = observation['data']['quote']
            def cents(value):
                scaled = Decimal(str(value)) * 100
                if not scaled.is_finite() or scaled != scaled.to_integral_value():
                    raise ValueError()
                return integer(int(scaled), 1)
            marks[symbol] = {'version': VERSION, 'symbol': symbol, 'source': 'alpaca',
                'feed': observation['feed'], 'at': quote['timestamp'], 'capturedAt': record['recorded_at'],
                'bidCents': cents(quote['bp']), 'askCents': cents(quote['ap'])}
        except (JournalError, ValueError, KeyError, TypeError, InvalidOperation):
            pass
    return value_deliveries(deliveries, marks, now, 'alpaca')
