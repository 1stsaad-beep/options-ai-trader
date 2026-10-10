"""Transactional, additive migrations. Never recreate a V0.2 trading ledger.

SQLite legacy FK constraints are enforced by equivalent triggers because SQLite
cannot add foreign keys in place. PostgreSQL uses native constraints. Invalid
legacy relationships abort startup and require manual offline review.
"""
from datetime import datetime, timezone
import json
import uuid

SCHEMA = [
"CREATE TABLE IF NOT EXISTS accounts (id TEXT PRIMARY KEY, name TEXT NOT NULL, config TEXT NOT NULL, equity INTEGER NOT NULL, realized INTEGER NOT NULL DEFAULT 0, state_known INTEGER NOT NULL DEFAULT 1, stopped INTEGER NOT NULL DEFAULT 0, snapshot_at TEXT NOT NULL)",
"CREATE TABLE IF NOT EXISTS shadow_decisions (id TEXT PRIMARY KEY, account_id TEXT NOT NULL, payload TEXT NOT NULL, created TEXT NOT NULL)",
"CREATE TABLE IF NOT EXISTS daily_pnl (account_id TEXT NOT NULL, day TEXT NOT NULL, pnl INTEGER NOT NULL, PRIMARY KEY(account_id,day))",
"CREATE TABLE IF NOT EXISTS watchlist (account_id TEXT NOT NULL, symbol TEXT NOT NULL, enabled INTEGER NOT NULL, verified INTEGER NOT NULL, PRIMARY KEY(account_id,symbol))",
"CREATE TABLE IF NOT EXISTS orders (id TEXT PRIMARY KEY, account_id TEXT NOT NULL, request_key TEXT NOT NULL, fingerprint TEXT NOT NULL, symbol TEXT NOT NULL, right_kind TEXT NOT NULL, expiry TEXT NOT NULL, strike INTEGER NOT NULL, side TEXT NOT NULL, quantity INTEGER NOT NULL, limit_cents INTEGER NOT NULL, filled INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL, UNIQUE(account_id,request_key))",
"CREATE TABLE IF NOT EXISTS positions (account_id TEXT NOT NULL, symbol TEXT NOT NULL, right_kind TEXT NOT NULL, expiry TEXT NOT NULL, strike INTEGER NOT NULL, quantity INTEGER NOT NULL, cost INTEGER NOT NULL, PRIMARY KEY(account_id,symbol,right_kind,expiry,strike))",
"CREATE TABLE IF NOT EXISTS fills (id TEXT PRIMARY KEY, order_id TEXT NOT NULL, quantity INTEGER NOT NULL, price_cents INTEGER NOT NULL, sequence INTEGER NOT NULL UNIQUE, day TEXT NOT NULL)",
"CREATE TABLE IF NOT EXISTS audit (id TEXT PRIMARY KEY, account_id TEXT, event TEXT NOT NULL, detail TEXT NOT NULL, created TEXT NOT NULL)",
"CREATE TABLE IF NOT EXISTS supervisor (id INTEGER PRIMARY KEY, stopped INTEGER NOT NULL)",
]
RELATIONS = [(t, 'account_id', 'accounts') for t in
             ('shadow_decisions', 'daily_pnl', 'watchlist', 'orders', 'positions', 'audit', 'market_snapshots')] + [('fills', 'order_id', 'orders')]


def base(db, postgres):
    for sql in SCHEMA:
        db.execute(sql)
    db.execute('INSERT INTO supervisor(id,stopped) VALUES(1,0) ON CONFLICT(id) DO NOTHING')


