import hmac
import os
from contextlib import asynccontextmanager
from typing import Optional
from fastapi import FastAPI, Depends, Header, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, StrictInt, StrictBool
from .repository import Repository
from .service import TradingService, Rejected
from .http_security import RequestLimits

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
class LifecycleRequest(StrictModel):
    request_key: str
    symbol: str
    right: str

class AutomationRun(StrictModel):
    """A run accepts no signals, prices, account override or risk bypass flags."""
    pass

def create_app(repository=None, token=None, market_data_provider=None):
    configured_token = token if token is not None else os.getenv('OPTIONS_API_TOKEN', '')
    @asynccontextmanager
    async def lifespan(app):
        if len(configured_token) < 24:
            raise RuntimeError('Set OPTIONS_API_TOKEN to a random value of at least 24 characters')
        if os.getenv('TRADING_MODE','paper') != 'paper' or os.getenv('ENABLE_LIVE','false').lower() != 'false':
            raise RuntimeError('Live execution is hard locked; only paper mode is permitted')
        app.state.repository = repository or Repository(os.getenv('DATABASE_URL','sqlite:///options_demo.db'))
        app.state.service = TradingService(app.state.repository)
        from .market_data import from_environment, DisabledMarketData
        app.state.market_data = (market_data_provider if market_data_provider is not None else
            DisabledMarketData() if os.getenv('OAT_MARKET_RUNTIME_ROLE') == 'api_cache_only' else from_environment())
        yield
        if repository is None:
            app.state.repository.close()
    app = FastAPI(title='Options AI Trader — synthetic paper only', version='1.0.0-rc.2', lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(RequestLimits)
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
        return {'status':'ok','version':'1.0.0-rc.2','mode':'paper','broker':'mock','live_enabled':False,'market_data':'synthetic','external_analysis_enabled':False}
    secured = [Depends(auth)]
    from .market_data_api import install_market_data_routes
    install_market_data_routes(app, secured, service, lambda: app.state.market_data)
    from .market_runtime_api import install_market_runtime_routes
    install_market_runtime_routes(app, secured, service)
    @app.get('/api/readiness',dependencies=secured)
    def readiness(s=Depends(service)):
        from .monitoring import readiness as inspect
        try:
            return inspect(s)
        except Exception:
            return JSONResponse(status_code=503, content={'api_ready': False, 'database_ready': False,
                'live_enabled': False, 'detail': 'Readiness unavailable; no entry authority'})
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
    @app.post('/api/accounts/{account_id}/mock-option-quotes/refresh',dependencies=secured)
    def refresh_option_quotes(account_id: str,body: AutomationRun,s=Depends(service)):
        from .automation import fixture_quotes
        with s.repo.transaction() as db:
            s.account(db,account_id)
            contracts = db.all('SELECT * FROM positions WHERE account_id=?',(account_id,))
            symbols = sorted({p['symbol'] for p in contracts})
            quotes = []
            for symbol in symbols:
                if not s.market_valid(db,account_id,symbol):
                    raise Rejected('Refresh the synthetic stock observation before option marks')
                quotes += fixture_quotes(symbol,s.now(),contracts)
            for q in quotes:
                s.record_option_mark(db,account_id,q.symbol,q.right,q.expiry.isoformat(),round(q.strike*100),round(q.bid*100),round(q.ask*100),q.timestamp)
            s.audit(db,account_id,'EXPLICIT_MOCK_OPTION_REFRESH',{'quotes':len(quotes),'source':'synthetic_fixture'})
            return {'quotes_refreshed':len(quotes),'source':'synthetic_fixture','account_reconciled':False,'live_enabled':False}
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
    @app.get('/api/accounts/{account_id}/decisions',dependencies=secured)
    def decisions(account_id: str,s=Depends(service)):
        return s.rows(account_id,'decision_snapshots')
    @app.get('/api/accounts/{account_id}/lifecycle',dependencies=secured)
    def lifecycle(account_id: str,s=Depends(service)):
        return s.rows(account_id,'lifecycle_intents')
    def lifecycle_inputs(s, account_id, symbol):
        from .worker import fixture_bars
        from .automation import fixture_quotes
        contracts = s.rows(account_id,'positions') + s.rows(account_id,'orders')
        now = s.now()
        return fixture_bars(symbol,now),fixture_quotes(symbol,now,contracts)
    @app.post('/api/accounts/{account_id}/reversal',dependencies=secured)
    def reversal(account_id: str,body: LifecycleRequest,s=Depends(service)):
        from .lifecycle import request_reversal
        bars,quotes = lifecycle_inputs(s,account_id,body.symbol)
        return request_reversal(s,account_id,body.request_key,body.symbol,body.right,bars,quotes)
    @app.post('/api/accounts/{account_id}/reversal/{intent_id}/advance',dependencies=secured)
    def advance(account_id: str,intent_id: str,body: AutomationRun,s=Depends(service)):
        from .lifecycle import advance_reversal
        intents = s.rows(account_id,'lifecycle_intents')
        intent = next((i for i in intents if i['id']==intent_id and i['kind']=='REVERSAL'),None)
        if intent is None:
            raise Rejected('Unknown account reversal')
        bars,quotes = lifecycle_inputs(s,account_id,intent['symbol'])
        return advance_reversal(s,account_id,intent_id,bars,quotes)
    @app.post('/api/accounts/{account_id}/scaling',dependencies=secured)
    def scaling(account_id: str,body: LifecycleRequest,s=Depends(service)):
        from .lifecycle import request_scaling
        bars,quotes = lifecycle_inputs(s,account_id,body.symbol)
        return request_scaling(s,account_id,body.request_key,body.symbol,body.right,bars,quotes)
    @app.get('/api/research/demo',dependencies=secured)
    def research_demo():
        from .research import synthetic_research_demo
        return synthetic_research_demo()
    @app.get('/api/accounts/{account_id}/research/{symbol}',dependencies=secured)
    def research_workbench(account_id: str,symbol: str,s=Depends(service)):
        from .research_workbench import inspect_workbench
        return inspect_workbench(s,account_id,symbol)
    @app.post('/api/accounts/{account_id}/research/{symbol}/snapshot',dependencies=secured)
    def research_snapshot(account_id: str,symbol: str,body: AutomationRun,s=Depends(service)):
        from .research_workbench import snapshot_workbench
        return snapshot_workbench(s,account_id,symbol)
    @app.get('/api/accounts/{account_id}/research/{symbol}/snapshots',dependencies=secured)
    def research_snapshot_list(account_id: str,symbol: str,s=Depends(service)):
        from .research_workbench import list_workbench_snapshots
        return list_workbench_snapshots(s,account_id,symbol)
    @app.get('/api/accounts/{account_id}/research/{symbol}/snapshots/{snapshot_id}/replay',dependencies=secured)
    def research_replay(account_id: str,symbol: str,snapshot_id: str,s=Depends(service)):
        from .research_workbench import replay_workbench
        return replay_workbench(s,account_id,symbol,snapshot_id)
    @app.post('/api/accounts/{account_id}/research/{symbol}/snapshots/{snapshot_id}/observations',dependencies=secured)
    def research_observation(account_id: str,symbol: str,snapshot_id: str,body: AutomationRun,s=Depends(service)):
        from .research_workbench import capture_workbench_observation
        return capture_workbench_observation(s,account_id,symbol,snapshot_id)
    @app.get('/api/accounts/{account_id}/analysis/{symbol}',dependencies=secured)
    def analysis(account_id: str,symbol: str,s=Depends(service)):
        from .analysis_service import inspect_analysis
        return inspect_analysis(s,account_id,symbol)
    @app.post('/api/accounts/{account_id}/analysis/{symbol}/snapshot',dependencies=secured)
    def analysis_snapshot(account_id: str,symbol: str,body: AutomationRun,s=Depends(service)):
        from .analysis_service import snapshot_analysis
        return snapshot_analysis(s,account_id,symbol)
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
