from copy import deepcopy
from datetime import timedelta
import json
import sqlite3
from types import SimpleNamespace

import pytest

from app.alert_webhook import Reply, Webhook, from_file, PATH
from app.observed_alert_delivery import AlertDelivery, ACK
from app.observed_paper_runtime import ObservedPaperRuntime
from app.observed_paper_alerts import page, acknowledge
from app.observed_paper_store import LedgerConflict
from app.repository import Session
from test_observed_paper import stored, iso

TARGET='a'*64


class Receiver:
    def __init__(self):self.calls=[];self.status=200;self.bad=False
    def send(self,body,key):
        self.calls.append((deepcopy(body),key))
        e=body['event']
        return Reply(self.status,{} if self.bad else {'contract':ACK,'sequence':e['sequence'],'eventHash':e['eventHash']})


def setup(tmp_path):
    repo,store,clock=stored(tmp_path)
    runtime=ObservedPaperRuntime(store);runtime.tick();runtime.close()
    receiver=Receiver();sender=AlertDelivery(repo.transaction,clock,receiver,TARGET,'first')
    return repo,store,clock,receiver,sender


def test_ordered_exact_ack_no_owner_ack_or_financial_writes(tmp_path):
    repo,store,clock,wire,sender=setup(tmp_path)
    before=store.snapshot('a',full=True);alerts=page(store,after=0)
    assert sender.tick()['state']=='DELIVERED'
    assert sender.tick()['state']=='DELIVERED'
    assert sender.tick()['state']=='IDLE'
    assert [v[0]['event']['sequence'] for v in wire.calls]==[1,2]
    assert page(store,after=0)==alerts and page(store)['acknowledged']['sequence']==0
    assert store.snapshot('a',full=True)==before
    for statement in ['UPDATE observed_alert_delivery_receipts SET payload=payload','DELETE FROM observed_alert_delivery_receipts']:
        with pytest.raises(sqlite3.IntegrityError),repo.transaction() as db:db.execute(statement)
    repo.close()


def test_http_200_without_matching_ack_retries_same_key_after_restart(tmp_path):
    repo,store,clock,wire,sender=setup(tmp_path);wire.bad=True
    assert sender.tick()['state']=='RETRY_PENDING'
    assert sender.tick()['state']=='BACKOFF'
    clock.step(5);wire.bad=False
    other=AlertDelivery(repo.transaction,clock,wire,TARGET,'second')
    assert other.tick()['state']=='DELIVERED'
    assert wire.calls[0]==wire.calls[1]
    repo.close()


@pytest.mark.parametrize('status',[401,403])
def test_auth_failure_latches_until_explicit_reset(tmp_path,status):
    repo,store,clock,wire,sender=setup(tmp_path);wire.status=status
    assert sender.tick()['state']=='AUTH_BLOCKED'
    clock.step(1000);wire.status=200
    assert sender.tick()['state']=='AUTH_BLOCKED' and len(wire.calls)==1
    sender.reset_auth();assert sender.tick()['state']=='DELIVERED'
    repo.close()


def test_429_and_transport_exception_backoff_without_leaking_payload(tmp_path):
    repo,store,clock,wire,sender=setup(tmp_path);wire.status=429
    assert sender.tick()['state']=='RETRY_PENDING';clock.step(59)
    assert sender.tick()['state']=='BACKOFF';clock.step(1)
    def fail(*_):raise RuntimeError('private provider text')
    sender.transport=SimpleNamespace(send=fail)
    assert sender.tick()=={'state':'RETRY_PENDING','sequence':1,'externalOrder':False}
    repo.close()


