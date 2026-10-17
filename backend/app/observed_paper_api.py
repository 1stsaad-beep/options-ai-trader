"""Owner-authenticated controls; public input can never supply an execution cycle."""
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, StrictInt

from .observed_paper_store import LedgerConflict


class CreateObserved(BaseModel):
    model_config=ConfigDict(extra='forbid')
    id:str
    name:str
    initial_cash_cents:StrictInt=1000000
    source:str='alpaca'


class ControlObserved(BaseModel):
    model_config=ConfigDict(extra='forbid')
    request_key:str
    expected_version:StrictInt
    command:dict


class CreateExperiment(BaseModel):
    model_config=ConfigDict(extra='forbid')
    source:str='alpaca'


def install_observed_paper_routes(app,secured,store_dependency):
    def guarded(operation):
        try: return operation()
        except LedgerConflict as exc: raise HTTPException(409,str(exc)) from None
        except (ValueError,TypeError,KeyError,OverflowError,AttributeError):
            raise HTTPException(422,'Invalid observed-paper input') from None

    @app.get('/api/observed-paper/accounts',dependencies=secured)
    def accounts():
        return {'mode':'observed_market_virtual','externalOrder':False,'accounts':store_dependency().accounts()}

    @app.get('/api/observed-paper/status',dependencies=secured)
    def runtime_status():
        from .observed_paper_status import status
        return status(store_dependency())

    @app.post('/api/observed-paper/accounts',dependencies=secured,status_code=201)
    def create(body:CreateObserved):
        return guarded(lambda:store_dependency().create(body.id,body.name,body.initial_cash_cents,body.source))

    @app.post('/api/observed-paper/experiment',dependencies=secured)
    def experiment(body:CreateExperiment):
        return guarded(lambda:store_dependency().experiment(body.source))

    @app.get('/api/observed-paper/comparison',dependencies=secured)
    def comparison(accounts:str):
        return guarded(lambda:store_dependency().comparison(accounts.split(',')))

    @app.get('/api/observed-paper/accounts/{account}/state',dependencies=secured)
    def state(account:str):
        return guarded(lambda:store_dependency().snapshot(account))

    @app.post('/api/observed-paper/accounts/{account}/control',dependencies=secured)
    def control(account:str,body:ControlObserved):
        if body.command.get('kind') not in {'CONFIGURE','ENABLE','REQUEST_CLOSE','CANCEL_CLOSE','SETTLE'}:
            raise HTTPException(422,'Only explicit virtual account controls are accepted')
        return guarded(lambda:store_dependency().command(account,body.request_key,body.command,expected_version=body.expected_version))

    @app.get('/api/observed-paper/accounts/{account}/events',dependencies=secured)
    def events(account:str,after:int=-1,limit:int=20):
        rows=guarded(lambda:store_dependency().events(account,after,limit))
        return {'account':account,'mode':'observed_market_virtual','events':rows,
                'nextAfter':rows[-1]['version'] if rows else after,'externalOrder':False}

    @app.post('/api/observed-paper/accounts/{account}/reconcile',dependencies=secured)
    def reconcile(account:str):
        return guarded(lambda:store_dependency().snapshot(account,full=True))

    @app.get('/api/observed-paper/accounts/{account}/performance',dependencies=secured)
    def performance(account:str):
        return guarded(lambda:store_dependency().performance(account))

    @app.get('/api/observed-paper/accounts/{account}/valuation',dependencies=secured)
    def valuation(account:str):
        return guarded(lambda:store_dependency().valuation(account))

    @app.get('/api/observed-paper/accounts/{account}/valuation-history',dependencies=secured)
    def valuation_history(account:str,after:int=-1,limit:int=50,through:int|None=None):
        return guarded(lambda:store_dependency().valuation_history(account,after,limit,through))
