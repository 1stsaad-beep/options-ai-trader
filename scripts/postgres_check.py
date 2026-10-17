"""Explicit PostgreSQL integration check; no broker connection.
Requires a disposable TEST_DATABASE_URL, never a personal production database.
"""
import os
import sys
from urllib.parse import urlparse
from pathlib import Path
from datetime import datetime, timezone, timedelta
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from app.repository import Repository
from app.service import TradingService, Rejected
url = os.environ.get('TEST_DATABASE_URL', '')
if not url.startswith(('postgresql://', 'postgres://')):
    raise SystemExit('Set TEST_DATABASE_URL to a disposable PostgreSQL test database')
if os.environ.get('TEST_DATABASE_ALLOW_DISPOSABLE') != '1':
    raise SystemExit('Set TEST_DATABASE_ALLOW_DISPOSABLE=1 to explicitly acknowledge writes to a disposable test database')
if urlparse(url).hostname not in {'localhost', '127.0.0.1', '::1', 'postgres'}:
    raise SystemExit('Only a local/container disposable PostgreSQL host is permitted')
repo = Repository(url)
with repo.transaction() as db:
    assert [row['version'] for row in db.all('SELECT version FROM schema_migrations ORDER BY version')] == [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]
    constraints = db.all("SELECT constraint_name FROM information_schema.table_constraints WHERE table_schema=current_schema() AND constraint_type='FOREIGN KEY'")
    assert len(constraints) >= 8

s = TradingService(repo)
a = s.create_account('postgres-isolation-A')['id']
b = s.create_account('postgres-isolation-B')['id']
s.watch(a, 'NVDA', True)
expiry = datetime.now(timezone.utc).date() + timedelta(days=7)
expiry += timedelta(days=(4-expiry.weekday())%7)
request = dict(request_key='pg-demo-1', symbol='NVDA', right='CALL',
    expiry=expiry.isoformat(),
    strike_cents=15000, side='BUY', quantity=2, limit_cents=100)
s.reconcile(a)
order = s.submit(a, request)
assert s.submit(a, request)['id'] == order['id']
assert s.rows(b, 'orders') == []
s.fill(a, order['id'], 'pg-demo-fill-'+order['id'], 1, 100)
assert s.rows(a, 'orders')[0]['status'] == 'PARTIAL'
s.disconnect(a)
try:
    s.submit(a, request | {'request_key': 'pg-demo-2'})
except Rejected:
    pass
else:
    raise AssertionError('Unknown account state admitted')
s.reconcile(a)
s.stop(a)
try:
    s.submit(a, request | {'request_key': 'pg-demo-3'})
except Rejected:
    pass
else:
    raise AssertionError('Stopped account admitted')
# Complete the owned-only lifecycle while emergency stop remains active.
s.cancel(a, order['id'])
close_request = request | {'request_key': 'pg-close-1', 'side': 'SELL_TO_CLOSE', 'quantity': 1}
close = s.submit(a, close_request)
try:
    s.fill(b, close['id'], 'pg-cross-'+close['id'], 1, 100)
except Rejected:
    pass
else:
    raise AssertionError('Cross-account execution admitted')
s.fill(a, close['id'], 'pg-close-fill-'+close['id'], 1, 100)
assert all(p['quantity'] == 0 for p in s.rows(a, 'positions'))
assert s.rows(b, 'orders') == []
try:
    s.submit(a, close_request | {'request_key': 'pg-naked'})
except Rejected:
    pass
else:
    raise AssertionError('Unowned close admitted')
repo.close()
print('PostgreSQL integration checks passed: migrations, native FK constraints, isolation, duplicate, partial, disconnect, stop, cancel, owned close, cross-account denial')
