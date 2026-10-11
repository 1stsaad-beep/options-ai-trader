"""Durable quantitative Mock reversal/scaling. No broker or narrative-AI input.

Callers supply completed bars and explicit synthetic quotes. Fresh quantitative
analysis is recomputed after flatness; an earlier proposal never authorizes the
new direction. Orders still pass TradingService under its repository risk lock.
"""
from contextlib import contextmanager
from copy import copy
from datetime import date, datetime, timedelta
import hashlib
import json
import uuid
from math import isclose

from .engines import AnalysisPipeline, OptionsSelectionEngine, OptionQuote
from .service import Rejected, validate_config


class _Bound:
    def __init__(self, db):
        self.db = db

    @contextmanager
    def transaction(self):
        yield self.db


def _service(service, db, intent_id=None):
    bound=copy(service)
    bound.repo=_Bound(db)
    bound._automation_authorized=True
    bound._automatic_origin=bool(getattr(service,'_automatic_origin',getattr(service,'_automation_authorized',False)))
    bound._intent_id=intent_id
    return bound


def _key(*parts):
    return hashlib.sha256('|'.join(map(str,parts)).encode()).hexdigest()


def _fresh(service, db, account_id, symbol):
    account=service.account(db,account_id)
    validate_config(account['config'])
    if not service.snapshot_valid(account) or not service.market_valid(db,account_id,symbol):
        raise Rejected('Lifecycle requires trusted fresh account and market observations')
    if account['config']['mode']!='paper' or account['config']['broker']!='mock':
        raise Rejected('Lifecycle is Mock only; Live and external brokers locked')
    service._validate_ledger(db,account_id)
    return account


def _analysis(service, account, symbol, bars, quotes, right):
    bars=list(bars)
    quotes=list(quotes)
    if any(not isinstance(q,OptionQuote) for q in quotes) or len({q.key for q in quotes})!=len(quotes):
        raise Rejected('Unique typed option quote snapshot required')
    analysis=AnalysisPipeline().analyze(bars,service.now())
    signal=next((s for s in analysis.signals if s.right==right and s.strategy in account['config']['strategies']),None)
    if signal is None:
        raise Rejected('Fresh quantitative signal no longer qualifies')
    quote=OptionsSelectionEngine().select(list(quotes),symbol,right,service.now(),max_spread_pct=account['config']['max_spread_pct']/100)
    if quote is None:
        raise Rejected('No eligible fresh target contract')
    for value in (quote.bid,quote.ask,quote.strike):
        if not isclose(value*100,round(value*100),abs_tol=1e-7):
            raise Rejected('Lifecycle quotes require exact-cent prices')
    bar_facts=[{'at':b.timestamp.isoformat(),'open':b.open,'high':b.high,'low':b.low,'close':b.close,'volume':b.volume} for b in bars]
    facts={'strategy':signal.strategy,'right':right,'symbol':symbol,'observed_at':signal.timestamp.isoformat(),'decision_at':service.now().isoformat(),'rule':'completed_bar_quantitative_v1','quote_at':quote.timestamp.isoformat(),'quantitative_reason':signal.reason,'score':signal.score,'regime':analysis.regime,'atr':analysis.atr,'bars_digest':hashlib.sha256(json.dumps(bar_facts,sort_keys=True).encode()).hexdigest(),'completed_bars':bar_facts[-512:],'contract':{'right':quote.right,'expiry':quote.expiry.isoformat(),'strike':quote.strike,'bid':quote.bid,'ask':quote.ask,'multiplier':quote.multiplier,'delta':quote.delta,'iv':quote.iv,'open_interest':quote.open_interest}}
    return quote,facts


def _quote(service, position, quotes):
    matches=[q for q in quotes if (q.symbol,q.right,q.expiry,round(q.strike*100))==(position['symbol'],position['right_kind'],date.fromisoformat(position['expiry']),position['strike'])]
    if len(matches)!=1:
        raise Rejected('Unique owned contract quote required')
    q=matches[0]
    for value in (q.bid,q.ask,q.strike):
        if not isclose(value*100,round(value*100),abs_tol=1e-7):
            raise Rejected('Owned quotes require exact-cent prices')
    if not 0 <= (service.now()-q.timestamp).total_seconds() <= 60 or q.bid<=0 or q.ask<q.bid:
        raise Rejected('Owned quote is stale, future or invalid')
    return q


