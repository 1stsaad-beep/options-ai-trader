"""Monthly spend cap of the agent (spec §5): every model/data call is logged with its USD cost; at the cap no new
trades and open trades are closed. Month = New York calendar month."""
from __future__ import annotations
import datetime as dt
from . import nyse


def month_start_utc(now: dt.datetime) -> dt.datetime:
    w = nyse.wall(now)
    return nyse.to_utc(w.year, w.month, 1)


def day_start_utc(now: dt.datetime) -> dt.datetime:
    w = nyse.wall(now)
    return nyse.to_utc(w.year, w.month, w.day)


class CostCap:
    def __init__(self, store, cap_usd: float):
        self.store, self.cap = store, cap_usd

    def record(self, now, usd, **kw):
        self.store.cost_add(now, usd, **kw)

    def month_spend(self, now) -> float:
        return self.store.cost_since(month_start_utc(now))

    def day_spend(self, now) -> float:
        return self.store.cost_since(day_start_utc(now))

    def reached(self, now) -> bool:
        return self.month_spend(now) >= self.cap
