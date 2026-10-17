import asyncio
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
import os
import sqlite3
import subprocess
import sys
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from app import alert_receiver as module
from app.alert_receiver import ReceiverStore, ReceiverConflict, create_app, main
from app.alert_webhook import Webhook, Reply, PATH
from app.observed_alert_delivery import AlertDelivery, VERSION, ACK
from app.observed_paper import canonical, digest
from app.observed_paper_alerts import ZERO, page
from app.observed_paper_runtime import ObservedPaperRuntime
from test_observed_paper import stored

TOKEN = 'synthetic-receiver-token-123456789'
TARGET = Webhook('https://receiver.example' + PATH, TOKEN).target_hash


def message(sequence=1, previous=ZERO, *, active=None, raised=None, resolved=None):
    active = ['WORKER_UNAVAILABLE'] if active is None else active
    original = {'sequence': sequence, 'detectedAt': '2026-10-16T15:00:00.000000Z',
                'active': active, 'raised': active if raised is None else raised,
                'resolved': [] if resolved is None else resolved, 'previousHash': previous}
    event = original | {'eventHash': digest(original)}
    return {'contract': VERSION, 'idempotencyKey': digest([VERSION, TARGET, sequence, event['eventHash']]),
            'event': event, 'externalOrder': False}


def setup(tmp_path):
    store = ReceiverStore(tmp_path / 'receiver.sqlite', TARGET)
    store.initialize()
    return store, TestClient(create_app(store, TOKEN))


def post(client, value, **kwargs):
    return client.post(PATH, content=canonical(value), headers={
        'Authorization': 'Bearer ' + TOKEN, 'Content-Type': 'application/json',
        'Idempotency-Key': value['idempotencyKey']}, **kwargs)


def test_commit_reopen_duplicate_and_recovery_keep_original(tmp_path):
    store, client = setup(tmp_path); first = message()
    result = post(client, first)
    assert result.status_code == 200 and result.json() == {'contract': ACK,
        'sequence': 1, 'eventHash': first['event']['eventHash']}
    reopened = ReceiverStore(store.path, TARGET)
    assert reopened.receive(first, first['idempotencyKey']) == result.json()
    second = message(2, first['event']['eventHash'], active=[], raised=[], resolved=['WORKER_UNAVAILABLE'])
    assert reopened.receive(second, second['idempotencyKey'])['sequence'] == 2
    assert post(client, first).json() == result.json()  # Exact old retry remains valid.
    saved = reopened.page(limit=1)
    assert saved['events'] == [first['event']] and saved['hasMore'] and saved['nextAfter'] == 1
    assert reopened.page(after=1)['events'] == [second['event']]
    assert store.path.stat().st_mode & 0o777 == 0o600
    assert result.headers['cache-control'] == 'no-store'
    with sqlite3.connect(store.path) as db:
        names = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert names == {'receiver_identity', 'receiver_events', 'receiver_head'}
        for command in ['UPDATE receiver_events SET payload=payload', 'DELETE FROM receiver_events',
                        'UPDATE receiver_identity SET target_hash=target_hash', 'DELETE FROM receiver_identity']:
            with pytest.raises(sqlite3.IntegrityError): db.execute(command)


def test_concurrent_receivers_commit_exact_event_once(tmp_path):
    store, _ = setup(tmp_path); value = message()
    def accept(_):
        return ReceiverStore(store.path, TARGET).receive(value, value['idempotencyKey'])
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(accept, range(16)))
    assert all(value == results[0] for value in results)
    assert store.page()['events'] == [value['event']]


def test_abrupt_process_exit_after_commit_can_retry_original(tmp_path):
    store, _ = setup(tmp_path); value = message()
    script = '''import json,os,sys
from app.alert_receiver import ReceiverStore
value=json.loads(sys.argv[3])
ReceiverStore(sys.argv[1],sys.argv[2]).receive(value,value['idempotencyKey'])
os._exit(17)
'''
    result = subprocess.run([sys.executable, '-c', script, str(store.path), TARGET, canonical(value)],
                            capture_output=True, timeout=10)
    assert result.returncode == 17, result.stderr.decode()
    reopened = ReceiverStore(store.path, TARGET)
    assert reopened.page()['events'] == [value['event']]
    assert reopened.receive(value, value['idempotencyKey'])['sequence'] == 1


def test_failed_head_commit_rolls_back_before_ack(tmp_path):
    store, client = setup(tmp_path); value = message()
    with sqlite3.connect(store.path) as db:
        db.execute("CREATE TRIGGER fail_head BEFORE UPDATE ON receiver_head BEGIN SELECT RAISE(ABORT,'synthetic disk failure'); END")
    result = post(client, value)
    assert result.status_code == 503 and result.json() == {'error': 'RECEIVER_UNAVAILABLE'}
    assert store.page()['sequence'] == 0
    with sqlite3.connect(store.path) as db: db.execute('DROP TRIGGER fail_head')
    assert post(client, value).status_code == 200


