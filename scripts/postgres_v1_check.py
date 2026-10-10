"""Disposable PostgreSQL multi-connection safety checks; no external broker."""
import json
import os
import sys
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from app.repository import Repository
from app.service import TradingService, Rejected


def run():
    url = os.environ.get('TEST_DATABASE_URL', '')
    if os.environ.get('TEST_DATABASE_ALLOW_DISPOSABLE') != '1':
        raise SystemExit('Explicit disposable database acknowledgement required')
    if not url.startswith(('postgresql://', 'postgres://')) or urlparse(url).hostname not in {'localhost', '127.0.0.1', '::1', 'postgres'}:
        raise SystemExit('Only a local/container disposable PostgreSQL database is permitted')
    first, second = Repository(url), Repository(url)
    services = [TradingService(first), TradingService(second)]
    checks = []
    prefix = 'v1-' + uuid.uuid4().hex
    expiry = datetime.now(timezone.utc).date() + timedelta(days=14)
    expiry += timedelta(days=(4 - expiry.weekday()) % 7)

    def request(key, right='CALL', side='BUY'):
        return dict(request_key=prefix + key, symbol='NVDA', right=right, side=side,
                    expiry=expiry.isoformat(), strike_cents=15000, quantity=1, limit_cents=50)

    def race(account, requests):
        gate = threading.Barrier(2)

        def submit(index):
            gate.wait(timeout=10)
            try:
                return services[index].submit(account, requests[index])
            except Rejected as exc:
                return {'rejected': str(exc)}
        with ThreadPoolExecutor(max_workers=2) as pool:
            return list(pool.map(submit, range(2)))

    try:
        a = services[0].create_account(prefix + '-A')['id']
        b = services[0].create_account(prefix + '-B')['id']
        for account in (a, b):
            services[0].watch(account, 'NVDA', True)
            services[0].configure(account, {'max_contracts': 1})
        results = race(a, [request('call'), request('put', 'PUT')])
        assert len([r for r in results if 'id' in r]) == 1
        assert len(services[0].rows(a, 'orders')) == 1
        checks.append('concurrent_opposite_direction_admission_serialized')
        winner = next(r for r in results if 'id' in r)
        same = request('same', winner['right_kind'])
        services[0].cancel(a, winner['id'])
        duplicates = race(a, [same, same])
        assert duplicates[0]['id'] == duplicates[1]['id']
        checks.append('concurrent_duplicate_has_one_receipt')
        current = duplicates[0]
        services[0].fill(a, current['id'], prefix + '-fill', 1, 50)
        try:
            services[1].submit(a, request('overcap', winner['right_kind']))
        except Rejected:
            pass
        else:
            raise AssertionError('Aggregate contract cap bypassed')
        checks.append('owned_plus_pending_contract_cap')
        # Explicit synthetic quote observation, not an inferred execution mark.
        with first.transaction() as db:
            services[0].record_option_mark(db,a,'NVDA',winner['right_kind'],expiry.isoformat(),15000,50,50,services[0].now())
        other_right = 'PUT' if winner['right_kind'] == 'CALL' else 'CALL'
        independent = services[1].submit(b, request('independent', other_right))
        assert independent['account_id'] == b
        checks.append('same_symbol_opposite_in_independent_account_allowed')
        close = services[0].submit(a, request('close', winner['right_kind'], 'SELL_TO_CLOSE'))
        services[0].stop(a)
        assert next(o for o in services[0].rows(a, 'orders') if o['id'] == close['id'])['status'] == 'PENDING'
        checks.append('emergency_preserves_owned_close')
        try:
            services[1].fill(b, close['id'], prefix + '-cross', 1, 50)
        except Rejected:
            pass
        else:
            raise AssertionError('Cross-account fill accepted')
        checks.append('cross_account_fill_denied')
        services[0].fill(a, close['id'], prefix + '-closed', 1, 50)
        assert not services[0].rows(a, 'positions')
        checks.append('owned_close_reaches_flat')
        snapshots = services[0].rows(a, 'decision_snapshots')
        assert snapshots
        for operation in ('UPDATE decision_snapshots SET payload=payload WHERE id=?',
                          'DELETE FROM decision_snapshots WHERE id=?'):
            try:
                with first.transaction() as db:
                    db.execute(operation, (snapshots[0]['id'],))
            except Exception as exc:
                assert 'immutable' in str(exc)
            else:
                raise AssertionError('Immutable decision changed')
        checks.append('decision_update_and_delete_guards')
        assert services[1].rows(a, 'decision_snapshots') == snapshots
        checks.append('snapshot_rollback_and_cross_connection_visibility')
        with first.transaction() as db:
            assert db.one('SELECT COUNT(*) AS n FROM schema_migrations')['n'] >= 4
        checks.append('additive_migrations')
        print(json.dumps({'status': 'passed', 'checks_passed': len(checks), 'checks_failed': 0,
                          'checks': checks, 'database': 'PostgreSQL', 'broker': 'none'}, indent=2))
    finally:
        second.close()
        first.close()


if __name__ == '__main__':
    run()
