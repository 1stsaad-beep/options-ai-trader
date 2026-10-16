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


def lifecycle_schema(db, postgres):
    """V1 adds side tables and widens money fields without recalculating history."""
    if postgres:
        for table,column in (('accounts','equity'),('accounts','realized'),('positions','cost'),('daily_pnl','pnl')):
            db.execute(f'ALTER TABLE {table} ALTER COLUMN {column} TYPE BIGINT')
    db.execute('CREATE UNIQUE INDEX uq_order_account_identity ON orders(account_id,id)')
    db.execute('CREATE TABLE order_costs (order_id TEXT PRIMARY KEY REFERENCES orders(id), commission_cents INTEGER NOT NULL CHECK(commission_cents>=0))')
    db.execute('CREATE TABLE runtime_health (name TEXT PRIMARY KEY, updated_at TEXT NOT NULL, payload TEXT NOT NULL)')
    db.execute('CREATE TABLE lifecycle_intents (id TEXT PRIMARY KEY, account_id TEXT NOT NULL REFERENCES accounts(id), request_key TEXT NOT NULL, kind TEXT NOT NULL, symbol TEXT NOT NULL, fingerprint TEXT NOT NULL, payload TEXT NOT NULL, state TEXT NOT NULL, order_id TEXT REFERENCES orders(id), created TEXT NOT NULL, updated TEXT NOT NULL, UNIQUE(account_id,request_key), UNIQUE(account_id,id), FOREIGN KEY(account_id,order_id) REFERENCES orders(account_id,id))')
    db.execute('CREATE TABLE decision_snapshots (id TEXT PRIMARY KEY, account_id TEXT NOT NULL REFERENCES accounts(id), order_id TEXT REFERENCES orders(id), intent_id TEXT, action TEXT NOT NULL, payload TEXT NOT NULL, digest TEXT NOT NULL, created TEXT NOT NULL, FOREIGN KEY(account_id,order_id) REFERENCES orders(account_id,id), FOREIGN KEY(account_id,intent_id) REFERENCES lifecycle_intents(account_id,id) DEFERRABLE INITIALLY DEFERRED)')
    db.execute('CREATE TABLE position_policies (account_id TEXT NOT NULL REFERENCES accounts(id), symbol TEXT NOT NULL, right_kind TEXT NOT NULL, expiry TEXT NOT NULL, strike INTEGER NOT NULL, generation INTEGER NOT NULL, high_bid INTEGER NOT NULL, partial_taken INTEGER NOT NULL DEFAULT 0, opened_at TEXT NOT NULL, PRIMARY KEY(account_id,symbol,right_kind,expiry,strike))')
    # A V0.5 position has no persisted high-water/time policy. Start tracking
    # prospectively at migration; do not invent its historical opening timestamp.
    for position in db.all('SELECT * FROM positions'):
        generation=db.one("SELECT COALESCE(MAX(f.sequence),0) AS n FROM fills f JOIN orders o ON o.id=f.order_id WHERE o.account_id=? AND o.symbol=? AND o.right_kind=? AND o.expiry=? AND o.strike=? AND o.side='BUY'",(position['account_id'],position['symbol'],position['right_kind'],position['expiry'],position['strike']))['n']
        db.execute('INSERT INTO position_policies VALUES(?,?,?,?,?,?,?,?,?)',(position['account_id'],position['symbol'],position['right_kind'],position['expiry'],position['strike'],generation,0,0,datetime.now(timezone.utc).isoformat()))
    db.execute('CREATE TABLE option_marks (account_id TEXT NOT NULL REFERENCES accounts(id), symbol TEXT NOT NULL, right_kind TEXT NOT NULL, expiry TEXT NOT NULL, strike INTEGER NOT NULL, bid INTEGER NOT NULL, ask INTEGER NOT NULL, observed_at TEXT NOT NULL, PRIMARY KEY(account_id,symbol,right_kind,expiry,strike))')
    db.execute('CREATE INDEX ix_decisions_account_created ON decision_snapshots(account_id,created)')
    db.execute('CREATE INDEX ix_intents_account_state ON lifecycle_intents(account_id,state)')
    if postgres:
        db.execute("CREATE FUNCTION immutable_decision_v1() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'decision snapshots are immutable'; END $$")
        db.execute('CREATE TRIGGER immutable_decision_v1 BEFORE UPDATE OR DELETE ON decision_snapshots FOR EACH ROW EXECUTE FUNCTION immutable_decision_v1()')
        db.execute('CREATE TRIGGER immutable_cost_v1 BEFORE UPDATE OR DELETE ON order_costs FOR EACH ROW EXECUTE FUNCTION immutable_decision_v1()')
    else:
        for action in ('UPDATE', 'DELETE'):
            db.execute(f"CREATE TRIGGER immutable_decision_v1_{action.lower()} BEFORE {action} ON decision_snapshots BEGIN SELECT RAISE(ABORT, 'decision snapshots are immutable'); END")
            db.execute(f"CREATE TRIGGER immutable_cost_v1_{action.lower()} BEFORE {action} ON order_costs BEGIN SELECT RAISE(ABORT, 'order costs are immutable'); END")


