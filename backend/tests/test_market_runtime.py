"""Offline independent-runtime integration, actual DBs and Alpaca normalizer.

All transport values are explicitly synthetic test responses, never account data.
"""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import timedelta
import json
import sqlite3
from unittest.mock import Mock
import pytest
from fastapi.testclient import TestClient
from app import market_runtime as rt, market_data_journal as journal
from app.main import create_app
from app.market_data import AlpacaBasicData, DataResponse, DisabledMarketData, MarketDataError
from app.repository import Repository
from app.service import TradingService
from test_alpaca_market_data import Clock
from test_alpaca_market_api import TOKEN, HEADERS


class FixtureTransport:
    def __init__(self, clock):
        self.clock, self.calls = clock, []
        self.failure = None
        self.hook = None

    def get(self, path, params):
        self.calls.append((path, deepcopy(params)))
        if self.hook:
            self.hook()
        if self.failure:
            if isinstance(self.failure, Exception):
                raise self.failure
            return self.failure
        ticker, at = params.get('symbols', 'AAPL'), self.clock.now()
        if path.endswith('/quotes/latest'):
            body = {'quotes': {ticker: {'t': at.isoformat(), 'bp': 130, 'ap': 131, 'bs': 10, 'as': 10}}}
        elif path.endswith('/trades/latest'):
            body = {'trades': {ticker: {'t': at.isoformat(), 'p': 130, 's': 10}}}
        elif '/options/snapshots/' in path:
            body = {'snapshots': {}}
        else:
            body = {'bars': {ticker: [{'t': (at - timedelta(minutes=30-i)).isoformat(),
                'o': 100+i, 'h': 101+i, 'l': 99+i, 'c': 100.5+i,
                'v': 200 if i == 29 else 100} for i in range(30)]}}
        return DataResponse(200, {}, body)


def runtime_fixture(repo, clock, *, owner='worker-a', limit=30):
    s = TradingService(repo)
    s.now = clock.now
    transport = FixtureTransport(clock)
    wrapped = rt.CoordinatedTransport(repo, owner, transport, clock.now, limit)
    provider = AlpacaBasicData(wrapped, now=clock.now, monotonic=clock.mono, sleep=clock.advance)
    return rt.MarketCollector(s, provider, owner=owner), transport


def enable(s, name='A', *, strategies=None):
    account = s.create_account(name)['id']
    # Only fixture-owned rows, not user state.
    with s.repo.transaction() as db:
        db.execute("DELETE FROM watchlist WHERE account_id=? AND symbol<>'AAPL'", (account,))
    rt.configure(s, account, expected_version=0, enabled=True,
                 strategies=strategies or {'breakout': True, 'pullback': False})
    return account


@pytest.fixture
def setup(tmp_path, monkeypatch):
    clock = Clock()
    monkeypatch.setattr(journal, 'utc_now', clock.now)
    monkeypatch.setattr('socket.create_connection', Mock(side_effect=AssertionError('External connection forbidden')))
    repo = Repository('sqlite:///' + str(tmp_path/'runtime.db'))
    collector, transport = runtime_fixture(repo, clock)
    yield collector, transport, clock
    repo.close()


def collect_cycle(collector):
    for _ in range(3):
        assert collector.tick()['state'] == 'COLLECTING_ANALYSIS_ONLY'


