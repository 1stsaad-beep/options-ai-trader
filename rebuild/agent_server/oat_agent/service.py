"""Entry point (Railway): python -m oat_agent.service
The code layer (guards, exits, cap, kill switch) and the bar feed always run. The model layer (Haiku watcher + strong
model on the ET schedule) runs ONLY after the owner turns it on (POST /agent/on); it is off on a fresh install."""
from __future__ import annotations
import datetime as dt
import logging
import os
import secrets
import threading
import time
from . import redact
from .agent import Agent
from .agent_tools import AgentTools
from .atlas_client import AtlasClient, JournalOutbox, size_tools_from_env
from .bar_feed import BarFeed
from .broker import AlpacaPaper
from .code_layer import CodeLayer
from .config import OwnerSettings
from .control_api import serve
from .data import AlpacaData
from .dossiers import Dossiers
from .events import Events
from .executor import Executor
from .llm import Claude
from .net import Http
from .outcomes import Outcomes
from .shadow import ShadowLedger
from .store import Store
from .tools import ToolBox


def utcnow():
    return dt.datetime.now(dt.timezone.utc)


def build(env=None, store=None, broker=None, data=None, http=None, clock=utcnow):
    env = os.environ if env is None else env
    settings = OwnerSettings.from_env(env)
    store = store or Store(env.get("OAT_DB_PATH", "/data/agent.db"))
    http = http or Http(env.get("ATLAS_BASE_URL"))
    broker = broker or AlpacaPaper(http=http, env=env)
    data = data or AlpacaData(http=http, env=env)
    master = store.get("shadow_master_seed")
    if master is None:                                   # generated once, stored and logged (spec §11)
        master = secrets.token_hex(16)
        store.put("shadow_master_seed", master)
        store.event(clock(), "shadow_master_seed", {"master_seed": master})
    x = Executor(broker, store, settings, clock, shadow=ShadowLedger(store, data, master))
    size_tools, _ = size_tools_from_env(env)
    outbox = JournalOutbox(store, AtlasClient(http, env=env), live=env.get("OAT_ATLAS_LIVE") == "1")
    outcomes = Outcomes(store, outbox, clock)
    x.on_exit_done = outcomes.on_exit_done
    tb = ToolBox(data, size_tools, Events(http=http, env=env), clock, settings.universe)
    dossiers = Dossiers(store)
    tools = AgentTools(tb, x, store, outbox, dossiers, clock, settings.strong_model)
    claude = Claude(http, x.cost, clock, env=env)
    agent = Agent(store, claude, tools, dossiers, data, clock, strong_model=settings.strong_model,
                  watcher_model=settings.watcher_model, universe=settings.universe)
    layer = CodeLayer(x, store, settings, clock, on_alert=agent.push_alert)
    feed = BarFeed(data, store, broker, layer, clock)
    return dict(settings=settings, store=store, executor=x, layer=layer, feed=feed, agent=agent, outbox=outbox)


def cycle(parts):
    x, now = parts["executor"], parts["executor"].clock()
    if x.status(now).is_open:
        x.snapshot()
        x.reconcile()
        parts["feed"].poll()
        parts["layer"].tick()
    parts["agent"].tick()
    parts["outbox"].flush()


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    redact.install()
    log = logging.getLogger("oat.service")
    parts = build()
    srv = serve(parts["store"], parts["executor"])
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    log.info("agent service started (paper only; model layer %s)", "ON" if parts["agent"].enabled() else "OFF")
    while True:
        try:
            cycle(parts)
        except Exception as e:  # noqa: BLE001 — one bad cycle never stops the loop
            log.error("cycle failed: %s", type(e).__name__)
        time.sleep(5)


if __name__ == "__main__":
    main()