def safety_schema(db, postgres):
    db.execute('CREATE TABLE IF NOT EXISTS market_snapshots (account_id TEXT NOT NULL, symbol TEXT NOT NULL, observed_at TEXT NOT NULL, available INTEGER NOT NULL CHECK(available IN (0,1)), PRIMARY KEY(account_id,symbol))')
    for table, column, parent in RELATIONS:
        orphan = db.one(f'SELECT c.{column} FROM {table} c LEFT JOIN {parent} p ON c.{column}=p.id WHERE c.{column} IS NOT NULL AND p.id IS NULL LIMIT 1')
        if orphan:
            raise ValueError(f'Unsafe legacy orphan in {table}; migration aborted')
        name = f'fk_{table}_{column}'
        db.execute(f'CREATE INDEX IF NOT EXISTS ix_{table}_{column} ON {table}({column})')
        if postgres:
            db.execute(f'ALTER TABLE {table} ADD CONSTRAINT {name} FOREIGN KEY ({column}) REFERENCES {parent}(id) ON DELETE RESTRICT ON UPDATE RESTRICT')
        else:
            for action in ('INSERT', 'UPDATE'):
                db.execute(f"CREATE TRIGGER IF NOT EXISTS {name}_{action.lower()} BEFORE {action} ON {table} WHEN NEW.{column} IS NOT NULL AND NOT EXISTS (SELECT 1 FROM {parent} WHERE id=NEW.{column}) BEGIN SELECT RAISE(ABORT, 'foreign key constraint failed'); END")
            db.execute(f"CREATE TRIGGER IF NOT EXISTS {name}_delete BEFORE DELETE ON {parent} WHEN EXISTS (SELECT 1 FROM {table} WHERE {column}=OLD.id) BEGIN SELECT RAISE(ABORT, 'foreign key constraint failed'); END")
            db.execute(f"CREATE TRIGGER IF NOT EXISTS {name}_parent_update BEFORE UPDATE OF id ON {parent} WHEN NEW.id<>OLD.id AND EXISTS (SELECT 1 FROM {table} WHERE {column}=OLD.id) BEGIN SELECT RAISE(ABORT, 'foreign key constraint failed'); END")
    for name, table, columns in [('orders_account_status','orders','account_id,status'), ('audit_account_created','audit','account_id,created'), ('shadow_account_created','shadow_decisions','account_id,created')]:
        db.execute(f'CREATE INDEX IF NOT EXISTS ix_{name} ON {table}({columns})')


def balance_baseline(db, postgres):
    """Freeze imported local balance; this never attests a broker's balance."""
    for account in db.all('SELECT id,equity FROM accounts'):
        events = db.all("SELECT detail FROM audit WHERE account_id=? AND event='ACCOUNT_CREATED'", (account['id'],))
        known = False
        for event in events:
            try:
                initial = json.loads(event['detail']).get('initial_equity_cents')
            except (ValueError, TypeError, AttributeError):
                raise ValueError('Malformed legacy account creation audit; migration aborted')
            if type(initial) is int:
                known = True
        if known:
            continue
        prior = db.one("SELECT id FROM audit WHERE account_id=? AND event='MIGRATION_BALANCE_BASELINE'", (account['id'],))
        if prior:
            continue
        detail = json.dumps({'initial_equity_cents': account['equity'], 'source': 'local_v02_import_unverified'}, sort_keys=True)
        db.execute('INSERT INTO audit VALUES(?,?,?,?,?)', (str(uuid.uuid4()), account['id'], 'MIGRATION_BALANCE_BASELINE', detail, datetime.now(timezone.utc).isoformat()))


MIGRATIONS = [(1, 'v02_baseline', base), (2, 'v03_safety_relations_market', safety_schema), (3, 'v03_import_balance_baseline', balance_baseline)]


def migrate(db, postgres):
    db.execute('CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL)')
    current = db.all('SELECT version,name FROM schema_migrations ORDER BY version')
    expected = {version: name for version, name, _ in MIGRATIONS}
    if any(expected.get(row['version']) != row['name'] for row in current):
        raise ValueError('Database migration history is incompatible with this binary')
    if [row['version'] for row in current] != [version for version, _, _ in MIGRATIONS[:len(current)]]:
        raise ValueError('Database migration history is not a contiguous sequence')
    versions = {row['version'] for row in current}
    for version, name, apply in MIGRATIONS:
        if version not in versions:
            apply(db, postgres)
            db.execute('INSERT INTO schema_migrations VALUES(?,?,?)', (version, name, datetime.now(timezone.utc).isoformat()))
