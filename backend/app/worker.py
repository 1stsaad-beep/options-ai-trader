"""Independent synthetic worker; opt-in Mock execution is explicit.

Account modes label decisions, not execution authority. Unknown broker state
must be explicitly reconciled by the caller, never silently repaired by a scan.
"""
import argparse
import json
import os
import signal
import threading
from datetime import datetime, timedelta, timezone
from .engines import AnalysisPipeline, Bar, MarketDataUnavailable
from .repository import Repository
from .service import Rejected, TradingService


def fixture_bars(symbol, now):
    base = {'NVDA': 100, 'AAPL': 200, 'TSLA': 250}.get(symbol, 150)
    end = now.replace(second=0, microsecond=0) - timedelta(minutes=1)
    bars = []
    for index in range(30):
        close = base + index * .2 + (2 if index == 29 else 0)
        bars.append(Bar(end-timedelta(minutes=29-index), close-.1, close+.2,
                        close-.3, close, 2000 if index == 29 else 1000))
    return bars


def scan_account(service, account_id, now=None, feed=None):
    now = now or datetime.now(timezone.utc)
    watches = service.rows(account_id, 'watchlist')
    with service.repo.transaction() as db:
        account = service.account(db, account_id)
    config = account['config']
    result = []
    feed = feed or fixture_bars
    with service.repo.transaction() as db:
        global_stopped = bool(db.one('SELECT stopped FROM supervisor WHERE id=1')['stopped'])
    for watch in watches:
        if not watch['enabled'] or not watch['verified']:
            continue
        common = {'symbol': watch['symbol'], 'timestamp': now.isoformat(),
                  'source': 'synthetic_fixture', 'actionable': False,
                  'mode': config['mode'], 'execution_mode': 'disabled',
                  'strategy': None, 'right': None, 'score': 0,
                  'regime': None, 'atr': None, 'ai_status': 'DISABLED'}
        with service.repo.transaction() as db:
            market_ok = service.market_valid(db, account_id, watch['symbol'])
        reason = None
        if config['mode'] not in ('analysis', 'shadow', 'paper'):
            reason = 'Unsupported or locked account mode'
        elif account['stopped'] or global_stopped:
            reason = 'Emergency stop active'
        elif not service.snapshot_valid(account):
            reason = 'Account/broker snapshot untrusted or stale; explicit reconciliation required'
        elif not market_ok:
            reason = 'Market observation unavailable or stale; explicit mock refresh required'
        if reason:
            result.append(common | {'decision': 'BLOCKED', 'reason': reason, 'missed_reason': reason})
            continue
        try:
            analysis = AnalysisPipeline().analyze(feed(watch['symbol'], now), now)
        except (MarketDataUnavailable, ValueError) as exc:
            result.append(common | {'decision': 'BLOCKED', 'reason': str(exc), 'missed_reason': str(exc)})
            continue
        except Exception:
            # Feed exceptions are an outage, not permission to reuse an old signal.
            reason = 'Feed processing unavailable'
            result.append(common | {'decision': 'BLOCKED', 'reason': reason, 'missed_reason': reason})
            continue
        for signal in analysis.signals:
            permitted = signal.strategy in config['strategies']
            result.append(common | {
                'strategy': signal.strategy, 'right': signal.right, 'score': signal.score,
                'reason': signal.reason, 'timestamp': signal.timestamp.isoformat(),
                'regime': analysis.regime, 'atr': analysis.atr, 'ai_status': analysis.ai_status,
                'decision': 'PROPOSAL' if permitted else 'STRATEGY_DISABLED',
                'missed_reason': 'Analysis worker never submits orders' if permitted else 'Account strategy disabled'})
        if not analysis.signals:
            result.append(common | {'decision': 'NO_SIGNAL', 'reason': analysis.explanation,
                                   'missed_reason': 'No quantitative entry rule passed',
                                   'regime': analysis.regime, 'atr': analysis.atr})
    return sorted(result, key=lambda item: (-item['score'], item['symbol'], item['strategy'] or ''))


