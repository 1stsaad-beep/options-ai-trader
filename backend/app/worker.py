"""Independent synthetic worker; opt-in Mock execution is explicit.

Account modes label decisions, not execution authority. Unknown broker state
must be explicitly reconciled by the caller, never silently repaired by a scan.
"""
import argparse
import json
import logging
import os
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
    return {'shadow_decisions_recorded': recorded, 'orders_submitted': sum(r['orders_submitted'] for r in automation), 'source': 'synthetic_fixture', 'automation': automation}


def opportunities_for(service, account_id):
    with service.repo.transaction() as db:
        service.account(db, account_id)
        stored = db.all('SELECT payload FROM shadow_decisions WHERE account_id=? ORDER BY created DESC LIMIT 100', (account_id,))
    return [json.loads(row['payload']) for row in stored] if stored else scan_account(service, account_id)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--once', action='store_true')
    parser.add_argument('--execute-mock', action='store_true', help='Execute only explicitly opted-in paper/mock accounts')
    parser.add_argument('--interval', type=int, default=30)
    args = parser.parse_args()
    if args.interval < 1:
        parser.error('interval must be positive')
    if os.getenv('TRADING_MODE', 'paper') != 'paper' or os.getenv('ENABLE_LIVE', 'false').lower() != 'false':
        raise RuntimeError('Live is hard locked')
    repo = Repository(os.getenv('DATABASE_URL', 'sqlite:///options_demo.db'))
    service = TradingService(repo)
    logging.basicConfig(level=logging.INFO)
    stop = threading.Event()
    try:
        while True:
            logging.info('worker_tick %s', tick(service, execute_mock=args.execute_mock))
            if args.once:
                break
            stop.wait(args.interval)
    except KeyboardInterrupt:
        stop.set()
    finally:
        repo.close()


if __name__ == '__main__':
    main()