def test_one_fetch_per_symbol_for_two_accounts_no_synthetic_mutation(setup):
    c, wire, _ = setup
    s = c.service
    a, b = enable(s), enable(s, 'B', strategies={'breakout': False, 'pullback': False})
    tables = ('accounts', 'watchlist', 'orders', 'fills', 'positions', 'option_marks',
              'market_snapshots', 'decision_snapshots', 'lifecycle_intents')
    def snapshot():
        with s.repo.transaction() as db:
            return {t: db.all('SELECT * FROM ' + t) for t in tables}
    before = snapshot()
    s.submit = Mock(side_effect=AssertionError('No order execution'))
    s.fill = Mock(side_effect=AssertionError('No fake stop fill'))
    collect_cycle(c)
    assert len(wire.calls) == 4  # chain + bars + quote + trade; NOT twice for two accounts
    assert snapshot() == before
    assert not c.tick()['new_risk_allowed']
    assert len(journal.list_records(s, a)['items']) == len(journal.list_records(s, b)['items']) == 3
    aa = next(e['detail'] for e in rt.events(s, a)['items'] if e['detail'].get('state') == 'PROPOSAL_ONLY')
    bb = next(e['detail'] for e in rt.events(s, b)['items'] if e['detail'].get('state') == 'PROPOSAL_ONLY')
    assert aa['analysis']['signals'][0]['right'] == 'CALL'
    assert bb['analysis']['signals'] == []
    with pytest.raises(journal.JournalError):
        journal.replay(s, b, aa['observation_id'])
    assert {l['state_now'] for l in rt.status(s, a)['latest']} == {
        'FRESH_IEX_TRADE', 'FRESH_COMPLETED_BARS', rt.INDICATIVE_REASON}


def test_stale_cache_does_not_claim_stop_or_fresh_quote(setup):
    c, _, clock = setup
    account = enable(c.service)
    collect_cycle(c)
    clock.advance(400)
    report = rt.status(c.service, account)
    assert report['state'] == 'WORKER_UNAVAILABLE' and not report['heartbeat_fresh']
    assert not report['stop_loss_execution_assumed'] and not report['new_risk_allowed']
    assert [l['state_now'] for l in report['latest']].count('STALE_OR_FUTURE_DATA') == 2
    assert c.service.rows(account, 'orders') == []


def test_network_failure_backoff_survives_new_collector_and_recovers(setup):
    c, wire, clock = setup
    account = enable(c.service)
    wire.failure = MarketDataError('DATA_CONNECTION_UNAVAILABLE')
    assert c.tick()['state'] == 'DATA_UNAVAILABLE'
    assert len(wire.calls) == 2
    assert c.tick()['state'] == 'BACKOFF'
    c.release()
    successor, new_wire = runtime_fixture(c.repo, clock, owner='worker-b')
    assert successor.tick()['state'] == 'BACKOFF' and not new_wire.calls
    clock.advance(6)
    assert successor.tick()['state'] == 'COLLECTING_ANALYSIS_ONLY'
    assert len(new_wire.calls) == 1
    assert c.service.rows(account, 'orders') == []


@pytest.mark.parametrize('code', [401, 403])
def test_auth_failure_persisted_without_credentials_in_output(setup, code):
    c, wire, clock = setup
    enable(c.service)
    wire.failure = DataResponse(code, {}, {'secret': 'must-never-be-logged'})
    c.tick()
    c.release()
    successor, wire2 = runtime_fixture(c.repo, clock, owner='worker-b')
    clock.advance(500)
    assert successor.tick()['state'] == 'AUTH_BLOCKED'
    assert not wire2.calls
    with c.repo.transaction() as db:
        assert 'must-never-be-logged' not in json.dumps(db.all('SELECT * FROM market_runtime_events'))


def test_retry_after_and_request_budget_persist_after_restart(setup):
    c, wire, clock = setup
    enable(c.service)
    wire.failure = DataResponse(429, {'Retry-After': '180'}, {})
    assert c.tick()['state'] == 'DATA_UNAVAILABLE'
    c.release()
    successor, new_wire = runtime_fixture(c.repo, clock, owner='worker-b', limit=1)
    clock.advance(61)
    assert successor.tick()['state'] == 'BACKOFF' and not new_wire.calls
    clock.advance(120)
    assert successor.tick()['state'] == 'COLLECTING_ANALYSIS_ONLY'
    successor.release()
    third, last_wire = runtime_fixture(c.repo, clock, owner='worker-c', limit=1)
    assert third.tick()['state'] == 'DATA_UNAVAILABLE'  # spent budget still present
    assert not last_wire.calls