def tick(service, now=None, feed=None, execute_mock=False, quote_feed=None):
    now = now or service.now()
    automation = []
    recorded = 0
    with service.repo.transaction() as db:
        account_ids = db.all('SELECT id FROM accounts ORDER BY name')
    for row in account_ids:
        try:
            with service.repo.transaction() as db:
                account = service.account(db, row['id'])
        except Rejected as exc:
            if execute_mock:
                from .automation import run_account
                automation.append(run_account(service, row['id'], now, feed, quote_feed))
            else:
                with service.repo.transaction() as db:
                    service.audit(db, row['id'], 'WORKER_ACCOUNT_BLOCKED', {'reason': str(exc)})
            continue
        # Do not call reconcile: scanning cannot establish broker/account truth.
        if execute_mock and account['config'].get('automation_enabled', False):
            from .automation import run_account
            automation.append(run_account(service, account['id'], now, feed, quote_feed))
        opportunities = scan_account(service, account['id'], now, feed)
        with service.repo.transaction() as db:
            for opportunity in opportunities:
                key = '|'.join((account['id'], opportunity['symbol'], opportunity['strategy'] or 'none',
                                opportunity['timestamp'], opportunity['decision']))
                cursor = db.execute('INSERT INTO shadow_decisions(id,account_id,payload,created) VALUES(?,?,?,?) ON CONFLICT(id) DO NOTHING',
                                    (key, account['id'], json.dumps(opportunity), now.isoformat()))
                recorded += cursor.rowcount
            service.audit(db, account['id'], 'SHADOW_SCAN', {
                'source': 'synthetic_fixture', 'mode': account['config']['mode'],
                'decisions': len(opportunities), 'orders_submitted': 0})
    with service.repo.transaction() as db:
        db.execute('INSERT INTO runtime_health(name,updated_at,payload) VALUES(?,?,?) ON CONFLICT(name) DO UPDATE SET updated_at=excluded.updated_at,payload=excluded.payload',
                   ('worker', now.isoformat(), json.dumps({'status': 'OK', 'source': 'synthetic_fixture',
                    'accounts_scanned': len(account_ids), 'execute_mock': execute_mock})))
    return {'shadow_decisions_recorded': recorded, 'orders_submitted': sum(r['orders_submitted'] for r in automation), 'source': 'synthetic_fixture', 'automation': automation}


def opportunities_for(service, account_id):
    with service.repo.transaction() as db:
        service.account(db, account_id)
        stored = db.all('SELECT payload FROM shadow_decisions WHERE account_id=? ORDER BY created DESC LIMIT 100', (account_id,))
    return [json.loads(row['payload']) for row in stored] if stored else scan_account(service, account_id)


def heartbeat_ok(repo, now):
    """Process liveness only; never repairs a ledger or grants entry authority."""
    try:
        with repo.transaction() as db:
            row = db.one("SELECT * FROM runtime_health WHERE name='worker'")
        return (row is not None and json.loads(row['payload'])['status'] == 'OK' and
                0 <= (now - datetime.fromisoformat(row['updated_at'])).total_seconds() <= 120)
    except (KeyError, TypeError, ValueError):
        return False


def main(argv=None):
    parser = argparse.ArgumentParser()
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--once', action='store_true')
    modes.add_argument('--healthcheck', action='store_true')
    parser.add_argument('--execute-mock', action='store_true', help='Execute only explicitly opted-in paper/mock accounts')
    parser.add_argument('--interval', type=int, default=30)
    args = parser.parse_args(argv)
    if not 1 <= args.interval <= 60:
        parser.error('interval must be between 1 and 60 seconds')
    if os.getenv('TRADING_MODE', 'paper') != 'paper' or os.getenv('ENABLE_LIVE', 'false').lower() != 'false':
        raise RuntimeError('Live is hard locked')
    stop = threading.Event()
    previous = {name:signal.signal(name, lambda *_:stop.set()) for name in (signal.SIGINT, signal.SIGTERM)}
    repo = None
    try:
        while not stop.is_set():
            try:
                if repo is None:
                    # Real process recovery preserves receipts but disarms stale
                    # account knowledge. Health probes never invalidate accounts.
                    repo = Repository(os.getenv('DATABASE_URL', 'sqlite:///options_demo.db'),
                                      invalidate_accounts=not args.healthcheck)
                if args.healthcheck:
                    return 0 if heartbeat_ok(repo, datetime.now(timezone.utc)) else 1
                result = tick(TradingService(repo), execute_mock=args.execute_mock)
                print(json.dumps({'component':'synthetic_worker', 'status':'OK',
                    'source':'synthetic_fixture', 'execute_mock':args.execute_mock,
                    'orders_submitted':result['orders_submitted'], 'external_orders_enabled':False}), flush=True)
                if args.once:
                    return 0
                stop.wait(args.interval)
            except Exception:
                # Never emit exception/HTTP/DB text, account data or credentials.
                print(json.dumps({'component':'synthetic_worker', 'status':'WORKER_UNAVAILABLE',
                    'execute_mock':args.execute_mock, 'external_orders_enabled':False}), flush=True)
                if repo is not None:
                    try:
                        with repo.transaction() as db:
                            db.execute("UPDATE runtime_health SET payload=? WHERE name='worker'",
                                (json.dumps({'status':'UNAVAILABLE','execute_mock':args.execute_mock}),))
                    except Exception:
                        pass
                    try:
                        repo.close()
                    except Exception:
                        pass
                repo = None
                if args.once or args.healthcheck:
                    return 1
                stop.wait(min(args.interval, 5))
    finally:
        if repo is not None:
            if stop.is_set():
                try:
                    with repo.transaction() as db:
                        db.execute("UPDATE runtime_health SET updated_at=?,payload=? WHERE name='worker'",
                            (datetime.now(timezone.utc).isoformat(), json.dumps({'status':'STOPPED',
                                'execute_mock':args.execute_mock, 'source':'synthetic_fixture'})))
                except Exception:
                    pass
            repo.close()
        for name, handler in previous.items():
            signal.signal(name, handler)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
