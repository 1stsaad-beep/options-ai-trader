"""Independent durable notification inbox. No trading database or outbound IO.

One configured endpoint/token belongs to one originating alert journal. An ACK
means this inbox committed the event, not that a person read it or a channel
delivered a message. Deploy behind HTTPS on a separately authorized host.
"""
import argparse
import asyncio
from contextlib import contextmanager
import hmac
import json
import os
from pathlib import Path
import sqlite3
import stat

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from .alert_webhook import PATH, Webhook, from_file, strict_json
from .observed_alert_delivery import VERSION, ACK
from .observed_paper import canonical, digest
from .observed_paper_alerts import decode, integer, ZERO
from .observed_paper_store import LedgerConflict
from .paper_settlement import stamp

MAX_BYTES = 8192
BODY_SECONDS = 2
SCHEMA = '''
CREATE TABLE receiver_identity (singleton INTEGER PRIMARY KEY CHECK(singleton=1), target_hash TEXT NOT NULL);
CREATE TABLE receiver_events (sequence INTEGER PRIMARY KEY, event_hash TEXT NOT NULL,
    previous_hash TEXT NOT NULL, idempotency_key TEXT NOT NULL UNIQUE, payload TEXT NOT NULL);
CREATE TABLE receiver_head (singleton INTEGER PRIMARY KEY CHECK(singleton=1), sequence INTEGER NOT NULL, event_hash TEXT NOT NULL);
CREATE TRIGGER receiver_events_no_update BEFORE UPDATE ON receiver_events BEGIN SELECT RAISE(ABORT, 'Immutable alert'); END;
CREATE TRIGGER receiver_events_no_delete BEFORE DELETE ON receiver_events BEGIN SELECT RAISE(ABORT, 'Immutable alert'); END;
CREATE TRIGGER receiver_identity_no_update BEFORE UPDATE ON receiver_identity BEGIN SELECT RAISE(ABORT, 'Immutable identity'); END;
CREATE TRIGGER receiver_identity_no_delete BEFORE DELETE ON receiver_identity BEGIN SELECT RAISE(ABORT, 'Immutable identity'); END;
'''


class ReceiverConflict(ValueError):
    pass


def envelope(value, target):
    try:
        if (not isinstance(value, dict) or set(value) != {'contract','idempotencyKey','event','externalOrder'}
                or value['contract'] != VERSION or value['externalOrder'] is not False
                or not isinstance(value['event'], dict) or len(canonical(value).encode()) > MAX_BYTES):
            raise ValueError()
        event = value['event']
        original = {k: v for k, v in event.items() if k != 'eventHash'}
        if decode({'sequence': event['sequence'], 'payload': canonical(original),
                   'digest': event['eventHash'], 'previous_hash': event['previousHash']}) != event:
            raise ValueError()
        if value['idempotencyKey'] != digest([VERSION, target, event['sequence'], event['eventHash']]):
            raise ValueError()
        return event
    except (ValueError, TypeError, KeyError, OverflowError, RecursionError, LedgerConflict):
        raise ValueError('Invalid notification envelope') from None


