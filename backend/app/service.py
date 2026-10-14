"""Paper-only transaction service. No path in this module sends network orders."""
import hashlib
import json
import re
import uuid
from datetime import date, datetime, timezone
from .adapters import MockBrokerAdapter, MOCK_SYMBOLS

class Rejected(ValueError):
    pass

DEFAULT_CONFIG = {'mode': 'paper', 'broker': 'mock', 'allocation_pct': 30, 'trade_risk_pct': 2, 'daily_loss_pct': 3, 'max_contracts': 5, 'strategies': ['breakout', 'pullback'], 'holding': 'intraday', 'risk_group': None, 'connection_id': None, 'group_allocation_pct': 30, 'group_daily_loss_pct': 3, 'automation_enabled': False, 'stop_loss_pct': 20, 'take_profit_pct': 30, 'auto_quantity': 1, 'auto_fill_chunk': 1, 'max_spread_pct': 10, 'elevated_risk_ack': None, 'max_positions': 20, 'max_contract_premium_cents': 1000000, 'global_allocation_pct': 30, 'global_daily_loss_pct': 3, 'scaling_enabled': False, 'scaling_max_additions': 2, 'scaling_quantity': 1, 'scaling_cooldown_seconds': 60, 'scaling_decreasing': False, 'trailing_stop_pct': 0, 'partial_profit_pct': 0, 'partial_exit_pct': 50, 'expiry_exit_days': 1, 'intraday_exit_hour_utc': 20, 'swing_max_days': 10, 'require_open_loss_marks': True, 'scenario_exit_enabled': False, 'commission_cents': 0, 'reversal_enabled': False, 'session_policy': 'synthetic_24x7', 'session_exit_buffer_minutes': 15}
ACTIVE = ('PENDING', 'PARTIAL')

def integer(value, name, minimum=1, maximum=100000000):
    if type(value) is not int or not minimum <= value <= maximum:
        raise Rejected(f'{name} must be an integer in [{minimum}, {maximum}]')
    return value

RISK_FIELDS = ('allocation_pct', 'trade_risk_pct', 'daily_loss_pct', 'group_allocation_pct', 'group_daily_loss_pct', 'global_allocation_pct', 'global_daily_loss_pct')
SAFE_CAPS = dict(allocation_pct=30, trade_risk_pct=2, daily_loss_pct=3, group_allocation_pct=30, group_daily_loss_pct=3, global_allocation_pct=30, global_daily_loss_pct=3)

def risk_acknowledgement(config):
    """Exact effective risk settings, not a reusable blanket approval."""
    return hashlib.sha256(json.dumps({key: config[key] for key in RISK_FIELDS}, sort_keys=True).encode()).hexdigest()

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
    for key in RISK_FIELDS:
        integer(config.get(key, DEFAULT_CONFIG[key]), key, 0, 100)
    if any(config.get(key, DEFAULT_CONFIG[key]) > cap for key, cap in SAFE_CAPS.items()):
        if config.get('elevated_risk_ack') != risk_acknowledgement(DEFAULT_CONFIG | config):
            raise Rejected('Elevated risk requires acknowledgement of the exact effective percentages')
    for key in ('scaling_enabled', 'scaling_decreasing', 'require_open_loss_marks', 'scenario_exit_enabled', 'reversal_enabled'):
        if type(config.get(key, DEFAULT_CONFIG[key])) is not bool:
            raise Rejected(f'{key} must be boolean')
    if config.get('require_open_loss_marks', True) is not True:
        raise Rejected('Fresh option marks are a mandatory risk gate and cannot be disabled')
    for key, minimum, maximum in [('commission_cents',0,100000), ('max_positions',1,1000), ('max_contract_premium_cents',1,100000000), ('scaling_max_additions',0,100), ('scaling_quantity',1,100), ('scaling_cooldown_seconds',1,86400), ('trailing_stop_pct',0,95), ('partial_profit_pct',0,500), ('partial_exit_pct',1,99), ('expiry_exit_days',0,30), ('intraday_exit_hour_utc',0,23), ('swing_max_days',1,365)]:
        integer(config.get(key, DEFAULT_CONFIG[key]), key, minimum, maximum)
    integer(config.get('max_contracts'), 'max_contracts', 1, 100)
    if config.get('session_policy', DEFAULT_CONFIG['session_policy']) not in ('synthetic_24x7', 'us_equity_options_2026_2027'):
        raise Rejected('Unsupported session policy')
    integer(config.get('session_exit_buffer_minutes', 15), 'session_exit_buffer_minutes', 1, 120)
    if config.get('holding') not in ('intraday', 'swing'):
        raise Rejected('Invalid holding mode')
    if not isinstance(config.get('strategies'), list) or not all(isinstance(item,str) and item in {'breakout','pullback'} for item in config['strategies']):
        raise Rejected('Only quantitative breakout/pullback strategies are available')

