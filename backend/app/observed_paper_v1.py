"""Independent, versioned market-priced virtual ledger transitions.

No broker adapter, network, synthetic-price fallback or implicit device import.
The SQL owner persists each transition and its exact observations atomically.
"""
from copy import deepcopy
from datetime import timedelta
from hashlib import sha256
import json
import re

from .engines import Bar
from .market_strategy import analyze, STRATEGIES
from .market_sessions import evaluate_session, prior_session_position, US_EQUITY_OPTIONS_POLICY
from .observed_option_replay import read_observation, iso
from .option_expiration import evaluate_expiration
from .paper_execution import project_execution, VERSION as EXECUTION_VERSION
from .paper_settlement import PATTERN, project, stamp, integer

VERSION = 'observed-paper-ledger-v1'
DEFAULTS = {'strategy':'trend','quantity':1,'riskPercent':5,'allocationPercent':30,
            'dailyLossPercent':3,'maxPositions':4,'maxContracts':10,'stopPercent':20,
            'takePercent':40,'trailPercent':15,'partialPercent':20,'holdingMode':'intraday',
            'maxHoldingDays':3,'contracts':{}}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)


def digest(value):
    return sha256(canonical(value).encode()).hexdigest()


def configuration(value):
    if not isinstance(value, dict) or set(value) != set(DEFAULTS):
        raise ValueError('Strict observed-paper configuration required')
    if value['strategy'] not in STRATEGIES or value['holdingMode'] not in ('intraday','swing'):
        raise ValueError('Unsupported observed-paper policy')
    for key, low, high in [('quantity',1,100),('riskPercent',1,20),('allocationPercent',1,100),
            ('dailyLossPercent',1,20),('maxPositions',1,10),('maxContracts',1,100),
            ('stopPercent',1,95),('takePercent',1,500),('trailPercent',0,95),
            ('partialPercent',0,500),('maxHoldingDays',1,365)]:
        if type(value[key]) is not int or not low <= value[key] <= high:
            raise ValueError('Invalid observed-paper limits')
    contracts = value['contracts']
    if not isinstance(contracts, dict) or len(contracts) > 10:
        raise ValueError('Bounded explicit contract watchlist required')
    for symbol, choices in contracts.items():
        if not isinstance(symbol, str) or not re.fullmatch(r'[A-Z]{1,6}', symbol) or not isinstance(choices, dict) or set(choices) - {'CALL','PUT'}:
            raise ValueError('Invalid contract identity')
        for direction, contract in choices.items():
            match = PATTERN.fullmatch(contract) if isinstance(contract, str) else None
            if not match or match[1] != symbol or ('CALL' if match[5] == 'C' else 'PUT') != direction or int(match[6]) <= 0 or int(match[6]) % 10:
                raise ValueError('Standard whole-cent OCC identity required')
            stamp(f'20{match[2]}-{match[3]}-{match[4]}T00:00:00Z')
    return deepcopy(value)


