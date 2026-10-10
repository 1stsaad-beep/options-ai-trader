"""Opt-in deterministic Mock execution; no network adapter or LLM authority.

A cycle owns the repository risk lock and transaction. Every mutation still goes
through TradingService. Existing order/fill keys are the durable recovery cursor.
"""
from contextlib import contextmanager
from copy import copy
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
from math import isclose

from .engines import AnalysisPipeline, OptionQuote, OptionsSelectionEngine, OpportunityRanking
from .service import ACTIVE, Rejected, validate_config


def fixture_quotes(symbol, now, contracts=()):
    """Explicit synthetic quotes; prices never represent real market prices."""
    expiry = now.date() + timedelta(days=14)
    expiry += timedelta(days=(4-expiry.weekday()) % 7)
    strike = {'NVDA': 100, 'AAPL': 200, 'TSLA': 250}.get(symbol, 150)
    identities = {(symbol, expiry, right, float(strike)) for right in ('CALL', 'PUT')}
    for row in contracts:
        if row['symbol'] == symbol:
            identities.add((symbol, date.fromisoformat(row['expiry']), row['right_kind'], row['strike']/100))
    return [OptionQuote(s, e, r, k, 1.00, 1.05, .5 if r == 'CALL' else -.5,
                        .3, 1000, now.replace(microsecond=0))
            for s, e, r, k in sorted(identities)]


class _BoundRepository:
    """Service calls share the outer transaction; no nested commits/unlocks."""
    def __init__(self, session):
        self.session = session

    @contextmanager
    def transaction(self):
        yield self.session


def _key(prefix, *parts):
    return prefix + sha256('|'.join(str(p) for p in parts).encode()).hexdigest()


def _contract(row):
    return (row['symbol'], date.fromisoformat(row['expiry']), row['right_kind'], row['strike']/100)


def _cents(value):
    cents = round(value*100)
    if cents <= 0 or not isclose(value*100, cents, abs_tol=1e-7):
        raise Rejected('Synthetic option quote must have positive exact-cent prices')
    return cents


def run_account(service, account_id, now=None, feed=None, quote_feed=None):
    """Run one opt-in paper/mock cycle, returning auditable actions and blockers.

    feed(symbol, as_of) -> completed bars; quote_feed(symbol, as_of) -> quotes.
    Injection points are local test dependencies, never API-provided order text.
    A disconnected/stale snapshot requires explicit operator reconciliation.
    """
    now = now or service.now()
    result = {'account_id': account_id, 'source': 'synthetic_mock', 'live_enabled': False,
              'orders_submitted': 0, 'fills_applied': 0, 'expired_positions': 0,
              'actions': [], 'blocked_reasons': []}
    try:
        if now.tzinfo is None or abs((now-service.now()).total_seconds()) > 1:
            raise Rejected('Automation clock must match the trusted service clock')
        with service.repo.transaction() as db:
            bound = copy(service)
            bound.repo = _BoundRepository(db)
            bound._automation_authorized = True
            before_orders=db.one('SELECT COUNT(*) AS n FROM orders WHERE account_id=?',(account_id,))['n']
            before_fills=db.one('SELECT COUNT(*) AS n FROM fills f JOIN orders o ON o.id=f.order_id WHERE o.account_id=?',(account_id,))['n']
            _cycle(bound, db, account_id, now, feed, quote_feed, result)
            result['orders_submitted']=db.one('SELECT COUNT(*) AS n FROM orders WHERE account_id=?',(account_id,))['n']-before_orders
            result['fills_applied']=db.one('SELECT COUNT(*) AS n FROM fills f JOIN orders o ON o.id=f.order_id WHERE o.account_id=?',(account_id,))['n']-before_fills
    except Exception as exc:
        # An unhandled cycle error rolled back every partial local mutation.
        result.update(orders_submitted=0, fills_applied=0, expired_positions=0, actions=[])
        reason = str(exc) if isinstance(exc, (Rejected, ValueError)) else 'Automation processing unavailable'
        result['blocked_reasons'].append(reason)
        with service.repo.transaction() as db:
            exists = db.one('SELECT id FROM accounts WHERE id=?', (account_id,))
            if exists and ('ledger' in reason.lower() or 'provenance' in reason.lower()):
                db.execute('UPDATE accounts SET state_known=0 WHERE id=?', (account_id,))
            service.audit(db, account_id if exists else None, 'AUTOMATION_BLOCKED', {'reason': reason})
    return result


