"""Random shadow ledger (spec §11, owner decision 2026-10-21, fixed before start — no other method):
for every agent entry, one shadow trade at the SAME entry time, with the same contract type (same OTM distance in
dollars from the underlying, same expiry) and a direction (call/put) chosen at random; it exits at the same time and
for the same reason as the agent's trade. Seeded: seed = SHA-256(master_seed + ":" + journal_id); both are logged.
Scoring is realistic for both legs: buy at the ask, sell at the bid."""
from __future__ import annotations
import hashlib
import random
from . import nyse
from .models import Contract


def seed_for(master_seed: str, journal_id: str) -> int:
    return int(hashlib.sha256(f"{master_seed}:{journal_id}".encode()).hexdigest()[:16], 16)


def random_direction(master_seed: str, journal_id: str) -> str:
    return "call" if random.Random(seed_for(master_seed, journal_id)).random() < 0.5 else "put"


def pick_strike(strikes, underlying, distance, right):
    """Nearest listed strike to underlying +/- distance on the shadow's OTM side."""
    target = underlying + distance if right == "call" else underlying - distance
    otm = [k for k in strikes if (k > underlying if right == "call" else k < underlying)]
    return min(otm, key=lambda k: (abs(k - target), k)) if otm else None


def _quote(snaps, occ):
    q = ((snaps.get(occ) or {}).get("latestQuote")) or {}
    return q.get("bp"), q.get("ap"), q.get("t")


class ShadowLedger:
    def __init__(self, store, data, master_seed: str):
        self.store, self.data, self.master = store, data, master_seed

    def open(self, journal_id, now, agent: Contract, qty, underlying, agent_ask):
        right = random_direction(self.master, journal_id)
        dist = abs(agent.strike - underlying)
        body = dict(master_seed=self.master, seed=seed_for(self.master, journal_id), direction=right,
                    otm_distance=round(dist, 4), expiry=agent.expiry.isoformat(), qty=qty, entry_ts=now.isoformat(),
                    underlying_at_entry=underlying,
                    agent=dict(occ=agent.occ, right=agent.right, strike=agent.strike, entry_ask=agent_ask))
        try:
            snaps = self.data.option_snapshots(agent.underlying, agent.expiry)
        except Exception as e:  # noqa: BLE001
            body["error"] = f"chain unavailable: {e}"
            self.store.shadow_put(journal_id, now, "no_quote", body); return body
        strikes = sorted({Contract.from_occ(o).strike for o in snaps if Contract.from_occ(o).right == right})
        k = pick_strike(strikes, underlying, dist, right)
        if k is None:
            self.store.shadow_put(journal_id, now, "no_quote", {**body, "error": "no OTM strike"}); return body
        c = Contract(agent.underlying, right, agent.expiry, k)
        bid, ask, qt = _quote(snaps, c.occ)
        body["shadow"] = dict(occ=c.occ, strike=k, entry_bid=bid, entry_ask=ask, quote_ts=qt)
        status = "pending_fill" if (bid and ask) else "no_quote"
        self.store.shadow_put(journal_id, now, status, body)
        self.store.event(now, "shadow_open", dict(journal_id=journal_id, status=status, **{k2: body[k2] for k2 in ("seed", "direction")}),
                         sym=agent.underlying)
        return body

    def agent_filled(self, journal_id, now, fill_price):
        r = self.store.shadow_get(journal_id)
        if not r or r["status"] != "pending_fill": return
        b = r["body"]; b["agent"]["alpaca_entry_fill"] = fill_price
        self.store.shadow_put(journal_id, now, "open", b)

    def void(self, journal_id, now, reason):
        r = self.store.shadow_get(journal_id)
        if not r or r["status"] not in ("pending_fill", "no_quote"): return
        self.store.shadow_put(journal_id, now, "void", {**r["body"], "void_reason": reason})

    def close(self, journal_id, now, reason, agent_exit_bid, agent_alpaca_exit=None):
        r = self.store.shadow_get(journal_id)
        if not r or r["status"] not in ("open", "pending_fill", "no_quote"): return None
        b = r["body"]
        qty = b["qty"]
        a = b["agent"]
        a.update(exit_bid=agent_exit_bid, alpaca_exit_fill=agent_alpaca_exit)
        if a.get("entry_ask") and agent_exit_bid is not None:
            a["pnl_realistic"] = round((agent_exit_bid - a["entry_ask"]) * 100 * qty, 2)
            a["pnl_realistic_pct"] = round(100 * (agent_exit_bid / a["entry_ask"] - 1), 2)
        b.update(exit_ts=now.isoformat(), exit_reason=reason)
        if r["status"] == "no_quote" or "shadow" not in b:
            self.store.shadow_put(journal_id, now, "closed_no_shadow", b); return b
        s = b["shadow"]
        try:
            snaps = self.data.option_snapshots(Contract.from_occ(s["occ"]).underlying, Contract.from_occ(s["occ"]).expiry)
            bid, ask, qt = _quote(snaps, s["occ"])
        except Exception as e:  # noqa: BLE001
            bid, ask, qt = None, None, None; s["exit_error"] = str(e)
        s.update(exit_bid=bid, exit_ask=ask, exit_quote_ts=qt)
        if bid is not None and s.get("entry_ask"):
            s["pnl_realistic"] = round((bid - s["entry_ask"]) * 100 * qty, 2)
            s["pnl_realistic_pct"] = round(100 * (bid / s["entry_ask"] - 1), 2)
        self.store.shadow_put(journal_id, now, "closed", b)
        self.store.event(now, "shadow_close", dict(journal_id=journal_id, agent=a.get("pnl_realistic"), shadow=s.get("pnl_realistic")),
                         sym=Contract.from_occ(s["occ"]).underlying)
        return b


def comparison(store):
    """Totals over closed trades: agent vs shadow realistic P&L (both legs present only)."""
    rows = [r["body"] for r in store.shadows("closed")]
    both = [b for b in rows if b["agent"].get("pnl_realistic") is not None and b["shadow"].get("pnl_realistic") is not None]
    return dict(trades=len(both), agent_pnl=round(sum(b["agent"]["pnl_realistic"] for b in both), 2),
                shadow_pnl=round(sum(b["shadow"]["pnl_realistic"] for b in both), 2),
                agent_wins=sum(b["agent"]["pnl_realistic"] > 0 for b in both),
                shadow_wins=sum(b["shadow"]["pnl_realistic"] > 0 for b in both),
                skill_claim_allowed=len(both) >= 100)
