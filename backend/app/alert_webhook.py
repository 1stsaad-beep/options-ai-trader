"""Explicit HTTPS receiver for sanitized alerts; no configurable method/path."""
from dataclasses import dataclass, field
from concurrent.futures import Future
import hashlib
import http.client
import ipaddress
import json
import os
import re
import socket
import ssl
import stat
import threading
import time
from urllib.parse import urlsplit

from .observed_paper import canonical

PATH='/oat/v1/alerts'
DEADLINE_SECONDS=5
DNS_SECONDS=2


def strict_json(raw):
    def pairs(values):
        result={}
        for key,value in values:
            if key in result: raise ValueError()
            result[key]=value
        return result
    def invalid(_): raise ValueError()
    return json.loads(raw,object_pairs_hook=pairs,parse_constant=invalid)


class Resolver:
    """At most one outstanding OS lookup; a stuck resolver cannot stall/retry-spawn."""
    def __init__(self):
        self.lock=threading.Lock();self.pending=None

    def resolve(self, host, timeout):
        with self.lock:
            if self.pending is None:
                future=Future();self.pending=(host,future)
                def lookup():
                    try:
                        answers=socket.getaddrinfo(host,443,type=socket.SOCK_STREAM)
                        if len(answers)>64:raise ValueError()
                        future.set_result(answers)
                    except Exception:future.set_exception(ValueError('DNS unavailable'))
                threading.Thread(target=lookup,daemon=True,name='alert-dns').start()
            name,future=self.pending
            if name!=host:raise ValueError()
        try:return future.result(timeout=timeout)
        finally:
            if future.done():
                with self.lock:
                    if self.pending==(name,future):self.pending=None


@dataclass(frozen=True)
class Webhook:
    endpoint: str = field(repr=False)
    token: str = field(repr=False)
    resolver: Resolver = field(default_factory=Resolver,repr=False,compare=False)

    def __post_init__(self):
        try:
            url=urlsplit(self.endpoint)
            if (url.scheme!='https' or not url.hostname or url.port not in (None,443) or url.username is not None or
                    url.password is not None or url.path!=PATH or url.query or url.fragment or
                    not re.fullmatch(r'[a-z0-9]+(?:[a-z0-9.-]*[a-z0-9])?',url.hostname) or
                    url.hostname.endswith(('alpaca.markets','interactivebrokers.com','ibkr.com')) or
                    not isinstance(self.token,str) or not 24 <= len(self.token) <= 256 or not self.token.isascii() or
                    any(ord(c)<=32 or ord(c)>=127 for c in self.token)):
                raise ValueError()
        except (ValueError,TypeError,AttributeError):
            raise ValueError('Invalid notification receiver configuration') from None

    @property
    def target_hash(self):
        # Token rotation does not rewind already acknowledged messages.
        url=urlsplit(self.endpoint)
        return hashlib.sha256(('https://'+url.hostname+PATH).encode()).hexdigest()

    def send(self, body, key):
        if (not isinstance(body,dict) or body.get('contract')!='observed-alert-delivery-v1' or
                body.get('externalOrder') is not False or body.get('idempotencyKey')!=key or
                not isinstance(key,str) or not re.fullmatch('[a-f0-9]{64}',key)):
            raise ValueError('Invalid notification envelope')
        from .observed_paper_alerts import decode
        if set(body)!={'contract','idempotencyKey','event','externalOrder'} or not isinstance(body['event'],dict):
            raise ValueError('Invalid notification envelope')
        event=body['event'];original={k:v for k,v in event.items() if k!='eventHash'}
        if decode({'sequence':event['sequence'],'payload':canonical(original),'digest':event['eventHash'],
                   'previous_hash':event['previousHash']})!=event:
            raise ValueError('Invalid notification event')
        data=canonical(body).encode()
        if len(data)>8192: raise ValueError('Notification too large')
        host=urlsplit(self.endpoint).hostname
        connection=None;timer=None
        deadline=time.monotonic()+DEADLINE_SECONDS
        def remaining():
            value=deadline-time.monotonic()
            if value<=0:raise TimeoutError()
            return value
        try:
            answers=self.resolver.resolve(host,min(DNS_SECONDS,remaining()))
            addresses=list(dict.fromkeys(row[4][0] for row in answers))
            if not addresses or len(addresses)>16 or any(not ipaddress.ip_address(ip).is_global or ipaddress.ip_address(ip).is_multicast for ip in addresses):
                raise ValueError()
            # Connect to the validated literal address; DNS cannot change the
            # destination between validation and TLS. SNI/Host retain the name.
            context=ssl.create_default_context()
            connection=http.client.HTTPSConnection(host,443,timeout=remaining(),context=context)
            sock=socket.create_connection((addresses[0],443),timeout=remaining())
            try:
                sock.settimeout(remaining())
                connection.sock=context.wrap_socket(sock,server_hostname=host)
            except BaseException:
                sock.close();raise
            tls_socket=connection.sock
            # Socket read timeouts alone permit an indefinitely slow byte stream.
            # Shutdown the connected TLS socket at the absolute request deadline.
            def expire():
                try:tls_socket.shutdown(socket.SHUT_RDWR)
                except OSError:pass
            timer=threading.Timer(remaining(),expire);timer.daemon=True;timer.start()
            connection.request('POST',PATH,body=data,headers={'Authorization':'Bearer '+self.token,
                'Content-Type':'application/json','Idempotency-Key':key,'Host':host})
            response=connection.getresponse()
            remaining()
            if response.status!=200: return Reply(response.status,{})
            raw=response.read(4097)
            remaining()
            if len(raw)>4096: raise ValueError()
            value=strict_json(raw.decode('utf-8'))
            return Reply(200,value if isinstance(value,dict) else {})
        except Exception:
            raise ValueError('Notification delivery unavailable') from None
        finally:
            if timer is not None:timer.cancel()
            if connection is not None: connection.close()


@dataclass(frozen=True)
class Reply:
    status: int
    body: dict


def from_file(path):
    """Read exactly the explicitly mounted receiver file; never discover keys."""
    descriptor=None
    try:
        descriptor=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
        info=os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_size>4096 or info.st_mode&0o007:
            raise ValueError()
        with os.fdopen(descriptor,'r') as source:
            descriptor=None;raw=source.read(4097)
            if len(raw)>4096:raise ValueError()
            value=strict_json(raw)
        if not isinstance(value,dict) or set(value)!={'endpoint','token'}:raise ValueError()
        return Webhook(value['endpoint'],value['token'])
    except Exception:
        raise ValueError('Notification receiver file unavailable') from None
    finally:
        if descriptor is not None:os.close(descriptor)