def test_actual_sender_lost_remote_ack_retry_deduplicates_without_financial_writes(tmp_path):
    inbox, client = setup(tmp_path)
    repo, store, clock = stored(tmp_path)
    runtime = ObservedPaperRuntime(store); runtime.tick(); runtime.close()
    before = store.snapshot('a', full=True); alerts = page(store, after=0); calls = []
    def send(body, key):
        calls.append((deepcopy(body), key))
        reply = post(client, body)
        assert reply.status_code == 200
        if len(calls) == 1: raise OSError('Synthetic lost ACK after receiver commit')
        return Reply(reply.status_code, reply.json())
    sender = AlertDelivery(repo.transaction, clock, SimpleNamespace(send=send), TARGET)
    assert sender.tick()['state'] == 'RETRY_PENDING'
    assert inbox.page()['sequence'] == 1
    clock.step(5)
    assert sender.tick()['state'] == 'DELIVERED'
    assert calls[0] == calls[1] and inbox.page()['sequence'] == 1
    assert sender.tick()['state'] == 'DELIVERED' and sender.tick()['state'] == 'IDLE'
    assert inbox.page()['events'] == alerts['events']
    assert store.snapshot('a', full=True) == before and page(store, after=0) == alerts
    repo.close()


@pytest.mark.parametrize('change', ['key', 'hash', 'extra', 'authority', 'code', 'bool-sequence'])
def test_invalid_envelope_never_acknowledged(tmp_path, change):
    store, client = setup(tmp_path); value = message()
    if change == 'key': value['idempotencyKey'] = 'a' * 64
    if change == 'hash': value['event']['eventHash'] = 'b' * 64
    if change == 'extra': value['private'] = 'should not be echoed'
    if change == 'authority': value['externalOrder'] = True
    if change == 'code': value['event']['active'] = ['arbitrary private message']
    if change == 'bool-sequence': value['event']['sequence'] = True
    result = post(client, value)
    assert result.status_code == 400 and result.json() == {'error': 'INVALID_NOTIFICATION'}
    assert store.page()['sequence'] == 0


@pytest.mark.parametrize('change', ['gap', 'previous', 'transition', 'conflicting-sequence'])
def test_chain_or_sequence_conflict_preserves_committed_original(tmp_path, change):
    store, client = setup(tmp_path); first = message()
    assert post(client, first).status_code == 200
    if change == 'gap': value = message(3, first['event']['eventHash'])
    if change == 'previous': value = message(2, 'a' * 64)
    if change == 'transition': value = message(2, first['event']['eventHash'], active=[], raised=[], resolved=[])
    if change == 'conflicting-sequence': value = message(active=[], raised=[])
    assert post(client, value).status_code == 409
    assert store.page()['events'] == [first['event']]


@pytest.mark.parametrize('corrupt', ['tail', 'head', 'removed-tail'])
def test_entire_stored_history_verified_even_for_old_duplicate(tmp_path, corrupt):
    store, client = setup(tmp_path); first = message()
    second = message(2, first['event']['eventHash'], active=[], raised=[], resolved=['WORKER_UNAVAILABLE'])
    assert post(client, first).status_code == post(client, second).status_code == 200
    with sqlite3.connect(store.path) as db:
        if corrupt == 'tail':
            db.execute('DROP TRIGGER receiver_events_no_update')
            db.execute("UPDATE receiver_events SET payload='{}' WHERE sequence=2")
        elif corrupt == 'head': db.execute('UPDATE receiver_head SET sequence=1')
        else:
            db.execute('DROP TRIGGER receiver_events_no_delete')
            db.execute('DELETE FROM receiver_events WHERE sequence=2')
    assert post(client, first).status_code == 409
    with pytest.raises(ReceiverConflict): store.page(limit=1)


def test_identity_binding_and_existing_files_never_overwritten(tmp_path):
    store, _ = setup(tmp_path)
    with pytest.raises(FileExistsError): store.initialize()
    with pytest.raises(ReceiverConflict): ReceiverStore(store.path, 'c' * 64).page()
    missing = ReceiverStore(tmp_path / 'missing.sqlite', TARGET)
    with pytest.raises(FileNotFoundError): missing.page()
    assert not missing.path.exists()
    link = tmp_path / 'link.sqlite'; link.symlink_to(store.path)
    with pytest.raises(OSError): ReceiverStore(link, TARGET).page()
    store.path.chmod(0o644)
    with pytest.raises(OSError): store.page()


@pytest.mark.parametrize('auth', [None, 'Bearer wrong', 'Basic synthetic'])
def test_authentication_precedes_read_or_write(tmp_path, auth):
    store, client = setup(tmp_path)
    for method in ('GET', 'POST'):
        result = client.request(method, PATH, content='invalid', headers={} if auth is None else {'Authorization': auth})
        assert result.status_code == 401 and result.json() == {'error': 'UNAUTHORIZED'}
    assert store.page()['sequence'] == 0


