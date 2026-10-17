from copy import deepcopy
from datetime import timedelta
import json
import threading
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import health_probe as module
from app import provider_https
from app.health_exporter import PATH, create_app, snapshot
from app.health_probe import HealthProbe, validate_response
from test_health_exporter import TOKEN, NONCE, setup, seed
from test_provider_https import wire, answers


def fixture_reply(tmp_path):
    repo, store, clock, url = setup(tmp_path); seed(repo, clock())
    value, status = snapshot(url, clock(), NONCE)
    repo.close()
    return value, clock


def fake_transport(monkeypatch, respond):
    calls = []; closed = []
    class Connection:
        def __init__(self, *a, **k): calls.append(('connection', a, k))
        def connect(self): pass
        def request(self, method, path, *, headers):
            calls.append(('request', method, path, headers)); self.reply = respond(method, path, headers)
        def getresponse(self):
            status, body = self.reply
            return SimpleNamespace(status=status, read=lambda n: body[:n])
        def close(self): closed.append(True)
    monkeypatch.setattr(module.http.client, 'HTTPSConnection', Connection)
    return calls, closed


def test_real_exporter_protocol_through_isolated_asgi_no_owner_route(tmp_path, monkeypatch):
    repo, store, clock, url = setup(tmp_path); seed(repo, clock())
    client = TestClient(create_app(url, TOKEN, clock))
    def respond(method, path, headers):
        response = client.request(method, path, headers=headers)
        return response.status_code, response.content
    calls, closed = fake_transport(monkeypatch, respond)
    probe = HealthProbe('https://health.example' + PATH, TOKEN, now=clock)
    first = probe.read(); second = probe.read()
    assert first['state'] == second['state'] == 'OBSERVED'
    assert first['remote']['components']['delivery'] == {'fresh': True, 'state': 'AUTH_BLOCKED'}
    assert first['remote']['nonce'] != second['remote']['nonce']
    requests = [c for c in calls if c[0] == 'request']
    assert len(requests) == 2 and all(c[1:3] == ('GET', PATH) for c in requests)
    assert calls[0][1] == ('health.example', 443) and calls[0][2]['context'].check_hostname
    assert closed == [True, True]
    assert TOKEN not in repr(probe) and TOKEN not in json.dumps(first)
    repo.close()


def test_exporter_database_outage_is_observed_unknown_not_worker_success(tmp_path, monkeypatch):
    repo, store, clock, url = setup(tmp_path); repo.close()
    def respond(method, path, headers):
        value, status = snapshot(url + '.missing', clock(), headers['X-OAT-Probe'])
        return status, json.dumps(value).encode()
    fake_transport(monkeypatch, respond)
    result = HealthProbe('https://health.example' + PATH, TOKEN, now=clock).read()
    assert result['state'] == 'OBSERVED' and result['remote']['databaseReadable'] is False
    assert all(v['state'] == 'UNKNOWN' for v in result['remote']['components'].values())


@pytest.mark.parametrize('endpoint', ['http://health.example' + PATH, 'https://health.example:444' + PATH,
    'https://health.example/api/accounts', 'https://x:y@health.example' + PATH,
    'https://health.example' + PATH + '?private=query', 'https://health.example' + PATH + '#fragment',
    'https://paper-api.alpaca.markets' + PATH, 'https://ibkr.com' + PATH])
def test_configuration_rejects_wrong_scheme_route_authority_and_broker_hosts(endpoint):
    with pytest.raises(ValueError, match='^Invalid health probe configuration$'):
        HealthProbe(endpoint, TOKEN)


@pytest.mark.parametrize('status,expected', [(401,'PROBE_AUTH_DENIED'), (403,'PROBE_AUTH_DENIED'),
    (429,'PROBE_RATE_LIMITED'), (302,'PROBE_INVALID_RESPONSE'), (500,'PROBE_INVALID_RESPONSE')])
def test_http_failure_is_sanitized_no_redirect_or_implicit_retry(monkeypatch, status, expected):
    calls, closed = fake_transport(monkeypatch, lambda *args: (status, b'private diagnostic'))
    value = HealthProbe('https://health.example' + PATH, TOKEN).read()
    assert value['state'] == expected and value['remote'] is None
    assert len(calls) == 2 and closed == [True] and 'private' not in json.dumps(value)


@pytest.mark.parametrize('corruption', ['nonce','stale','future','extra','authority','bool','state','fresh',
    'alerts','diagnostic','auth-latch','db-status','unknown','unverified-access'])