def test_lost_local_commit_reuses_receiver_idempotency_key(tmp_path,monkeypatch):
    repo,store,clock,wire,sender=setup(tmp_path);execute=Session.execute
    def fail(self,statement,params=()):
        if statement.startswith('INSERT INTO observed_alert_delivery_receipts'):raise sqlite3.OperationalError('disk unavailable')
        return execute(self,statement,params)
    monkeypatch.setattr(Session,'execute',fail)
    with pytest.raises(sqlite3.OperationalError):sender.tick()
    monkeypatch.setattr(Session,'execute',execute)
    assert sender.tick()['state']=='STANDBY'
    clock.step(30);assert sender.tick()['state']=='DELIVERED'
    assert wire.calls[0]==wire.calls[1]
    repo.close()


def test_old_sender_cannot_ack_successor_or_reset_active_lease(tmp_path):
    repo,store,clock,wire,sender=setup(tmp_path)
    original=wire.send
    successor=AlertDelivery(repo.transaction,clock,wire,TARGET,'successor')
    def delayed(body,key):
        with pytest.raises(LedgerConflict):sender.reset_auth()
        assert successor.tick()['state']=='STANDBY'
        clock.step(30);wire.send=original
        assert successor.tick()['state']=='DELIVERED'
        return original(body,key)
    wire.send=delayed
    assert sender.tick()['state']=='OWNERSHIP_LOST'
    with repo.transaction() as db:assert db.one('SELECT COUNT(*) AS n FROM observed_alert_delivery_receipts')['n']==1
    repo.close()


def test_full_tail_corruption_blocks_first_delivery_and_changed_target_starts_own_cursor(tmp_path):
    repo,store,clock,wire,sender=setup(tmp_path)
    assert sender.tick()['state']=='DELIVERED'
    new=AlertDelivery(repo.transaction,clock,wire,'b'*64)
    assert new.tick()['sequence']==1
    with repo.transaction() as db:
        db.execute('DROP TRIGGER immutable_observed_alert_update')
        db.execute("UPDATE observed_alert_events SET payload='{}' WHERE sequence=2")
    with pytest.raises(LedgerConflict):sender.tick()
    assert len(wire.calls)==2;repo.close()


def test_manual_owner_ack_does_not_suppress_external_backlog(tmp_path):
    repo,store,clock,wire,sender=setup(tmp_path)
    e=page(store,after=0)['events'][-1];acknowledge(store,e['sequence'],e['eventHash'],0)
    assert not page(store)['events']
    assert sender.tick()['sequence']==1
    repo.close()


@pytest.mark.parametrize('endpoint',['http://receiver.example'+PATH,'https://receiver.example/other',
    'https://receiver.example'+PATH+'?token=x','https://user@receiver.example'+PATH,
    'https://receiver.example:8443'+PATH,'https://paper-api.alpaca.markets'+PATH])
def test_receiver_configuration_rejects_unapproved_scheme_path_host(endpoint):
    with pytest.raises(ValueError):Webhook(endpoint,'offline-test-token-123456789')


@pytest.mark.parametrize('ip',['127.0.0.1','10.0.0.1','169.254.169.254','::1','fc00::1','224.0.0.1'])
def test_nonpublic_receiver_is_rejected_before_socket(tmp_path,monkeypatch,ip):
    repo,store,clock,wire,sender=setup(tmp_path);sender.tick();body,key=wire.calls[0]
    monkeypatch.setattr('app.alert_webhook.socket.getaddrinfo',lambda *a,**k:[(0,0,0,'',(ip,443))])
    monkeypatch.setattr('app.alert_webhook.socket.create_connection',lambda *a,**k:pytest.fail('Socket forbidden'))
    with pytest.raises(ValueError,match='^Notification delivery unavailable$'):
        Webhook('https://receiver.example'+PATH,'offline-test-token-123456789').send(body,key)
    repo.close()


def test_secret_file_is_explicit_private_bounded_and_not_exposed(tmp_path):
    p=tmp_path/'receiver.json';p.write_text(json.dumps({'endpoint':'https://receiver.example'+PATH,'token':'offline-test-token-123456789'}));p.chmod(0o600)
    receiver=from_file(p)
    assert 'offline-test' not in repr(receiver) and 'receiver.example' not in repr(receiver)
    assert receiver.target_hash==Webhook('https://receiver.example'+PATH,'different-offline-token-12345').target_hash
    p.chmod(0o644)
    with pytest.raises(ValueError):from_file(p)
    p.chmod(0o600);link=tmp_path/'link';link.symlink_to(p)
    with pytest.raises(ValueError):from_file(link)


