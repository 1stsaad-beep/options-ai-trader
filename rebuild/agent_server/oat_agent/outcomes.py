"""Outcome of each agent trade (spec §8: fills, exit reason, P&L realistic and P&L Alpaca-fill), appended to the local
journal and queued for ATLAS after the exit order finishes."""
from __future__ import annotations
from .atlas_client import dec


class Outcomes:
    def __init__(self, store, outbox, clock):
        self.store, self.outbox, self.clock = store, outbox, clock

    def on_exit_done(self, journal_id, order):
        now = self.clock()
        if any(r["kind"] == "outcome" and r["body"].get("journal_id") == journal_id for r in self.store.journal(500)):
            return None
        sh = (self.store.shadow_get(journal_id) or {}).get("body", {})
        a = sh.get("agent", {})
        fills = [e["body"] for e in self.store.events(limit=2000) if e["kind"] in ("entry_filled", "exit_done")
                 and e["body"].get("journal_id") == journal_id]
        exit_ev = next((e["body"] for e in self.store.events("exit_submitted", 2000) if e["body"].get("journal_id") == journal_id), {})
        qty = sh.get("qty") or order.filled_qty
        alp = None
        if a.get("alpaca_entry_fill") is not None and order.filled_avg is not None:
            alp = (order.filled_avg - a["alpaca_entry_fill"]) * 100 * qty
        body = dict(journal_id=journal_id,
                    fills=[{k: (dec(v) if isinstance(v, float) else v) for k, v in f.items()} for f in fills],
                    exit_reason=exit_ev.get("reason") or sh.get("exit_reason") or "UNKNOWN",
                    pnl_realistic=dec(a.get("pnl_realistic")), pnl_alpaca_fill=dec(alp))
        self.store.journal_add(now, "outcome", body, sym=None, jid=f"{journal_id}:outcome")
        self.outbox.enqueue("outcome", body)
        return body
