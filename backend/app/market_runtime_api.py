"""Authenticated local controls/cache reads; never accept keys, prices or orders."""
from fastapi import Depends
from pydantic import BaseModel, ConfigDict, StrictBool, StrictInt
from . import market_runtime as runtime


class RuntimeConfig(BaseModel):
    model_config = ConfigDict(extra='forbid')
    expected_version: StrictInt
    enabled: StrictBool
    strategies: dict[str, StrictBool]


def install_market_runtime_routes(app, secured, service_dependency):
    prefix = '/api/accounts/{account_id}/market-runtime'

    @app.get(prefix + '/status', dependencies=secured)
    def status(account_id: str, s=Depends(service_dependency)):
        return runtime.status(s, account_id)

    @app.put(prefix + '/config', dependencies=secured)
    def configure(account_id: str, body: RuntimeConfig, s=Depends(service_dependency)):
        return runtime.configure(s, account_id, **body.model_dump())

    @app.get(prefix + '/events', dependencies=secured)
    def events(account_id: str, limit: int = 50, before: str | None = None, s=Depends(service_dependency)):
        return runtime.events(s, account_id, limit=limit, before=before)

    @app.post(prefix + '/events/{event_id}/ack', dependencies=secured)
    def acknowledge(account_id: str, event_id: str, s=Depends(service_dependency)):
        return runtime.acknowledge(s, account_id, event_id)