def research_observation_schema(db, postgres):
    """Preserve decisions and append only observations actually captured later."""
    db.execute('CREATE UNIQUE INDEX uq_decision_account_identity ON decision_snapshots(account_id,id)')
    db.execute('CREATE TABLE research_observations (account_id TEXT NOT NULL, snapshot_id TEXT NOT NULL, observed_at TEXT NOT NULL, captured_at TEXT NOT NULL, payload TEXT NOT NULL, digest TEXT NOT NULL, PRIMARY KEY(snapshot_id,observed_at), FOREIGN KEY(account_id,snapshot_id) REFERENCES decision_snapshots(account_id,id))')
    if postgres:
        db.execute('CREATE TRIGGER immutable_research_observation BEFORE UPDATE OR DELETE ON research_observations FOR EACH ROW EXECUTE FUNCTION immutable_decision_v1()')
    else:
        for action in ('UPDATE', 'DELETE'):
            db.execute(f"CREATE TRIGGER immutable_research_observation_{action.lower()} BEFORE {action} ON research_observations BEGIN SELECT RAISE(ABORT, 'research observations are immutable'); END")


def market_data_journal_schema(db, postgres):
    """A separate observation archive; never an execution mark or old decision."""
    db.execute('CREATE TABLE market_data_journal (id TEXT NOT NULL UNIQUE, account_id TEXT NOT NULL REFERENCES accounts(id), sequence INTEGER NOT NULL CHECK(sequence>0), request_key TEXT NOT NULL, fingerprint TEXT NOT NULL, kind TEXT NOT NULL, symbol TEXT NOT NULL, recorded_at TEXT NOT NULL, payload TEXT NOT NULL, digest TEXT NOT NULL, size_bytes INTEGER NOT NULL CHECK(size_bytes>0), PRIMARY KEY(account_id,sequence), UNIQUE(account_id,request_key))')
    db.execute('CREATE INDEX ix_market_journal_account_time ON market_data_journal(account_id,recorded_at,sequence)')
    if postgres:
        db.execute("CREATE FUNCTION immutable_market_journal_v1() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'market data journal is immutable'; END $$")
        db.execute('CREATE TRIGGER immutable_market_journal_v1 BEFORE UPDATE OR DELETE ON market_data_journal FOR EACH ROW EXECUTE FUNCTION immutable_market_journal_v1()')
    else:
        for action in ('UPDATE', 'DELETE'):
            db.execute(f"CREATE TRIGGER immutable_market_journal_v1_{action.lower()} BEFORE {action} ON market_data_journal BEGIN SELECT RAISE(ABORT, 'market data journal is immutable'); END")