class ReceiverStore:
    def __init__(self, path, target):
        self.path = Path(path).absolute()
        self.target = target

    def _private_file(self):
        info = self.path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077:
            raise OSError('Receiver store unavailable')

    @contextmanager
    def transaction(self):
        self._private_file()
        db = sqlite3.connect(self.path.as_uri() + '?mode=rw', uri=True, timeout=1)
        db.row_factory = sqlite3.Row
        try:
            db.execute('PRAGMA synchronous=FULL')
            db.execute('BEGIN IMMEDIATE')
            identity = db.execute('SELECT * FROM receiver_identity').fetchall()
            if len(identity) != 1 or identity[0]['singleton'] != 1 or identity[0]['target_hash'] != self.target:
                raise ReceiverConflict('Receiver identity requires review')
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def initialize(self):
        # Explicit creation only, O_EXCL prevents adopting/replacing an existing
        # database or symlink. Parent directory is operator-owned and trusted.
        descriptor = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        os.close(descriptor)
        db = sqlite3.connect(self.path)
        try:
            db.execute('PRAGMA synchronous=FULL')
            db.executescript('BEGIN IMMEDIATE;\n' + SCHEMA)
            db.execute('INSERT INTO receiver_identity VALUES(1,?)', (self.target,))
            db.execute('INSERT INTO receiver_head VALUES(1,0,?)', (ZERO,))
            db.commit()
        except BaseException:
            db.rollback()
            # Preserve a failed original for review; never silently reset it.
            raise
        finally:
            db.close()

    def _verify(self, db, after=0, limit=0):
        sequence = 0; previous = ZERO; active = []; detected = None; selected = []
        try:
            for row in db.execute('SELECT * FROM receiver_events ORDER BY sequence'):
                sequence += 1
                value = strict_json(row['payload'])
                event = envelope(value, self.target)
                if (row['payload'] != canonical(value) or event['sequence'] != sequence
                        or row['sequence'] != sequence or row['event_hash'] != event['eventHash']
                        or row['previous_hash'] != previous or event['previousHash'] != previous
                        or row['idempotency_key'] != value['idempotencyKey']
                        or event['raised'] != sorted(set(event['active']) - set(active))
                        or event['resolved'] != sorted(set(active) - set(event['active']))
                        or detected is not None and stamp(event['detectedAt']) < detected):
                    raise ValueError()
                previous = event['eventHash']; active = event['active']; detected = stamp(event['detectedAt'])
                if sequence > after and len(selected) < limit:
                    selected.append(event)
            heads = db.execute('SELECT * FROM receiver_head').fetchall()
            if len(heads) != 1 or dict(heads[0]) != {'singleton': 1, 'sequence': sequence, 'event_hash': previous}:
                raise ValueError()
        except (ValueError, TypeError, KeyError, OverflowError, RecursionError):
            raise ReceiverConflict('Receiver journal requires review') from None
        return sequence, previous, active, detected, selected

    def receive(self, value, key):
        event = envelope(value, self.target)
        if key != value['idempotencyKey']:
            raise ValueError('Invalid notification key')
        payload = canonical(value)
        with self.transaction() as db:
            sequence, previous, active, detected, _ = self._verify(db)
            saved = db.execute('SELECT payload FROM receiver_events WHERE sequence=?', (event['sequence'],)).fetchone()
            if saved:
                if saved['payload'] != payload:
                    raise ReceiverConflict('Conflicting notification')
            else:
                if (event['sequence'] != sequence + 1 or event['previousHash'] != previous
                        or event['raised'] != sorted(set(event['active']) - set(active))
                        or event['resolved'] != sorted(set(active) - set(event['active']))
                        or detected is not None and stamp(event['detectedAt']) < detected):
                    raise ReceiverConflict('Notification sequence requires review')
                db.execute('INSERT INTO receiver_events VALUES(?,?,?,?,?)',
                    (event['sequence'], event['eventHash'], previous, key, payload))
                db.execute('UPDATE receiver_head SET sequence=?,event_hash=? WHERE singleton=1',
                    (event['sequence'], event['eventHash']))
        # Context exit committed successfully before an ACK can leave this call.
        return {'contract': ACK, 'sequence': event['sequence'], 'eventHash': event['eventHash']}

    def page(self, after=0, limit=25):
        integer(after); integer(limit, 1, 25)
        with self.transaction() as db:
            sequence, previous, _, _, events = self._verify(db, after, limit)
            if after > sequence:
                raise ValueError('Invalid receiver cursor')
        cursor = events[-1]['sequence'] if events else after
        return {'contract': 'independent-alert-receiver-v1', 'externalOrder': False,
                'sequence': sequence, 'eventHash': previous, 'after': after,
                'nextAfter': cursor, 'hasMore': cursor < sequence, 'events': events}


