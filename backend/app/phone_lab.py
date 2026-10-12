"""Isolated Lab19 connectivity exercise, never a market-price simulator.

The production API/runtime remain unchanged. This entrypoint only accepts the
phone-lab database, forces DisabledMarketData, and rejects non-runtime writes.
"""
from contextlib import asynccontextmanager
import os
import re
from urllib.parse import urlsplit

from fastapi.responses import JSONResponse
from .main import create_app
from .market_data import DisabledMarketData
from . import market_runtime as runtime

ACCOUNT_NAMES = ('Phone Lab A — Mock', 'Phone Lab B — Mock')


def validate_environment():
    url = urlsplit(os.getenv('DATABASE_URL', ''))
    if (os.getenv('OAT_PHONE_LAB') != 'isolated_mock_only'
            or os.getenv('TRADING_MODE') != 'paper'
            or os.getenv('BROKER_PROVIDER') != 'mock'
            or os.getenv('ENABLE_LIVE') != 'false'
            or url.scheme != 'postgresql' or url.hostname != 'postgres'
            or url.username != 'phone_lab' or url.path != '/options_phone_lab'
            or url.query or url.fragment
            or any(value for key, value in os.environ.items()
                   if key.startswith(('OAT_ALPACA_', 'APCA_', 'ALPACA_', 'IBKR_')))):
        raise RuntimeError('PHONE_LAB_ISOLATION_REQUIRED')


def seed_accounts(service):
    """Seed only an empty, isolated DB; never reset account controls on restart."""
    accounts = service.list_accounts()
    if accounts and (len(accounts) != 2 or {a['name'] for a in accounts} != set(ACCOUNT_NAMES)):
        raise RuntimeError('PHONE_LAB_EXISTING_DATA_REFUSED')
    if not accounts:
        for index, name in enumerate(ACCOUNT_NAMES):
            account = service.create_account(name)['id']
            service.watch(account, ('AAPL', 'MSFT')[index], True)
            runtime.configure(service, account, expected_version=0, enabled=index == 0,
                              strategies={'breakout': index == 0, 'pullback': False})
    with service.repo.transaction() as db:
        for account in service.list_accounts_in(db):
            runtime.event_in(db, account['id'], 'phone-lab-ready-v1', service.now(),
                             'PHONE_LAB_READY', {'synthetic_test': True, 'provider_connected': False,
                                                 'prices_generated': False})


def build_app(repository=None, token=None):
    """Injected repository is for tests; public factory validates PostgreSQL."""
    app = create_app(repository=repository, token=token, market_data_provider=DisabledMarketData())
    original_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(application):
        async with original_lifespan(application):
            seed_accounts(application.state.service)
            yield

    app.router.lifespan_context = lifespan

    @app.middleware('http')
    async def runtime_only_writes(request, call_next):
        path = request.url.path
        allowed = (request.method == 'GET'
                   or request.method == 'PUT' and re.fullmatch(r'/api/accounts/[^/]+/market-runtime/config', path)
                   or request.method == 'POST' and re.fullmatch(r'/api/accounts/[^/]+/market-runtime/events/[^/]+/ack', path))
        if not allowed:
            return JSONResponse({'detail': 'PHONE_LAB_RUNTIME_CONTROLS_ONLY'}, status_code=403)
        response = await call_next(request)
        response.headers['Cache-Control'] = 'no-store'
        return response

    @app.get('/phone-lab')
    def lab_identity():
        return {'lab': 'Lab19-phone-connectivity', 'mode': 'mock_provider_disabled',
                'provider_connected': False, 'external_orders_enabled': False,
                'virtual_fills_enabled': False}

    return app


def create_phone_app():
    validate_environment()
    return build_app()


if __name__ == '__main__':
    validate_environment()
    # Approval is rejected before the normal worker could read a provider secret.
    from .market_runtime_worker import main
    raise SystemExit(main())
