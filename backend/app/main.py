import hmac
import os
from contextlib import asynccontextmanager
from typing import Optional
from fastapi import FastAPI, Depends, Header, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, StrictInt, StrictBool
from .repository import Repository
from .service import TradingService, Rejected

class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid')
class AccountCreate(StrictModel):
    name: str
    equity_cents: StrictInt = 1000000
class WatchCreate(StrictModel):
    symbol: str
    enabled: StrictBool = False
class WatchChange(StrictModel):
    enabled: StrictBool
class MarketObservation(StrictModel):
    symbol: str
    available: StrictBool = True
class OrderCreate(StrictModel):
    request_key: str
    symbol: str
    right: str
    expiry: str
    strike_cents: StrictInt
    side: str
    quantity: StrictInt
    limit_cents: StrictInt
class FillCreate(StrictModel):
    fill_id: str
    quantity: StrictInt
    price_cents: StrictInt
class StopCreate(StrictModel):
    account_id: Optional[str] = None
class AutomationRun(StrictModel):
    """A run accepts no signals, prices, account override or risk bypass flags."""
    pass

def create_app(repository=None, token=None):
    configured_token = token if token is not None else os.getenv('OPTIONS_API_TOKEN', '')
    @asynccontextmanager
    async def lifespan(app):
        if len(configured_token) < 24:
            raise RuntimeError('Set OPTIONS_API_TOKEN to a random value of at least 24 characters')
        if os.getenv('TRADING_MODE','paper') != 'paper' or os.getenv('ENABLE_LIVE','false').lower() != 'false':
            raise RuntimeError('Live execution is hard locked; only paper mode is permitted')
        app.state.repository = repository or Repository(os.getenv('DATABASE_URL','sqlite:///options_demo.db'))
        app.state.service = TradingService(app.state.repository)
        yield
        if repository is None:
            app.state.repository.close()
    app = FastAPI(title='Options AI Trader — synthetic paper only', version='0.4.0', lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    def auth(authorization: Optional[str] = Header(default=None)):
        if len(configured_token) < 24 or not authorization or not hmac.compare_digest(authorization.encode('utf-8'), ('Bearer '+configured_token).encode('utf-8')):
            raise HTTPException(401, 'Valid API bearer token required')
    def service():
        return app.state.service
    @app.exception_handler(Rejected)
    async def rejected(request, exc):
        return JSONResponse(status_code=409,content={'detail':str(exc)})
    @app.get('/health')
    def health():
        return {'status':'ok','version':'0.4.0','mode':'paper','broker':'mock','live_enabled':False,'market_data':'synthetic','external_analysis_enabled':False}
    secured = [Depends(auth)]
    @app.get('/openapi.json',dependencies=secured,include_in_schema=False)
    def protected_schema():
        return app.openapi()
    @app.get('/docs',dependencies=secured,include_in_schema=False)
    def protected_docs():
        from fastapi.openapi.docs import get_swagger_ui_html
        return get_swagger_ui_html(openapi_url='/openapi.json',title=app.title)
    @app.get('/api/accounts',dependencies=secured)
    def accounts(s=Depends(service)):
        return s.list_accounts()
    @app.post('/api/accounts',dependencies=secured,status_code=201)
    def create_account(body: AccountCreate,s=Depends(service)):
        return s.create_account(body.name,body.equity_cents)
    @app.get('/api/accounts/{account_id}/status',dependencies=secured)
    def status(account_id: str,s=Depends(service)):
        return s.status(account_id)
    @app.post('/api/accounts/{account_id}/mock-market-data',dependencies=secured)
    def market_data(account_id: str,body: MarketObservation,s=Depends(service)):
        return s.mock_market_data(account_id,body.symbol,body.available)
    @app.get('/api/accounts/{account_id}/risk',dependencies=secured)
    def risk(account_id: str,s=Depends(service)):
        with s.repo.transaction() as db:
            return s.account(db,account_id)['config']
    @app.put('/api/accounts/{account_id}/risk',dependencies=secured)
    def update_risk(account_id: str,body: dict,s=Depends(service)):
        return s.configure(account_id,body)['config']
    @app.get('/api/accounts/{account_id}/watchlist',dependencies=secured)
    def watchlist(account_id: str,s=Depends(service)):
        return s.rows(account_id,'watchlist')
    @app.post('/api/accounts/{account_id}/watchlist',dependencies=secured)
    def watch(account_id: str,body: WatchCreate,s=Depends(service)):
        return s.watch(account_id,body.symbol,body.enabled)
    @app.patch('/api/accounts/{account_id}/watchlist/{symbol}',dependencies=secured)
    def toggle_watch(account_id: str,symbol: str,body: WatchChange,s=Depends(service)):
        return s.watch(account_id,symbol,body.enabled)
    @app.delete('/api/accounts/{account_id}/watchlist/{symbol}',dependencies=secured)
    def remove_watch(account_id: str,symbol: str,s=Depends(service)):
        s.remove_watch(account_id,symbol)
        return {'removed':True}
    @app.get('/api/accounts/{account_id}/orders',dependencies=secured)
    def orders(account_id: str,s=Depends(service)):
        return s.rows(account_id,'orders')
    @app.post('/api/accounts/{account_id}/orders',dependencies=secured)
    def submit(account_id: str,body: OrderCreate,s=Depends(service)):
        return s.submit(account_id,body.model_dump())
    @app.post('/api/accounts/{account_id}/orders/{order_id}/mock-fill',dependencies=secured)
    def fill(account_id: str,order_id: str,body: FillCreate,s=Depends(service)):
        return s.fill(account_id,order_id,body.fill_id,body.quantity,body.price_cents)
    @app.post('/api/accounts/{account_id}/orders/{order_id}/cancel',dependencies=secured)
    def cancel(account_id: str,order_id: str,s=Depends(service)):
        return s.cancel(account_id,order_id)
    @app.get('/api/accounts/{account_id}/positions',dependencies=secured)
    def positions(account_id: str,s=Depends(service)):
        return s.rows(account_id,'positions')
    @app.get('/api/accounts/{account_id}/audit',dependencies=secured)
    def audit(account_id: str,s=Depends(service)):
        return s.rows(account_id,'audit')
    @app.get('/api/accounts/{account_id}/performance',dependencies=secured)
    def performance(account_id: str,s=Depends(service)):
        return s.performance(account_id)
    @app.get('/api/accounts/{account_id}/opportunities',dependencies=secured)
    def opportunities(account_id: str,s=Depends(service)):
        from .worker import opportunities_for
        return opportunities_for(s,account_id)
    @app.post('/api/accounts/{account_id}/automation/run',dependencies=secured)
    def automation_run(account_id: str,body: AutomationRun,s=Depends(service)):
        from .automation import run_account
        with s.repo.transaction() as db:
            s.account(db,account_id)
        return run_account(s,account_id)
    @app.post('/api/emergency-stop',dependencies=secured)
    def stop(body: StopCreate,s=Depends(service)):
        return s.stop(body.account_id)
    @app.post('/api/accounts/{account_id}/disconnect',dependencies=secured)
    def disconnect(account_id: str,s=Depends(service)):
        s.disconnect(account_id)
        return {'state_known':False}
    @app.post('/api/accounts/{account_id}/reconcile',dependencies=secured)
    def reconcile(account_id: str,s=Depends(service)):
        return s.reconcile(account_id)
    return app

app = create_app()