def test_disabled_worker_opens_no_database_or_receiver_file(monkeypatch,capsys):
    from app import observed_alert_delivery_worker as worker
    monkeypatch.delenv('OAT_ALERT_DELIVERY_APPROVAL',raising=False)
    monkeypatch.setattr(worker,'from_file',lambda *_:pytest.fail('Secret must remain unread'))
    monkeypatch.setattr(worker,'connection',lambda *_:pytest.fail('Database must remain unopened'))
    assert worker.main(['--once'])==0
    assert json.loads(capsys.readouterr().out)['state']=='DISABLED'


def fake_https(monkeypatch, raw=b'{}', status=200, slow=False):
    import threading
    from app import alert_webhook as module
    stopped=threading.Event();calls=[]
    class Socket:
        def settimeout(self,value):assert 0<value<=5
        def shutdown(self,how):stopped.set()
        def close(self):calls.append('socket_closed')
    sock=Socket()
    def connect(address,timeout):
        assert address==('93.184.216.34',443) and 0<timeout<=5
        calls.append('pinned');return sock
    def wrap(value,server_hostname):
        assert value is sock and server_hostname=='receiver.example'
        calls.append('verified_tls_hostname');return sock
    class Response:
        def read(self,size):
            assert size==4097
            if slow:assert stopped.wait(1)
            return raw
    response=Response();response.status=status
    class Connection:
        def __init__(self,*a,**k):self.sock=None
        def request(self,method,path,body,headers):
            assert method=='POST' and path==PATH
            assert headers['Host']=='receiver.example'
            assert headers['Idempotency-Key']==json.loads(body)['idempotencyKey']
            calls.append('one_post')
        def getresponse(self):return response
        def close(self):calls.append('closed')
    monkeypatch.setattr(module.socket,'getaddrinfo',lambda *a,**k:[(0,0,0,'',('93.184.216.34',443))])
    monkeypatch.setattr(module.socket,'create_connection',connect)
    monkeypatch.setattr(module.ssl,'create_default_context',lambda:SimpleNamespace(wrap_socket=wrap))
    monkeypatch.setattr(module.http.client,'HTTPSConnection',Connection)
    return calls


def test_https_pins_validated_ip_and_preserves_tls_host_and_exact_post(tmp_path,monkeypatch):
    repo,store,clock,wire,sender=setup(tmp_path);sender.tick();body,key=wire.calls[0]
    calls=fake_https(monkeypatch,b'{"contract":"observed-alert-ack-v1"}')
    assert Webhook('https://receiver.example'+PATH,'offline-test-token-123456789').send(body,key).status==200
    assert calls==['pinned','verified_tls_hostname','one_post','closed']
    repo.close()


@pytest.mark.parametrize('raw',[b'x'*4097,b'{"x":1,"x":2}',b'{"x":NaN}',b'\xff'])
def test_https_response_is_bounded_and_strict(tmp_path,monkeypatch,raw):
    repo,store,clock,wire,sender=setup(tmp_path);sender.tick();body,key=wire.calls[0]
    calls=fake_https(monkeypatch,raw)
    with pytest.raises(ValueError,match='^Notification delivery unavailable$'):
        Webhook('https://receiver.example'+PATH,'offline-test-token-123456789').send(body,key)
    assert calls[-1]=='closed';repo.close()