def request_reversal(service, account_id, request_key, symbol, target_right, bars, quotes):
    """Record a confirmed opposing strategy and start cancelling/closing owned risk."""
    if target_right not in ('CALL','PUT') or not isinstance(request_key,str) or not 1<=len(request_key)<=80:
        raise Rejected('Valid reversal direction and key required')
    identity={'symbol':symbol,'target_right':target_right}
    fingerprint=_key(json.dumps(identity,sort_keys=True))
    with service.repo.transaction() as db:
        prior=db.one('SELECT * FROM lifecycle_intents WHERE account_id=? AND request_key=?',(account_id,request_key))
        if prior:
            if prior['fingerprint']!=fingerprint or prior['kind']!='REVERSAL':
                raise Rejected('Lifecycle idempotency payload mismatch')
            return prior
        account=_fresh(service,db,account_id,symbol)
        if account['stopped'] or db.one('SELECT stopped FROM supervisor WHERE id=1')['stopped']:
            raise Rejected('Emergency stop blocks new reversal plans')
        if db.one("SELECT id FROM lifecycle_intents WHERE account_id=? AND symbol=? AND kind='REVERSAL' AND state NOT IN ('COMPLETE','EXPIRED','CANCELLED')",(account_id,symbol)):
            raise Rejected('Unresolved reversal already owns this symbol')
        quotes=list(quotes)
        _,facts=_analysis(service,account,symbol,bars,quotes,target_right)
        positions=db.all('SELECT * FROM positions WHERE account_id=? AND symbol=?',(account_id,symbol))
        if not positions or any(p['right_kind']==target_right for p in positions):
            raise Rejected('Reversal requires owned opposite direction')
        # Validate every close quote before changing any reservation.
        closing=[(p,_quote(service,p,quotes)) for p in positions]
        identifier=str(uuid.uuid4())
        payload={**identity,'automatic':bool(getattr(service,'_automation_authorized',False)),'facts':facts,'expires_at':(service.now()+timedelta(seconds=60)).isoformat(),'close_order_ids':[]}
        bound=_service(service,db,identifier)
        bound._decision_context={'reason':'QUANTITATIVE_REVERSAL_CLOSE','signal':facts}
        for order in db.all("SELECT * FROM orders WHERE account_id=? AND symbol=? AND side='BUY' AND status IN ('PENDING','PARTIAL')",(account_id,symbol)):
            bound.cancel(account_id,order['id'])
        for position,q in closing:
            key=(account_id,symbol,position['right_kind'],position['expiry'],position['strike'])
            reserved=db.all("SELECT * FROM orders WHERE account_id=? AND symbol=? AND right_kind=? AND expiry=? AND strike=? AND side='SELL_TO_CLOSE' AND status IN ('PENDING','PARTIAL')",key)
            payload['close_order_ids'].extend(o['id'] for o in reserved)
            available=position['quantity']-sum(o['quantity']-o['filled'] for o in reserved)
            if available:
                order=bound.submit(account_id,dict(request_key='v1-r:'+_key(identifier,*key),symbol=symbol,right=position['right_kind'],expiry=position['expiry'],strike_cents=position['strike'],side='SELL_TO_CLOSE',quantity=available,limit_cents=round(q.bid*100)))
                payload['close_order_ids'].append(order['id'])
        stamp=service.now().isoformat()
        db.execute('INSERT INTO lifecycle_intents VALUES(?,?,?,?,?,?,?,?,?,?,?)',(identifier,account_id,request_key,'REVERSAL',symbol,fingerprint,json.dumps(payload,sort_keys=True),'WAIT_FLAT',None,stamp,stamp))
        service.decision(db,account_id,'REVERSAL_REQUESTED',payload,intent_id=identifier)
        return db.one('SELECT * FROM lifecycle_intents WHERE id=?',(identifier,))


