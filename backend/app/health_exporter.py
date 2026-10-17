"""Separate read-only operational endpoint for an outside-host monitor.

No Repository initialization, migrations, trading routes, provider keys or
outbound IO. A fresh blocked/disabled process is live, not ready to trade.
"""
import argparse
from datetime import datetime, timezone
import hmac
import json
import os
import re
import stat

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from .alert_webhook import strict_json
from .observed_option_replay import iso
from .observed_paper_status import read_status
from .repository import Session
from .runtime_health import heartbeat_valid, readonly_connection

PATH = '/oat/v1/health'
VERSION = 'independent-health-v1'
COMPONENTS = {'worker': 'observed_paper', 'watchdog': 'observed_watchdog', 'delivery': 'observed_alert_delivery'}


def validate_token(token):
    if (not isinstance(token, str) or not 24 <= len(token) <= 256 or not token.isascii()
            or any(ord(c) <= 32 or ord(c) >= 127 for c in token)):
        raise ValueError('Invalid health token')
    return token


def token_file(path):
    descriptor = None
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o007 or info.st_size > 4096:
            raise ValueError()
        with os.fdopen(descriptor, 'r') as source:
            descriptor = None
            value = strict_json(source.read(4097))
        if not isinstance(value, dict) or set(value) != {'token'}:
            raise ValueError()
        return validate_token(value['token'])
    except Exception:
        raise ValueError('Health token file unavailable') from None
    finally:
        if descriptor is not None:
            os.close(descriptor)


def snapshot(url, now, nonce):
    if not isinstance(nonce, str) or re.fullmatch('[a-f0-9]{32}', nonce) is None:
        raise ValueError('Explicit probe nonce required')
    base = {'contract': VERSION, 'nonce': nonce, 'serverTime': iso(now),
            'externalOrder': False, 'executionAllowed': False, 'newEntryAllowed': False}
    try:
        postgres = url.startswith(('postgresql://', 'postgres://'))
        with readonly_connection(url) as connection:
            # All components/budget come from one consistent read-only snapshot.
            connection.execute('BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY' if postgres else 'BEGIN')
            db = Session(connection, postgres)
            sizes = db.all("SELECT length(payload) AS n FROM runtime_health WHERE name IN ('observed_paper','observed_watchdog','observed_alert_delivery')")
            sizes += db.all("SELECT length(payload) AS n FROM observed_paper_data_state WHERE name='budget'")
            if any(row['n'] > 4096 for row in sizes):
                raise ValueError('Operational state requires review')
            operational = read_status(db, now)
            components = {}
            for label, name in COMPONENTS.items():
                row = db.one('SELECT * FROM runtime_health WHERE name=?', (name,))
                fresh = heartbeat_valid(row, name, now)
                payload = json.loads(row['payload']) if fresh else {}
                components[label] = {'fresh': fresh, 'state': payload['state'] if fresh else 'UNAVAILABLE'}
            connection.rollback()
        access = operational['dataAccess']
        return base | {'databaseReadable': True, 'components': components,
                       'workerDiagnostic': operational['diagnosticCode'], 'workerAlerts': operational['alerts'],
                       'dataAccess': {'verified': access['status'] == 'OBSERVED',
                                      'authBlocked': access['authBlocked'],
                                      'backoff': 'DATA_BACKOFF' in operational['alerts'] if access['status'] == 'OBSERVED' else None}}, 200
    except Exception:
        return base | {'databaseReadable': False,
                       'components': {key: {'fresh': False, 'state': 'UNKNOWN'} for key in COMPONENTS},
                       'workerDiagnostic': None, 'workerAlerts': [],
                       'dataAccess': {'verified': False, 'authBlocked': None, 'backoff': None}}, 503


def create_app(url, token, now=None):
    validate_token(token)
    now = now or (lambda: datetime.now(timezone.utc))
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @app.get(PATH)
    async def health(request: Request):
        headers = {'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'}
        values = request.headers.getlist('authorization')
        if len(values) != 1 or not hmac.compare_digest(values[0].encode(), ('Bearer ' + token).encode()):
            return JSONResponse({'error': 'UNAUTHORIZED'}, status_code=401, headers=headers)
        nonces = request.headers.getlist('x-oat-probe')
        if request.query_params or len(nonces) != 1 or re.fullmatch('[a-f0-9]{32}', nonces[0]) is None:
            return JSONResponse({'error': 'INVALID_PROBE'}, status_code=400, headers=headers)
        value, status = await run_in_threadpool(snapshot, url, now(), nonces[0])
        return JSONResponse(value, status_code=status, headers=headers)
    return app


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args(argv)
    if os.getenv('TRADING_MODE', 'paper') != 'paper' or os.getenv('ENABLE_LIVE', 'false').lower() != 'false':
        return 1
    if os.getenv('OAT_HEALTH_EXPORT_APPROVAL') != 'read_only_approved':
        print(json.dumps({'component': 'health_exporter', 'state': 'DISABLED', 'externalOrder': False}), flush=True)
        return 0
    try:
        token = token_file(os.environ['OAT_HEALTH_TOKEN_FILE'])
        url = os.environ['DATABASE_URL']
        if args.check:
            _, status = snapshot(url, datetime.now(timezone.utc), '0' * 32)
            return 0 if status == 200 else 1
        import uvicorn
        uvicorn.run(create_app(url, token), host='127.0.0.1', port=8082, access_log=False, log_level='critical')
        return 0
    except Exception:
        print(json.dumps({'component': 'health_exporter', 'state': 'UNAVAILABLE', 'externalOrder': False}), flush=True)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
