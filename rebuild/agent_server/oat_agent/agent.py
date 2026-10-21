"""Orchestrator (spec §5): schedule (ET) 08:45 plan + tradable list + alerts · 09:46 re-plan after the first 15m bar
· event-driven during RTH (alert hits and a 5-minute check of open positions go to the Haiku watcher, which may only
wake the strong model) · 16:15 review. Nothing runs unless the owner has enabled the agent (control API /agent/on)."""
from __future__ import annotations
import datetime as dt
import json
from . import nyse
from .llm import CapReached, LLMError
from .prompts import WATCHER_SYSTEM
from .session import run_session

JOBS = (("plan", 8, 45), ("replan", 9, 46), ("review", 16, 15))
WATCH_EVERY = dt.timedelta(minutes=5)
MIN_WAKE_GAP = dt.timedelta(minutes=3)


def due_jobs(now, done: set):
    w = nyse.wall(now)
    if not nyse.is_trading_day(w.date()): return []
    out = []
    for name, h, m in JOBS:
        t = nyse.to_utc(w.year, w.month, w.day, h, m)
        sess = nyse.session(w.date())
        if name == "review" and sess.early_close: t = sess.close_utc + dt.timedelta(minutes=15)
        if now >= t and name not in done: out.append(name)
    return out


PROMPTS = {
    "plan": ("Pre-market plan for {date} (New York). Steps: tradable_today; for each tradable symbol read its dossier and "
             "events; look at daily and 1h structure; map the decision levels; write 2 scenarios per candidate; set_alert on "
             "the levels that would make you act; add short dossier notes. No orders now (market closed)."),
    "replan": ("09:46 re-plan after the first closed 15m bar of {date}. Re-anchor expected_range; update the plan and alerts; "
               "only enter if a setup is confirmed (thesis first, then place_order)."),
    "event": ("Event at {time} ET: {context}. Decide: enter (thesis first), manage or close an open position, adjust "
              "alerts, or do nothing. Explain briefly."),
    "review": ("Post-market review for {date}. For every trade today (journal_read) grade it, tag the setup, compare with "
               "the plan; hypothesis_add for repeatable setups; write dossier notes. No orders."),
}


class Agent:
    def __init__(self, store, claude, tools, dossiers, data, clock, *, strong_model, watcher_model, universe):
        self.store, self.claude, self.tools, self.dos, self.data, self.clock = store, claude, tools, dossiers, data, clock
        self.strong, self.watcher_model, self.universe = strong_model, watcher_model, list(universe)

    def enabled(self):
        return bool(self.store.get("agent_enabled", False))

    # ---------------------------------------------------------------- alert queue (filled by the code layer)
    def push_alert(self, alert, value):
        q = self.store.get("alert_queue", [])
        q.append({"alert": alert, "value": value, "t": self.clock().isoformat()})
        self.store.put("alert_queue", q[-50:])

    # ---------------------------------------------------------------- watcher
    def watch(self, context: dict):
        try:
            r = self.claude.create(model=self.watcher_model, system=WATCHER_SYSTEM, max_tokens=200, purpose="watcher",
                                   messages=[{"role": "user", "content": json.dumps(context, ensure_ascii=False, default=str)[:20000]}])
        except (CapReached, LLMError) as e:
            self.store.event(self.clock(), "watcher_error", {"error": str(e)})
            return {"wake": False, "reason": f"error: {e}"}
        text = "".join(b.get("text", "") for b in r.get("content") or [] if b.get("type") == "text").strip()
        try:
            j = json.loads(text[text.find("{"): text.rfind("}") + 1])
            out = {"wake": bool(j.get("wake")), "reason": str(j.get("reason", ""))[:300]}
        except ValueError:
            out = {"wake": False, "reason": "unparseable watcher answer"}
        self.store.event(self.clock(), "watcher", {**out, "context_kind": context.get("kind")})
        return out

    def _position_context(self):
        pos = []
        for p in self.tools.x.broker.positions():
            m = self.store.meta(p.contract.occ) or {}
            q = self.tools.x.broker.option_quote(p.contract)
            thesis = next((r["body"] for r in self.store.journal(200) if r["id"] == m.get("journal_id")), None)
            pos.append(dict(occ=p.contract.occ, qty=p.qty, entry=p.avg_price, bid=q.bid, ask=q.ask,
                            invalidation=m.get("invalidation"),
                            thesis=None if thesis is None else {k: thesis.get(k) for k in ("scenarios", "exit_plan", "invalidation_level")}))
        return pos

    # ---------------------------------------------------------------- tick
    def tick(self):
        now = self.clock()
        if not self.enabled(): return []
        ran = []
        day = nyse.date_key(now)
        done = set(self.store.get(f"jobs:{day}", []))
        for job in due_jobs(now, done):
            if job == "review": self._refresh_dossier_stats(now)
            w = nyse.wall(now)
            r = run_session(self.claude, self.tools, self.store, self.clock, kind=job, model=self.strong,
                            prompt=PROMPTS[job].format(date=w.date().isoformat()))
            done.add(job)
            self.store.put(f"jobs:{day}", sorted(done))
            ran.append(r)
        if not self.tools.x.status(now).is_open: return ran
        reasons = []
        q = self.store.get("alert_queue", [])
        if q:
            self.store.put("alert_queue", [])
            v = self.watch({"kind": "alert_hits", "alerts": q, "positions": self._position_context()})
            if v["wake"]: reasons.append(f"alert: {v['reason']}")
        last_watch = self.store.get("last_position_watch")
        if self.tools.x.broker.positions() and (last_watch is None or now - dt.datetime.fromisoformat(last_watch) >= WATCH_EVERY):
            self.store.put("last_position_watch", now.isoformat())
            v = self.watch({"kind": "position_check", "positions": self._position_context()})
            if v["wake"]: reasons.append(f"position: {v['reason']}")
        last_wake = self.store.get("last_strong_wake")
        if reasons and (last_wake is None or now - dt.datetime.fromisoformat(last_wake) >= MIN_WAKE_GAP):
            self.store.put("last_strong_wake", now.isoformat())
            ran.append(run_session(self.claude, self.tools, self.store, self.clock, kind="event", model=self.strong,
                                   prompt=PROMPTS["event"].format(time=nyse.hm(now), context=" | ".join(reasons))))
        return ran

    def _refresh_dossier_stats(self, now):
        for sym in self.universe:
            try:
                self.dos.refresh_stats(sym, now, self.data.bars(sym, "1d", 120, now))
            except Exception as e:  # noqa: BLE001
                self.store.event(now, "dossier_error", {"sym": sym, "error": str(e)})