def advance_reversal(service, account_id, intent_id, bars, quotes):
    with service.repo.transaction() as db:
        intent=db.one("SELECT * FROM lifecycle_intents WHERE account_id=? AND id=? AND kind='REVERSAL'",(account_id,intent_id))
        if not intent:
            raise Rejected('Unknown account reversal')
        if intent['state'] in ('COMPLETE','EXPIRED','CANCELLED'):
            return intent
        payload=json.loads(intent['payload'])
        account=_fresh(service,db,account_id,intent['symbol'])
        if payload.get('automatic') and not account['config']['reversal_enabled']:
            raise Rejected('Automatic reversal disabled after intent creation')
        bound=_service(service,db,intent_id)
        bound._automatic_origin=payload['automatic']
        if intent['order_id']:
            order=db.one('SELECT * FROM orders WHERE account_id=? AND id=?',(account_id,intent['order_id']))
            if order['status']=='FILLED':
                db.execute("UPDATE lifecycle_intents SET state='COMPLETE',updated=? WHERE id=?",(service.now().isoformat(),intent_id))
            elif order['status'] in ('CANCELLED','EXPIRED'):
                db.execute("UPDATE lifecycle_intents SET state='CANCELLED',updated=? WHERE id=?",(service.now().isoformat(),intent_id))
            return db.one('SELECT * FROM lifecycle_intents WHERE id=?',(intent_id,))
        pending=db.one("SELECT id FROM orders WHERE account_id=? AND symbol=? AND status IN ('PENDING','PARTIAL')",(account_id,intent['symbol']))
        owned=db.one('SELECT symbol FROM positions WHERE account_id=? AND symbol=?',(account_id,intent['symbol']))
        if owned or pending:
            return intent  # Neither elapsed time nor partial fills prove flatness.
        if service.now()>datetime.fromisoformat(payload['expires_at']):
            db.execute("UPDATE lifecycle_intents SET state='EXPIRED',updated=? WHERE id=?",(service.now().isoformat(),intent_id))
            return db.one('SELECT * FROM lifecycle_intents WHERE id=?',(intent_id,))
        # A repriced close cancels one receipt and creates a replacement. All
        # old reservations must be terminal; flatness is proven by the complete
        # account fill ledger above, never by cancelled receipt status alone.
        if any(db.one('SELECT status FROM orders WHERE id=? AND account_id=?',(oid,account_id))['status'] not in ('FILLED','CANCELLED') for oid in payload['close_order_ids']):
            raise Rejected('Reversal close receipts remain unresolved')
        bound.reconcile(account_id)
        quote,facts=_analysis(bound,account,intent['symbol'],bars,quotes,payload['target_right'])
        bound._decision_context={'reason':'REVALIDATED_REVERSAL_ENTRY','signal':facts,'reconciled_at':service.now().isoformat()}
        order=bound.submit(account_id,dict(request_key='v1-r:'+_key(intent_id,'entry'),symbol=intent['symbol'],right=quote.right,expiry=quote.expiry.isoformat(),strike_cents=round(quote.strike*100),side='BUY',quantity=account['config']['auto_quantity'],limit_cents=round(quote.ask*100)))
        db.execute("UPDATE lifecycle_intents SET state='WAIT_ENTRY',order_id=?,updated=? WHERE id=?",(order['id'],service.now().isoformat(),intent_id))
        service.decision(db,account_id,'REVERSAL_REVALIDATED',facts,order['id'],intent_id)
        return db.one('SELECT * FROM lifecycle_intents WHERE id=?',(intent_id,))