def test_two_connections_lease_and_recovery_preserve_demo_state(setup):
    c, _, clock = setup
    account = enable(c.service)
    c.service.reconcile(account)
    with c.repo.transaction() as db:
        path = db.one('PRAGMA database_list')['file']
        before = db.one('SELECT * FROM accounts WHERE id=?', (account,))
    other_repo = Repository('sqlite:///' + path, invalidate_accounts=False)
    try:
        other, wire = runtime_fixture(other_repo, clock, owner='worker-b')
        with ThreadPoolExecutor(max_workers=2) as pool:
            states = list(pool.map(lambda r: r.tick()['state'], [c, other]))
        assert sorted(states) == ['COLLECTING_ANALYSIS_ONLY', 'STANDBY']
        with other_repo.transaction() as db:
            assert db.one('SELECT * FROM accounts WHERE id=?', (account,)) == before
        winner = c if states[0] != 'STANDBY' else other
        loser = other if winner is c else c
        clock.advance(rt.LEASE_SECONDS + 1)
        assert loser.tick()['state'] == 'COLLECTING_ANALYSIS_ONLY'
        assert winner.tick()['state'] == 'STANDBY'
    finally:
        other_repo.close()


def test_lease_fencing_rejects_result_returning_after_takeover(setup):
    c, wire, clock = setup
    account = enable(c.service)
    def takeover():
        clock.advance(121)
        with c.repo.transaction() as db:
            state = rt.coordinator_in(db)
            state.update(owner='successor', lease_until=journal.utc(clock.now()+timedelta(seconds=120)))
            rt.save_coordinator(db, state)
    wire.hook = takeover
    assert c.tick()['state'] == 'COLLECTOR_LEASE_LOST'
    assert journal.list_records(c.service, account)['items'] == []


def test_disable_during_fetch_prevents_archive_and_decision(setup):
    c, wire, _ = setup
    account = enable(c.service)
    wire.hook = lambda: rt.configure(c.service, account, expected_version=1, enabled=False,
                                   strategies={'breakout': False, 'pullback': False})
    c.tick()
    assert journal.list_records(c.service, account)['items'] == []
    assert not any(e['kind'] == 'OBSERVATION_ANALYZED' for e in rt.events(c.service, account)['items'])


def test_disabled_default_weekend_unknown_calendar_no_requests(setup):
    c, wire, clock = setup
    account = c.service.create_account('off')['id']
    assert c.tick()['state'] == 'NO_ACTIVE_DEMAND'
    rt.configure(c.service, account, expected_version=0, enabled=True,
                 strategies={'breakout': True, 'pullback': False})
    clock.advance(5*86400)
    assert c.tick()['state'] == 'SESSION_CLOSED'  # Saturday
    clock.advance(730*86400)
    assert c.tick()['state'] == 'SESSION_CLOSED'  # outside verified calendar
    assert not wire.calls


def test_disabled_provider_does_not_connect_even_enabled_account(setup):
    c, wire, _ = setup
    enable(c.service)
    c.provider = DisabledMarketData()
    assert c.tick()['state'] == 'DISABLED' and not wire.calls


def test_archive_capacity_fault_is_visible_without_fills(setup, monkeypatch):
    c, _, _ = setup
    account = enable(c.service)
    monkeypatch.setattr(journal, 'MAX_ACCOUNT_RECORDS', 1)
    assert c.tick()['state'] == 'COLLECTING_ANALYSIS_ONLY'
    assert c.tick()['state'] == 'NO_ACTIVE_DEMAND'
    assert c.tick()['state'] == 'NO_ACTIVE_DEMAND'
    assert rt.status(c.service, account)['archive']['records'] == 1
    assert rt.status(c.service, account)['collection_block_reason'] == 'JOURNAL_CAPACITY_REACHED'
    faults = [e for e in rt.events(c.service, account)['items'] if e['kind'] == 'ACCOUNT_COLLECTION_BLOCKED']
    assert len(faults) == 1 and faults[0]['detail']['code'] == 'JOURNAL_CAPACITY_REACHED'
    with c.repo.transaction() as db:
        assert db.all('SELECT * FROM fills') == []


