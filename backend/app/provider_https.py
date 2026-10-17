"""Bounded HTTPS lifecycle for the two fixed read-only provider hosts.

Only DNS runs in a background thread. A timed-out caller never leaves an HTTP
request running, and repeated requests share at most one OS lookup per host.
"""
from concurrent.futures import Future
from contextlib import contextmanager
import http.client
import ipaddress
import socket
import ssl
import threading
import time

DNS_SECONDS = 2


class Resolver:
    def __init__(self):
        self._lock = threading.Lock()
        self._pending = None

    def resolve(self, host, timeout):
        with self._lock:
            if self._pending is None:
                future = Future()
                self._pending = (host, future)

                def lookup():
                    try:
                        answers = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
                        if not 1 <= len(answers) <= 64:
                            raise OSError()
                        future.set_result(answers)
                    except Exception:
                        future.set_exception(OSError('Provider DNS unavailable'))

                threading.Thread(target=lookup, daemon=True, name='provider-dns').start()
            name, future = self._pending
            if name != host:
                raise OSError('Provider DNS unavailable')
        try:
            return future.result(timeout=timeout)
        finally:
            if future.done():
                with self._lock:
                    if self._pending == (name, future):
                        self._pending = None


# Shared across transport instances: constructing a new client cannot multiply
# stuck DNS threads. No configurable host, proxy, port, or resolver endpoint.
_RESOLVERS = {host: Resolver() for host in ('data.alpaca.markets', 'paper-api.alpaca.markets')}


@contextmanager
def provider_connection(host, *, timeout):
    if host not in _RESOLVERS:
        raise OSError('Provider host forbidden')
    deadline = time.monotonic() + timeout
    expired = threading.Event()
    lock = threading.Lock()
    sockets = []

    def remaining():
        value = deadline - time.monotonic()
        if expired.is_set() or value <= 0:
            raise TimeoutError('Provider deadline exceeded')
        return value

    def expire():
        with lock:
            expired.set()
            for sock in sockets:
                try:
                    sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass

    def track(sock):
        with lock:
            if expired.is_set() or time.monotonic() >= deadline:
                sock.close()
                raise TimeoutError('Provider deadline exceeded')
            sockets.append(sock)

    connection = None
    timer = threading.Timer(remaining(), expire)
    timer.daemon = True
    timer.start()
    try:
        connection = http.client.HTTPSConnection(host, 443, timeout=remaining(),
                                                 context=ssl.create_default_context())

        def create_socket(address, timeout=None, source_address=None):
            if address != (host, 443) or source_address is not None:
                raise OSError('Provider destination forbidden')
            answers = _RESOLVERS[host].resolve(host, min(DNS_SECONDS, remaining()))
            try:
                addresses = list(dict.fromkeys(row[4][0] for row in answers))
                if not 1 <= len(addresses) <= 16 or any(
                    not ipaddress.ip_address(ip).is_global or ipaddress.ip_address(ip).is_multicast
                    for ip in addresses
                ):
                    raise ValueError()
                ip = ipaddress.ip_address(addresses[0])
            except (ValueError, IndexError, TypeError):
                raise OSError('Provider DNS unavailable') from None
            remaining()
            sock = socket.socket(socket.AF_INET6 if ip.version == 6 else socket.AF_INET,
                                 socket.SOCK_STREAM)
            track(sock)
            try:
                sock.settimeout(remaining())
                # A literal sockaddr avoids a second DNS lookup / rebinding.
                sock.connect((str(ip), 443))
                sock.settimeout(remaining())
                return sock
            except BaseException:
                sock.close()
                raise

        connection._create_connection = create_socket
        original_connect = connection.connect

        def connect():
            original_connect()
            track(connection.sock)
            connection.sock.settimeout(remaining())

        connection.connect = connect
        yield connection, remaining
        remaining()  # Reject late non-200 responses and decoded JSON too.
    finally:
        timer.cancel()
        if connection is not None:
            connection.close()
        with lock:
            for sock in sockets:
                sock.close()