def market_runtime_schema(db, postgres):
    """Operational state is mutable; original observations and events are not."""
    db.execute('CREATE TABLE market_runtime_config (account_id TEXT PRIMARY KEY REFERENCES accounts(id), version INTEGER NOT NULL, payload TEXT NOT NULL)')
    db.execute('CREATE TABLE market_runtime_coordinator (name TEXT PRIMARY KEY, payload TEXT NOT NULL)')
    db.execute('CREATE TABLE market_runtime_tasks (symbol TEXT NOT NULL, kind TEXT NOT NULL, next_due TEXT NOT NULL, PRIMARY KEY(symbol,kind))')
    db.execute('CREATE UNIQUE INDEX uq_market_journal_account_id ON market_data_journal(account_id,id)')
    db.execute('CREATE TABLE market_runtime_latest (account_id TEXT NOT NULL, symbol TEXT NOT NULL, kind TEXT NOT NULL, observation_id TEXT NOT NULL, state TEXT NOT NULL, PRIMARY KEY(account_id,symbol,kind), FOREIGN KEY(account_id,observation_id) REFERENCES market_data_journal(account_id,id))')
    db.execute('CREATE TABLE market_runtime_events (id TEXT PRIMARY KEY, account_id TEXT NOT NULL REFERENCES accounts(id), event_key TEXT NOT NULL, created TEXT NOT NULL, payload TEXT NOT NULL, digest TEXT NOT NULL, UNIQUE(account_id,event_key), UNIQUE(account_id,id))')
    db.execute('CREATE TABLE market_runtime_ack (account_id TEXT NOT NULL, event_id TEXT PRIMARY KEY, acknowledged_at TEXT NOT NULL, FOREIGN KEY(account_id,event_id) REFERENCES market_runtime_events(account_id,id))')
    db.execute('CREATE INDEX ix_runtime_events_account_time ON market_runtime_events(account_id,created,id)')
    if postgres:
        db.execute('CREATE TRIGGER immutable_runtime_event BEFORE UPDATE OR DELETE ON market_runtime_events FOR EACH ROW EXECUTE FUNCTION immutable_market_journal_v1()')
    else:
        for action in ('UPDATE', 'DELETE'):
            db.execute(f"CREATE TRIGGER immutable_runtime_event_{action.lower()} BEFORE {action} ON market_runtime_events BEGIN SELECT RAISE(ABORT, 'runtime events are immutable'); END")


def market_segments_schema(db, postgres):
    from .market_segments import append
    db.execute('CREATE TABLE market_journal_segments (account_id TEXT NOT NULL REFERENCES accounts(id), number INTEGER NOT NULL, first_sequence INTEGER NOT NULL, last_sequence INTEGER NOT NULL, record_count INTEGER NOT NULL, size_bytes BIGINT NOT NULL, first_sha256 TEXT NOT NULL, sealed INTEGER NOT NULL, chain_sha256 TEXT NOT NULL, PRIMARY KEY(account_id,number))')
    # Reconstruct indexes only; never rewrite original payloads or availability.
    for raw in db.execute('SELECT account_id,sequence,size_bytes,digest FROM market_data_journal ORDER BY account_id,sequence'):
        row = dict(raw)
        append(db, row['account_id'], row['sequence'], row['size_bytes'], row['digest'])
    if postgres:
        db.execute("CREATE FUNCTION guard_market_segment() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF TG_OP='DELETE' OR OLD.sealed=1 THEN RAISE EXCEPTION 'sealed segments are immutable'; END IF; RETURN NEW; END $$")
        db.execute('CREATE TRIGGER guard_market_segment BEFORE UPDATE OR DELETE ON market_journal_segments FOR EACH ROW EXECUTE FUNCTION guard_market_segment()')
    else:
        db.execute("CREATE TRIGGER guard_market_segment_update BEFORE UPDATE ON market_journal_segments WHEN OLD.sealed=1 BEGIN SELECT RAISE(ABORT, 'sealed segments are immutable'); END")
        db.execute("CREATE TRIGGER guard_market_segment_delete BEFORE DELETE ON market_journal_segments BEGIN SELECT RAISE(ABORT, 'segments are immutable'); END")