def test_redirect_is_not_followed_and_slow_response_has_absolute_deadline(tmp_path,monkeypatch):
    repo,store,clock,wire,sender=setup(tmp_path);sender.tick();body,key=wire.calls[0]
    calls=fake_https(monkeypatch,status=302)
    assert Webhook('https://receiver.example'+PATH,'offline-test-token-123456789').send(body,key)==Reply(302,{})
    assert calls.count('one_post')==1
    calls=fake_https(monkeypatch,slow=True)
    monkeypatch.setattr('app.alert_webhook.DEADLINE_SECONDS',.03)
    with pytest.raises(ValueError,match='^Notification delivery unavailable$'):
        Webhook('https://receiver.example'+PATH,'offline-test-token-123456789').send(body,key)
    assert calls[-1]=='closed';repo.close()


def test_stuck_dns_is_bounded_and_does_not_spawn_more_lookups(monkeypatch):
    import threading
    from app.alert_webhook import Resolver
    release=threading.Event();done=threading.Event();calls=[]
    def lookup(*a,**k):
        calls.append(1);release.wait(2);done.set();return []
    monkeypatch.setattr('app.alert_webhook.socket.getaddrinfo',lookup)
    resolver=Resolver()
    try:
        for _ in range(3):
            with pytest.raises(TimeoutError):resolver.resolve('receiver.example',.01)
        assert calls==[1]
    finally:release.set();assert done.wait(1)


def test_duplicate_receiver_configuration_is_rejected(tmp_path):
    p=tmp_path/'receiver.json';p.write_text('{"endpoint":"x","endpoint":"y","token":"z"}');p.chmod(0o600)
    with pytest.raises(ValueError,match='^Notification receiver file unavailable$'):from_file(p)


def test_delivery_health_stop_is_owner_fenced_and_expiry_is_liveness_only(tmp_path):
    from app.observed_alert_delivery_worker import health,stop_health
    from app.runtime_health import probe_heartbeat
    repo,store,clock,wire,sender=setup(tmp_path)
    url='sqlite:///'+str(tmp_path/'observed.db')
    # Use the actual repository file chosen by the common fixture.
    with repo.transaction() as db:url='sqlite:///'+db.one('PRAGMA database_list')['file']
    health(url,'first',clock(),'AUTH_BLOCKED')
    assert probe_heartbeat(url,'observed_alert_delivery',clock())
    clock.step(31);assert not probe_heartbeat(url,'observed_alert_delivery',clock())
    health(url,'second',clock(),'IDLE');stop_health(url,'first')
    assert probe_heartbeat(url,'observed_alert_delivery',clock())
    stop_health(url,'second');assert not probe_heartbeat(url,'observed_alert_delivery',clock())
    repo.close()


def test_missing_database_is_not_created_by_enabled_worker(tmp_path,monkeypatch,capsys):
    from app import observed_alert_delivery_worker as worker
    path=tmp_path/'must-not-exist.db'
    monkeypatch.setenv('OAT_ALERT_DELIVERY_APPROVAL','notifications_only_approved')
    monkeypatch.setenv('DATABASE_URL','sqlite:///'+str(path))
    monkeypatch.setattr(worker,'from_file',lambda *_:SimpleNamespace(target_hash=TARGET,send=lambda *_:pytest.fail('No send')))
    assert worker.main(['--once'])==1 and not path.exists()
    out=capsys.readouterr().out
    assert 'DELIVERY_UNAVAILABLE' in out and str(path) not in out


def test_disposable_cross_connection_acceptance_on_sqlite(tmp_path):
    import sys
    from pathlib import Path
    from app.repository import Repository
    sys.path.insert(0,str(Path(__file__).parents[2]/'scripts'))
    from alert_delivery_check import check
    repo,store,clock,wire,sender=setup(tmp_path)
    other=Repository('sqlite:///'+str(tmp_path/'observed.db'),invalidate_accounts=False)
    try:assert len(check([repo,other]))==4
    finally:other.close();repo.close()


def test_future_original_alert_blocks_network_after_clock_regression(tmp_path):
    repo,store,clock,wire,sender=setup(tmp_path);clock.step(-1)
    with pytest.raises(LedgerConflict):sender.tick()
    assert not wire.calls;repo.close()