def create_app(store, token):
    # Reuse the explicit receiver token validator; do not discover credentials.
    Webhook('https://receiver.example' + PATH, token)
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    def response(body, status=200):
        return JSONResponse(body, status_code=status, headers={'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'})

    def authorized(request):
        values = request.headers.getlist('authorization')
        return len(values) == 1 and hmac.compare_digest(values[0].encode(), ('Bearer ' + token).encode())

    @app.api_route(PATH, methods=['GET', 'POST'])
    async def receive(request: Request):
        if not authorized(request):
            return response({'error': 'UNAUTHORIZED'}, 401)
        try:
            if request.method == 'GET':
                if set(request.query_params) - {'after','limit'} or any(len(request.query_params.getlist(k)) != 1 for k in request.query_params):
                    raise ValueError()
                value = await run_in_threadpool(store.page, int(request.query_params.get('after','0')),
                                                int(request.query_params.get('limit','25')))
                return response(value)
            if request.query_params:
                raise ValueError()
            lengths = request.headers.getlist('content-length')
            if len(lengths) > 1 or lengths and (not lengths[0].isdigit() or int(lengths[0]) > MAX_BYTES):
                return response({'error': 'REQUEST_TOO_LARGE'}, 413)
            if (request.headers.get('content-type') != 'application/json'
                    or request.headers.get('content-encoding') is not None
                    or len(request.headers.getlist('idempotency-key')) != 1):
                raise ValueError()
            async def read():
                body = bytearray()
                async for chunk in request.stream():
                    if len(body) + len(chunk) > MAX_BYTES:
                        raise OverflowError()
                    body.extend(chunk)
                return bytes(body)
            raw = await asyncio.wait_for(read(), BODY_SECONDS)
            if lengths and int(lengths[0]) != len(raw):
                raise ValueError()
            value = strict_json(raw.decode('utf-8'))
            ack = await run_in_threadpool(store.receive, value, request.headers['idempotency-key'])
            return response(ack)
        except ReceiverConflict:
            return response({'error': 'RECEIVER_REVIEW_REQUIRED'}, 409)
        except OverflowError:
            return response({'error': 'REQUEST_TOO_LARGE'}, 413)
        except (TimeoutError, asyncio.TimeoutError):
            return response({'error': 'REQUEST_TIMEOUT'}, 408)
        except (ValueError, TypeError, KeyError, RecursionError):
            return response({'error': 'INVALID_NOTIFICATION'}, 400)
        except Exception:
            return response({'error': 'RECEIVER_UNAVAILABLE'}, 503)
    return app


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--initialize', action='store_true')
    group.add_argument('--healthcheck', action='store_true')
    args = parser.parse_args(argv)
    if os.getenv('TRADING_MODE','paper') != 'paper' or os.getenv('ENABLE_LIVE','false').lower() != 'false':
        return 1
    if os.getenv('OAT_ALERT_INBOX_APPROVAL') != 'receiver_only_approved':
        print(json.dumps({'component': 'alert_receiver', 'state': 'DISABLED', 'externalOrder': False}), flush=True)
        return 0
    try:
        config = from_file(os.environ['OAT_ALERT_RECEIVER_FILE'])
        store = ReceiverStore(os.environ['OAT_ALERT_INBOX_FILE'], config.target_hash)
        if args.initialize:
            store.initialize()
        else:
            store.page(limit=1)  # Existing schema/identity/chain must be valid.
        if args.initialize or args.healthcheck:
            return 0
        import uvicorn
        uvicorn.run(create_app(store, config.token), host='127.0.0.1', port=8081,
                    access_log=False, log_level='critical')
        return 0
    except Exception:
        print(json.dumps({'component': 'alert_receiver', 'state': 'UNAVAILABLE', 'externalOrder': False}), flush=True)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
