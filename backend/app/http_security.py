"""Bounded request admission for the personal-owner API, not multi-user auth.

Limits are process-local defense in depth; a future public deployment also
needs a trusted TLS proxy with shared connection/rate controls.
"""
import time
from collections import OrderedDict, deque


class RequestLimits:
    def __init__(self, app, max_body_bytes=131072, requests_per_minute=240,
                 max_clients=1024, clock=time.monotonic):
        self.app = app
        self.max_body_bytes = max_body_bytes
        self.limit = requests_per_minute
        self.max_clients = max_clients
        self.clock = clock
        self.clients = OrderedDict()

    async def reject(self, send, status, detail):
        import json
        body = json.dumps({'detail': detail}).encode()
        await send({'type': 'http.response.start', 'status': status,
                    'headers': [(b'content-type', b'application/json'),
                                (b'cache-control', b'no-store')]})
        await send({'type': 'http.response.body', 'body': body})

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        now = self.clock()
        # Never trust a client-supplied X-Forwarded-For as an identity.
        client = (scope.get('client') or ('unknown', 0))[0]
        while self.clients:
            key, stamps = next(iter(self.clients.items()))
            if stamps and stamps[-1] > now - 60:
                break
            self.clients.pop(key)
        if client not in self.clients and len(self.clients) >= self.max_clients:
            return await self.reject(send, 429, 'Request admission capacity reached')
        stamps = self.clients.setdefault(client, deque())
        self.clients.move_to_end(client)
        while stamps and stamps[0] <= now - 60:
            stamps.popleft()
        if len(stamps) >= self.limit:
            return await self.reject(send, 429, 'Request rate exceeded; retry later')
        stamps.append(now)
        lengths = [v for k, v in scope.get('headers', []) if k.lower() == b'content-length']
        if lengths:
            try:
                declared = int(lengths[0])
                if len(lengths) != 1 or declared < 0:
                    raise ValueError
            except ValueError:
                return await self.reject(send, 400, 'Invalid content length')
            if declared > self.max_body_bytes:
                return await self.reject(send, 413, 'Request body too large')
        chunks, size = [], 0
        while True:
            message = await receive()
            if message['type'] == 'http.disconnect':
                return
            chunk = message.get('body', b'')
            size += len(chunk)
            if size > self.max_body_bytes:
                return await self.reject(send, 413, 'Request body too large')
            chunks.append(chunk)
            if not message.get('more_body', False):
                break
        body = b''.join(chunks)
        consumed = False

        async def bounded_receive():
            nonlocal consumed
            if consumed:
                return await receive()
            consumed = True
            return {'type': 'http.request', 'body': body, 'more_body': False}

        async def secured_send(message):
            if message['type'] == 'http.response.start':
                message['headers'] = list(message.get('headers', [])) + [
                    (b'cache-control', b'no-store'),
                    (b'x-content-type-options', b'nosniff'),
                    (b'x-frame-options', b'DENY'),
                    (b'referrer-policy', b'no-referrer')]
            await send(message)
        await self.app(scope, bounded_receive, secured_send)
