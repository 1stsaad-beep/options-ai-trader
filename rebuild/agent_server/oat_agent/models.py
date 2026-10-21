"""Plain data types shared by guards, the code layer and the broker client."""
from __future__ import annotations
import datetime as dt
from dataclasses import dataclass, field

OPEN_ORDER_STATUSES = {"new", "accepted", "pending_new", "partially_filled", "pending_replace", "pending_cancel",
                       "accepted_for_bidding", "held", "pending", "partiallyFilled"}


def occ_symbol(underlying: str, expiry: dt.date, right: str, strike: float) -> str:
    return f"{underlying}{expiry:%y%m%d}{'C' if right == 'call' else 'P'}{int(round(strike * 1000)):08d}"


def parse_occ(occ: str):
    root, rest = occ[:-15], occ[-15:]
    exp = dt.date(2000 + int(rest[0:2]), int(rest[2:4]), int(rest[4:6]))
    right = "call" if rest[6] == "C" else "put"
    return root, exp, right, int(rest[7:]) / 1000


@dataclass(frozen=True)
class Contract:
    underlying: str
    right: str            # call | put
    expiry: dt.date
    strike: float

    @property
    def occ(self): return occ_symbol(self.underlying, self.expiry, self.right, self.strike)

    @staticmethod
    def from_occ(occ):
        u, e, r, k = parse_occ(occ); return Contract(u, r, e, k)


@dataclass(frozen=True)
class Position:
    contract: Contract
    qty: int
    avg_price: float       # per share


@dataclass(frozen=True)
class Order:
    id: str
    contract: Contract
    side: str              # buy_to_open | sell_to_close
    qty: int
    limit: float
    status: str

    @property
    def is_open(self): return self.status in OPEN_ORDER_STATUSES


@dataclass(frozen=True)
class Quote:
    bid: float | None
    ask: float | None
    ts: dt.datetime | None          # quote time (exchange)

    @property
    def two_sided(self): return bool(self.bid and self.ask and self.bid > 0 and self.ask >= self.bid)

    def age_s(self, now): return None if self.ts is None else (now - self.ts).total_seconds()


@dataclass(frozen=True)
class EntryRequest:
    contract: Contract
    qty: int
    limit: float | None
    side: str = "buy_to_open"
    order_type: str = "limit"
    journal_id: str | None = None
    invalidation: float | None = None      # underlying price; the code layer exits when a 5m close breaks it


@dataclass
class GuardState:
    """Per-account guard memory (persisted by store.py)."""
    day_key: str | None = None
    day_start_equity: float | None = None
    orders_day_key: str | None = None
    orders_today: int = 0
    last_trade_at: dict = field(default_factory=dict)     # underlying -> datetime of last entry/exit submission
    paused: bool = False                                  # owner kill switch: no new entries