def test_event_immutability_ack_isolation_and_duplicate_control(setup):
    c, _, _ = setup
    a, b = enable(c.service), enable(c.service, 'B')
    first = rt.events(c.service, a)['items'][0]
    for sql in ('UPDATE market_runtime_events SET payload=payload', 'DELETE FROM market_runtime_events'):
        with pytest.raises(sqlite3.IntegrityError, match='immutable'):
            with c.repo.transaction() as db:
                db.execute(sql)
    assert rt.acknowledge(c.service, a, first['id'])['acknowledged']
    assert rt.acknowledge(c.service, a, first['id'])['acknowledged']
    with pytest.raises(journal.JournalError, match='NOT_FOUND'):
        rt.acknowledge(c.service, b, first['id'])
    result = rt.configure(c.service, a, expected_version=0, enabled=True,
                          strategies={'breakout': True, 'pullback': False})
    assert result['version'] == 1
    assert len(rt.events(c.service, a)['items']) == 1
    with pytest.raises(journal.JournalError, match='VERSION_CONFLICT'):
        rt.configure(c.service, a, expected_version=0, enabled=False,
                     strategies={'breakout': True, 'pullback': False})


@pytest.mark.parametrize('invalid', ['future', 'gap', 'stale', 'incomplete'])
def test_analysis_rejects_invalid_causal_input(setup, invalid):
    c, _, clock = setup
    enable(c.service)
    collect_cycle(c)
    with c.repo.transaction() as db:
        value = json.loads(db.one("SELECT payload FROM market_data_journal WHERE kind='stock_bars'")['payload'])['observation']
    bars = value['data']['bars']
    if invalid == 'future':
        bars[-1]['closed_at'] = journal.utc(clock.now()+timedelta(minutes=1))
    elif invalid == 'gap':
        del bars[-12:-5]
    elif invalid == 'stale':
        clock.advance(181)
    else:
        value['complete'] = False
    assert rt.analyze(value, clock.now(), {'breakout': True})['state'] == 'ANALYSIS_UNAVAILABLE'


def test_api_auth_strict_controls_account_scope_no_upstream_reads(setup):
    c, wire, _ = setup
    a, b = enable(c.service), enable(c.service, 'B')
    app = create_app(c.repo, TOKEN, DisabledMarketData())
    prefix = f'/api/accounts/{a}/market-runtime'
    with TestClient(app) as client:
        assert client.get(prefix + '/status').status_code == 401
        assert client.get(prefix + '/status', headers=HEADERS).json()['state'] == 'WORKER_UNAVAILABLE'
        for extra in ({'price': 1}, {'api_key': 'reject'}, {'execute': True}):
            response = client.put(prefix + '/config', headers=HEADERS, json={
                'expected_version': 1, 'enabled': True,
                'strategies': {'breakout': False, 'pullback': True}, **extra})
            assert response.status_code == 422
        event = client.get(prefix + '/events', headers=HEADERS).json()['items'][0]
        assert client.post(f'/api/accounts/{b}/market-runtime/events/{event["id"]}/ack', headers=HEADERS).status_code == 404
        assert client.get(prefix + '/events?limit=101', headers=HEADERS).status_code == 422
    assert not wire.calls


def test_disposable_multi_connection_acceptance_harness(tmp_path, monkeypatch):
    from pathlib import Path
    from test_operations_v1 import module
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / 'scripts'))
    harness = module('market_runtime_check')
    url = 'sqlite:///' + str(tmp_path/'harness.db')
    repos = [Repository(url, invalidate_accounts=False) for _ in range(2)]
    try:
        checks = harness.check(repos)
        assert len(checks) == 8
    finally:
        for repo in repos:
            repo.close()