@pytest.mark.parametrize('body', ['{"x":1,"x":2}', '{"x":NaN}', '[1]', '\ud800', 'x' * 8193, '[' * 4000])
def test_bounded_strict_body_rejection(tmp_path, body):
    store, client = setup(tmp_path)
    result = client.post(PATH, content=body.encode('utf-8', errors='surrogatepass'), headers={
        'Authorization': 'Bearer ' + TOKEN, 'Content-Type': 'application/json', 'Idempotency-Key': 'a' * 64})
    assert result.status_code in (400, 413) and store.page()['sequence'] == 0


def test_slow_chunked_body_is_cancelled_at_total_deadline(tmp_path, monkeypatch):
    store, _ = setup(tmp_path); monkeypatch.setattr(module, 'BODY_SECONDS', .02)
    async def run():
        cancelled = asyncio.Event()
        async def body():
            try:
                yield b'{'
                await asyncio.Event().wait()
            finally: cancelled.set()
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(store, TOKEN)), base_url='http://synthetic') as client:
            result = await client.post(PATH, content=body(), headers={'Authorization': 'Bearer ' + TOKEN,
                'Content-Type': 'application/json', 'Idempotency-Key': 'a' * 64})
        assert result.status_code == 408 and cancelled.is_set()
    asyncio.run(run())
    assert store.page()['sequence'] == 0


def test_chunked_oversize_body_stops_before_consuming_rest(tmp_path):
    store, _ = setup(tmp_path)
    async def run():
        async def body():
            yield b'x' * 4096
            yield b'x' * 4097
            raise AssertionError('Must stop reading an oversized stream')
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(store, TOKEN)), base_url='http://synthetic') as client:
            result = await client.post(PATH, content=body(), headers={'Authorization': 'Bearer ' + TOKEN,
                'Content-Type': 'application/json', 'Idempotency-Key': 'a' * 64})
        assert result.status_code == 413
    asyncio.run(run())
    assert store.page()['sequence'] == 0


def test_duplicate_auth_or_idempotency_headers_are_rejected(tmp_path):
    store, client = setup(tmp_path); value = message()
    base = [('Authorization', 'Bearer ' + TOKEN), ('Content-Type', 'application/json'),
            ('Idempotency-Key', value['idempotencyKey'])]
    assert client.post(PATH, content=canonical(value), headers=base + [base[0]]).status_code == 401
    assert client.post(PATH, content=canonical(value), headers=base + [base[2]]).status_code == 400
    assert store.page()['sequence'] == 0


def test_paged_get_is_authenticated_bounded_and_read_only(tmp_path):
    store, client = setup(tmp_path); value = message(); post(client, value)
    headers = {'Authorization': 'Bearer ' + TOKEN}
    assert client.get(PATH, headers=headers).json() == store.page()
    for query in ['limit=26', 'after=-1', 'after=2', 'limit=1&limit=2', 'token=private']:
        result = client.get(PATH + '?' + query, headers=headers)
        assert result.status_code == 400 and result.json() == {'error': 'INVALID_NOTIFICATION'}
    assert client.get('/openapi.json').status_code == 404
    assert store.page()['sequence'] == 1


def test_disabled_cli_does_not_read_secret_or_open_store(monkeypatch, capsys):
    monkeypatch.delenv('OAT_ALERT_INBOX_APPROVAL', raising=False)
    monkeypatch.setenv('TRADING_MODE', 'paper'); monkeypatch.setenv('ENABLE_LIVE', 'false')
    def forbidden(*a, **k): raise AssertionError('Disabled means no IO')
    monkeypatch.setattr(module, 'from_file', forbidden)
    assert main(['--initialize']) == 0
    assert json.loads(capsys.readouterr().out)['state'] == 'DISABLED'


def test_explicit_cli_initialize_and_healthcheck_no_network(tmp_path, monkeypatch):
    secret = tmp_path / 'receiver.json'
    secret.write_text(json.dumps({'endpoint': 'https://receiver.example' + PATH, 'token': TOKEN})); secret.chmod(0o600)
    path = tmp_path / 'cli.sqlite'
    monkeypatch.setenv('TRADING_MODE', 'paper'); monkeypatch.setenv('ENABLE_LIVE', 'false')
    monkeypatch.setenv('OAT_ALERT_INBOX_APPROVAL', 'receiver_only_approved')
    monkeypatch.setenv('OAT_ALERT_RECEIVER_FILE', str(secret)); monkeypatch.setenv('OAT_ALERT_INBOX_FILE', str(path))
    assert main(['--healthcheck']) == 1 and not path.exists()
    assert main(['--initialize']) == 0 and main(['--healthcheck']) == 0
    before = path.read_bytes()
    assert main(['--initialize']) == 1 and path.read_bytes() == before
    monkeypatch.setenv('ENABLE_LIVE', 'true')
    assert main(['--healthcheck']) == 1