def test_forged_cached_and_inconsistent_reports_are_rejected(tmp_path, monkeypatch, corruption):
    value, clock = fixture_reply(tmp_path)
    def respond(method, path, headers):
        body = deepcopy(value); body['nonce'] = headers['X-OAT-Probe']
        if corruption == 'nonce': body['nonce'] = 'b' * 32
        if corruption == 'stale': body['serverTime'] = (clock() - timedelta(seconds=6)).isoformat()
        if corruption == 'future': body['serverTime'] = (clock() + timedelta(seconds=6)).isoformat()
        if corruption == 'extra': body['private'] = 'not permitted'
        if corruption == 'authority': body['executionAllowed'] = True
        if corruption == 'bool': body['components']['worker']['fresh'] = 1
        if corruption == 'state': body['components']['worker']['state'] = 'arbitrary private state'
        if corruption == 'fresh': body['components']['worker']['fresh'] = False
        if corruption == 'alerts': body['workerAlerts'].append('arbitrary private alert')
        if corruption == 'diagnostic': body['workerDiagnostic'] = 'arbitrary private diagnostic'
        if corruption == 'auth-latch': body['workerAlerts'].remove('DATA_AUTH_OR_ENTITLEMENT_DENIED')
        if corruption == 'db-status': body['databaseReadable'] = False
        if corruption == 'unknown': body['components']['delivery'] = {'fresh': False, 'state': 'UNKNOWN'}
        if corruption == 'unverified-access': body['dataAccess']['verified'] = False
        return 200, json.dumps(body).encode()
    fake_transport(monkeypatch, respond)
    result = HealthProbe('https://health.example' + PATH, TOKEN, now=clock).read()
    assert result['state'] == 'PROBE_INVALID_RESPONSE' and result['remote'] is None
    assert 'private' not in json.dumps(result)


def test_fresh_last_auth_diagnostic_does_not_override_explicit_latch_reset(tmp_path):
    body, clock = fixture_reply(tmp_path)
    body['dataAccess']['authBlocked'] = False
    body['workerDiagnostic'] = 'DATA_AUTH_OR_ENTITLEMENT_DENIED'
    assert validate_response(body, NONCE, clock(), clock(), 200) == body


@pytest.mark.parametrize('raw', [b'x' * 8193, b'{"x":1,"x":2}', b'{"x":NaN}', b'\xff', b'[' * 4000])
def test_strict_bounded_response_never_becomes_health(monkeypatch, raw):
    fake_transport(monkeypatch, lambda *args: (200, raw))
    assert HealthProbe('https://health.example' + PATH, TOKEN).read()['state'] == 'PROBE_INVALID_RESPONSE'


@pytest.mark.parametrize('stage', ['headers', 'body'])
def test_probe_whole_network_deadline_interrupts_slow_stream(monkeypatch, stage):
    monkeypatch.setattr(module, 'DEADLINE_SECONDS', .15)
    with wire(monkeypatch, stage=stage) as (calls, requests):
        result = HealthProbe('https://health.example' + PATH, TOKEN).read()
        assert result['state'] == 'PROBE_UNAVAILABLE' and result['remote'] is None
        assert len(requests) == 1 and requests[0].startswith(('GET ' + PATH).encode())
        assert ('tls', 'health.example') in calls


def test_stuck_dns_cannot_start_http_late_or_spawn_more_lookups(monkeypatch):
    release = threading.Event(); calls = []
    def lookup(*args, **kwargs):
        calls.append(args); assert release.wait(2); return answers()
    monkeypatch.setattr(provider_https, 'DNS_SECONDS', .02)
    monkeypatch.setattr(provider_https.socket, 'getaddrinfo', lookup)
    def forbidden(*args): raise AssertionError('No connection after DNS deadline')
    monkeypatch.setattr(provider_https.socket, 'socket', forbidden)
    probe = HealthProbe('https://health.example' + PATH, TOKEN)
    try:
        for _ in range(3): assert probe.read()['state'] == 'PROBE_UNAVAILABLE'
        assert len(calls) == 1
    finally:
        release.set()


def test_clock_regression_does_not_grant_health(tmp_path, monkeypatch):
    value, clock = fixture_reply(tmp_path); times = [clock(), clock() - timedelta(seconds=1)]
    def respond(method, path, headers):
        value['nonce'] = headers['X-OAT-Probe']; return 200, json.dumps(value).encode()
    fake_transport(monkeypatch, respond)
    probe = HealthProbe('https://health.example' + PATH, TOKEN, now=lambda: times.pop(0) if len(times) > 1 else times[0])
    assert probe.read()['state'] == 'PROBE_INVALID_RESPONSE'


def test_late_valid_json_is_discarded_after_decode(tmp_path, monkeypatch):
    value, clock = fixture_reply(tmp_path); elapsed = [0]
    monkeypatch.setattr(provider_https.time, 'monotonic', lambda: elapsed[0])
    def respond(method, path, headers):
        value['nonce'] = headers['X-OAT-Probe']; return 200, json.dumps(value).encode()
    calls, closed = fake_transport(monkeypatch, respond)
    decode = module.strict_json
    def late(raw):
        result = decode(raw); elapsed[0] = 6; return result
    monkeypatch.setattr(module, 'strict_json', late)
    result = HealthProbe('https://health.example' + PATH, TOKEN, now=clock).read()
    assert result['state'] == 'PROBE_UNAVAILABLE' and result['remote'] is None
    assert len(calls) == 2 and closed == [True]