def request_scaling(service, account_id, request_key, symbol, right, bars, quotes):
    """Reserve an addition once, only after fresh profitable owned-position evidence."""
    if not isinstance(request_key,str) or not 1<=len(request_key)<=80 or right not in ('CALL','PUT'):
        raise Rejected('Valid scaling key and direction required')
    fingerprint=_key(symbol,right,'SCALING')
    with service.repo.transaction() as db:
        prior=db.one('SELECT * FROM lifecycle_intents WHERE account_id=? AND request_key=?',(account_id,request_key))
        if prior:
            if prior['fingerprint']!=fingerprint or prior['kind']!='SCALING':
                raise Rejected('Lifecycle idempotency payload mismatch')
            return prior
        account=_fresh(service,db,account_id,symbol)
        config=account['config']
        if not config['scaling_enabled']:
            raise Rejected('Position scaling disabled')
        if db.one("SELECT id FROM lifecycle_intents WHERE account_id=? AND symbol=? AND kind='REVERSAL' AND state NOT IN ('COMPLETE','EXPIRED','CANCELLED')",(account_id,symbol)):
            raise Rejected('Reversal takes precedence over scaling')
        if db.one("SELECT id FROM orders WHERE account_id=? AND symbol=? AND status IN ('PENDING','PARTIAL')",(account_id,symbol)):
            raise Rejected('Unresolved orders take precedence over scaling')
        positions=db.all('SELECT * FROM positions WHERE account_id=? AND symbol=? AND right_kind=?',(account_id,symbol,right))
        if len(positions)!=1:
            raise Rejected('Scaling requires one unambiguous owned long contract')
        position=positions[0]
        quotes=list(quotes)
        q=_quote(service,position,quotes)
        service.record_option_mark(db,account_id,symbol,right,position['expiry'],position['strike'],round(q.bid*100),round(q.ask*100),q.timestamp)
        if (round(q.bid*100)*100-config['commission_cents'])*position['quantity']<=position['cost']:
            raise Rejected('Scaling requires a profitable fresh bid mark')
        selected,facts=_analysis(service,account,symbol,bars,quotes,right)
        if selected.key!=q.key:
            raise Rejected('Scaling target must be the existing contract')
        policy=db.one('SELECT * FROM position_policies WHERE account_id=? AND symbol=? AND right_kind=? AND expiry=? AND strike=?',(account_id,symbol,right,position['expiry'],position['strike']))
        if not policy:
            raise Rejected('Position generation unavailable for scaling')
        prior_adds=[r for r in db.all("SELECT * FROM lifecycle_intents WHERE account_id=? AND symbol=? AND kind='SCALING'",(account_id,symbol)) if json.loads(r['payload'])['generation']==policy['generation']]
        if len(prior_adds)>=config['scaling_max_additions']:
            raise Rejected('Scaling addition budget exhausted')
        if prior_adds and (service.now()-max(datetime.fromisoformat(r['created']) for r in prior_adds)).total_seconds()<config['scaling_cooldown_seconds']:
            raise Rejected('Scaling cooldown active')
        quantity=config['scaling_quantity']//(2**len(prior_adds)) if config['scaling_decreasing'] else config['scaling_quantity']
        if quantity<1:
            raise Rejected('Decreasing scale rounds to zero contracts')
        identifier=str(uuid.uuid4())
        payload={'generation':policy['generation'],'addition_number':len(prior_adds)+1,'mark_bid_cents':round(q.bid*100),'quantity':quantity,'facts':facts}
        bound=_service(service,db,identifier)
        bound._decision_context={'reason':'PROFITABLE_POSITION_SCALING',**payload}
        order=bound.submit(account_id,dict(request_key='v1-s:'+_key(identifier),symbol=symbol,right=right,expiry=position['expiry'],strike_cents=position['strike'],side='BUY',quantity=quantity,limit_cents=round(q.ask*100)))
        stamp=service.now().isoformat()
        db.execute('INSERT INTO lifecycle_intents VALUES(?,?,?,?,?,?,?,?,?,?,?)',(identifier,account_id,request_key,'SCALING',symbol,fingerprint,json.dumps(payload,sort_keys=True),'RESERVED',order['id'],stamp,stamp))
        service.decision(db,account_id,'SCALING_RESERVED',payload,order['id'],identifier)
        return db.one('SELECT * FROM lifecycle_intents WHERE id=?',(identifier,))
