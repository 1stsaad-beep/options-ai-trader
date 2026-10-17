"""No provider traffic: real HTTP parser on local socket pairs, fake TLS/DNS."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import socket
import threading
import time
from types import SimpleNamespace

import pytest

from app import provider_https as module
from app import market_data, option_metadata
from app.market_data import AlpacaDataTransport, DataCredentials, MarketDataError
from app.option_metadata import AlpacaMetadataTransport, TERMS_PREFIX

HOST = 'data.alpaca.markets'
SYMBOL = 'AAPL261120C00200000'


def answers(ip='93.184.216.34'):
    return [(socket.AF_INET6 if ':' in ip else socket.AF_INET,
             socket.SOCK_STREAM, 6, '', (ip, 443))]


@pytest.fixture
def isolated(monkeypatch):
    resolvers = {host: module.Resolver() for host in module._RESOLVERS}
    monkeypatch.setattr(module, '_RESOLVERS', resolvers)
    return resolvers


def test_dns_timeout_has_one_pending_lookup_and_recovers(isolated, monkeypatch):
    entered = threading.Event(); release = threading.Event(); calls = []

    def lookup(*args, **kwargs):
        calls.append(args); entered.set()
        assert release.wait(2)
        return answers()

    monkeypatch.setattr(module.socket, 'getaddrinfo', lookup)
    resolver = isolated[HOST]
    try:
        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = [pool.submit(resolver.resolve, HOST, .03) for _ in range(8)]
            assert entered.wait(1)
            for future in futures:
                with pytest.raises(TimeoutError):
                    future.result(timeout=1)
        assert len(calls) == 1
        release.set()
        assert resolver.resolve(HOST, 1) == answers()
        assert len(calls) == 1
        assert resolver.resolve(HOST, 1) == answers()
        assert len(calls) == 2
    finally:
        release.set()


@pytest.mark.parametrize('result', [[], answers() * 65, OSError('private diagnostic')])
def test_dns_empty_excessive_and_failed_answers_are_sanitized(isolated, monkeypatch, result):
    def lookup(*args, **kwargs):
        if isinstance(result, Exception):
            raise result
        return result
    monkeypatch.setattr(module.socket, 'getaddrinfo', lookup)
    with pytest.raises(OSError, match='^Provider DNS unavailable$'):
        isolated[HOST].resolve(HOST, 1)


@pytest.mark.parametrize('kind', ['data', 'terms', 'greeks'])
def test_dns_stall_sends_no_request_and_is_shared_across_client_instances(isolated, monkeypatch, kind):
    release = threading.Event(); calls = []; connections = []
    def lookup(*args, **kwargs):
        calls.append(args)
        assert release.wait(2)
        return answers()
    monkeypatch.setattr(module.socket, 'getaddrinfo', lookup)
    monkeypatch.setattr(module, 'DNS_SECONDS', .02)
    monkeypatch.setattr(module.socket, 'socket', lambda *args: connections.append(args))
    try:
        for _ in range(3):
            transport, path, params = client(kind)
            with pytest.raises(MarketDataError, match='^DATA_CONNECTION_UNAVAILABLE$'):
                transport.get(path, params)
        assert len(calls) == 1 and connections == []
    finally:
        release.set()


def client(kind):
    credentials = DataCredentials('fixture-id', 'fixture-secret')
    if kind == 'data':
        return AlpacaDataTransport(credentials), '/v2/stocks/quotes/latest', {'feed': 'iex'}
    if kind == 'terms':
        return AlpacaMetadataTransport(credentials), TERMS_PREFIX + SYMBOL, {}
    return AlpacaMetadataTransport(credentials), option_metadata.SNAPSHOTS, {'symbols': SYMBOL, 'feed': 'opra'}


@pytest.mark.parametrize('ips', [
    ['127.0.0.1'], ['10.0.0.1'], ['169.254.169.254'], ['::1'], ['ff0e::1'],
    ['93.184.216.34', '192.168.0.1'], ['bad-address'],
])
def test_dns_validation_rejects_all_unsafe_answers_before_credentials(isolated, monkeypatch, ips):
    monkeypatch.setattr(module.socket, 'getaddrinfo', lambda *a, **k: sum((answers(ip) for ip in ips), []))
    def forbidden(*args):
        raise AssertionError('No socket may be opened')
    monkeypatch.setattr(module.socket, 'socket', forbidden)
    transport, path, params = client('data')
    with pytest.raises(MarketDataError, match='^DATA_CONNECTION_UNAVAILABLE$'):
        transport.get(path, params)


@contextmanager
def wire(monkeypatch, *, stage='ok', ip='93.184.216.34'):
    local, peer = socket.socketpair()
    stop = threading.Event(); calls = []; requests = []; errors = []

    class RawSocket:
        def connect(self, destination): calls.append(('connect', destination))
        def settimeout(self, value): local.settimeout(value)
        def setsockopt(self, *args): pass
        def shutdown(self, how): local.shutdown(how)
        def close(self): local.close()

    class Context:
        def wrap_socket(self, sock, *, server_hostname):
            calls.append(('tls', server_hostname))
            return local

    def server():
        try:
            data = b''
            while b'\r\n\r\n' not in data:
                chunk = peer.recv(4096)
                if not chunk:
                    return
                data += chunk
            requests.append(data)
            if stage == 'headers':
                peer.sendall(b'HTTP/1.1 200 OK\r\nX-Slow: ')
                while not stop.wait(.01): peer.sendall(b'x')
            elif stage == 'body':
                peer.sendall(b'HTTP/1.1 200 OK\r\nContent-Length: 100000\r\nConnection: close\r\n\r\n{"data":"')
                while not stop.wait(.01): peer.sendall(b'x')
            else:
                peer.sendall(b'HTTP/1.1 200 OK\r\nContent-Length: 11\r\nConnection: close\r\n\r\n{"ok":true}')
        except OSError:
            pass  # Expected peer shutdown at the deadline.
        except BaseException as error:
            errors.append(error)
        finally:
            peer.close()

    def make_socket(family, sock_type):
        calls.append(('socket', family, sock_type))
        return RawSocket()
    monkeypatch.setattr(module.socket, 'getaddrinfo', lambda *a, **k: answers(ip))
    monkeypatch.setattr(module.socket, 'socket', make_socket)
    monkeypatch.setattr(module.ssl, 'create_default_context', Context)
    worker = threading.Thread(target=server, daemon=True)
    worker.start()
    try:
        yield calls, requests
    finally:
        stop.set(); local.close(); peer.close()
        worker.join(1)
        assert not worker.is_alive() and errors == []


@pytest.mark.parametrize('kind', ['data', 'terms', 'greeks'])
@pytest.mark.parametrize('ip', ['93.184.216.34', '2606:4700:4700::1111'])
def test_fixed_host_literal_connection_original_tls_name_and_get(isolated, monkeypatch, kind, ip):
    transport, path, params = client(kind)
    expected = 'paper-api.alpaca.markets' if kind == 'terms' else HOST
    with wire(monkeypatch, ip=ip) as (calls, requests):
        result = transport.get(path, params)
        assert result.body == {'ok': True}
        assert ('connect', (ip, 443)) in calls
        assert ('tls', expected) in calls
        assert calls[0] == ('socket', socket.AF_INET6 if ':' in ip else socket.AF_INET, socket.SOCK_STREAM)
        assert len(requests) == 1 and requests[0].startswith(b'GET ')
        assert ('Host: ' + expected).encode() in requests[0]


@pytest.mark.parametrize('kind', ['data', 'terms', 'greeks'])
@pytest.mark.parametrize('stage', ['headers', 'body'])
def test_absolute_deadline_interrupts_slow_stream_without_retry(isolated, monkeypatch, kind, stage):
    target = market_data if kind == 'data' else option_metadata
    durations = []
    def shortened(host, *, timeout):
        durations.append(timeout)
        return module.provider_connection(host, timeout=.15)
    monkeypatch.setattr(target, 'provider_connection', shortened)
    with wire(monkeypatch, stage=stage) as (calls, requests):
        start = time.monotonic()
        transport, path, params = client(kind)
        with pytest.raises(MarketDataError, match='^DATA_CONNECTION_UNAVAILABLE$'):
            transport.get(path, params)
        assert time.monotonic() - start < 2
        assert durations == [8 if kind == 'data' else 4]
        assert len(requests) == 1


def test_late_valid_json_is_discarded_and_connection_closed(monkeypatch):
    closed = []; clock = [0]
    monkeypatch.setattr(module.time, 'monotonic', lambda: clock[0])
    connection = SimpleNamespace(connect=lambda: None, request=lambda *a, **k: None,
        close=lambda: closed.append(True), getresponse=lambda: SimpleNamespace(
            status=200, getheaders=lambda: [], read=lambda limit: b'{}'))
    monkeypatch.setattr(module.http.client, 'HTTPSConnection', lambda *a, **k: connection)
    original = market_data.json.loads
    def decode(body, **kwargs):
        value = original(body, **kwargs)
        clock[0] = 9
        return value
    monkeypatch.setattr(market_data.json, 'loads', decode)
    transport, path, params = client('data')
    with pytest.raises(MarketDataError, match='^DATA_CONNECTION_UNAVAILABLE$'):
        transport.get(path, params)
    assert closed == [True]


def test_unknown_host_never_constructs_connection(monkeypatch):
    def forbidden(*a, **k): raise AssertionError('No network')
    monkeypatch.setattr(module.http.client, 'HTTPSConnection', forbidden)
    with pytest.raises(OSError, match='Provider host forbidden'):
        with module.provider_connection('api.alpaca.markets', timeout=1):
            pass


@pytest.mark.parametrize('phase', ['connect', 'tls'])
def test_failed_connection_closes_socket_and_never_sends_credentials(isolated, monkeypatch, phase):
    calls = []
    class Raw:
        def settimeout(self, value): assert 0 < value <= 8
        def setsockopt(self, *args): pass
        def connect(self, address):
            calls.append('connect')
            if phase == 'connect': raise OSError('private network diagnostic')
        def close(self): calls.append('closed')
        def sendall(self, data): raise AssertionError('Credentials must not be sent')
    class Context:
        def wrap_socket(self, sock, *, server_hostname):
            calls.append('tls')
            raise module.ssl.SSLCertVerificationError('private TLS diagnostic')
    monkeypatch.setattr(module.socket, 'getaddrinfo', lambda *a, **k: answers())
    monkeypatch.setattr(module.socket, 'socket', lambda *a: Raw())
    monkeypatch.setattr(module.ssl, 'create_default_context', Context)
    transport, path, params = client('data')
    with pytest.raises(MarketDataError, match='^DATA_CONNECTION_UNAVAILABLE$'):
        transport.get(path, params)
    assert calls.count('connect') == 1 and 'closed' in calls
    assert ('tls' in calls) == (phase == 'tls')
