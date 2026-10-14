"""Transactional, explicitly virtual stock delivery. No provider or order client."""
from datetime import date, datetime, timedelta, timezone
import hashlib
import json

from .paper_settlement import PATTERN, project, stamp


def terms(contract):
    match = PATTERN.fullmatch(contract) if isinstance(contract, str) else None
    if not match:
        raise ValueError('Standard OCC contract required')
    expiry = date(2000 + int(match[2]), int(match[3]), int(match[4]))
    return match[1], 'CALL' if match[5] == 'C' else 'PUT', expiry.isoformat(), int(match[6]) // 10


def acquisition_time(fill):
    # Legacy fills only prove the day, so never invent intraday ownership.
    return fill.get('recorded_at') or (datetime.combine(date.fromisoformat(fill['day']),
        datetime.min.time(), timezone.utc) + timedelta(days=1)).isoformat()


def decode(row):
    if hashlib.sha256(row['payload'].encode()).hexdigest() != row['digest']:
        raise ValueError('Settlement receipt digest mismatch')
    value = json.loads(row['payload'])
    if set(value) != {'request', 'result'} or value['request']['id'] != row['receipt_id']:
        raise ValueError('Settlement receipt identity mismatch')
    return value


def settle(service, account_id, request):
    from .service import Rejected
    try:
        with service.repo.transaction() as db:
            account = service.account(db, account_id)
            service._validate_ledger(db, account_id)
            if not isinstance(request, dict):
                raise ValueError('Strict receipt required')
            prior = db.one('SELECT * FROM paper_settlement_receipts WHERE account_id=? AND receipt_id=?',
                           (account_id, request.get('id')))
            if prior:
                saved = decode(prior)
                if saved['request'] != request:
                    raise Rejected('Receipt identity conflict')
                return saved['result']
            config = account['config']
            if config['mode'] != 'paper' or config['broker'] != 'mock' or config['session_policy'] != 'us_equity_options_2026_2027':
                raise Rejected('Explicit US equity paper/mock policy required')
            if config['automation_enabled'] or not service.snapshot_valid(account):
                raise Rejected('Stop automation and reconcile the account before paper settlement')
            if db.one("SELECT id FROM audit WHERE account_id=? AND event='MOCK_EXPIRY_WRITEOFF'", (account_id,)):
                raise Rejected('Legacy synthetic writeoffs require historical lot reconstruction before delivery settlement')
            if db.one("SELECT id FROM orders WHERE account_id=? AND status IN ('PENDING','PARTIAL')", (account_id,)):
                raise Rejected('Resolve pending orders before settlement')
            if db.one("SELECT id FROM lifecycle_intents WHERE account_id=? AND state NOT IN ('COMPLETE','EXPIRED','CANCELLED')", (account_id,)):
                raise Rejected('Resolve lifecycle intents before settlement')
            key = terms(request['contract'])
            position = db.one('SELECT * FROM positions WHERE account_id=? AND symbol=? AND right_kind=? AND expiry=? AND strike=?', (account_id,) + key)
            latest = db.one("SELECT f.day,t.recorded_at FROM fills f JOIN orders o ON o.id=f.order_id LEFT JOIN fill_receipt_times t ON t.fill_id=f.id WHERE o.account_id=? AND o.symbol=? AND o.right_kind=? AND o.expiry=? AND o.strike=? AND o.side='BUY' ORDER BY f.sequence DESC LIMIT 1", (account_id,) + key)
            delivery = db.one('SELECT quantity,cost FROM paper_delivery_positions WHERE account_id=? AND symbol=?', (account_id, key[0]))
            option_basis = sum(p['cost'] for p in db.all('SELECT cost FROM positions WHERE account_id=?', (account_id,)))
            delivery_basis = sum(p['cost'] for p in db.all('SELECT cost FROM paper_delivery_positions WHERE account_id=?', (account_id,)))
            cash = account['equity'] + account['realized'] - option_basis - delivery_basis
            now = service.now()
            projected = project(None if position is None else {
                'contract': request['contract'], 'quantity': position['quantity'], 'cost': position['cost'],
                'entryFees': 0, 'opened': acquisition_time(latest)}, delivery, cash, request, now)
            removed = projected['optionQuantity']
            if removed:
                db.execute('UPDATE positions SET quantity=quantity-?,cost=cost-? WHERE account_id=? AND symbol=? AND right_kind=? AND expiry=? AND strike=?',
                           (removed, projected['removedCost'], account_id) + key)
                db.execute('DELETE FROM positions WHERE account_id=? AND quantity=0', (account_id,))
                if removed == position['quantity']:
                    db.execute('DELETE FROM position_policies WHERE account_id=? AND symbol=? AND right_kind=? AND expiry=? AND strike=?', (account_id,) + key)
            owned = delivery or {'quantity': 0, 'cost': 0}
            quantity, cost = owned['quantity'] + projected['shareDelta'], owned['cost'] + projected['shareBasisDelta']
            if quantity:
                db.execute('INSERT INTO paper_delivery_positions VALUES(?,?,?,?) ON CONFLICT(account_id,symbol) DO UPDATE SET quantity=excluded.quantity,cost=excluded.cost', (account_id, key[0], quantity, cost))
            else:
                db.execute('DELETE FROM paper_delivery_positions WHERE account_id=? AND symbol=?', (account_id, key[0]))
            pnl = projected['realizedPnl']
            db.execute('UPDATE accounts SET realized=realized+? WHERE id=?', (pnl, account_id))
            db.execute('INSERT INTO daily_pnl VALUES(?,?,?) ON CONFLICT(account_id,day) DO UPDATE SET pnl=daily_pnl.pnl+excluded.pnl',
                       (account_id, now.astimezone(timezone.utc).date().isoformat(), pnl))
            payload = json.dumps({'request': request, 'result': projected}, sort_keys=True, allow_nan=False)
            cursor = db.one('SELECT COALESCE(MAX(f.sequence),0) AS n FROM fills f JOIN orders o ON o.id=f.order_id WHERE o.account_id=?', (account_id,))['n']
            sequence = db.one('SELECT COALESCE(MAX(sequence),0)+1 AS n FROM paper_settlement_receipts WHERE account_id=?', (account_id,))['n']
            db.execute('INSERT INTO paper_settlement_receipts VALUES(?,?,?,?,?,?,?)', (account_id, sequence,
                request['id'], cursor, now.isoformat(), payload, hashlib.sha256(payload.encode()).hexdigest()))
            service.audit(db, account_id, 'PAPER_SETTLEMENT', {'receipt_id': request['id'], 'sequence': sequence, 'external_order': False})
            service._validate_ledger(db, account_id)
            return projected
    except (ValueError, TypeError, KeyError, OverflowError) as exc:
        raise Rejected('Invalid paper settlement: ' + str(exc)) from None