def create(account, name, initial, source):
    if not isinstance(account, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', account):
        raise ValueError('Invalid account identifier')
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80 or source not in ('fixture','alpaca'):
        raise ValueError('Invalid observed-paper account')
    if type(initial) is not int or not 10000 <= initial <= 100000000:
        raise ValueError('Invalid initial virtual capital')
    return {'contract':VERSION,'id':account,'name':name.strip(),'source':source,'initialCash':initial,
            'cash':initial,'realized':0,'fees':0,'enabled':False,'config':deepcopy(DEFAULTS),
            'positions':{},'deliveries':{},'dailyRealized':{},'consumption':{},'lastSignals':{},
            'closedTrades':0,'winningTrades':0,'lastAt':None,'executionContract':EXECUTION_VERSION}


def validate(state):
    if state['contract'] != VERSION or state['source'] not in ('alpaca','fixture') or type(state['enabled']) is not bool:
        raise ValueError('Invalid observed-paper state')
    configuration(state['config'])
    for key in ('cash','initialCash','fees','closedTrades','winningTrades'):
        integer(state[key])
    integer(abs(state['realized']))
    basis = 0
    for symbol, p in state['positions'].items():
        m = PATTERN.fullmatch(p['contract'])
        if not m or m[1] != symbol or not 1 <= integer(p['quantity']) <= 1000000:
            raise ValueError('Invalid owned contract')
        basis += integer(p['cost']); stamp(p['opened'])
        stamp(p['changedAt']); stamp(p['markAt']); integer(p['highBid']); integer(abs(p['roundPnl']))
        if type(p['partialTaken']) is not bool: raise ValueError('Invalid position policy')
        intent = p.get('closeIntent')
        if intent is not None and not 1 <= integer(intent['quantity']) <= p['quantity']:
            raise ValueError('Invalid residual close intent')
    for p in state['deliveries'].values():
        if integer(p['quantity']) <= 0:
            raise ValueError('Invalid delivered inventory')
        basis += integer(p['cost'])
        stamp(p['changedAt'])
    if state['cash'] + basis != state['initialCash'] + state['realized']:
        raise ValueError('Observed-paper balance invariant failed')
    if sum(state['dailyRealized'].values())!=state['realized'] or state['winningTrades']>state['closedTrades']:
        raise ValueError('Observed-paper performance invariant failed')


def apply(original, command, at):
    """Pure replayable transition; only supplied contemporaneous option quotes fill."""
    validate(original)
    state = deepcopy(original)
    at = stamp(at); at_text = iso(at)
    if state['lastAt'] and at < stamp(state['lastAt']):
        raise ValueError('Clock moved backwards')
    if not isinstance(command, dict) or not isinstance(command.get('kind'), str):
        raise ValueError('Strict command required')
    kind = command['kind']; facts = {'kind':kind,'fills':[],'blocked':[], 'externalOrder':False}
    if kind == 'CONFIGURE':
        if set(command) != {'kind','config'} or state['enabled']:
            raise ValueError('Stop before configuring')
        state['config'] = configuration(command['config'])
    elif kind == 'ENABLE':
        if set(command) != {'kind','enabled'} or type(command['enabled']) is not bool:
            raise ValueError('Explicit enable required')
        state['enabled'] = command['enabled']
    elif kind == 'REQUEST_CLOSE':
        if set(command) != {'kind','symbol'} or command['symbol'] not in state['positions']:
            raise ValueError('Owned position required')
        p = state['positions'][command['symbol']]
        p['closeIntent'] = {'quantity':p['quantity'],'reason':'MANUAL_CLOSE'}
    elif kind == 'CANCEL_CLOSE':
        if set(command) != {'kind','symbol'} or state['enabled'] or command['symbol'] not in state['positions']:
            raise ValueError('Stop before canceling an owned close intent')
        state['positions'][command['symbol']]['closeIntent'] = None
    elif kind == 'SETTLE':
        if set(command) != {'kind','request'} or state['enabled']:
            raise ValueError('Stop before explicit settlement')
        r = command['request']; m = PATTERN.fullmatch(r['contract']); symbol = m[1] if m else None
        position = state['positions'].get(symbol)
        if position and (position['contract'] != r['contract'] or position.get('closeIntent')):
            raise ValueError('Unresolved position or close intent')
        result = project(None if position is None else {**position,'entryFees':0}, state['deliveries'].get(symbol), state['cash'], r, at)
        # Late receipts are allowed only while their inventory has not moved
        # since the effective event. No historical inventory is silently rewritten.
        for inventory in (position, state['deliveries'].get(symbol)):
            if inventory and stamp(r['effectiveAt']) < stamp(inventory['changedAt']):
                raise ValueError('Receipt predates inventory movement')
        state['cash'] += result['cashDelta']
        if position and result['optionQuantity']:
            position['quantity'] -= result['optionQuantity']; position['cost'] -= result['removedCost']
            position['changedAt'] = r['effectiveAt']
            if not position['quantity']: state['positions'].pop(symbol)
        delivery = state['deliveries'].get(symbol, {'quantity':0,'cost':0})
        delivery['quantity'] += result['shareDelta']; delivery['cost'] += result['shareBasisDelta']
        if result['shareDelta']: delivery['changedAt'] = r['effectiveAt']
        if delivery['quantity']: state['deliveries'][symbol] = delivery
        else: state['deliveries'].pop(symbol, None)
        _realized(state, result['realizedPnl'], at_text)
        state['fees'] += r['feeCents']; facts['settlement'] = result
    elif kind == 'CYCLE':
        if set(command) != {'kind','observation'}:
            raise ValueError('Strict cycle required')
        _cycle(state, command['observation'], at, facts)
    else:
        raise ValueError('Unknown observed-paper command')
    state['lastAt'] = at_text
    validate(state)
    return state, facts


def _realized(state, amount, at):
    state['realized'] += amount
    day = at[:10]; state['dailyRealized'][day] = state['dailyRealized'].get(day, 0) + amount


def _cycle(state, observation, at, facts):
    if not isinstance(observation, dict) or set(observation) != {'source','capturedAt','quotes','bars','stockFeed'}:
        raise ValueError('Strict captured observation required')
    captured = stamp(observation['capturedAt'])
    if observation['source'] != state['source'] or not 0 <= (at-captured).total_seconds() <= 8:
        raise ValueError('Source mismatch or stale capture')
    if not isinstance(observation['quotes'], list) or len(observation['quotes']) > 30 or not isinstance(observation['bars'], dict) or len(observation['bars']) > 10:
        raise ValueError('Bounded observation required')
    quotes = {}
    for q in observation['quotes']:
        try:
            read_observation({'account':state['id'],'source':state['source'],'capturedAt':iso(captured),'quote':q})
            if q['contract'] in quotes:
                raise ValueError('Ambiguous option observation')
            quotes[q['contract']] = q
        except (KeyError, ValueError, TypeError):
            # A malformed member never hides a different qualified owned quote.
            if isinstance(q, dict) and isinstance(q.get('contract'), str): quotes[q['contract']] = None
    config = state['config']; session = evaluate_session(at, US_EQUITY_OPTIONS_POLICY)
    signals = {}; source_bars = {}
    for symbol, rows in observation['bars'].items():
        try:
            if observation['stockFeed'] not in ('iex','sip') or not isinstance(rows, list) or not 35 <= len(rows) <= 1000:
                raise ValueError()
            bars = [Bar(stamp(b['at']), *(b[k] for k in ('o','h','l','c','v'))) for b in rows]
            if any(set(b)!={'at','o','h','l','c','v'} for b in rows): raise ValueError()
            if any(type(v) not in (int,float) or abs(v)>1e12 for b in rows for k,v in b.items() if k!='at'): raise ValueError()
            if any(b.timestamp.second or b.timestamp.microsecond or b.timestamp+timedelta(minutes=1)>captured for b in bars): raise ValueError()
            if not 60 <= (at-bars[-1].timestamp).total_seconds() <= 150: raise ValueError()
            if any((b.timestamp-a.timestamp).total_seconds()!=60 for a,b in zip(bars[-35:],bars[-34:])): raise ValueError()
            signals[symbol] = analyze(bars, config['strategy']); source_bars[symbol] = bars
        except (KeyError, ValueError, TypeError, OverflowError, AttributeError):
            facts['blocked'].append({'symbol':symbol,'reason':'OPTIONAL_ANALYSIS_UNAVAILABLE'})

    def ordered_quote(contract):
        q = quotes.get(contract)
        if not q: return None
        prior = state['consumption'].get(contract)
        identity = digest(q); used = 0
        for position in state['positions'].values():
            if position['contract']==contract:
                if stamp(q['at'])<stamp(position['markAt']): return None
                if stamp(q['at'])==stamp(position['markAt']) and identity!=position['markIdentity']: return None
        if prior:
            if stamp(q['at']) < stamp(prior['at']): return None
            if stamp(q['at']) == stamp(prior['at']):
                if identity != prior['identity']: return None
                used = prior['quantity']
        return q, used, identity

    def execution(contract, side, requested):
        ordered = ordered_quote(contract)
        if ordered is None: return None
        q, used, identity = ordered
        model = project_execution(q, side, requested, used, at)
        if model['quantity'] <= 0: return None
        return q, model, used, identity

    def consume(symbol, side, item, reason):
        q, model, used, identity = item
        state['consumption'][q['contract']] = {'at':q['at'],'identity':identity,'quantity':used+model['quantity']}
        state['cash'] += model['cashDeltaCents']; state['fees'] += model['feeCents']
        facts['fills'].append({'symbol':symbol,'contract':q['contract'],'side':side,'reason':reason,'quote':q,'execution':model})

    closed = set()
    for symbol, p in list(state['positions'].items()):
        if not state['enabled'] and not p.get('closeIntent'): continue
        ordered = ordered_quote(p['contract']); q = ordered[0] if ordered else None
        timing = evaluate_expiration(_expiry(p['contract']), at)
        if not timing['close_fill_allowed']:
            facts['blocked'].append({'symbol':symbol,'reason':'EXPIRY_REVIEW_REQUIRED'}); continue
        if state['enabled']:
            reason = None; quantity = p['quantity']
            if config['holdingMode']=='intraday' and (session.exit_due or prior_session_position(stamp(p['opened']),at)): reason='INTRADAY_EXIT'
            elif at-stamp(p['opened']) >= timedelta(days=config['maxHoldingDays']): reason='MAXIMUM_HOLDING'
            elif not timing['entry_allowed']: reason='EXPIRY_PROTECTION'
            if q and project_execution(q,'SELL_TO_CLOSE',1,0,at)['quantity']:
                bid = q['bid']-1; p['highBid'] = max(p['highBid'], bid)
                p['markAt']=q['at']; p['markIdentity']=digest(q)
                proceeds = bid*100*p['quantity']-70*p['quantity']; pnl = proceeds-p['cost']
                if pnl*100 <= -p['cost']*config['stopPercent']: reason='STOP_LOSS'
                elif pnl*100 >= p['cost']*config['takePercent']: reason='TAKE_PROFIT'
                elif config['trailPercent'] and bid*100 <= p['highBid']*(100-config['trailPercent']): reason='TRAILING_STOP'
                elif not reason and not p['partialTaken'] and p['quantity']>1 and config['partialPercent'] and pnl*100>=p['cost']*config['partialPercent']:
                    reason='PARTIAL_PROFIT'; quantity=(p['quantity']+1)//2
            signal = signals.get(symbol)
            if signal and signal['confirmedReverse'] and signal['direction'] not in ('WAIT', _direction(p['contract'])):
                reason='CONFIRMED_REVERSAL'; quantity=p['quantity']
            existing = p.get('closeIntent')
            if reason and (not existing or existing['reason']=='PARTIAL_PROFIT' and reason!='PARTIAL_PROFIT'):
                p['closeIntent']={'quantity':quantity,'reason':reason}
        intent = p.get('closeIntent')
        if not intent or not session.fill_allowed: continue
        item = execution(p['contract'],'SELL_TO_CLOSE',intent['quantity'])
        if not item: continue
        quantity = item[1]['quantity']; removed = p['cost']*quantity//p['quantity']
        realized = item[1]['cashDeltaCents']-removed
        consume(symbol,'SELL_TO_CLOSE',item,intent['reason']); _realized(state,realized,iso(at))
        p['quantity']-=quantity; p['cost']-=removed; p['roundPnl']+=realized; intent['quantity']-=quantity
        p['changedAt']=iso(at)
        if not p['quantity']:
            state['closedTrades']+=1; state['winningTrades']+=int(p['roundPnl']>0)
            state['positions'].pop(symbol); closed.add(symbol)
        elif not intent['quantity']:
            if intent['reason']=='PARTIAL_PROFIT': p['partialTaken']=True
            p['closeIntent']=None
    if not state['enabled'] or not session.entry_allowed: return
    for symbol, choices in config['contracts'].items():
        if symbol in state['positions'] or symbol in closed: continue
        signal = signals.get(symbol)
        if not signal or signal['direction']=='WAIT': continue
        contract = choices.get(signal['direction'])
        if not contract or not evaluate_expiration(_expiry(contract),at)['entry_allowed']: continue
        # This first durable engine release has no independently qualified
        # deliverable/Greek metadata adapter. OPRA prices alone must not silently
        # turn the fixture eligibility assumption into a market-entry authority.
        # Owned protection and explicit paper settlement remain independent.
        if state['source']=='alpaca':
            facts['blocked'].append({'symbol':symbol,'reason':'CONTRACT_ELIGIBILITY_UNVERIFIED'})
            continue
        signal_key = config['strategy']+'|'+iso(source_bars[symbol][-1].timestamp)
        if state['lastSignals'].get(symbol)==signal_key: continue
        item = execution(contract,'BUY',config['quantity'])
        if not item: continue
        ordered_quotes={c:ordered_quote(c)[0] for c in quotes if ordered_quote(c) is not None}
        cost = -item[1]['cashDeltaCents']; reason = _risk(state,cost,item[1]['quantity'],ordered_quotes,at)
        if reason:
            facts['blocked'].append({'symbol':symbol,'reason':reason}); continue
        consume(symbol,'BUY',item,signal['reason'])
        state['positions'][symbol] = {'contract':contract,'quantity':item[1]['quantity'],'cost':cost,'opened':iso(at),
            'highBid':max(0,item[0]['bid']-1),'partialTaken':False,'closeIntent':None,'roundPnl':0,'changedAt':iso(at),
            'markAt':item[0]['at'],'markIdentity':digest(item[0])}
        state['lastSignals'][symbol] = signal_key
    # Only expired operational quote-use cache is pruned; immutable events retain
    # every original quote and fill. Active contract chronology is never pruned.
    active = {p['contract'] for p in state['positions'].values()} | {c for choices in config['contracts'].values() for c in choices.values()}
    state['consumption'] = {c:v for c,v in state['consumption'].items() if c in active or at-stamp(v['at'])<=timedelta(seconds=30)}


def _expiry(contract):
    match = PATTERN.fullmatch(contract)
    return stamp(f'20{match[2]}-{match[3]}-{match[4]}T00:00:00Z').date()


def _direction(contract):
    return 'CALL' if PATTERN.fullmatch(contract)[5]=='C' else 'PUT'


def _risk(state, cost, quantity, quotes, at):
    c = state['config']; initial = state['initialCash']; positions = state['positions']
    if state['deliveries']: return 'DELIVERED_STOCK_REVIEW_REQUIRED'
    if any(p.get('closeIntent') for p in positions.values()): return 'UNRESOLVED_CLOSE_INTENT'
    if cost>state['cash'] or cost*100>initial*c['riskPercent']: return 'TRADE_RISK_LIMIT'
    if (sum(p['cost'] for p in positions.values())+cost)*100>initial*c['allocationPercent']: return 'ALLOCATION_RISK_LIMIT'
    if len(positions)>=c['maxPositions'] or sum(p['quantity'] for p in positions.values())+quantity>c['maxContracts']: return 'POSITION_OR_QUANTITY_LIMIT'
    loss = max(0,-state['dailyRealized'].get(iso(at)[:10],0))
    for p in positions.values():
        q = quotes.get(p['contract'])
        if not q or project_execution(q,'SELL_TO_CLOSE',1,0,at)['quantity']<=0: return 'OPTION_MARK_UNAVAILABLE'
        loss += max(0,p['cost']-((q['bid']-1)*100-70)*p['quantity'])
    if loss*100>=initial*c['dailyLossPercent']: return 'DAILY_LOSS_LIMIT'
    return None