def _cycle(service, db, account_id, now, feed, quote_feed, result):
    from .worker import fixture_bars
    account = service.account(db, account_id)
    validate_config(account['config'])
    config = account['config']
    if not config['automation_enabled']:
        raise Rejected('Automatic Mock execution is disabled for this account')
    if config['mode'] != 'paper' or config['broker'] != 'mock':
        raise Rejected('Automatic execution requires paper/mock; Live is locked')
    if not service.snapshot_valid(account):
        raise Rejected('Account snapshot untrusted or stale; explicit reconciliation required')
    service._validate_ledger(db, account_id)

    def guard(quote=None):
        current = service.account(db, account_id)
        validate_config(current['config'])
        if not service.snapshot_valid(current) or current['config']['mode'] != 'paper' or not current['config']['automation_enabled']:
            raise Rejected('Automatic execution lost trusted paper/mock account state')
        if quote is not None:
            if not timedelta(0) <= service.now()-quote.timestamp <= timedelta(seconds=60):
                raise Rejected('Execution quote became future or stale before execution')
            if not service.market_valid(db, account_id, quote.symbol):
                raise Rejected('Market observation became unavailable or stale before execution')
        # This only validates a previously trusted mock ledger; it cannot repair
        # an unknown/disconnected account. The outer lock prevents a TOCTOU gap.
        service.reconcile(account_id)

    guard()
    result['expired_positions'] = service.expire(account_id)
    if result['expired_positions']:
        result['actions'].append({'type': 'EXPIRY_WRITEOFF', 'count': result['expired_positions'],
                                  'policy': 'synthetic_premium_lost_no_exercise'})
    cache = {}

    def quotes(symbol):
        if symbol in cache:
            return cache[symbol]
        if not service.market_valid(db, account_id, symbol):
            raise Rejected('Market observation unavailable or stale; explicit mock refresh required')
        contracts = db.all('SELECT * FROM positions WHERE account_id=? AND symbol=?', (account_id, symbol))
        contracts += db.all("SELECT * FROM orders WHERE account_id=? AND symbol=? AND status IN ('PENDING','PARTIAL')", (account_id, symbol))
        try:
            values = list(quote_feed(symbol, now) if quote_feed else fixture_quotes(symbol, now, contracts))
        except Exception as exc:
            raise Rejected('Option quote feed unavailable') from exc
        seen = set()
        for q in values:
            if not isinstance(q, OptionQuote) or q.symbol != symbol or q.key in seen:
                raise Rejected('Invalid or ambiguous option quote snapshot')
            seen.add(q.key)
            if not timedelta(0) <= now-q.timestamp <= timedelta(seconds=60):
                raise Rejected('Future or stale option quote snapshot')
            _cents(q.bid)
            _cents(q.ask)
            service.record_option_mark(db,account_id,q.symbol,q.right,q.expiry.isoformat(),_cents(q.strike),_cents(q.bid),_cents(q.ask),q.timestamp)
        cache[symbol] = values
        return values

    def quote_for(row):
        key = _contract(row)
        q = next((q for q in quotes(row['symbol']) if q.key == key), None)
        if q is None:
            raise Rejected('Owned/order contract quote unavailable')
        if (q.ask-q.bid)*100 > ((q.ask+q.bid)/2)*config['max_spread_pct']:
            raise Rejected('Option spread exceeds account limit')
        return q

    def submit(request, reason, quote, facts=None):
        guard(quote)
        prior = db.one('SELECT id FROM orders WHERE account_id=? AND request_key=?', (account_id, request['request_key']))
        service._decision_context={'reason':reason,'quote':{'bid_cents':_cents(quote.bid),'ask_cents':_cents(quote.ask),'observed_at':quote.timestamp.isoformat()},'strategy_source':'completed_bar_quantitative_worker','facts':facts or {}}
        order = service.submit(account_id, request)
        if not prior:
            result['orders_submitted'] += 1
            result['actions'].append({'type': 'ORDER', 'order_id': order['id'], 'side': order['side'], 'reason': reason})
        return order

    def fill(order, q):
        if order['status'] not in ACTIVE:
            return
        fill_id = _key('auto-f:', account_id, order['id'], q.timestamp.isoformat())
        if db.one('SELECT id FROM fills WHERE id=?', (fill_id,)):
            return  # One durable fill chunk per order and observed quote time.
        price = _cents(q.ask if order['side'] == 'BUY' else q.bid)
        if (order['side'] == 'BUY' and price > order['limit_cents']) or (order['side'] == 'SELL_TO_CLOSE' and price < order['limit_cents']):
            return
        guard(q)
        quantity = min(config['auto_fill_chunk'], order['quantity']-order['filled'])
        service.fill(account_id, order['id'], fill_id, quantity, price)
        result['fills_applied'] += 1
        result['actions'].append({'type': 'FILL', 'order_id': order['id'], 'quantity': quantity, 'price_cents': price})

    def blocked(symbol, exc):
        reason = str(exc) if isinstance(exc, (Rejected, ValueError)) else 'Automation feed/analysis unavailable'
        result['blocked_reasons'].append(f'{symbol}: {reason}')
        service.audit(db, account_id, 'AUTOMATION_SYMBOL_BLOCKED', {'symbol': symbol, 'reason': reason})
        if 'ledger' in reason.lower() or 'provenance' in reason.lower():
            raise Rejected(reason)

    from .lifecycle import request_reversal, request_scaling
    exit_symbols = set()
    # Opposite signals are an explicit opt-in exit-and-revalidate policy. The
    # lifecycle captures the original facts before cancelling any old entries.
    if config['reversal_enabled'] and not account['stopped'] and not db.one('SELECT stopped FROM supervisor WHERE id=1')['stopped']:
        for row in db.all('SELECT DISTINCT symbol,right_kind FROM positions WHERE account_id=?',(account_id,)):
            try:
                analysis=AnalysisPipeline().analyze((feed or fixture_bars)(row['symbol'],now),now)
                signal=next((s for s in analysis.signals if s.right!=row['right_kind'] and s.strategy in config['strategies']),None)
                if signal is None:
                    continue
                policy=db.one('SELECT generation FROM position_policies WHERE account_id=? AND symbol=?',(account_id,row['symbol']))
                generation=policy['generation'] if policy else 0
                intent=request_reversal(service,account_id,_key('reverse:',account_id,row['symbol'],generation,signal.right),row['symbol'],signal.right,(feed or fixture_bars)(row['symbol'],now),quotes(row['symbol']))
                result['actions'].append({'type':'REVERSAL_INTENT','intent_id':intent['id'],'state':intent['state']})
            except Exception as exc:
                blocked(row['symbol'],exc)
    for position in db.all('SELECT * FROM positions WHERE account_id=? ORDER BY symbol', (account_id,)):
        try:
            q = quote_for(position)
            premium = _cents(q.bid)*100*position['quantity']
            loss = premium*100 <= position['cost']*(100-config['stop_loss_pct'])
            profit = premium*100 >= position['cost']*(100+config['take_profit_pct'])
            owned_key = (account_id, position['symbol'], position['right_kind'], position['expiry'], position['strike'])
            pending_closes = db.all("SELECT * FROM orders WHERE account_id=? AND symbol=? AND right_kind=? AND expiry=? AND strike=? AND side='SELL_TO_CLOSE' AND status IN ('PENDING','PARTIAL')", owned_key)
            automatic_closes = [o for o in pending_closes if o['request_key'].startswith(('auto-x:', 'v1-r:'))]
            policy=db.one('SELECT * FROM position_policies WHERE account_id=? AND symbol=? AND right_kind=? AND expiry=? AND strike=?',owned_key)
            bid=_cents(q.bid)
            high=max(policy['high_bid'] if policy else 0,bid)
            if policy:
                db.execute('UPDATE position_policies SET high_bid=? WHERE account_id=? AND symbol=? AND right_kind=? AND expiry=? AND strike=?',(high,)+owned_key)
            trailing=bool(config['trailing_stop_pct'] and bid*100<=high*(100-config['trailing_stop_pct']))
            intraday=config['holding']=='intraday' and now.hour>=config['intraday_exit_hour_utc']
            swing=config['holding']=='swing' and policy is not None and (now-datetime.fromisoformat(policy['opened_at'])).days>=config['swing_max_days']
            near_expiry=(date.fromisoformat(position['expiry'])-now.date()).days<=config['expiry_exit_days']
            partial=bool(config['partial_profit_pct'] and policy and not policy['partial_taken'] and position['quantity']>=2 and premium*100>=position['cost']*(100+config['partial_profit_pct']))
            invalidated=False
            if config['scenario_exit_enabled']:
                current_analysis=AnalysisPipeline().analyze((feed or fixture_bars)(position['symbol'],now),now)
                invalidated=any(s.right!=position['right_kind'] and s.strategy in config['strategies'] for s in current_analysis.signals)
            if not (loss or profit or trailing or intraday or swing or near_expiry or partial or invalidated or automatic_closes):
                continue
            exit_symbols.add(position['symbol'])
            reason = 'STOP_LOSS' if loss else 'TAKE_PROFIT' if profit else 'TRAILING_STOP' if trailing else 'EXPIRY_PROTECTION' if near_expiry else 'INTRADAY_EXIT' if intraday else 'SWING_TIME_EXIT' if swing else 'SCENARIO_INVALIDATED' if invalidated else 'PARTIAL_PROFIT' if partial else 'RESUME_CLOSE'
            # Cancel every residual entry for this contract before managing its
            # owned partial inventory, including manually submitted entries.
            for order in db.all("SELECT * FROM orders WHERE account_id=? AND symbol=? AND right_kind=? AND expiry=? AND strike=? AND side='BUY' AND status IN ('PENDING','PARTIAL')", owned_key):
                guard()
                service.cancel(account_id, order['id'])
                result['actions'].append({'type': 'CANCEL', 'order_id': order['id'], 'reason': reason})
            for order in automatic_closes:
                if _cents(q.bid) < order['limit_cents']:
                    guard()
                    service.cancel(account_id, order['id'])
                    result['actions'].append({'type': 'CANCEL', 'order_id': order['id'], 'reason': 'REPRICE_OWNED_CLOSE'})
                else:
                    fill(order, q)
            current = db.one('SELECT * FROM positions WHERE account_id=? AND symbol=? AND right_kind=? AND expiry=? AND strike=?', owned_key)
            if not current:
                continue
            reserved = sum(o['quantity']-o['filled'] for o in db.all("SELECT * FROM orders WHERE account_id=? AND symbol=? AND right_kind=? AND expiry=? AND strike=? AND side='SELL_TO_CLOSE' AND status IN ('PENDING','PARTIAL')", owned_key))
            available = current['quantity']-reserved
            if available <= 0:
                continue
            generation = db.one("SELECT COALESCE(MAX(f.sequence),0) AS n FROM fills f JOIN orders o ON o.id=f.order_id WHERE o.account_id=? AND o.symbol=? AND o.right_kind=? AND o.expiry=? AND o.strike=? AND o.side='BUY'", owned_key)['n']
            request = {'request_key': _key('auto-x:', *owned_key, generation, q.timestamp.isoformat()),
                       'symbol': position['symbol'], 'right': position['right_kind'], 'expiry': position['expiry'],
                       'strike_cents': position['strike'], 'side': 'SELL_TO_CLOSE',
                       'quantity': max(1,min(available-1,available*config['partial_exit_pct']//100)) if reason=='PARTIAL_PROFIT' else available, 'limit_cents': _cents(q.bid)}
            prior = db.one('SELECT * FROM orders WHERE account_id=? AND request_key=?', (account_id, request['request_key']))
            # A consumed observation cannot close another chunk or create an
            # altered idempotent payload after a partial fill/repeated tick.
            if prior:
                fill(prior, q)
            else:
                close=submit(request, reason, q, {'owned_quantity':current['quantity'],'owned_cost_cents':current['cost'],'bid_mark_cents':_cents(q.bid),'policy':policy})
                if reason=='PARTIAL_PROFIT':
                    db.execute('UPDATE position_policies SET partial_taken=1 WHERE account_id=? AND symbol=? AND right_kind=? AND expiry=? AND strike=?',owned_key)
                fill(close, q)
        except Exception as exc:
            blocked(position['symbol'], exc)

    # Resume durable automatic entries after lost responses/restart. Manual
    # orders remain under operator control, except residual risk-exit cancels.
    for order in db.all("SELECT * FROM orders WHERE account_id=? AND side='BUY' AND status IN ('PENDING','PARTIAL') ORDER BY id", (account_id,)):
        if not order['request_key'].startswith(('auto-e:', 'v1-r:', 'v1-s:')) or order['symbol'] in exit_symbols:
            continue
        try:
            fill(order, quote_for(order))
        except Exception as exc:
            blocked(order['symbol'], exc)

    # Durable reversals only advance after old fills/cancellations are settled.
    from .lifecycle import advance_reversal
    for intent in db.all("SELECT * FROM lifecycle_intents WHERE account_id=? AND kind='REVERSAL' AND state NOT IN ('COMPLETE','EXPIRED','CANCELLED')",(account_id,)):
        try:
            advance_reversal(service,account_id,intent['id'],(feed or fixture_bars)(intent['symbol'],now),quotes(intent['symbol']))
        except Exception as exc:
            blocked(intent['symbol'],exc)

    if config['scaling_enabled']:
        for position in db.all('SELECT * FROM positions WHERE account_id=?',(account_id,)):
            if position['symbol'] in exit_symbols:
                continue
            try:
                q=quote_for(position)
                if _cents(q.bid)*100*position['quantity']<=position['cost']:
                    continue
                intent=request_scaling(service,account_id,_key('scale:',account_id,position['symbol'],q.timestamp.isoformat()),position['symbol'],position['right_kind'],(feed or fixture_bars)(position['symbol'],now),quotes(position['symbol']))
                result['actions'].append({'type':'SCALING_INTENT','intent_id':intent['id'],'state':intent['state']})
            except Exception as exc:
                blocked(position['symbol'],exc)

    ranked = []
    analysis_facts = {}
    current = service.account(db, account_id)
    if not current['stopped'] and not db.one('SELECT stopped FROM supervisor WHERE id=1')['stopped']:
        for watch in db.all('SELECT * FROM watchlist WHERE account_id=? AND enabled=1 AND verified=1 ORDER BY symbol', (account_id,)):
            symbol = watch['symbol']
            if symbol in exit_symbols:
                continue
            if db.one('SELECT symbol FROM positions WHERE account_id=? AND symbol=?', (account_id, symbol)) or db.one("SELECT id FROM orders WHERE account_id=? AND symbol=? AND status IN ('PENDING','PARTIAL')", (account_id, symbol)):
                continue
            entry_key = _key('auto-e:', account_id, symbol, now.date().isoformat())
            if db.one('SELECT id FROM orders WHERE account_id=? AND request_key=?', (account_id, entry_key)):
                continue
            try:
                quotes(symbol)
                completed_bars=list((feed or fixture_bars)(symbol, now))
                analysis = AnalysisPipeline().analyze(completed_bars, now)
                analysis_facts[symbol]={'regime':analysis.regime,'atr':analysis.atr,'realized_volatility':analysis.realized_volatility,'completed_bars':[{'at':b.timestamp.isoformat(),'open':b.open,'high':b.high,'low':b.low,'close':b.close,'volume':b.volume} for b in completed_bars[-512:]]}
                for signal in analysis.signals:
                    if signal.strategy in config['strategies']:
                        ranked.append((symbol, signal))
            except Exception as exc:
                blocked(symbol, exc)
    for symbol, signal in OpportunityRanking.rank(ranked):
        try:
            entry_key = _key('auto-e:', account_id, symbol, now.date().isoformat())
            if db.one('SELECT id FROM orders WHERE account_id=? AND request_key=?', (account_id, entry_key)):
                continue
            q = OptionsSelectionEngine().select(quotes(symbol), symbol, signal.right, now,
                                                max_spread_pct=config['max_spread_pct']/100)
            if q is None:
                raise Rejected('No eligible fresh single-leg option quote')
            request = {'request_key': entry_key, 'symbol': symbol, 'right': q.right, 'expiry': q.expiry.isoformat(),
                       'strike_cents': _cents(q.strike), 'side': 'BUY', 'quantity': config['auto_quantity'],
                       'limit_cents': _cents(q.ask)}
            facts=analysis_facts[symbol]|{'signal':{'strategy':signal.strategy,'right':signal.right,'score':signal.score,'reason':signal.reason,'observed_at':signal.timestamp.isoformat()}}
            order = submit(request, signal.strategy, q, facts)
            fill(order, q)
        except Exception as exc:
            blocked(symbol, exc)
    service.audit(db, account_id, 'AUTOMATION_CYCLE', result)
