"""Entry point (Railway): python -m oat_agent.service
Stage 1 runs the code layer only (guards, exits, cap, kill switch, control API). Bars/indicators/model come in
stages 2-3; no entry is ever made by stage 1 code."""
from __future__ import annotations
import datetime as dt
import logging
import os
import threading
import time
from . import redact
from .broker import AlpacaPaper
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
    x = Executor(broker, store, settings, utcnow)
    layer = CodeLayer(x, store, settings, utcnow)
    srv = serve(store, x)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    log.info("agent service started (paper only)")
    while True:
        try:
            now = utcnow()
            if x.status(now).is_open:
                x.snapshot()
                layer.tick()
        except Exception as e:  # noqa: BLE001 — one bad cycle never stops the loop
            log.error("cycle failed: %s", e)
        time.sleep(5)


if __name__ == "__main__":
    main()
