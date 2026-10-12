"""Account-scoped observations in a separate namespace, never synthetic marks.

Existing Demo risk, orders, permissions and persistence are not migrated. Basic
options are monitoring-only; the real-market virtual order gate cannot reach the
synthetic submit/fill path or any broker, even if a caller supplies a price.
"""
from datetime import datetime
from typing import Literal
from fastapi import Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict
from .market_data import MarketDataError, MODE, INDICATIVE_REASON, OPTION, symbol
from .service import Rejected
from . import market_data_journal as journal


class VirtualOrderIntent(BaseModel):
    model_config = ConfigDict(extra='forbid')
    symbol: str
    contract: str
    request_key: str


class CaptureObservation(BaseModel):
    model_config = ConfigDict(extra='forbid')
    kind: Literal['stock_snapshot', 'stock_bars', 'option_chain', 'option_bars']
    symbol: str
    request_key: str
    contract: str | None = None
    start: datetime | None = None
    end: datetime | None = None
    timeframe: str | None = None


def scoped_symbol(service, account_id, ticker):
    ticker = symbol(ticker)
    with service.repo.transaction() as db:
        service.account(db, account_id)
        row = db.one('SELECT symbol FROM watchlist WHERE account_id=? AND symbol=?', (account_id, ticker))
        if row is None:
            raise Rejected('Symbol is not in this account watchlist')
    # enabled/verified describe synthetic execution, not real-data entitlement.
    return ticker


def scoped_contract(ticker, contract):
    contract = symbol(contract, option=True)
    root = OPTION.fullmatch(contract)[1]
    if root != ticker and root not in [ticker + str(n) for n in range(1, 10)]:
        raise MarketDataError('OPTION_UNDERLYING_MISMATCH')
    return contract


def account_result(account_id, result):
    # Observations cannot grant execution authority, regardless of provider.
    return {**result, 'account_id': account_id, 'mode': MODE,
            'virtual_fills_enabled': False, 'external_orders_enabled': False}


def install_market_data_routes(app, secured, service_dependency, provider_dependency):
    @app.exception_handler(journal.JournalError)
    async def journal_error(request, exc):
        return JSONResponse(status_code=exc.status, content={'detail': exc.code, 'mode': MODE,
            'synthetic_fallback': False, 'external_orders_enabled': False, 'virtual_fills_enabled': False})

    @app.exception_handler(MarketDataError)
    async def market_data_error(request, exc):
        status = 429 if exc.code == 'DATA_RATE_LIMITED' else 503
        if exc.code.startswith(('INVALID_', 'OPTION_UNDERLYING_')):
            status = 422
        return JSONResponse(status_code=status, content={'detail': exc.code, 'mode': MODE,
            'synthetic_fallback': False, 'external_orders_enabled': False, 'virtual_fills_enabled': False})

    prefix = '/api/accounts/{account_id}/market-data'

    @app.post(prefix + '/observations', dependencies=secured)
    def capture_observation(account_id: str, body: CaptureObservation,
                            s=Depends(service_dependency), p=Depends(provider_dependency)):
        return journal.capture(s, account_id, body.model_dump(), p)

    @app.get(prefix + '/observations', dependencies=secured)
    def list_observations(account_id: str, as_of: datetime | None = None,
                          before_sequence: int | None = None, limit: int = 20, s=Depends(service_dependency)):
        return journal.list_records(s, account_id, as_of=as_of, before_sequence=before_sequence, limit=limit)

    @app.get(prefix + '/observations/{observation_id}', dependencies=secured)
    def replay_observation(account_id: str, observation_id: str, as_of: datetime | None = None,
                            s=Depends(service_dependency)):
        return journal.replay(s, account_id, observation_id, as_of=as_of)

    @app.get(prefix + '/status', dependencies=secured)
    def data_status(account_id: str, s=Depends(service_dependency), p=Depends(provider_dependency)):
        watch = s.rows(account_id, 'watchlist')
        return {'schema_version': 1, **account_result(account_id, p.status()),
                'symbols': sorted(row['symbol'] for row in watch),
                'execution_block_reason': INDICATIVE_REASON,
                'synthetic_demo_separate': True, 'virtual_execution_state': 'ANALYSIS_ONLY',
                'watchlist_enabled_field': 'synthetic_permission_only'}

    @app.get(prefix + '/stocks/{ticker}/snapshot', dependencies=secured)
    def stock_snapshot(account_id: str, ticker: str, s=Depends(service_dependency), p=Depends(provider_dependency)):
        ticker = scoped_symbol(s, account_id, ticker)
        return account_result(account_id, p.stock_snapshot(ticker))

    @app.get(prefix + '/stocks/{ticker}/bars', dependencies=secured)
    def stock_bars(account_id: str, ticker: str, start: datetime, end: datetime, timeframe: str = '1Day',
                   s=Depends(service_dependency), p=Depends(provider_dependency)):
        ticker = scoped_symbol(s, account_id, ticker)
        return account_result(account_id, p.stock_bars(ticker, start, end, timeframe))

    @app.get(prefix + '/options/{ticker}/chain', dependencies=secured)
    def option_chain(account_id: str, ticker: str, s=Depends(service_dependency), p=Depends(provider_dependency)):
        ticker = scoped_symbol(s, account_id, ticker)
        return account_result(account_id, p.option_chain(ticker))

    @app.get(prefix + '/options/{ticker}/bars', dependencies=secured)
    def option_bars(account_id: str, ticker: str, contract: str, start: datetime, end: datetime, timeframe: str = '1Day',
                    s=Depends(service_dependency), p=Depends(provider_dependency)):
        ticker = scoped_symbol(s, account_id, ticker)
        contract = scoped_contract(ticker, contract)
        return account_result(account_id, p.option_bars(contract, start, end, timeframe))

    @app.post(prefix + '/virtual-orders', dependencies=secured)
    def virtual_order(account_id: str, body: VirtualOrderIntent, s=Depends(service_dependency)):
        ticker = scoped_symbol(s, account_id, body.symbol)
        scoped_contract(ticker, body.contract)
        if not 1 <= len(body.request_key) <= 128:
            raise Rejected('Invalid virtual request key')
        # No accepted receipt and no call to s.submit/s.fill: a rejection is not
        # an order. Repeated rejections may be audited; never duplicate fills.
        with s.repo.transaction() as db:
            s.audit(db, account_id, 'REAL_MARKET_VIRTUAL_ORDER_BLOCKED', {
                'mode': MODE, 'symbol': ticker, 'reason': INDICATIVE_REASON})
        return JSONResponse(status_code=409, content={'detail': INDICATIVE_REASON,
            'account_id': account_id, 'mode': MODE, 'accepted': False,
            'virtual_fills_enabled': False, 'external_orders_enabled': False,
            'required': 'Qualified fresh actual option quotes, contract metadata and a separately accepted local execution integration'})
