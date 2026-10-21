"""Entry point (Railway): python -m oat_agent.service
Stages 1-2 run the code layer and data feed only (guards, exits, cap, kill switch, control API). Bars/indicators/model come in
stages 2-3; no entry is ever made by stage 1 code."""
from __future__ import annotations
import datetime as dt
import logging
import os
import threading
import time
from . import redact
from .bar_feed import BarFeed
from .broker import AlpacaPaper
from .data import AlpacaData
from .shadow import ShadowLedger
from .code_layer import CodeLayer
from .config import OwnerSettings
from .control_api import serve
from .executor import Executor
from .store import Store


def utcnow():
    return dt.datetime.now(dt.timezone.utc)


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    redact.install()
    log = logging.getLogger("oat.service")
    settings = OwnerSettings.from_env()
    store = Store(os.environ.get("OAT_DB_PATH", "/data/agent.db"))
    broker = AlpacaPaper()
    data = AlpacaData()
    master = store.get("shadow_master_seed")
    if master is None:                                   # generated once, stored and logged (spec §11: seed logged)
        import secrets
        master = secrets.token_hex(16)
        store.put("shadow_master_seed", master)
        store.event(utcnow(), "shadow_master_seed", {"master_seed": master})
    x = Executor(broker, store, settings, utcnow, shadow=ShadowLedger(store, data, master))
    layer = CodeLayer(x, store, settings, utcnow)
    feed = BarFeed(data, store, broker, layer, utcnow)
    from .atlas_client import AtlasClient, JournalOutbox, size_tools_from_env
    from .net import Http
    size_tools, _ = size_tools_from_env()
    outbox = JournalOutbox(store, AtlasClient(Http(os.environ.get("ATLAS_BASE_URL"))), live=os.environ.get("OAT_ATLAS_LIVE") == "1")
    srv = serve(store, x)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    log.info("agent service started (paper only)")
    while True:
        try:
            now = utcnow()
            if x.status(now).is_open:
                x.snapshot()
                x.reconcile()
                feed.poll()
                layer.tick()
            outbox.flush()
        except Exception as e:  # noqa: BLE001 — one bad cycle never stops the loop
            log.error("cycle failed: %s", e)
        time.sleep(5)


if __name__ == "__main__":
    main()
