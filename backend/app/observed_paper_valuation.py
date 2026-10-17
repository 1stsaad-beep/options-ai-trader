"""Read-only, version-bound liquidation model from accepted original quotes.

This is neither an execution receipt nor a new-entry/Greek entitlement. The
whole position must fit the remaining conservative displayed-size allowance.
Missing stock quotes cannot be replaced by an option, candle or settlement price.
"""
from datetime import timedelta
import json

from .observed_option_replay import iso, read_observation
from .observed_paper import digest
from .paper_execution import project_execution
from .paper_settlement import integer, stamp

VERSION = 'observed-paper-valuation-v1'


def summarize(rows, state, now):
    as_of = iso(now)
    if state['lastAt'] and stamp(state['lastAt']) > now:
        raise ValueError('Valuation clock precedes current state')
    wanted = {}
    for p in state['positions'].values():
        authority = {'at': p['markAt'], 'identity': p['markIdentity']}
        consumed = state['consumption'].get(p['contract'])
        # A stopped partial close may have a newer accepted fill quote than
        # the last protection mark. Never resurrect the older liquidity.
        if consumed and stamp(consumed['at']) > stamp(authority['at']):
            authority = consumed
        wanted[p['contract']] = authority
    quotes = {}
    # Caller streams newest first; only one original event and active matches
    # are resident. No full event list or historical account state is copied.
    if wanted:
        for row in rows:
            original = json.loads(row['payload'])
            if stamp(original['at']) > now:
                continue
            if stamp(original['at']) < now - timedelta(seconds=30):
                break
            command = original['command']
            if command['kind'] != 'CYCLE':
                continue
            observation = command['observation']
            if observation['source'] != state['source'] or stamp(observation['capturedAt']) > now:
                continue
            for quote in observation['quotes']:
                if not isinstance(quote, dict):
                    continue
                contract = quote.get('contract')
                authority = wanted.get(contract) if isinstance(contract, str) else None
                if (not authority or contract in quotes or quote.get('at') != authority['at']
                        or digest(quote) != authority['identity']):
                    continue
                try:
                    read_observation({'account': state['id'], 'source': state['source'],
                        'capturedAt': observation['capturedAt'], 'quote': quote})
                    read_observation({'account': state['id'], 'source': state['source'],
                        'capturedAt': as_of, 'quote': quote})
                except (ValueError, TypeError, KeyError, OverflowError):
                    continue
                quotes[contract] = (quote, observation['capturedAt'])
            if len(quotes) == len(wanted):
                break
    options = []; deliveries = []; basis = amount = 0; complete = True
    for symbol, position in sorted(state['positions'].items()):
        basis = integer(basis + position['cost'])
        leg = {'symbol': symbol, 'contract': position['contract'], 'quantity': position['quantity'],
            'basisCents': position['cost'], 'status': 'QUALIFIED_ORIGINAL_QUOTE_UNAVAILABLE',
            'valueCents': None, 'unrealizedPnlCents': None, 'quote': None, 'capturedAt': None,
            'modeledExitFeeCents': None, 'modeledAvailableQuantity': 0}
        saved = quotes.get(position['contract'])
        if saved:
            quote, captured = saved
            prior = state['consumption'].get(position['contract'])
            consumed = prior['quantity'] if prior and prior['at'] == quote['at'] and prior['identity'] == digest(quote) else 0
            model = project_execution(quote, 'SELL_TO_CLOSE', position['quantity'], consumed, now)
            leg.update(quote=quote, capturedAt=captured, status='INSUFFICIENT_REMAINING_LIQUIDITY',
                modeledAvailableQuantity=model['quantity'])
            if model['quantity'] == position['quantity'] and model['cashDeltaCents'] is not None:
                value = integer(model['cashDeltaCents'])
                leg.update(status='OBSERVED_MODEL', valueCents=value,
                    unrealizedPnlCents=value-position['cost'], modeledExitFeeCents=model['feeCents'])
                amount = integer(amount + value)
        complete = complete and leg['valueCents'] is not None
        options.append(leg)
    for symbol, position in sorted(state['deliveries'].items()):
        basis = integer(basis + position['cost']); complete = False
        deliveries.append({'symbol': symbol, 'quantity': position['quantity'], 'basisCents': position['cost'],
            'status': 'QUALIFIED_STOCK_QUOTE_UNAVAILABLE', 'valueCents': None})
    equity = integer(state['cash'] + amount) if complete else None
    return {'contract': VERSION, 'account': state['id'], 'source': state['source'], 'asOf': as_of,
        'externalOrder': False, 'executionAllowed': False, 'newEntryAllowed': False,
        'status': ('OBSERVED_MODEL' if options else 'CASH_ONLY') if complete else 'INCOMPLETE',
        'complete': complete, 'cashCents': state['cash'], 'ownedBasisCents': basis,
        'liquidationEquityCents': equity, 'unrealizedPnlCents': amount-basis if complete else None,
        'totalPnlCents': equity-state['initialCash'] if complete else None,
        'options': options, 'deliveries': deliveries,
        'policy': 'original_opra_bid_minus_one_cent_and_70_cent_exit_fee_remaining_25pct_size',
        'limitations': ['Read-only model; no guaranteed fill, queue priority or new risk authority',
            'Complete current valuation does not establish a historical equity drawdown or Sharpe',
            'Missing delivery stock quotes make the whole portfolio incomplete']}
