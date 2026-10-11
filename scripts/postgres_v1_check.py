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
        # Actual PostgreSQL persistence/locking for prospective research input.
        from app.research_workbench import snapshot_workbench, capture_workbench_observation, replay_workbench
        clock = [datetime(2026, 10, 9, 14, tzinfo=timezone.utc)]
        research = [TradingService(repo, now=lambda: clock[0], today=lambda: clock[0].date())
                    for repo in (first, second)]
        journal_account = research[0].create_account(prefix + '-research')['id']
        research[0].watch(journal_account, 'NVDA', True)
        saved = snapshot_workbench(research[0], journal_account, 'NVDA')
        key = saved['snapshot_id']
        clock[0] += timedelta(minutes=1)
        barrier = threading.Barrier(2)
        def capture(index):
            barrier.wait(timeout=10)
            return capture_workbench_observation(research[index], journal_account, 'NVDA', key)
        with ThreadPoolExecutor(max_workers=2) as pool:
            captured = list(pool.map(capture, range(2)))
        assert captured[0] == captured[1]
        with first.transaction() as db:
            assert db.one('SELECT COUNT(*) AS n FROM research_observations WHERE snapshot_id=?', (key,))['n'] == 1
        checks.append('concurrent_research_observation_has_one_immutable_receipt')
        clock[0] += timedelta(minutes=1)
        capture_workbench_observation(research[0], journal_account, 'NVDA', key)
        replay = replay_workbench(research[1], journal_account, 'NVDA', key)
        assert replay['counterfactual']['status'] == 'REPLAYED'
        assert replay['original_workbench'] == saved['workbench']
        checks.append('cross_connection_research_replay_uses_saved_observations')
        for statement in ('UPDATE research_observations SET digest=digest WHERE snapshot_id=?',
                          'DELETE FROM research_observations WHERE snapshot_id=?'):
            try:
                with first.transaction() as db:
                    db.execute(statement, (key,))
            except Exception as exc:
                assert 'immutable' in str(exc)
            else:
                raise AssertionError('Research observation changed')
        checks.append('research_observation_update_delete_guards')
        try:
            capture_workbench_observation(research[1], b, 'NVDA', key)
        except Rejected:
            pass
        else:
            raise AssertionError('Cross-account research observation accepted')
        checks.append('research_observation_account_isolation')

        # Reuse both real database connections with an explicit, independent
        # expiry clock. These are synthetic contracts, never broker receipts.
        expiry_clock = [datetime(2026, 10, 8, 14, tzinfo=timezone.utc)]
        expiring = [TradingService(repo, now=lambda: expiry_clock[0],
                                   today=lambda: expiry_clock[0].date())
                    for repo in (first, second)]
        expiry_account = expiring[0].create_account(prefix + '-expiry', 3_000_000)['id']
        expiring[0].watch(expiry_account, 'NVDA', True)
        expiring[0].configure(expiry_account, {
            'session_policy': 'us_equity_options_2026_2027', 'commission_cents': 65})
        expiry_request = dict(request_key=prefix + '-expiry-entry', symbol='NVDA',
            right='CALL', side='BUY', expiry='2026-10-09', strike_cents=10000,
            quantity=2, limit_cents=105)
        entry = expiring[0].submit(expiry_account, expiry_request)
        expiring[0].fill(expiry_account, entry['id'], prefix + '-expiry-owned', 2, 105)

        def expiry_refresh(stamp):
            expiry_clock[0] = datetime.fromisoformat(stamp)
            expiring[0].reconcile(expiry_account)
            expiring[0].mock_market_data(expiry_account, 'NVDA')
            with first.transaction() as db:
                expiring[0].record_option_mark(db, expiry_account, 'NVDA', 'CALL',
                    '2026-10-09', 10000, 100, 105, expiry_clock[0])

        expiry_refresh('2026-10-09T19:59:59+00:00')
        close_request = expiry_request | {'request_key': prefix + '-expiry-close',
                                         'side': 'SELL_TO_CLOSE', 'limit_cents': 100}
        expiry_close = expiring[0].submit(expiry_account, close_request)
        receipt = prefix + '-expiry-partial-close'
        expiring[0].fill(expiry_account, expiry_close['id'], receipt, 1, 100)
        remainder = expiring[0].rows(expiry_account, 'positions')
        assert len(remainder) == 1 and remainder[0]['quantity'] == 1
        assert remainder[0]['cost'] == 10565
        with first.transaction() as db:
            original_policy = db.one('SELECT * FROM position_policies WHERE account_id=?', (expiry_account,))
        assert expiring[0].performance(expiry_account)['realized_pnl_cents'] == -630
        checks.append('us_final_session_owned_partial_close_and_fees')

        expiry_clock[0] = datetime(2026, 10, 9, 20, tzinfo=timezone.utc)
        expiry_barrier = threading.Barrier(2)
        def review_expiry(index):
            expiry_barrier.wait(timeout=10)
            return expiring[index].expire(expiry_account)
        with ThreadPoolExecutor(max_workers=2) as pool:
            reviewed = list(pool.map(review_expiry, range(2)))
        assert reviewed == [0, 0]
        with first.transaction() as db:
            assert db.one("SELECT COUNT(*) AS n FROM audit WHERE account_id=? AND event='MOCK_EXPIRY_REVIEW_REQUIRED'",
                          (expiry_account,))['n'] == 1
            assert db.one("SELECT COUNT(*) AS n FROM audit WHERE account_id=? AND event='MOCK_EXPIRY_WRITEOFF'",
                          (expiry_account,))['n'] == 0
        checks.append('concurrent_us_expiry_review_has_one_event_without_writeoff')
        assert expiring[1].rows(expiry_account, 'positions') == remainder
        with second.transaction() as db:
            assert db.one('SELECT * FROM position_policies WHERE account_id=?', (expiry_account,)) == original_policy
        assert expiring[1].reconcile(expiry_account)['resubmitted'] == 0
        checks.append('us_expiry_preserves_inventory_basis_policy_and_reconciled_ledger')
        assert expiring[1].fill(expiry_account, expiry_close['id'], receipt, 1, 100)['filled'] == 1
        assert expiring[1].submit(expiry_account, close_request)['id'] == expiry_close['id']
        checks.append('us_expiry_preserves_lost_reply_order_and_partial_fill_receipts')
        try:
            expiring[1].fill(expiry_account, expiry_close['id'], prefix + '-expiry-late', 1, 100)
        except Rejected:
            pass
        else:
            raise AssertionError('Expired residual received a phantom fill')
        checks.append('us_expiry_blocks_new_close_fill_at_cutoff')

        # The next session and a freshly timestamped synthetic mark do not
        # establish settlement, release exposure, or authorize a new direction.
        expiry_refresh('2026-10-12T14:00:00+00:00')
        value = expiring[1].performance(expiry_account)
        assert value['realized_pnl_cents'] == -630 and value['open_premium_cents'] == 10565
        assert value['valuation_complete'] is False and value['unrealized_pnl_cents'] is None
        assert value['net_liquidation_cents'] is None
        status = expiring[1].status(expiry_account)
        assert len(status['expiration_reviews']) == 1 and not status['new_entries_allowed']
        checks.append('us_expiry_fresh_mark_cannot_fabricate_pnl_or_complete_valuation')
        try:
            expiring[1].configure(expiry_account, {'session_policy': 'synthetic_24x7'})
        except Rejected:
            pass
        else:
            raise AssertionError('Session policy change bypassed unresolved expiry')
        checks.append('us_expiry_policy_downgrade_blocked_with_owned_exposure')
        for direction in ('CALL', 'PUT'):
            try:
                expiring[1].submit(expiry_account, expiry_request | {
                    'request_key': prefix + '-after-expiry-' + direction,
                    'right': direction, 'expiry': '2026-10-23', 'quantity': 1})
            except Rejected:
                pass
            else:
                raise AssertionError('Reconciliation released unresolved expiry risk')
        assert expiring[1].rows(expiry_account, 'positions') == remainder
        assert expiring[1].expire(expiry_account) == 0
        with second.transaction() as db:
            assert db.one("SELECT COUNT(*) AS n FROM audit WHERE account_id=? AND event='MOCK_EXPIRY_REVIEW_REQUIRED'",
                          (expiry_account,))['n'] == 1
        checks.append('us_expiry_reconciled_same_and_opposite_new_entries_stay_blocked')
        print(json.dumps({'status': 'passed', 'checks_passed': len(checks), 'checks_failed': 0,
                          'checks': checks, 'database': 'PostgreSQL', 'broker': 'none'}, indent=2))
    finally:
        second.close()
        first.close()


if __name__ == '__main__':
    run()
