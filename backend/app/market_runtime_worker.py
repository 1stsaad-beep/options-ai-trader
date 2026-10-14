"""Long-lived, opt-in collector process. Safe default: no credentials, no network.

Healthcheck verifies process heartbeat only, never market/execution readiness.
Do not mount Alpaca secrets into the API or synthetic worker.
"""
import argparse
from datetime import datetime, timezone
import json
import os
import signal
import stat
import threading
import uuid

from .market_data import AlpacaBasicData, AlpacaDataTransport, DataCredentials, DisabledMarketData, MarketDataError
from .market_runtime import CoordinatedTransport, MarketCollector, coordinator_in, save_coordinator, event_in
from .market_data_journal import timestamp
from .repository import Repository
from .service import TradingService


def credentials_from_file(path):
    """Read only one explicit server secret; never search for another app's keys."""
    descriptor = None
    try:
        if not path or not os.path.isabs(path):
            raise ValueError()
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_size > 4096 or info.st_mode & 0o007:
            raise ValueError()
        with os.fdopen(descriptor, 'r', encoding='utf-8') as handle:
            descriptor = None
            value = json.loads(handle.read(4097))
        if not isinstance(value, dict) or set(value) != {'key_id', 'secret_key'}:
            raise ValueError()
        return DataCredentials(**value)
    except (OSError, ValueError, TypeError, UnicodeError, MarketDataError):
        raise MarketDataError('INVALID_COLLECTOR_SECRET_FILE') from None
    finally:
        if descriptor is not None:
            os.close(descriptor)


def build_provider(repo, owner, now):
    if os.getenv('OAT_ALPACA_DATA_APPROVAL') != 'read_only_approved':
        return DisabledMarketData()
    credentials = credentials_from_file(os.getenv('OAT_ALPACA_DATA_CREDENTIALS_FILE', ''))
    try:
        budget = int(os.getenv('OAT_ALPACA_COLLECTOR_REQUESTS_PER_MINUTE', '10'))
        transport = CoordinatedTransport(repo, owner, AlpacaDataTransport(credentials), now, budget)
        return AlpacaBasicData(transport, now=now, requests_per_minute=budget, max_pages=2)
    except ValueError:
        raise MarketDataError('INVALID_COLLECTOR_REQUEST_BUDGET') from None


def heartbeat_ok(repo, now):
    from .runtime_health import heartbeat_valid
    with repo.transaction() as db:
        row = db.one("SELECT updated_at,payload FROM runtime_health WHERE name='market_collector'")
    return heartbeat_valid(row, 'market_collector', now)


def reset_auth_lock(service):
    """Explicit server-operator maintenance; no connection or order is made."""
    with service.repo.transaction() as db:
        state = coordinator_in(db)
        now = service.now()
        if state['owner'] and state['lease_until'] and timestamp(state['lease_until']) > now:
            raise MarketDataError('STOP_COLLECTOR_BEFORE_AUTH_RESET')
        state.update(auth_blocked=False, retry_at=None, failures=0)
        save_coordinator(db, state)
        key = 'auth-reset:' + str(uuid.uuid4())
        for account in db.all('SELECT account_id FROM market_runtime_config'):
            event_in(db, account['account_id'], key, now, 'OPERATOR_AUTH_LOCK_RESET',
                     {'connection_performed': False})


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--healthcheck', action='store_true')
    group.add_argument('--reset-auth-lock', action='store_true')
    group.add_argument('--once', action='store_true', help='One tick, still disabled without separate approval')
    args = parser.parse_args(argv)
    if os.getenv('TRADING_MODE', 'paper') != 'paper' or os.getenv('ENABLE_LIVE', 'false').lower() != 'false':
        raise SystemExit('Live is hard locked')
    now = lambda: datetime.now(timezone.utc)
    url = os.getenv('DATABASE_URL', 'sqlite:///options_demo.db')
    if args.healthcheck:
        from .runtime_health import probe_heartbeat
        return 0 if probe_heartbeat(url, 'market_collector', now()) else 1
    stop = threading.Event()
    previous = {name:signal.signal(name, lambda *_:stop.set()) for name in (signal.SIGTERM, signal.SIGINT)}
    repo = collector = None
    owner = str(uuid.uuid4())
    try:
        while not stop.is_set():
            try:
                if repo is None:
                    repo = Repository(url, invalidate_accounts=False)
                service = TradingService(repo)
                if args.reset_auth_lock:
                    reset_auth_lock(service)
                    return 0
                if collector is None:
                    collector = MarketCollector(service, build_provider(repo, owner, now), owner=owner, now=now)
                result = collector.tick()
                # No account names, observations, credentials, URLs or exception messages in stdout.
                print(json.dumps({'component': 'market_collector', 'state': result['state'],
                                  'external_orders_enabled': False, 'virtual_fills_enabled': False}), flush=True)
                if args.once:
                    return 0
            except Exception:
                print(json.dumps({'component': 'market_collector', 'state': 'WORKER_UNAVAILABLE',
                                  'external_orders_enabled': False, 'virtual_fills_enabled': False}), flush=True)
                if repo is not None:
                    try:
                        repo.close()
                    except Exception:
                        pass
                repo = collector = None
                if args.once or args.healthcheck or args.reset_auth_lock:
                    return 1
            stop.wait(5)  # Responsive SIGTERM; bounded retry even while the DB is unavailable.
    finally:
        if collector is not None:
            try:
                collector.release(mark_stopped=stop.is_set() or args.once)
            except Exception:
                pass
        if repo is not None:
            repo.close()
        for name, handler in previous.items():
            signal.signal(name, handler)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
