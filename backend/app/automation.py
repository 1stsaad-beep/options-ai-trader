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
            _cycle(bound, db, account_id, now, feed, quote_feed, result)
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

    def submit(request, reason, quote):
        guard(quote)
        prior = db.one('SELECT id FROM orders WHERE account_id=? AND request_key=?', (account_id, request['request_key']))
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

    exit_symbols = set()
    for position in db.all('SELECT * FROM positions WHERE account_id=? ORDER BY symbol', (account_id,)):
        try:
            q = quote_for(position)
            premium = _cents(q.bid)*100*position['quantity']
            loss = premium*100 <= position['cost']*(100-config['stop_loss_pct'])
            profit = premium*100 >= position['cost']*(100+config['take_profit_pct'])
            owned_key = (account_id, position['symbol'], position['right_kind'], position['expiry'], position['strike'])
            pending_closes = db.all("SELECT * FROM orders WHERE account_id=? AND symbol=? AND right_kind=? AND expiry=? AND strike=? AND side='SELL_TO_CLOSE' AND status IN ('PENDING','PARTIAL')", owned_key)
            automatic_closes = [o for o in pending_closes if o['request_key'].startswith('auto-x:')]
            if not (loss or profit or automatic_closes):
                continue
            exit_symbols.add(position['symbol'])
            reason = 'STOP_LOSS' if loss else 'TAKE_PROFIT' if profit else 'RESUME_CLOSE'
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
                       'quantity': min(available, config['max_contracts']), 'limit_cents': _cents(q.bid)}
            prior = db.one('SELECT * FROM orders WHERE account_id=? AND request_key=?', (account_id, request['request_key']))
            # A consumed observation cannot close another chunk or create an
            # altered idempotent payload after a partial fill/repeated tick.
            if prior:
                fill(prior, q)
            else:
                fill(submit(request, reason, q), q)
        except Exception as exc:
            blocked(position['symbol'], exc)

    # Resume durable automatic entries after lost responses/restart. Manual
    # orders remain under operator control, except residual risk-exit cancels.
    for order in db.all("SELECT * FROM orders WHERE account_id=? AND side='BUY' AND status IN ('PENDING','PARTIAL') ORDER BY id", (account_id,)):
        if not order['request_key'].startswith('auto-e:') or order['symbol'] in exit_symbols:
            continue
        try:
            fill(order, quote_for(order))
        except Exception as exc:
            blocked(order['symbol'], exc)

    ranked = []
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
                analysis = AnalysisPipeline().analyze((feed or fixture_bars)(symbol, now), now)
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
            order = submit(request, signal.strategy, q)
            fill(order, q)
        except Exception as exc:
            blocked(symbol, exc)
    service.audit(db, account_id, 'AUTOMATION_CYCLE', result)