class Replay:
    """Interleave immutable settlement receipts with the original ordered fills."""
    def __init__(self, db, account_id, initial, inventory, daily):
        self.rows = db.all('SELECT * FROM paper_settlement_receipts WHERE account_id=? ORDER BY sequence', (account_id,))
        self.initial, self.inventory, self.daily = initial, inventory, daily
        self.deliveries, self.acquired = {}, {}
        self.index = self.cursor = 0

    def through(self, next_fill, realized):
        while self.index < len(self.rows) and (next_fill is None or self.rows[self.index]['fill_cursor'] < next_fill):
            row = self.rows[self.index]
            if row['sequence'] != self.index + 1 or row['fill_cursor'] != self.cursor:
                raise ValueError('Settlement sequence/fill cursor mismatch')
            saved = decode(row)
            request = saved['request']
            key = terms(request['contract'])
            held, cost = self.inventory.get(key, (0, 0))
            cash = self.initial + realized - sum(v[1] for v in self.inventory.values()) - sum(p['cost'] for p in self.deliveries.values())
            result = project(None if not held else {'contract': request['contract'], 'quantity': held, 'cost': cost,
                'entryFees': 0, 'opened': self.acquired[key]}, self.deliveries.get(key[0]), cash, request, stamp(row['recorded_at']))
            if result != saved['result']:
                raise ValueError('Settlement arithmetic mismatch')
            if result['optionQuantity']:
                self.inventory[key] = held - result['optionQuantity'], cost - result['removedCost']
            old = self.deliveries.get(key[0], {'quantity': 0, 'cost': 0})
            qty, basis = old['quantity'] + result['shareDelta'], old['cost'] + result['shareBasisDelta']
            if qty:
                self.deliveries[key[0]] = {'quantity': qty, 'cost': basis}
            else:
                self.deliveries.pop(key[0], None)
            pnl = result['realizedPnl']
            realized += pnl
            day = stamp(row['recorded_at']).date().isoformat()
            self.daily[day] = self.daily.get(day, 0) + pnl
            self.index += 1
        return realized