def paper_settlement_schema(db, postgres):
    db.execute('CREATE TABLE paper_delivery_positions (account_id TEXT NOT NULL REFERENCES accounts(id), symbol TEXT NOT NULL, quantity BIGINT NOT NULL CHECK(quantity>0), cost BIGINT NOT NULL CHECK(cost>0), PRIMARY KEY(account_id,symbol))')
    db.execute('CREATE TABLE paper_settlement_receipts (account_id TEXT NOT NULL REFERENCES accounts(id), sequence BIGINT NOT NULL CHECK(sequence>0), receipt_id TEXT NOT NULL, fill_cursor BIGINT NOT NULL CHECK(fill_cursor>=0), recorded_at TEXT NOT NULL, payload TEXT NOT NULL, digest TEXT NOT NULL, PRIMARY KEY(account_id,sequence), UNIQUE(account_id,receipt_id))')
    db.execute('CREATE TABLE fill_receipt_times (fill_id TEXT PRIMARY KEY REFERENCES fills(id), recorded_at TEXT NOT NULL)')
    for table in ('paper_settlement_receipts', 'fill_receipt_times'):
        if postgres:
            db.execute(f'CREATE TRIGGER immutable_{table} BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION immutable_decision_v1()')
        else:
            for action in ('UPDATE', 'DELETE'):
                db.execute(f"CREATE TRIGGER immutable_{table}_{action.lower()} BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT, 'receipts are immutable'); END")


def observed_paper_schema(db, postgres):
    """Separate balances; never import or alias the synthetic/device ledger."""
    db.execute('CREATE TABLE observed_paper_accounts (id TEXT PRIMARY KEY, payload TEXT NOT NULL, version BIGINT NOT NULL, event_hash TEXT NOT NULL)')
    db.execute('CREATE TABLE observed_paper_events (account_id TEXT NOT NULL REFERENCES observed_paper_accounts(id), sequence BIGINT NOT NULL, request_key TEXT NOT NULL, fingerprint TEXT NOT NULL, receipt_id TEXT, payload TEXT NOT NULL, digest TEXT NOT NULL, previous_hash TEXT NOT NULL, after_hash TEXT NOT NULL, created TEXT NOT NULL, size_bytes BIGINT NOT NULL, PRIMARY KEY(account_id,sequence), UNIQUE(account_id,request_key), UNIQUE(account_id,receipt_id))')
    db.execute('CREATE TABLE observed_paper_segments (account_id TEXT NOT NULL REFERENCES observed_paper_accounts(id), number BIGINT NOT NULL, first_sequence BIGINT NOT NULL, last_sequence BIGINT NOT NULL, size_bytes BIGINT NOT NULL, sealed INTEGER NOT NULL, chain_hash TEXT NOT NULL, PRIMARY KEY(account_id,number))')
    db.execute('CREATE TABLE observed_paper_lease (name TEXT PRIMARY KEY, owner TEXT NOT NULL, generation BIGINT NOT NULL, expires_at TEXT NOT NULL)')
    db.execute('CREATE TABLE observed_paper_data_state (name TEXT PRIMARY KEY, payload TEXT NOT NULL)')
    if postgres:
        db.execute('CREATE TRIGGER immutable_observed_paper_event BEFORE UPDATE OR DELETE ON observed_paper_events FOR EACH ROW EXECUTE FUNCTION immutable_decision_v1()')
        db.execute('CREATE TRIGGER guard_observed_paper_segment BEFORE UPDATE OR DELETE ON observed_paper_segments FOR EACH ROW EXECUTE FUNCTION guard_market_segment()')
    else:
        for action in ('UPDATE', 'DELETE'):
            db.execute(f"CREATE TRIGGER immutable_observed_paper_event_{action.lower()} BEFORE {action} ON observed_paper_events BEGIN SELECT RAISE(ABORT, 'observed-paper events are immutable'); END")
        db.execute("CREATE TRIGGER guard_observed_paper_segment_update BEFORE UPDATE ON observed_paper_segments WHEN OLD.sealed=1 BEGIN SELECT RAISE(ABORT, 'sealed segments are immutable'); END")
        db.execute("CREATE TRIGGER guard_observed_paper_segment_delete BEFORE DELETE ON observed_paper_segments BEGIN SELECT RAISE(ABORT, 'segments are immutable'); END")


MIGRATIONS = [(1, 'v02_baseline', base), (2, 'v03_safety_relations_market', safety_schema), (3, 'v03_import_balance_baseline', balance_baseline), (4, 'v1_decisions_lifecycle', lifecycle_schema), (5, 'v1_research_observations', research_observation_schema), (6, 'v1_market_data_journal', market_data_journal_schema), (7, 'v1_market_runtime', market_runtime_schema), (8, 'v1_market_segments', market_segments_schema), (9, 'v1_paper_settlement', paper_settlement_schema), (10, 'v1_observed_paper_runtime', observed_paper_schema)]


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