class TradingService:
    def __init__(self, repository, today=None, now=None):
        self.repo = repository
        self.now = now or (lambda: datetime.now(timezone.utc))
        self.today = today or (lambda: datetime.now(timezone.utc).date())
    def market_session(self, config):
        from .market_sessions import evaluate_session, unavailable_session
        try:
            return evaluate_session(self.now(), config['session_policy'],
                                    config['session_exit_buffer_minutes']).as_dict()
        except Exception:
            # Calendar failure never fabricates executable hours or prevents
            # independently justified owned close intents being journaled.
            return unavailable_session(config['session_policy']).as_dict()

    def option_expiration(self, config, expiry):
        """Contract timing only; never a settlement, exercise, or fill receipt."""
        expiry = date.fromisoformat(expiry) if isinstance(expiry, str) else expiry
        if config['session_policy'] == 'synthetic_24x7':
            active = expiry > self.today()
            return {'status': 'LEGACY_SYNTHETIC', 'nominal_expiry': expiry.isoformat(),
                    'entry_allowed': active, 'close_intent_allowed': active,
                    'close_fill_allowed': active, 'review_required': False,
                    'days_to_last_trade': (expiry-self.today()).days,
                    'policy_version': 'synthetic_premium_lost_no_exercise'}
        from .option_expiration import evaluate_expiration
        return evaluate_expiration(expiry, self.now())

    def expiration_reviews(self, db, account):
        if account['config']['session_policy'] == 'synthetic_24x7':
            return []
        reviews = []
        for position in db.all('SELECT * FROM positions WHERE account_id=?', (account['id'],)):
            timing = self.option_expiration(account['config'], position['expiry'])
            if timing['review_required']:
                reviews.append(position | {'expiration': timing})
        return reviews

    def entry_session_current(self, db, order, session):
        if session['policy'] == 'synthetic_24x7':
            return True
        if not session['entry_allowed'] or not session['opens_at']:
            return False
        records = db.all("SELECT payload,digest FROM decision_snapshots WHERE account_id=? AND order_id=? AND action='ORDER_ACCEPTED'",
                         (order['account_id'], order['id']))
        try:
            if len(records) != 1 or hashlib.sha256(records[0]['payload'].encode()).hexdigest() != records[0]['digest']:
                return False
            accepted_at = datetime.fromisoformat(json.loads(records[0]['payload'])['recorded_at'])
            return datetime.fromisoformat(session['opens_at']) <= accepted_at <= self.now()
        except (ValueError, TypeError, KeyError):
            return False

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
        if not isinstance(changes, dict):
            raise Rejected('Configuration object required')
        if not set(changes) <= set(DEFAULT_CONFIG):
            raise Rejected('Unknown configuration field')
        with self.repo.transaction() as db:
            account = self.account(db, account_id)
            config = account['config'] | changes
            if changes.get('elevated_risk_ack') is True:
                config['elevated_risk_ack'] = risk_acknowledgement(config)
            validate_config(config)
            if config['session_policy'] != account['config']['session_policy']:
                outstanding = db.one('SELECT account_id FROM positions WHERE account_id=?', (account_id,))
                outstanding = outstanding or db.one('SELECT account_id FROM paper_delivery_positions WHERE account_id=?', (account_id,))
                outstanding = outstanding or db.one("SELECT id FROM orders WHERE account_id=? AND status IN ('PENDING','PARTIAL')", (account_id,))
                outstanding = outstanding or db.one("SELECT id FROM lifecycle_intents WHERE account_id=? AND state NOT IN ('COMPLETE','EXPIRED','CANCELLED')", (account_id,))
                if outstanding:
                    raise Rejected('Session policy cannot change while inventory, orders or lifecycle intents remain unresolved')
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
                if (-(daily['pnl'] if daily else 0)+self._open_loss(db,account))*100>=equity*account['config']['daily_loss_pct']:
                    raise Rejected('Daily loss gate closed')
                risk_ready=True
            except Rejected:
                risk_ready=False
            watches=db.all('SELECT symbol FROM watchlist WHERE account_id=? AND enabled=1 AND verified=1',(account_id,))
            market_ready=any(self.market_valid(db,account_id,w['symbol']) for w in watches)
            session=self.market_session(account['config'])
            return {'state_known':bool(account['state_known']),'snapshot_valid':valid,'stopped':bool(account['stopped']),'global_stopped':globally_stopped,'mode':account['config']['mode'],'broker':'mock','live_enabled':False,'source':'synthetic_mock','market_data_ready':market_ready,'risk_guard_ready':risk_ready,'session':session,'expiration_reviews':self.expiration_reviews(db,account),'new_entries_allowed':session['entry_allowed'] and valid and market_ready and risk_ready and not account['stopped'] and not globally_stopped and account['config']['mode']=='paper' and account['config']['allocation_pct']>0 and account['config']['trade_risk_pct']>0,'emergency_policy':'owned_closes_only_after_trusted_reconciliation'}

    def _check_supervisor(self, db, account, cost=0):
        self._check_linked_risk(db,account,cost)
        # Global caps are the strictest acknowledged member settings; defaults 30/3.
        for member in db.all('SELECT id FROM accounts'):
            self._validate_ledger(db,member['id'])
        # Untrusted unrelated capital is excluded, but its committed exposure/loss stays counted.
        all_capital = sum(max(0,a['equity']+a['realized']) for a in db.all('SELECT * FROM accounts') if self.snapshot_valid(a))
        all_exposure = sum(p['cost'] for p in db.all('SELECT cost FROM positions')) + sum(self._pending_cost(db,o) for o in db.all("SELECT * FROM orders WHERE side='BUY' AND status IN ('PENDING','PARTIAL')"))
        global_daily=sum(row['pnl'] for row in db.all('SELECT pnl FROM daily_pnl WHERE day=?',(self.today().isoformat(),)))
        members=[self.account(db,row['id']) for row in db.all('SELECT id FROM accounts')]
        global_open_loss=sum(self._open_loss(db,a) for a in members)
        global_loss=min((a['config']['global_daily_loss_pct'] for a in members), default=3)
        global_allocation=min((a['config']['global_allocation_pct'] for a in members), default=30)
        if (-global_daily+global_open_loss)*100 >= all_capital*global_loss:
            raise Rejected('Global daily loss limit reached')
        if (all_exposure+cost)*100 > all_capital*global_allocation:
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
            exposure+=sum(self._pending_cost(db,o) for o in db.all("SELECT * FROM orders WHERE account_id=? AND side='BUY' AND status IN ('PENDING','PARTIAL')",(member['id'],)))
            pnl=db.one('SELECT pnl FROM daily_pnl WHERE account_id=? AND day=?',(member['id'],self.today().isoformat()))
            daily+=(pnl['pnl'] if pnl else 0)-self._open_loss(db,member)
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
        if table not in {'watchlist', 'orders', 'positions', 'audit', 'decision_snapshots', 'lifecycle_intents', 'paper_settlement_receipts', 'paper_delivery_positions'}:
            raise Rejected('Unsupported resource')
        with self.repo.transaction() as db:
            self.account(db, account_id)
            return db.all(f'SELECT * FROM {table} WHERE account_id=?', (account_id,))
    def stop(self, account_id=None):
        with self.repo.transaction() as db:
            if account_id:
                self.account(db, account_id)
                db.execute('UPDATE accounts SET stopped=1 WHERE id=?', (account_id,))
                db.execute("UPDATE orders SET status='CANCELLED' WHERE account_id=? AND side='BUY' AND status IN ('PENDING','PARTIAL')", (account_id,))
            else:
                db.execute('UPDATE supervisor SET stopped=1 WHERE id=1')
                db.execute("UPDATE orders SET status='CANCELLED' WHERE side='BUY' AND status IN ('PENDING','PARTIAL')")
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
        from .settlement_ledger import Replay, acquisition_time
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
        settlements = Replay(db, account_id, initial, inventory, daily_ledger)
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
        ledger=db.all('SELECT f.*,t.recorded_at FROM fills f JOIN orders o ON o.id=f.order_id LEFT JOIN fill_receipt_times t ON t.fill_id=f.id WHERE o.account_id=? ORDER BY f.sequence',(account_id,))
        for fill in ledger:
            realized = settlements.through(fill['sequence'], realized)
            order=by_id[fill['order_id']]
            quantity,price=fill['quantity'],fill['price_cents']
            if quantity<=0 or price<=0 or (order['side']=='BUY' and price>order['limit_cents']) or (order['side']=='SELL_TO_CLOSE' and price<order['limit_cents']):
                raise Rejected('Invalid fill ledger')
            key=(order['symbol'],order['right_kind'],order['expiry'],order['strike'])
            held,cost=inventory.get(key,(0,0))
            if order['side']=='BUY':
                inventory[key]=(held+quantity,cost+quantity*(price*100+self._fee(db,order['id'])))
                settlements.acquired[key] = acquisition_time(fill)
            else:
                if held<quantity:
                    raise Rejected('Short inventory in fill ledger')
                removed=cost*quantity//held
                pnl=quantity*(price*100-self._fee(db,order['id']))-removed
                realized+=pnl
                daily_ledger[fill['day']]=daily_ledger.get(fill['day'],0)+pnl
                inventory[key]=(held-quantity,cost-removed)
            settlements.cursor = fill['sequence']
        realized = settlements.through(None, realized)
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
        actual_deliveries = {p['symbol']: {'quantity': p['quantity'], 'cost': p['cost']} for p in
            db.all('SELECT * FROM paper_delivery_positions WHERE account_id=?', (account_id,))}
        if actual_deliveries != settlements.deliveries:
            raise Rejected('Delivered share ledger mismatch; account remains locked')

    def settle_paper(self, account_id, request):
        from .settlement_ledger import settle
        return settle(self, account_id, request)

    def decision(self, db, account_id, action, facts, order_id=None, intent_id=None):
        if order_id is not None and not db.one('SELECT id FROM orders WHERE account_id=? AND id=?',(account_id,order_id)):
            raise Rejected('Decision order belongs to a different account or is unknown')
        if intent_id is not None:
            intent=db.one('SELECT account_id FROM lifecycle_intents WHERE id=?',(intent_id,))
            if intent is not None and intent['account_id']!=account_id:
                raise Rejected('Decision intent belongs to a different account')
        payload = json.dumps({'schema_version': 1, 'source': 'synthetic_mock', 'rule_version': 'v1.0',
                              'recorded_at': self.now().isoformat(), **facts}, sort_keys=True, allow_nan=False)
        identifier = str(uuid.uuid4())
        db.execute('INSERT INTO decision_snapshots VALUES(?,?,?,?,?,?,?,?)',
                   (identifier, account_id, order_id, intent_id, action, payload,
                    hashlib.sha256(payload.encode()).hexdigest(), self.now().isoformat()))
        return identifier

    def _fee(self, db, order_id):
        row=db.one('SELECT commission_cents FROM order_costs WHERE order_id=?',(order_id,))
        return row['commission_cents'] if row else 0  # Immutable pre-V1 receipts had no modeled fee.

    def _pending_cost(self, db, order):
        return (order['quantity']-order['filled'])*(order['limit_cents']*100+self._fee(db,order['id']))

    def _direction_and_quantity(self, db, account, symbol, right, additional=0):
        if db.one('SELECT symbol FROM paper_delivery_positions WHERE account_id=?', (account['id'],)):
            raise Rejected('Delivered stock valuation unavailable; new option exposure blocked')
        positions = db.all('SELECT * FROM positions WHERE account_id=?', (account['id'],))
        pending = db.all("SELECT * FROM orders WHERE account_id=? AND side='BUY' AND status IN ('PENDING','PARTIAL')", (account['id'],))
        if any(p['symbol']==symbol and p['right_kind']!=right and p['quantity']>0 for p in positions):
            raise Rejected('Opposite direction locked by owned contracts')
        if any(o['symbol']==symbol and o['right_kind']!=right for o in pending):
            raise Rejected('Opposite direction locked by unresolved entry')
        total = sum(p['quantity'] for p in positions) + sum(o['quantity']-o['filled'] for o in pending)
        if total+additional > account['config']['max_contracts']:
            raise Rejected('Contract limit exceeded: owned plus pending contracts')
        keys = {(p['symbol'],p['right_kind'],p['expiry'],p['strike']) for p in positions}
        keys |= {(o['symbol'],o['right_kind'],o['expiry'],o['strike']) for o in pending}
        if len(keys) > account['config']['max_positions']:
            raise Rejected('Maximum open positions exceeded')

    def _check_quantitative_fill_policy(self, db, account, order):
        """Current permissions for a new quantitative BUY fill, from saved facts.

        This never reinterprets manual orders or already recorded fill receipts.
        Older automated orders lacking sufficient evidence remain cancellable,
        but cannot acquire new inventory by inventing their original strategy.
        """
        prefix, separator, _ = order['request_key'].partition(':')
        if not separator or prefix not in ('auto-e', 'v1-r', 'v1-s'):
            return
        records = db.all("SELECT * FROM decision_snapshots WHERE account_id=? AND order_id=? AND action='ORDER_ACCEPTED'",
                         (account['id'], order['id']))
        automatic_reversal = False
        try:
            if len(records) != 1:
                raise ValueError('Unique accepted decision required')
            record = records[0]
            if hashlib.sha256(record['payload'].encode()).hexdigest() != record['digest']:
                raise ValueError('Accepted decision digest mismatch')
            accepted = json.loads(record['payload'])
            automatic_authority = accepted.get('automatic_authority')
            if 'automatic_authority' in accepted and type(automatic_authority) is not bool:
                raise ValueError('Explicit execution authority required')
            request = accepted['request']
            if (accepted['source'] != 'synthetic_mock'
                    or hashlib.sha256(json.dumps(request, sort_keys=True).encode()).hexdigest() != order['fingerprint']):
                raise ValueError('Accepted decision order mismatch')
            facts = accepted['facts']
            if prefix == 'auto-e':
                if facts['strategy_source'] != 'completed_bar_quantitative_worker':
                    raise ValueError('Unknown strategy authority')
                signal = facts.get('facts', {}).get('signal')
                strategy = signal['strategy'] if signal is not None else facts['reason']
                if signal is not None and signal['right'] != order['right_kind']:
                    raise ValueError('Accepted signal direction mismatch')
            else:
                kind = 'REVERSAL' if prefix == 'v1-r' else 'SCALING'
                intent = db.one('SELECT * FROM lifecycle_intents WHERE account_id=? AND id=? AND order_id=? AND kind=?',
                                (account['id'], record['intent_id'], order['id'], kind))
                if not intent or intent['symbol'] != order['symbol']:
                    raise ValueError('Accepted lifecycle identity mismatch')
                payload = json.loads(intent['payload'])
                if kind == 'REVERSAL':
                    if (facts['reason'] != 'REVALIDATED_REVERSAL_ENTRY'
                            or payload['target_right'] != order['right_kind']
                            or type(payload['automatic']) is not bool):
                        raise ValueError('Accepted reversal authority mismatch')
                    automatic_reversal = payload['automatic']
                    signal = facts['signal']
                else:
                    if facts['reason'] != 'PROFITABLE_POSITION_SCALING':
                        raise ValueError('Accepted scaling authority mismatch')
                    signal = facts['facts']
                if signal['right'] != order['right_kind'] or signal['symbol'] != order['symbol']:
                    raise ValueError('Accepted lifecycle signal identity mismatch')
                strategy = signal['strategy']
            if prefix == 'v1-s' and automatic_authority is None:
                # Legacy scaling receipts did not distinguish caller origin.
                # A formerly enabled worker cannot be assumed to be manual.
                automatic_authority = accepted['config']['automation_enabled']
                if type(automatic_authority) is not bool:
                    raise ValueError('Legacy execution authority unavailable')
            if strategy not in ('breakout', 'pullback'):
                raise ValueError('Unknown quantitative strategy')
        except (ValueError, TypeError, KeyError, AttributeError):
            raise Rejected('Quantitative entry authorization evidence unavailable or invalid; cancel the remaining order') from None
        if strategy not in account['config']['strategies']:
            raise Rejected('Quantitative entry strategy disabled before fill')
        if automatic_reversal and not account['config']['reversal_enabled']:
            raise Rejected('Automatic reversal disabled before fill')
        if (prefix == 'auto-e' or automatic_reversal or automatic_authority) and not account['config']['automation_enabled']:
            raise Rejected('Automatic entry execution disabled before fill')

    def _check_scale_fill(self, db, account, order):
        if not account['config']['scaling_enabled']:
            raise Rejected('Scaling disabled before fill')
        key=(account['id'],order['symbol'],order['right_kind'],order['expiry'],order['strike'])
        intent=db.one("SELECT * FROM lifecycle_intents WHERE account_id=? AND order_id=? AND kind='SCALING'",(account['id'],order['id']))
        try:
            payload=json.loads(intent['payload']) if intent else {}
            number=integer(payload.get('addition_number'),'scaling addition ordinal',1,100)
            generation=integer(payload.get('generation'),'scaling generation',1)
            if payload.get('quantity')!=order['quantity']:
                raise Rejected('Scaling quantity ledger mismatch')
        except (ValueError,TypeError,KeyError):
            raise Rejected('Malformed scaling intent ledger') from None
        policy=db.one('SELECT generation FROM position_policies WHERE account_id=? AND symbol=? AND right_kind=? AND expiry=? AND strike=?',key)
        if not policy or policy['generation']!=generation:
            raise Rejected('Scaling parent position generation changed before fill')
        config=account['config']
        if number>config['scaling_max_additions']:
            raise Rejected('Scaling addition budget reduced before fill')
        allowed=config['scaling_quantity']//(2**(number-1)) if config['scaling_decreasing'] else config['scaling_quantity']
        # The accepted payload is immutable: cancel an oversized remainder;
        # never silently rewrite it into a different idempotent order.
        if order['quantity']>allowed:
            raise Rejected('Scaling quantity reduced before fill')
        owned=db.one('SELECT * FROM positions WHERE account_id=? AND symbol=? AND right_kind=? AND expiry=? AND strike=?',key)
        mark=db.one('SELECT * FROM option_marks WHERE account_id=? AND symbol=? AND right_kind=? AND expiry=? AND strike=?',key)
        if not owned or not mark or not 0 <= (self.now()-datetime.fromisoformat(mark['observed_at'])).total_seconds() <= 60:
            raise Rejected('Scaling fill requires fresh owned-position mark')
        if (mark['bid']*100-account['config']['commission_cents'])*owned['quantity']<=owned['cost']:
            raise Rejected('Scaling position is no longer profitable before fill')
        if db.one("SELECT id FROM orders WHERE account_id=? AND symbol=? AND side='SELL_TO_CLOSE' AND status IN ('PENDING','PARTIAL')",(account['id'],order['symbol'])):
            raise Rejected('Owned close takes precedence over scaling fill')

    def record_option_mark(self, db, account_id, symbol, right, expiry, strike, bid, ask, observed_at):
        """Validated synthetic bid/ask observation; never an inferred broker valuation."""
        integer(bid, 'bid', 1, 1000000)
        integer(ask, 'ask', bid, 1000000)
        if not 0 <= (self.now()-observed_at).total_seconds() <= 60:
            raise Rejected('Option mark stale or future')
        if not self.market_valid(db, account_id, symbol):
            raise Rejected('Option mark requires current market observation')
        key=(account_id,symbol,right,expiry,strike)
        previous=db.one('SELECT observed_at FROM option_marks WHERE account_id=? AND symbol=? AND right_kind=? AND expiry=? AND strike=?',key)
        if previous and observed_at < datetime.fromisoformat(previous['observed_at']):
            raise Rejected('Option mark cannot move backwards')
        db.execute('INSERT INTO option_marks VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(account_id,symbol,right_kind,expiry,strike) DO UPDATE SET bid=excluded.bid,ask=excluded.ask,observed_at=excluded.observed_at', key+(bid,ask,observed_at.isoformat()))

    def _projected_close_fee(self, db, account, position):
        closes=db.all("SELECT * FROM orders WHERE account_id=? AND symbol=? AND right_kind=? AND expiry=? AND strike=? AND side='SELL_TO_CLOSE' AND status IN ('PENDING','PARTIAL')",(account['id'],position['symbol'],position['right_kind'],position['expiry'],position['strike']))
        reserved=sum(o['quantity']-o['filled'] for o in closes)
        if reserved>position['quantity']:
            raise Rejected('Closing reservation ledger exceeds owned inventory')
        return sum((o['quantity']-o['filled'])*self._fee(db,o['id']) for o in closes)+(position['quantity']-reserved)*account['config']['commission_cents']

    def _open_loss(self, db, account):
        if db.one('SELECT symbol FROM paper_delivery_positions WHERE account_id=?', (account['id'],)):
            raise Rejected('Delivered stock valuation unavailable; open-loss risk unknown')
        if self.expiration_reviews(db, account):
            raise Rejected('Unresolved option expiration; open-loss valuation unavailable')
        loss=0
        for p in db.all('SELECT * FROM positions WHERE account_id=?',(account['id'],)):
            if not self.market_valid(db,account['id'],p['symbol']):
                raise Rejected('Owned market feed unavailable; open-loss valuation untrusted')
            mark=db.one('SELECT * FROM option_marks WHERE account_id=? AND symbol=? AND right_kind=? AND expiry=? AND strike=?',(account['id'],p['symbol'],p['right_kind'],p['expiry'],p['strike']))
            if not mark or not 0 <= (self.now()-datetime.fromisoformat(mark['observed_at'])).total_seconds() <= 60:
                raise Rejected('Fresh option marks required for open-loss risk')
            loss += max(0, p['cost']-mark['bid']*100*p['quantity']+self._projected_close_fee(db,account,p))
        return loss

    def submit(self, account_id, request):
        try:
            return self._submit(account_id,request)
        except Rejected as exc:
            with self.repo.transaction() as db:
                if 'ledger' in str(exc).lower() or 'provenance' in str(exc).lower():
                    db.execute('UPDATE accounts SET state_known=0 WHERE id=?',(account_id,))
                exists=db.one('SELECT id FROM accounts WHERE id=?',(account_id,))
                if exists:
                    self.decision(db, account_id, 'ORDER_REJECTED', {'reason': str(exc), 'symbol': request.get('symbol') if isinstance(request, dict) else None})
                self.audit(db,account_id if exists else None,'ORDER_REJECTED',{'reason':str(exc),'symbol':request.get('symbol') if isinstance(request,dict) else None,'source':'quantitative_risk_gate'})
            raise
    def _submit(self, account_id, request):
        required = {'request_key','symbol','right','expiry','strike_cents','side','quantity','limit_cents'}
        if not isinstance(request,dict) or set(request) != required:
            raise Rejected('Exact single-leg option order fields required')
        if not isinstance(request['request_key'], str) or not 1 <= len(request['request_key']) <= 100:
            raise Rejected('Idempotency key required')
        if request['request_key'].startswith(('auto-e:', 'auto-x:', 'v1-r:', 'v1-s:')) and not getattr(self, '_automation_authorized', False):
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
            expiration = self.option_expiration(config, expiry)
            session = self.market_session(config)
            if request['side'] == 'BUY' and not session['entry_allowed']:
                raise Rejected('Market session blocks new entry: ' + session['status'])
            if not expiration['entry_allowed' if request['side'] == 'BUY' else 'close_intent_allowed']:
                raise Rejected('Expiration policy blocks order: expired or same-day entry disabled')
            if config['mode'] != 'paper':
                raise Rejected('Order execution disabled in shadow/analysis modes')
            if request['side']=='BUY' and (account['stopped'] or db.one('SELECT stopped FROM supervisor WHERE id=1')['stopped']):
                raise Rejected('Emergency stop active')
            if not self.snapshot_valid(account):
                raise Rejected('Account state unknown; reconcile first')
            self._validate_ledger(db,account_id)
            if request['side']=='BUY' and quantity > config['max_contracts']:
                raise Rejected('Contract limit exceeded')
            position_key = (account_id, symbol, request['right'], request['expiry'], strike)
            if request['side'] == 'BUY':
                active_intent=db.one("SELECT id FROM lifecycle_intents WHERE account_id=? AND symbol=? AND kind='REVERSAL' AND state NOT IN ('COMPLETE','EXPIRED','CANCELLED')",(account_id,symbol))
                if active_intent and active_intent['id']!=getattr(self,'_intent_id',None):
                    raise Rejected('Unresolved reversal owns this symbol entry lock')
                self._direction_and_quantity(db, account, symbol, request['right'], quantity)
                if price*100 > config['max_contract_premium_cents']:
                    raise Rejected('Maximum contract premium exceeded')
                identities={(p['symbol'],p['right_kind'],p['expiry'],p['strike']) for p in db.all('SELECT * FROM positions WHERE account_id=?',(account_id,))}
                identities|={(o['symbol'],o['right_kind'],o['expiry'],o['strike']) for o in db.all("SELECT * FROM orders WHERE account_id=? AND side='BUY' AND status IN ('PENDING','PARTIAL')",(account_id,))}
                identities.add((symbol,request['right'],request['expiry'],strike))
                if len(identities)>config['max_positions']:
                    raise Rejected('Maximum open positions exceeded')
                watch = db.one('SELECT * FROM watchlist WHERE account_id=? AND symbol=?', (account_id, symbol))
                if not watch or not watch['enabled'] or not watch['verified']:
                    raise Rejected('Watchlist symbol must have mock verification and be enabled')
                if not self.market_valid(db,account_id,symbol):
                    raise Rejected('Market data unavailable or stale; refresh mock observation')
                cost = quantity * (price * 100 + config['commission_cents'])
                equity = max(0,account['equity']+account['realized'])
                if cost * 100 > equity * config['trade_risk_pct']:
                    raise Rejected('Per-trade maximum premium risk exceeded')
                daily = db.one('SELECT pnl FROM daily_pnl WHERE account_id=? AND day=?', (account_id,self.today().isoformat()))
                if (-(daily['pnl'] if daily else 0)+self._open_loss(db,account)) * 100 >= equity * config['daily_loss_pct']:
                    raise Rejected('Daily loss limit reached')
                positions = db.all('SELECT cost FROM positions WHERE account_id=?', (account_id,))
                pending = db.all("SELECT * FROM orders WHERE account_id=? AND side='BUY' AND status IN ('PENDING','PARTIAL')", (account_id,))
                exposure = sum(p['cost'] for p in positions) + sum(self._pending_cost(db,o) for o in pending)
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
            db.execute('INSERT INTO order_costs VALUES(?,?)',(order_id,config['commission_cents']))
            self.decision(db, account_id, 'ORDER_ACCEPTED', {'request':request, 'config':config, 'session':session, 'expiration':expiration, 'automatic_authority':bool(getattr(self,'_automatic_origin',getattr(self,'_automation_authorized',False))), 'account_equity_cents':account['equity'], 'realized_pnl_cents':account['realized'], 'facts':getattr(self, '_decision_context', {'reason':'MANUAL_STRUCTURED_REQUEST','language_model_authority':False}), 'risk_rules':'v1_direction_owned_pending_cap_allocation_daily_trust'}, order_id, getattr(self, '_intent_id', None))
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
            expiration = self.option_expiration(account['config'], order['expiry'])
            if not expiration['entry_allowed' if order['side'] == 'BUY' else 'close_fill_allowed']:
                raise Rejected('Expiration policy blocks fill: expired, final-day entry or unverified calendar')
            session = self.market_session(account['config'])
            if not session['fill_allowed']:
                raise Rejected('Market session blocks fill: ' + session['status'])
            if order['side'] == 'BUY' and not self.entry_session_current(db, order, session):
                raise Rejected('Market session or prior-session decision blocks entry fill')
            if account['config']['mode'] != 'paper':
                raise Rejected('Fill simulation disabled outside paper/mock mode')
            if not self.snapshot_valid(account) or (order['side']=='BUY' and (account['stopped'] or db.one('SELECT stopped FROM supervisor WHERE id=1')['stopped'])):
                raise Rejected('Fill simulation locked')
            self._validate_ledger(db,account_id)
            if order['side']=='BUY':
                config=account['config']
                validate_config(config)
                self._direction_and_quantity(db, account, order['symbol'], order['right_kind'])
                self._check_quantitative_fill_policy(db, account, order)
                scaling=db.one("SELECT id FROM lifecycle_intents WHERE account_id=? AND order_id=? AND kind='SCALING'",(account_id,order_id))
                if scaling:
                    self._check_scale_fill(db,account,order)
                watch=db.one('SELECT enabled,verified FROM watchlist WHERE account_id=? AND symbol=?',(account_id,order['symbol']))
                if order['limit_cents']*100>config['max_contract_premium_cents']:
                    raise Rejected('Maximum contract premium exceeded before fill')
                if order['quantity']>config['max_contracts'] or not watch or not watch['enabled'] or not watch['verified']:
                    raise Rejected('Mock buy fill locked by contract cap or watchlist policy')
                if config['mode']!='paper' or not self.market_valid(db,account_id,order['symbol']):
                    raise Rejected('Mock buy fill locked by mode or stale market data')
                equity=max(0,account['equity']+account['realized'])
                daily=db.one('SELECT pnl FROM daily_pnl WHERE account_id=? AND day=?',(account_id,self.today().isoformat()))
                if (-(daily['pnl'] if daily else 0)+self._open_loss(db,account))*100 >= equity*config['daily_loss_pct']:
                    raise Rejected('Daily loss limit reached before fill')
                if order['quantity']*(order['limit_cents']*100+self._fee(db,order_id))*100 > equity*config['trade_risk_pct']:
                    raise Rejected('Trade risk exceeded before fill')
                exposure=sum(p['cost'] for p in db.all('SELECT cost FROM positions WHERE account_id=?',(account_id,)))
                exposure+=sum(self._pending_cost(db,o) for o in db.all("SELECT * FROM orders WHERE account_id=? AND side='BUY' AND status IN ('PENDING','PARTIAL')",(account_id,)))
                if exposure*100>equity*config['allocation_pct']:
                    raise Rejected('Account allocation exceeded before fill')
                self._check_supervisor(db,account)
            if order['status'] not in ACTIVE or quantity > order['quantity']-order['filled']:
                raise Rejected('Invalid fill state or excessive quantity')
            if (order['side']=='BUY' and price_cents > order['limit_cents']) or (order['side']=='SELL_TO_CLOSE' and price_cents < order['limit_cents']):
                raise Rejected('Fill violates limit')
            key = (account_id, order['symbol'], order['right_kind'], order['expiry'], order['strike'])
            position = db.one('SELECT * FROM positions WHERE account_id=? AND symbol=? AND right_kind=? AND expiry=? AND strike=?', key)
            if order['side']=='BUY':
                current_qty = position['quantity'] if position else 0
                current_cost = position['cost'] if position else 0
                if current_qty == 0:
                    generation=db.one('SELECT COALESCE(MAX(sequence),0) AS n FROM fills')['n']+1
                    db.execute('INSERT INTO position_policies VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(account_id,symbol,right_kind,expiry,strike) DO UPDATE SET generation=excluded.generation,high_bid=0,partial_taken=0,opened_at=excluded.opened_at', key+(generation,0,0,self.now().isoformat()))
                db.execute('INSERT INTO positions VALUES(?,?,?,?,?,?,?) ON CONFLICT(account_id,symbol,right_kind,expiry,strike) DO UPDATE SET quantity=excluded.quantity,cost=excluded.cost', key+(current_qty+quantity,current_cost+quantity*(price_cents*100+self._fee(db,order_id))))
            else:
                if not position or position['quantity'] < quantity:
                    raise Rejected('Owned inventory unavailable')
                removed_cost = position['cost'] * quantity // position['quantity']
                pnl = quantity*(price_cents*100-self._fee(db,order_id))-removed_cost
                db.execute('UPDATE accounts SET realized=realized+? WHERE id=?', (pnl, account_id))
                db.execute('INSERT INTO daily_pnl VALUES(?,?,?) ON CONFLICT(account_id,day) DO UPDATE SET pnl=daily_pnl.pnl+excluded.pnl', (account_id,self.today().isoformat(),pnl))
                db.execute('UPDATE positions SET quantity=quantity-?,cost=cost-? WHERE account_id=? AND symbol=? AND right_kind=? AND expiry=? AND strike=?', (quantity,removed_cost)+key)
                db.execute('DELETE FROM positions WHERE account_id=? AND quantity=0', (account_id,))
                if position['quantity'] == quantity:
                    db.execute('DELETE FROM position_policies WHERE account_id=? AND symbol=? AND right_kind=? AND expiry=? AND strike=?',key)
                updated=self.account(db,account_id)
                daily=db.one('SELECT pnl FROM daily_pnl WHERE account_id=? AND day=?',(account_id,self.today().isoformat()))['pnl']
                if -daily*100 >= max(0,updated['equity']+updated['realized'])*updated['config']['daily_loss_pct']:
                    db.execute("UPDATE orders SET status='CANCELLED' WHERE account_id=? AND side='BUY' AND status IN ('PENDING','PARTIAL')",(account_id,))
                    self.audit(db,account_id,'DAILY_LOSS_PENDING_BUYS_CANCELLED',{'daily_pnl_cents':daily})
            filled = order['filled']+quantity
            status = 'FILLED' if filled==order['quantity'] else 'PARTIAL'
            sequence=db.one('SELECT COALESCE(MAX(sequence),0) AS n FROM fills')['n']+1
            db.execute('INSERT INTO fills VALUES(?,?,?,?,?,?)', (fill_id,order_id,quantity,price_cents,sequence,self.today().isoformat()))
            db.execute('INSERT INTO fill_receipt_times VALUES(?,?)', (fill_id,self.now().isoformat()))
            db.execute('UPDATE orders SET filled=?,status=? WHERE id=?', (filled,status,order_id))
            if status == 'FILLED':
                db.execute("UPDATE lifecycle_intents SET state='COMPLETE',updated=? WHERE account_id=? AND order_id=?",(self.now().isoformat(),account_id,order_id))
            if order['side']=='SELL_TO_CLOSE':
                self._cancel_unsafe_pending_buys(db)
            self.audit(db, account_id, 'MOCK_FILL', {'order_id':order_id,'quantity':quantity,'price_cents':price_cents,'commission_cents':quantity*self._fee(db,order_id)})
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
                if (-(daily['pnl'] if daily else 0)+self._open_loss(db,member))*100 >= equity*member['config']['daily_loss_pct']:
                    raise Rejected('Account daily loss reached')
                self._check_supervisor(db,member)
            except Exception as exc:
                # A verified owned close must not be undone because a risk
                # calculation for pending entries is unavailable. Cancel those
                # synthetic reservations; every future entry/fill still runs
                # the mandatory supervisor and fails closed on its exception.
                # Unexpected diagnostics may contain sensitive implementation
                # details, so persist only the generic outage category.
                reason = str(exc) if isinstance(exc, Rejected) else 'Risk supervision unavailable; pending Mock buys cancelled'
                db.execute("UPDATE orders SET status='CANCELLED' WHERE account_id=? AND side='BUY' AND status IN ('PENDING','PARTIAL')",(member_id,))
                self.audit(db,member_id,'RISK_PENDING_BUYS_CANCELLED',{'reason':reason,'source':'synthetic_mock'})

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
        """Legacy fixture writeoffs or US close-only review; never inferred exercise."""
        written_off = 0
        with self.repo.transaction() as db:
            if account_id is not None and not self.snapshot_valid(self.account(db, account_id)):
                raise Rejected('Account state unknown; expiry requires trusted reconciliation')
            ids = [account_id] if account_id is not None else [r['id'] for r in db.all('SELECT id FROM accounts ORDER BY id')]
            for current_id in ids:
                account = self.account(db, current_id)
                positions = db.all('SELECT * FROM positions WHERE account_id=?', (current_id,))
                if account['config']['session_policy'] == 'synthetic_24x7':
                    expired = [p for p in positions if p['expiry'] <= self.today().isoformat()]
                    if expired:
                        if not self.snapshot_valid(account):
                            raise Rejected('Account state unknown; expiry requires trusted reconciliation')
                        self._validate_ledger(db, current_id)
                    for position in expired:
                        # Historical explicitly synthetic policy; do not reinterpret old receipts.
                        db.execute('UPDATE accounts SET realized=realized-? WHERE id=?', (position['cost'], current_id))
                        db.execute('INSERT INTO daily_pnl VALUES(?,?,?) ON CONFLICT(account_id,day) DO UPDATE SET pnl=daily_pnl.pnl+excluded.pnl', (current_id, self.today().isoformat(), -position['cost']))
                        self.audit(db, current_id, 'MOCK_EXPIRY_WRITEOFF', position | {'settlement_day': self.today().isoformat()})
                    db.execute('DELETE FROM positions WHERE account_id=? AND expiry<=?', (current_id, self.today().isoformat()))
                    db.execute('DELETE FROM position_policies WHERE account_id=? AND expiry<=?', (current_id, self.today().isoformat()))
                    db.execute("UPDATE orders SET status='EXPIRED' WHERE account_id=? AND expiry<=? AND status IN ('PENDING','PARTIAL')", (current_id, self.today().isoformat()))
                    written_off += len(expired)
                    continue

                reviews = self.expiration_reviews(db, account)
                pending = db.all("SELECT * FROM orders WHERE account_id=? AND status IN ('PENDING','PARTIAL')", (current_id,))
                changes = []
                for order in pending:
                    timing = self.option_expiration(account['config'], order['expiry'])
                    if timing['status'] == 'EXPIRY_REVIEW_REQUIRED':
                        changes.append((order, 'EXPIRED', timing))
                    elif order['side'] == 'BUY' and not timing['entry_allowed']:
                        changes.append((order, 'CANCELLED', timing))
                if reviews or changes:
                    if not self.snapshot_valid(account):
                        raise Rejected('Account state unknown; expiry review requires trusted reconciliation')
                    self._validate_ledger(db, current_id)
                previous = set()
                for row in db.all("SELECT detail FROM audit WHERE account_id=? AND event='MOCK_EXPIRY_REVIEW_REQUIRED'", (current_id,)):
                    try:
                        previous.add(json.loads(row['detail'])['review_key'])
                    except (ValueError, TypeError, KeyError):
                        raise Rejected('Malformed expiry review audit ledger') from None
                for review in reviews:
                    identity = {k: review[k] for k in ('symbol', 'right_kind', 'expiry', 'strike')}
                    key = (current_id, review['symbol'], review['right_kind'], review['expiry'], review['strike'])
                    policy = db.one('SELECT generation FROM position_policies WHERE account_id=? AND symbol=? AND right_kind=? AND expiry=? AND strike=?', key)
                    identity.update(generation=policy['generation'] if policy else None,
                                    status=review['expiration']['status'], cutoff_at=review['expiration'].get('cutoff_at'))
                    review_key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
                    if review_key not in previous:
                        self.audit(db, current_id, 'MOCK_EXPIRY_REVIEW_REQUIRED', review | {
                            'review_key': review_key, 'settlement_created': False,
                            'reason': 'Retained inventory and basis; exercise, delivery and settlement are unresolved'})
                        previous.add(review_key)
                for order, status, timing in changes:
                    db.execute('UPDATE orders SET status=? WHERE id=?', (status, order['id']))
                    self.audit(db, current_id, 'MOCK_EXPIRY_ORDER_BLOCKED', {
                        'order_id': order['id'], 'status': status, 'expiration': timing})
            if written_off:
                self._cancel_unsafe_pending_buys(db)
        return written_off
    def performance(self, account_id):
        with self.repo.transaction() as db:
            account = self.account(db, account_id)
            positions = db.all('SELECT * FROM positions WHERE account_id=?', (account_id,))
            deliveries = db.all('SELECT symbol,quantity,cost FROM paper_delivery_positions WHERE account_id=?', (account_id,))
            receipts = db.all('SELECT * FROM paper_settlement_receipts WHERE account_id=? ORDER BY sequence', (account_id,))
            from .settlement_ledger import decode
            settled = [decode(r)['result'] for r in receipts]
            premium=sum(p['cost'] for p in positions)
            delivery_basis=sum(p['cost'] for p in deliveries)
            cash=account['equity']+account['realized']-premium-delivery_basis
            unrealized=0
            complete=self.snapshot_valid(account) and not self.expiration_reviews(db, account) and not bool(deliveries)
            for position in positions:
                key=(account_id,position['symbol'],position['right_kind'],position['expiry'],position['strike'])
                mark=db.one('SELECT * FROM option_marks WHERE account_id=? AND symbol=? AND right_kind=? AND expiry=? AND strike=?',key)
                if not self.market_valid(db,account_id,position['symbol']) or not mark or not 0 <= (self.now()-datetime.fromisoformat(mark['observed_at'])).total_seconds() <= 60:
                    complete=False
                else:
                    unrealized+=mark['bid']*100*position['quantity']-position['cost']-self._projected_close_fee(db,account,position)
            reserved=sum(self._pending_cost(db,o) for o in db.all("SELECT * FROM orders WHERE account_id=? AND side='BUY' AND status IN ('PENDING','PARTIAL')",(account_id,)))
            fees=sum(f['quantity']*self._fee(db,f['order_id']) for f in db.all('SELECT f.* FROM fills f JOIN orders o ON o.id=f.order_id WHERE o.account_id=?',(account_id,)))
            fees+=sum(r['feeCents'] for r in settled)
            return {'source':'synthetic_mock','equity_cents':account['equity'],'realized_pnl_cents':account['realized'],'open_premium_cents':premium,'open_positions':len(positions),'live_enabled':False,'unrealized_pnl_cents':unrealized if complete else None,'valuation_complete':complete,'simulated_cash_cents':cash,'available_after_reservations_cents':cash-reserved,'total_commissions_cents':fees,'net_liquidation_cents':account['equity']+account['realized']+unrealized if complete else None,'valuation_policy':'fresh_synthetic_bid_minus_owned_basis_and_projected_close_fees','delivered_shares':deliveries,'delivered_share_basis_cents':delivery_basis,'settlement_events':len(settled),'settlement_realized_pnl_cents':sum(r['realizedPnl'] for r in settled),'settlement_source':'explicit_paper_receipts_not_broker_confirmation'}
