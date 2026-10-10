"""Paper-only transaction service. No path in this module sends network orders."""
import hashlib
import json
import re
import uuid
from datetime import date, datetime, timezone
from .adapters import MockBrokerAdapter, MOCK_SYMBOLS

class Rejected(ValueError):
    pass

DEFAULT_CONFIG = {'mode': 'paper', 'broker': 'mock', 'allocation_pct': 30, 'trade_risk_pct': 2, 'daily_loss_pct': 3, 'max_contracts': 5, 'strategies': ['breakout', 'pullback'], 'holding': 'intraday', 'risk_group': None, 'connection_id': None, 'group_allocation_pct': 30, 'group_daily_loss_pct': 3, 'automation_enabled': False, 'stop_loss_pct': 20, 'take_profit_pct': 30, 'auto_quantity': 1, 'auto_fill_chunk': 1, 'max_spread_pct': 10}
ACTIVE = ('PENDING', 'PARTIAL')

def integer(value, name, minimum=1, maximum=100000000):
    if type(value) is not int or not minimum <= value <= maximum:
        raise Rejected(f'{name} must be an integer in [{minimum}, {maximum}]')
    return value

def validate_config(config):
    if type(config.get('automation_enabled', False)) is not bool:
        raise Rejected('automation_enabled must be boolean')
    for field, default, maximum in [('stop_loss_pct',20,95),('take_profit_pct',30,500),('auto_quantity',1,100),('auto_fill_chunk',1,100),('max_spread_pct',10,50)]:
        integer(config.get(field,default),field,1,maximum)
    if config.get('mode') not in ('paper', 'shadow', 'analysis') or config.get('broker') != 'mock':
        raise Rejected('Live and external broker execution are locked; use paper/mock')
    for key in ('risk_group', 'connection_id'):
        if config.get(key) is not None and (not isinstance(config[key], str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', config[key])):
            raise Rejected('Invalid group/connection identifier')
    integer(config.get('group_allocation_pct',30), 'group_allocation_pct', 1, 30)
    integer(config.get('group_daily_loss_pct',3), 'group_daily_loss_pct', 1, 3)
    for key in ('allocation_pct', 'trade_risk_pct', 'daily_loss_pct'):
        integer(config.get(key), key, 1, {'allocation_pct':30,'trade_risk_pct':2,'daily_loss_pct':3}[key])
    integer(config.get('max_contracts'), 'max_contracts', 1, 100)
    if config.get('holding') not in ('intraday', 'swing'):
        raise Rejected('Invalid holding mode')
    if not isinstance(config.get('strategies'), list) or not all(isinstance(item,str) and item in {'breakout','pullback'} for item in config['strategies']):
        raise Rejected('Only quantitative breakout/pullback strategies are available')

class TradingService:
    def __init__(self, repository, today=None, now=None):
        self.repo = repository
        self.now = now or (lambda: datetime.now(timezone.utc))
        self.today = today or (lambda: datetime.now(timezone.utc).date())
    def snapshot_valid(self, account):
        try:
            age=(self.now()-datetime.fromisoformat(account['snapshot_at'])).total_seconds()
            return bool(account['state_known']) and 0 <= age <= 120
        except (ValueError, TypeError, OverflowError):
            return False
    def audit(self, db, account, event, detail):
        db.execute('INSERT INTO audit VALUES(?,?,?,?,?)', (str(uuid.uuid4()), account, event, json.dumps(detail, sort_keys=True), self.now().isoformat()))
    def account(self, db, account_id):
        account = db.one('SELECT * FROM accounts WHERE id=?', (account_id,))
        if account is None:
            raise Rejected('Unknown account')
        try:
            account['config'] = DEFAULT_CONFIG | json.loads(account['config'])
        except (ValueError, TypeError):
            raise Rejected('Malformed account configuration ledger; account remains locked') from None
        return account
    def create_account(self, name, equity=1000000):
        if not isinstance(name, str) or not name.strip() or len(name) > 80:
            raise Rejected('Account name required (max 80 characters)')
        integer(equity, 'equity_cents', 10000)
        account_id = str(uuid.uuid4())
        with self.repo.transaction() as db:
            db.execute('INSERT INTO accounts(id,name,config,equity,snapshot_at) VALUES(?,?,?,?,?)', (account_id, name, json.dumps(DEFAULT_CONFIG), equity, self.now().isoformat()))
            for symbol in ('NVDA', 'AAPL', 'TSLA'):
                db.execute('INSERT INTO watchlist VALUES(?,?,0,0)', (account_id, symbol))
            self.audit(db, account_id, 'ACCOUNT_CREATED', {'broker': 'mock', 'initial_equity_cents': equity})
            return self.account(db, account_id)
    def list_accounts_in(self, db):
        return [self.account(db,row['id']) for row in db.all('SELECT id FROM accounts ORDER BY name')]

    def list_accounts(self):
        with self.repo.transaction() as db:
            return [self.account(db, row['id']) for row in db.all('SELECT id FROM accounts ORDER BY name')]
    def configure(self, account_id, changes):
        if not set(changes) <= set(DEFAULT_CONFIG):
            raise Rejected('Unknown configuration field')
        with self.repo.transaction() as db:
            account = self.account(db, account_id)
            config = account['config'] | changes
            validate_config(config)
            db.execute('UPDATE accounts SET config=? WHERE id=?', (json.dumps(config), account_id))
            self.audit(db, account_id, 'CONFIG_CHANGED', changes)
            return self.account(db, account_id)
    def watch(self, account_id, symbol, enabled=False):
        symbol = symbol.upper() if isinstance(symbol, str) else ''
        if not re.fullmatch(r'[A-Z][A-Z0-9.]{0,9}', symbol):
            raise Rejected('Invalid symbol')
        if type(enabled) is not bool:
            raise Rejected('enabled must be boolean')
        # The synthetic fixture has explicit demo entitlements, never real verification.
        verified = MockBrokerAdapter().verify_symbol(symbol)['verified']
        if enabled and not verified:
            raise Rejected('Mock symbol/market data entitlement unavailable')
        with self.repo.transaction() as db:
            self.account(db, account_id)
            db.execute('INSERT INTO watchlist VALUES(?,?,?,?) ON CONFLICT(account_id,symbol) DO UPDATE SET enabled=excluded.enabled,verified=excluded.verified', (account_id, symbol, int(enabled), int(verified)))
            if enabled:
                self._market_observation(db, account_id, symbol, True)
            self.audit(db, account_id, 'WATCHLIST_UPDATED', {'symbol': symbol, 'enabled': enabled, 'verification': 'mock_fixture_only'})
            return {'symbol': symbol, 'enabled': enabled, 'verified': verified, 'source': 'mock'}
    def _market_observation(self, db, account_id, symbol, available):
        db.execute('INSERT INTO market_snapshots(account_id,symbol,observed_at,available) VALUES(?,?,?,?) ON CONFLICT(account_id,symbol) DO UPDATE SET observed_at=excluded.observed_at,available=excluded.available', (account_id,symbol,self.now().isoformat(),int(available)))

    def mock_market_data(self, account_id, symbol, available=True):
        if type(available) is not bool or not isinstance(symbol,str):
            raise Rejected('Invalid mock market observation')
        symbol=symbol.upper()
        with self.repo.transaction() as db:
            self.account(db,account_id)
            watch=db.one('SELECT * FROM watchlist WHERE account_id=? AND symbol=?',(account_id,symbol))
            if not watch or not watch['verified']:
                raise Rejected('Mock entitlement unavailable')
            self._market_observation(db,account_id,symbol,available)
            self.audit(db,account_id,'MOCK_MARKET_OBSERVATION',{'symbol':symbol,'available':available,'source':'synthetic_fixture'})
        return {'symbol':symbol,'available':available,'observed_at':self.now().isoformat(),'source':'synthetic_fixture'}

    def market_valid(self, db, account_id, symbol):
        row=db.one('SELECT * FROM market_snapshots WHERE account_id=? AND symbol=?',(account_id,symbol))
        if not row or not row['available']:
            return False
        try:
            age=(self.now()-datetime.fromisoformat(row['observed_at'])).total_seconds()
            return 0<=age<=60
        except (ValueError,TypeError,OverflowError):
            return False

    def status(self, account_id):
        with self.repo.transaction() as db:
            account=self.account(db,account_id)
            globally_stopped=bool(db.one('SELECT stopped FROM supervisor WHERE id=1')['stopped'])
            valid=self.snapshot_valid(account)
            try:
                self._validate_ledger(db,account_id)
                validate_config(account['config'])
                self._check_supervisor(db,account)
                daily=db.one('SELECT pnl FROM daily_pnl WHERE account_id=? AND day=?',(account_id,self.today().isoformat()))
                equity=max(0,account['equity']+account['realized'])
                if -(daily['pnl'] if daily else 0)*100>=equity*account['config']['daily_loss_pct']:
                    raise Rejected('Daily loss gate closed')
                risk_ready=True
            except Rejected:
                risk_ready=False
            watches=db.all('SELECT symbol FROM watchlist WHERE account_id=? AND enabled=1 AND verified=1',(account_id,))
            market_ready=any(self.market_valid(db,account_id,w['symbol']) for w in watches)
            return {'state_known':bool(account['state_known']),'snapshot_valid':valid,'stopped':bool(account['stopped']),'global_stopped':globally_stopped,'mode':account['config']['mode'],'broker':'mock','live_enabled':False,'source':'synthetic_mock','market_data_ready':market_ready,'risk_guard_ready':risk_ready,'new_entries_allowed':valid and market_ready and risk_ready and not account['stopped'] and not globally_stopped and account['config']['mode']=='paper','emergency_policy':'owned_closes_only_after_trusted_reconciliation'}

    def _check_supervisor(self, db, account, cost=0):
        self._check_linked_risk(db,account,cost)
        # Global supervisor caps all mock exposure at 30% of all initial account capital.
        for member in db.all('SELECT id FROM accounts'):
            self._validate_ledger(db,member['id'])
        # Untrusted unrelated capital is excluded, but its committed exposure/loss stays counted.
        all_capital = sum(max(0,a['equity']+a['realized']) for a in db.all('SELECT * FROM accounts') if self.snapshot_valid(a))
        all_exposure = sum(p['cost'] for p in db.all('SELECT cost FROM positions')) + sum((o['quantity']-o['filled'])*o['limit_cents']*100 for o in db.all("SELECT * FROM orders WHERE side='BUY' AND status IN ('PENDING','PARTIAL')"))
        global_daily=sum(row['pnl'] for row in db.all('SELECT pnl FROM daily_pnl WHERE day=?',(self.today().isoformat(),)))
        if -global_daily*100 >= all_capital*3:
            raise Rejected('Global daily loss limit reached')
        if (all_exposure+cost)*100 > all_capital*30:
            raise Rejected('Global allocation exceeded')

    def _check_linked_risk(self, db, account, cost):
        group=account['config'].get('risk_group')
        if not group:
            return
        members=[self.account(db,a['id']) for a in db.all('SELECT id FROM accounts')]
        members=[a for a in members if a['config'].get('risk_group')==group]
        capital=sum(max(0,a['equity']+a['realized']) for a in members)
        exposure,daily=0,0
        for member in members:
            # Linked capital may not dilute group risk with an untrusted balance.
            if not self.snapshot_valid(member):
                raise Rejected('Linked account state unknown; reconcile group first')
            self._validate_ledger(db,member['id'])
            exposure+=sum(p['cost'] for p in db.all('SELECT cost FROM positions WHERE account_id=?',(member['id'],)))
            exposure+=sum((o['quantity']-o['filled'])*o['limit_cents']*100 for o in db.all("SELECT * FROM orders WHERE account_id=? AND side='BUY' AND status IN ('PENDING','PARTIAL')",(member['id'],)))
            pnl=db.one('SELECT pnl FROM daily_pnl WHERE account_id=? AND day=?',(member['id'],self.today().isoformat()))
            daily+=pnl['pnl'] if pnl else 0
        allocation=min(a['config']['group_allocation_pct'] for a in members)
        loss=min(a['config']['group_daily_loss_pct'] for a in members)
        if -daily*100>=capital*loss:
            raise Rejected('Linked group daily loss limit reached')
        if (exposure+cost)*100>capital*allocation:
            raise Rejected('Linked group allocation exceeded')

    def remove_watch(self, account_id, symbol):
        with self.repo.transaction() as db:
            self.account(db, account_id)
            db.execute('DELETE FROM watchlist WHERE account_id=? AND symbol=?', (account_id, symbol.upper()))
            self.audit(db, account_id, 'WATCHLIST_REMOVED', {'symbol': symbol.upper()})
    def rows(self, account_id, table):
        if table not in {'watchlist', 'orders', 'positions', 'audit'}:
            raise Rejected('Unsupported resource')
        with self.repo.transaction() as db:
            self.account(db, account_id)
            return db.all(f'SELECT * FROM {table} WHERE account_id=?', (account_id,))
    def stop(self, account_id=None):
        with self.repo.transaction() as db:
            if account_id:
                self.account(db, account_id)
                db.execute('UPDATE accounts SET stopped=1 WHERE id=?', (account_id,))
                db.execute("UPDATE orders SET status='CANCELLED' WHERE account_id=? AND status IN ('PENDING','PARTIAL')", (account_id,))
            else:
                db.execute('UPDATE supervisor SET stopped=1 WHERE id=1')
                db.execute("UPDATE orders SET status='CANCELLED' WHERE status IN ('PENDING','PARTIAL')")
            self.audit(db, account_id, 'EMERGENCY_STOP', {})
        return {'stopped': True, 'account_id': account_id}
    def disconnect(self, account_id):
        with self.repo.transaction() as db:
            account=self.account(db, account_id)
            connection=account['config'].get('connection_id')
            affected=[account_id]
            if connection:
                affected=[a['id'] for a in self.list_accounts_in(db) if a['config'].get('connection_id')==connection]
            for affected_id in affected:
                db.execute('UPDATE accounts SET state_known=0 WHERE id=?', (affected_id,))
                self.audit(db, affected_id, 'DISCONNECTED', {'shared_connection':bool(connection)})
    def reconcile(self, account_id):
        try:
            return self._reconcile(account_id)
        except Rejected:
            with self.repo.transaction() as db:
                db.execute('UPDATE accounts SET state_known=0 WHERE id=?',(account_id,))
                exists=db.one('SELECT id FROM accounts WHERE id=?',(account_id,))
                self.audit(db,account_id if exists else None,'RECONCILIATION_FAILED',{'state_known':False,'requested_account':account_id})
            raise
    def _reconcile(self, account_id):
        # The mock broker's ledger is the same durable transaction store. No resend occurs.
        with self.repo.transaction() as db:
            self.account(db, account_id)
            self._validate_ledger(db, account_id)
            db.execute('UPDATE accounts SET state_known=1,snapshot_at=? WHERE id=?', (self.now().isoformat(),account_id))
            self.audit(db, account_id, 'MOCK_RECONCILED', {'orders': len(db.all('SELECT id FROM orders WHERE account_id=?',(account_id,))), 'resubmitted': 0})
        return {'state_known': True, 'resubmitted': 0, 'source': 'mock_durable_ledger'}
    def _validate_ledger(self, db, account_id):
        try:
            return self._validate_ledger_data(db, account_id)
        except Rejected:
            raise
        except (ValueError, TypeError, KeyError, OverflowError):
            raise Rejected('Malformed trading ledger; account remains locked') from None

    def _validate_ledger_data(self, db, account_id):
        account=self.account(db,account_id)
        integer(account['equity'],'equity_cents',10000)
        creation=db.one("SELECT detail FROM audit WHERE account_id=? AND event='ACCOUNT_CREATED'",(account_id,))
        initial=json.loads(creation['detail']).get('initial_equity_cents') if creation else None
        if type(initial) is not int:
            baseline=db.one("SELECT detail FROM audit WHERE account_id=? AND event='MIGRATION_BALANCE_BASELINE'",(account_id,))
            initial=json.loads(baseline['detail']).get('initial_equity_cents') if baseline else None
        if type(initial) is not int or initial!=account['equity']:
            raise Rejected('Initial balance provenance mismatch')
        orders = db.all('SELECT * FROM orders WHERE account_id=?', (account_id,))
        inventory = {}
        realized = 0
        daily_ledger = {}
        by_id = {order['id']:order for order in orders}
        for order in orders:
            payload=dict(request_key=order['request_key'],symbol=order['symbol'],right=order['right_kind'],expiry=order['expiry'],strike_cents=order['strike'],side=order['side'],quantity=order['quantity'],limit_cents=order['limit_cents'])
            if order['status'] not in ('PENDING','PARTIAL','FILLED','CANCELLED','EXPIRED') or hashlib.sha256(json.dumps(payload,sort_keys=True).encode()).hexdigest()!=order['fingerprint']:
                raise Rejected('Order identity/status ledger mismatch')
            fills = db.all('SELECT * FROM fills WHERE order_id=?', (order['id'],))
            total = sum(f['quantity'] for f in fills)
            if total != order['filled'] or not 0 <= total <= order['quantity']:
                raise Rejected('Ledger mismatch; account remains locked')
            if order['status']=='FILLED' and total != order['quantity']:
                raise Rejected('Invalid filled status')
            if order['status']=='PENDING' and total != 0:
                raise Rejected('Invalid pending status')
            if order['status']=='PARTIAL' and not 0 < total < order['quantity']:
                raise Rejected('Invalid partial status')
        ledger=db.all('SELECT f.* FROM fills f JOIN orders o ON o.id=f.order_id WHERE o.account_id=? ORDER BY f.sequence',(account_id,))
        for fill in ledger:
            order=by_id[fill['order_id']]
            quantity,price=fill['quantity'],fill['price_cents']
            if quantity<=0 or price<=0 or (order['side']=='BUY' and price>order['limit_cents']) or (order['side']=='SELL_TO_CLOSE' and price<order['limit_cents']):
                raise Rejected('Invalid fill ledger')
            key=(order['symbol'],order['right_kind'],order['expiry'],order['strike'])
            held,cost=inventory.get(key,(0,0))
            if order['side']=='BUY':
                inventory[key]=(held+quantity,cost+quantity*price*100)
            else:
                if held<quantity:
                    raise Rejected('Short inventory in fill ledger')
                removed=cost*quantity//held
                pnl=quantity*price*100-removed
                realized+=pnl
                daily_ledger[fill['day']]=daily_ledger.get(fill['day'],0)+pnl
                inventory[key]=(held-quantity,cost-removed)
        expired=db.all("SELECT detail FROM audit WHERE account_id=? AND event='MOCK_EXPIRY_WRITEOFF'",(account_id,))
        for event in expired:
            position=json.loads(event['detail'])
            key=(position['symbol'],position['right_kind'],position['expiry'],position['strike'])
            if inventory.get(key)!=(position['quantity'],position['cost']):
                raise Rejected('Expiry ledger mismatch')
            realized-=position['cost']
            day=position['settlement_day']
            daily_ledger[day]=daily_ledger.get(day,0)-position['cost']
            inventory[key]=(0,0)
        expected={key:value for key,value in inventory.items() if value[0]}
        actual={(p['symbol'],p['right_kind'],p['expiry'],p['strike']):(p['quantity'],p['cost']) for p in db.all('SELECT * FROM positions WHERE account_id=?',(account_id,))}
        actual_daily={row['day']:row['pnl'] for row in db.all('SELECT day,pnl FROM daily_pnl WHERE account_id=?',(account_id,))}
        if actual_daily!=daily_ledger:
            raise Rejected('Daily risk ledger mismatch; account remains locked')
        if expected!=actual or realized!=self.account(db,account_id)['realized']:
            raise Rejected('Position/P&L ledger mismatch; account remains locked')

    def submit(self, account_id, request):
        try:
            return self._submit(account_id,request)
        except Rejected as exc:
            with self.repo.transaction() as db:
                if 'ledger' in str(exc).lower() or 'provenance' in str(exc).lower():
                    db.execute('UPDATE accounts SET state_known=0 WHERE id=?',(account_id,))
                exists=db.one('SELECT id FROM accounts WHERE id=?',(account_id,))
                self.audit(db,account_id if exists else None,'ORDER_REJECTED',{'reason':str(exc),'symbol':request.get('symbol') if isinstance(request,dict) else None,'source':'quantitative_risk_gate'})
            raise
    def _submit(self, account_id, request):
        required = {'request_key','symbol','right','expiry','strike_cents','side','quantity','limit_cents'}
        if not isinstance(request,dict) or set(request) != required:
            raise Rejected('Exact single-leg option order fields required')
        if not isinstance(request['request_key'], str) or not 1 <= len(request['request_key']) <= 100:
            raise Rejected('Idempotency key required')
        if request['request_key'].startswith(('auto-e:', 'auto-x:')) and not getattr(self, '_automation_authorized', False):
            raise Rejected('Automatic order identifiers are reserved for the quantitative Mock worker')
        fingerprint = hashlib.sha256(json.dumps(request, sort_keys=True).encode()).hexdigest()
        with self.repo.transaction() as db:
            self.account(db, account_id)
            previous = db.one('SELECT * FROM orders WHERE account_id=? AND request_key=?', (account_id,request['request_key']))
            if previous:
                if previous['fingerprint'] != fingerprint:
                    raise Rejected('Idempotency key reused with different payload')
                return previous
        symbol = request['symbol']
        if not isinstance(symbol, str) or not re.fullmatch(r'[A-Z][A-Z0-9.]{0,9}', symbol):
            raise Rejected('Invalid symbol')
        if request['right'] not in ('CALL','PUT') or request['side'] not in ('BUY','SELL_TO_CLOSE'):
            raise Rejected('Only long calls/puts and owned closing sells are supported')
        try:
            expiry = date.fromisoformat(request['expiry'])
        except (TypeError, ValueError):
            raise Rejected('Expiry must be ISO date')
        if expiry <= self.today():
            raise Rejected('Expired or same-day contracts are disabled')
        quantity = integer(request['quantity'], 'quantity', 1, 100)
        price = integer(request['limit_cents'], 'limit_cents', 1, 1000000)
        strike = integer(request['strike_cents'], 'strike_cents')
        if symbol not in MOCK_SYMBOLS or not 5000 <= strike <= 100000 or strike % 100 or expiry.weekday()!=4 or (expiry-self.today()).days>90:
            raise Rejected('Option unavailable in standard 100-share synthetic mock contract catalogue')
        fingerprint = hashlib.sha256(json.dumps(request, sort_keys=True).encode()).hexdigest()
        with self.repo.transaction() as db:
            account = self.account(db, account_id)
            previous = db.one('SELECT * FROM orders WHERE account_id=? AND request_key=?', (account_id, request['request_key']))
            if previous:
                if previous['fingerprint'] != fingerprint:
                    raise Rejected('Idempotency key reused with different payload')
                return previous
            config = account['config']
            validate_config(config)
            if config['mode'] != 'paper':
                raise Rejected('Order execution disabled in shadow/analysis modes')
            if request['side']=='BUY' and (account['stopped'] or db.one('SELECT stopped FROM supervisor WHERE id=1')['stopped']):
                raise Rejected('Emergency stop active')
            if not self.snapshot_valid(account):
                raise Rejected('Account state unknown; reconcile first')
            self._validate_ledger(db,account_id)
            if quantity > config['max_contracts']:
                raise Rejected('Contract limit exceeded')
            position_key = (account_id, symbol, request['right'], request['expiry'], strike)
            if request['side'] == 'BUY':
                watch = db.one('SELECT * FROM watchlist WHERE account_id=? AND symbol=?', (account_id, symbol))
                if not watch or not watch['enabled'] or not watch['verified']:
                    raise Rejected('Watchlist symbol must have mock verification and be enabled')
                if not self.market_valid(db,account_id,symbol):
                    raise Rejected('Market data unavailable or stale; refresh mock observation')
                cost = quantity * price * 100
                equity = max(0,account['equity']+account['realized'])
                if cost * 100 > equity * config['trade_risk_pct']:
                    raise Rejected('Per-trade maximum premium risk exceeded')
                daily = db.one('SELECT pnl FROM daily_pnl WHERE account_id=? AND day=?', (account_id,self.today().isoformat()))
                if -(daily['pnl'] if daily else 0) * 100 >= equity * config['daily_loss_pct']:
                    raise Rejected('Daily loss limit reached')
                positions = db.all('SELECT cost FROM positions WHERE account_id=?', (account_id,))
                pending = db.all("SELECT * FROM orders WHERE account_id=? AND side='BUY' AND status IN ('PENDING','PARTIAL')", (account_id,))
                exposure = sum(p['cost'] for p in positions) + sum((o['quantity']-o['filled'])*o['limit_cents']*100 for o in pending)
                if (exposure+cost)*100 > equity*config['allocation_pct']:
                    raise Rejected('Account allocation exceeded')
                self._check_supervisor(db,account,cost)
            else:
                position = db.one('SELECT * FROM positions WHERE account_id=? AND symbol=? AND right_kind=? AND expiry=? AND strike=?', position_key)
                reserved = db.all("SELECT quantity,filled FROM orders WHERE account_id=? AND symbol=? AND right_kind=? AND expiry=? AND strike=? AND side='SELL_TO_CLOSE' AND status IN ('PENDING','PARTIAL')", position_key)
                if not position or quantity > position['quantity']-sum(o['quantity']-o['filled'] for o in reserved):
                    raise Rejected('Cannot sell unowned or already reserved contracts')
            order_id = str(uuid.uuid4())
            db.execute('INSERT INTO orders(id,account_id,request_key,fingerprint,symbol,right_kind,expiry,strike,side,quantity,limit_cents,status) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)', (order_id,account_id,request['request_key'],fingerprint,symbol,request['right'],request['expiry'],strike,request['side'],quantity,price,'PENDING'))
            self.audit(db, account_id, 'MOCK_ORDER_ACCEPTED', {'order_id':order_id})
            return db.one('SELECT * FROM orders WHERE id=?', (order_id,))
    def fill(self, account_id, order_id, fill_id, quantity, price_cents):
        try:
            return self._fill(account_id,order_id,fill_id,quantity,price_cents)
        except Rejected as exc:
            if 'ledger' in str(exc).lower() or 'provenance' in str(exc).lower():
                with self.repo.transaction() as db:
                    exists=db.one('SELECT id FROM accounts WHERE id=?',(account_id,))
                    if exists:
                        db.execute('UPDATE accounts SET state_known=0 WHERE id=?',(account_id,))
                        self.audit(db,account_id,'FILL_REJECTED_UNTRUSTED_LEDGER',{'reason':str(exc)})
            raise

    def _fill(self, account_id, order_id, fill_id, quantity, price_cents):
        integer(quantity, 'fill quantity', 1, 100)
        integer(price_cents, 'fill price', 1, 1000000)
        if not isinstance(fill_id, str) or not 1 <= len(fill_id) <= 100:
            raise Rejected('Fill identifier required')
        with self.repo.transaction() as db:
            account = self.account(db, account_id)
            order = db.one('SELECT * FROM orders WHERE account_id=? AND id=?', (account_id, order_id))
            if not order:
                raise Rejected('Unknown account order')
            prior = db.one('SELECT * FROM fills WHERE id=?', (fill_id,))
            if prior:
                if any(prior[k] != v for k,v in {'id':fill_id,'order_id':order_id,'quantity':quantity,'price_cents':price_cents}.items()):
                    raise Rejected('Fill identifier collision')
                return order
            validate_config(account['config'])
            if account['config']['mode'] != 'paper':
                raise Rejected('Fill simulation disabled outside paper/mock mode')
            if not self.snapshot_valid(account) or (order['side']=='BUY' and (account['stopped'] or db.one('SELECT stopped FROM supervisor WHERE id=1')['stopped'])):
                raise Rejected('Fill simulation locked')
            self._validate_ledger(db,account_id)
            if order['side']=='BUY':
                config=account['config']
                validate_config(config)
                watch=db.one('SELECT enabled,verified FROM watchlist WHERE account_id=? AND symbol=?',(account_id,order['symbol']))
                if order['quantity']>config['max_contracts'] or not watch or not watch['enabled'] or not watch['verified']:
                    raise Rejected('Mock buy fill locked by contract cap or watchlist policy')
                if config['mode']!='paper' or not self.market_valid(db,account_id,order['symbol']):
                    raise Rejected('Mock buy fill locked by mode or stale market data')
                equity=max(0,account['equity']+account['realized'])
                daily=db.one('SELECT pnl FROM daily_pnl WHERE account_id=? AND day=?',(account_id,self.today().isoformat()))
                if -(daily['pnl'] if daily else 0)*100 >= equity*config['daily_loss_pct']:
                    raise Rejected('Daily loss limit reached before fill')
                if order['quantity']*order['limit_cents']*100*100 > equity*config['trade_risk_pct']:
                    raise Rejected('Trade risk exceeded before fill')
                exposure=sum(p['cost'] for p in db.all('SELECT cost FROM positions WHERE account_id=?',(account_id,)))
                exposure+=sum((o['quantity']-o['filled'])*o['limit_cents']*100 for o in db.all("SELECT * FROM orders WHERE account_id=? AND side='BUY' AND status IN ('PENDING','PARTIAL')",(account_id,)))
                if exposure*100>equity*config['allocation_pct']:
                    raise Rejected('Account allocation exceeded before fill')
                self._check_supervisor(db,account)
            if order['status'] not in ACTIVE or quantity > order['quantity']-order['filled']:
                raise Rejected('Invalid fill state or excessive quantity')
            if date.fromisoformat(order['expiry']) <= self.today():
                raise Rejected('Cannot fill expired contract')
            if (order['side']=='BUY' and price_cents > order['limit_cents']) or (order['side']=='SELL_TO_CLOSE' and price_cents < order['limit_cents']):
                raise Rejected('Fill violates limit')
            key = (account_id, order['symbol'], order['right_kind'], order['expiry'], order['strike'])
            position = db.one('SELECT * FROM positions WHERE account_id=? AND symbol=? AND right_kind=? AND expiry=? AND strike=?', key)
            if order['side']=='BUY':
                current_qty = position['quantity'] if position else 0
                current_cost = position['cost'] if position else 0
                db.execute('INSERT INTO positions VALUES(?,?,?,?,?,?,?) ON CONFLICT(account_id,symbol,right_kind,expiry,strike) DO UPDATE SET quantity=excluded.quantity,cost=excluded.cost', key+(current_qty+quantity,current_cost+quantity*price_cents*100))
            else:
                if not position or position['quantity'] < quantity:
                    raise Rejected('Owned inventory unavailable')
                removed_cost = position['cost'] * quantity // position['quantity']
                pnl = quantity*price_cents*100-removed_cost
                db.execute('UPDATE accounts SET realized=realized+? WHERE id=?', (pnl, account_id))
                db.execute('INSERT INTO daily_pnl VALUES(?,?,?) ON CONFLICT(account_id,day) DO UPDATE SET pnl=daily_pnl.pnl+excluded.pnl', (account_id,self.today().isoformat(),pnl))
                db.execute('UPDATE positions SET quantity=quantity-?,cost=cost-? WHERE account_id=? AND symbol=? AND right_kind=? AND expiry=? AND strike=?', (quantity,removed_cost)+key)
                db.execute('DELETE FROM positions WHERE account_id=? AND quantity=0', (account_id,))
                updated=self.account(db,account_id)
                daily=db.one('SELECT pnl FROM daily_pnl WHERE account_id=? AND day=?',(account_id,self.today().isoformat()))['pnl']
                if -daily*100 >= max(0,updated['equity']+updated['realized'])*updated['config']['daily_loss_pct']:
                    db.execute("UPDATE orders SET status='CANCELLED' WHERE account_id=? AND side='BUY' AND status IN ('PENDING','PARTIAL')",(account_id,))
                    self.audit(db,account_id,'DAILY_LOSS_PENDING_BUYS_CANCELLED',{'daily_pnl_cents':daily})
            filled = order['filled']+quantity
            status = 'FILLED' if filled==order['quantity'] else 'PARTIAL'
            sequence=db.one('SELECT COALESCE(MAX(sequence),0) AS n FROM fills')['n']+1
            db.execute('INSERT INTO fills VALUES(?,?,?,?,?,?)', (fill_id,order_id,quantity,price_cents,sequence,self.today().isoformat()))
            db.execute('UPDATE orders SET filled=?,status=? WHERE id=?', (filled,status,order_id))
            if order['side']=='SELL_TO_CLOSE':
                self._cancel_unsafe_pending_buys(db)
            self.audit(db, account_id, 'MOCK_FILL', {'order_id':order_id,'quantity':quantity,'price_cents':price_cents})
            return db.one('SELECT * FROM orders WHERE id=?', (order_id,))
    def _cancel_unsafe_pending_buys(self, db):
        # Durable Mock cancellation; an external broker would require acknowledgement states.
        for row in db.all("SELECT DISTINCT account_id FROM orders WHERE side='BUY' AND status IN ('PENDING','PARTIAL')"):
            member_id=row['account_id']
            try:
                member=self.account(db,member_id)
            except Rejected as exc:
                db.execute("UPDATE orders SET status='CANCELLED' WHERE account_id=? AND side='BUY' AND status IN ('PENDING','PARTIAL')",(member_id,))
                db.execute('UPDATE accounts SET state_known=0 WHERE id=?',(member_id,))
                self.audit(db,member_id,'RISK_PENDING_BUYS_CANCELLED',{'reason':str(exc),'source':'synthetic_mock'})
                continue
            equity=max(0,member['equity']+member['realized'])
            daily=db.one('SELECT pnl FROM daily_pnl WHERE account_id=? AND day=?',(member_id,self.today().isoformat()))
            try:
                if -(daily['pnl'] if daily else 0)*100 >= equity*member['config']['daily_loss_pct']:
                    raise Rejected('Account daily loss reached')
                self._check_supervisor(db,member)
            except Rejected as exc:
                db.execute("UPDATE orders SET status='CANCELLED' WHERE account_id=? AND side='BUY' AND status IN ('PENDING','PARTIAL')",(member_id,))
                self.audit(db,member_id,'RISK_PENDING_BUYS_CANCELLED',{'reason':str(exc),'source':'synthetic_mock'})

    def cancel(self, account_id, order_id):
        with self.repo.transaction() as db:
            self.account(db, account_id)
            order = db.one('SELECT * FROM orders WHERE account_id=? AND id=?', (account_id,order_id))
            if not order:
                raise Rejected('Unknown account order')
            if order['status'] in ACTIVE:
                db.execute("UPDATE orders SET status='CANCELLED' WHERE id=?", (order_id,))
                self.audit(db, account_id, 'MOCK_ORDER_CANCELLED', {'order_id':order_id})
            return db.one('SELECT * FROM orders WHERE id=?', (order_id,))
    def expire(self, account_id=None):
        try:
            return self._expire(account_id)
        except Rejected:
            with self.repo.transaction() as db:
                for account in db.all('SELECT DISTINCT account_id FROM positions WHERE expiry<=?' + (' AND account_id=?' if account_id else ''), (self.today().isoformat(),account_id) if account_id else (self.today().isoformat(),)):
                    db.execute('UPDATE accounts SET state_known=0 WHERE id=?',(account['account_id'],))
                    self.audit(db,account['account_id'],'MOCK_EXPIRY_BLOCKED',{'reason':'ledger_untrusted'})
            raise

    def _expire(self, account_id=None):
        with self.repo.transaction() as db:
            if account_id is not None and not self.snapshot_valid(self.account(db,account_id)):
                raise Rejected('Account state unknown; expiry requires trusted reconciliation')
            suffix = ' AND account_id=?' if account_id is not None else ''
            params = (self.today().isoformat(),account_id) if account_id is not None else (self.today().isoformat(),)
            expired = db.all('SELECT * FROM positions WHERE expiry<=?'+suffix, params)
            for account_id in sorted({p['account_id'] for p in expired}):
                self._validate_ledger(db,account_id)
            for position in expired:
                account_id = position['account_id']
                # Conservative synthetic settlement: premium lost; assignment/exercise unsupported.
                db.execute('UPDATE accounts SET realized=realized-? WHERE id=?', (position['cost'],account_id))
                db.execute('INSERT INTO daily_pnl VALUES(?,?,?) ON CONFLICT(account_id,day) DO UPDATE SET pnl=daily_pnl.pnl+excluded.pnl', (account_id,self.today().isoformat(),-position['cost']))
                self.audit(db, account_id, 'MOCK_EXPIRY_WRITEOFF', position|{'settlement_day':self.today().isoformat()})
            db.execute('DELETE FROM positions WHERE expiry<=?'+suffix, params)
            db.execute("UPDATE orders SET status='EXPIRED' WHERE expiry<=? AND status IN ('PENDING','PARTIAL')"+suffix, params)
            if expired:
                self._cancel_unsafe_pending_buys(db)
        return len(expired)
    def performance(self, account_id):
        with self.repo.transaction() as db:
            account = self.account(db, account_id)
            positions = db.all('SELECT * FROM positions WHERE account_id=?', (account_id,))
            return {'source':'synthetic_mock','equity_cents':account['equity'],'realized_pnl_cents':account['realized'],'open_premium_cents':sum(p['cost'] for p in positions),'open_positions':len(positions),'live_enabled':False,'unrealized_pnl_cents':None}
