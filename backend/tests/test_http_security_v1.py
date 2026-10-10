import asyncio

from fastapi.testclient import TestClient

from app.http_security import RequestLimits
from app.main import create_app
from app.repository import Repository


def exercise(messages, headers=(), requests=1, clock=lambda: 1):
    reached, sent = [], []

    async def downstream(scope, receive, send):
        reached.append(await receive())
        await send({'type': 'http.response.start', 'status': 200, 'headers': []})
        await send({'type': 'http.response.body', 'body': b'ok'})

    app = RequestLimits(downstream, max_body_bytes=8, requests_per_minute=2, clock=clock)

    async def run():
        for _ in range(requests):
            pending = iter(messages)

            async def receive():
                return next(pending)

            async def send(message):
                sent.append(message)

            await app({'type': 'http', 'client': ('local', 1), 'headers': headers}, receive, send)
    asyncio.run(run())
    return reached, sent


def test_chunked_oversized_body_never_reaches_handler():
    reached, sent = exercise([
        {'type': 'http.request', 'body': b'12345', 'more_body': True},
        {'type': 'http.request', 'body': b'67890'}])
    assert reached == []
    assert sent[0]['status'] == 413


def test_declared_size_and_duplicate_lengths_rejected_before_read():
    for headers, code in [([(b'content-length', b'9')], 413),
                          ([(b'content-length', b'-1')], 400),
                          ([(b'content-length', b'1'), (b'content-length', b'1')], 400)]:
        reached, sent = exercise([], headers)
        assert reached == []
        assert sent[0]['status'] == code


def test_rate_gate_bounded_and_body_integrity_preserved():
    reached, sent = exercise([{'type': 'http.request', 'body': b'12345678'}], requests=3)
    assert len(reached) == 2
    assert all(r['body'] == b'12345678' for r in reached)
    assert [s['status'] for s in sent if s['type'] == 'http.response.start'] == [200, 200, 429]
    assert dict(sent[0]['headers'])[b'cache-control'] == b'no-store'


def test_api_auth_and_large_body_are_closed_and_unmutated():
    repo = Repository()
    token = 'test-token-at-least-32-characters-long'
    try:
        with TestClient(create_app(repo, token)) as client:
            assert client.get('/openapi.json').status_code == 401
            response = client.post('/api/accounts', content=b'x' * 131073,
                                   headers={'Authorization': 'Bearer ' + token})
            assert response.status_code == 413
            accounts = client.get('/api/accounts', headers={'Authorization': 'Bearer ' + token})
            assert accounts.json() == []
            assert accounts.headers['x-content-type-options'] == 'nosniff'
    finally:
        repo.close()
