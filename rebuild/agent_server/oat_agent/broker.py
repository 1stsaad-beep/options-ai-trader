"""Alpaca PAPER broker client (the only broker). Base URL is hard-coded to the paper endpoint (config.py); the HTTP
layer (net.py) additionally refuses the live host. Keys come only from the environment and are sent only as
headers — never logged, never returned."""
from __future__ import annotations
import datetime as dt
import os
import uuid
from . import config, nyse
from .models import Contract, Order, Position, Quote
from .net import Http


def _t(s):
    if not s: return None
    s = s.replace("Z", "+00:00")
    if "." in s:                         # trim nanoseconds to microseconds for fromisoformat
        head, frac = s.split(".", 1)
        tz = frac[frac.find("+"):] if "+" in frac else (frac[frac.find("-"):] if "-" in frac else "")
        digits = frac[: len(frac) - len(tz)] if tz else frac
        s = f"{head}.{digits[:6].ljust(6, '0')}{tz}"
    return dt.datetime.fromisoformat(s).astimezone(dt.timezone.utc)


class BrokerError(Exception):
    pass


class AlpacaPaper:
    def __init__(self, http: Http | None = None, env=None):
        env = env or os.environ
        self._key = env.get("ALPACA_PAPER_KEY_ID", "")
        self._secret = env.get("ALPACA_PAPER_SECRET_KEY", "")
        self.http = http or Http(env.get("ATLAS_BASE_URL"))
        self.base = config.PAPER_TRADING_URL          # hard-coded, not configurable
        self.data = config.MARKET_DATA_URL

    def __repr__(self):                                # never expose keys
        return "AlpacaPaper(paper-api.alpaca.markets)"

    def _h(self):
        return {"APCA-API-KEY-ID": self._key, "APCA-API-SECRET-KEY": self._secret}

    def _get(self, url):
        code, body = self.http.request("GET", url, self._h())
        if code >= 300: raise BrokerError(f"GET {url.split('?')[0]} -> {code}")
        return body

    # ---- account state
    def account(self):
        a = self._get(f"{self.base}/v2/account")
        return dict(equity=float(a["equity"]), last_equity=float(a.get("last_equity", a["equity"])),
                    cash=float(a.get("cash", 0)), options_buying_power=float(a.get("options_buying_power", a.get("buying_power", 0))))

    def positions(self):
        out = []
        for p in self._get(f"{self.base}/v2/positions"):
            if p.get("asset_class") not in (None, "us_option"): continue
            out.append(Position(Contract.from_occ(p["symbol"]), int(float(p["qty"])), float(p["avg_entry_price"])))
        return out

    def open_orders(self):
        out = []
        for o in self._get(f"{self.base}/v2/orders?status=open&limit=500"):
            if len(o["symbol"]) < 16: continue                 # equities are never traded here
            side = "buy_to_open" if o["side"] == "buy" else "sell_to_close"
            out.append(Order(o["id"], Contract.from_occ(o["symbol"]), side, int(float(o["qty"])),
                             float(o.get("limit_price") or 0), o["status"]))
        return out

    def clock(self):
        c = self._get(f"{self.base}/v2/clock")
        return nyse.BrokerClock(bool(c["is_open"]), _t(c["next_open"]), _t(c["next_close"]))

    # ---- orders (limit only)
    def place(self, contract: Contract, side: str, qty: int, limit: float, client_id: str | None = None):
        if side not in ("buy_to_open", "sell_to_close"): raise BrokerError(f"side not allowed: {side}")
        body = dict(symbol=contract.occ, qty=str(int(qty)), side="buy" if side == "buy_to_open" else "sell",
                    type="limit", time_in_force="day", limit_price=f"{max(0.01, round(limit, 2)):.2f}",
                    client_order_id=client_id or f"oat-agent-{uuid.uuid4().hex[:16]}")
        code, r = self.http.request("POST", f"{self.base}/v2/orders", self._h(), body)
        if code >= 300: raise BrokerError(f"order rejected ({code}): {(r or {}).get('message', '')[:200]}")
        return Order(r["id"], contract, side, int(qty), float(body["limit_price"]), r["status"])

    def cancel(self, order_id: str):
        code, _ = self.http.request("DELETE", f"{self.base}/v2/orders/{order_id}", self._h())
        return code < 300

    # ---- prices used by the guards (stage 2 adds the full data tools)
    def stock_last(self, sym):
        r = self._get(f"{self.data}/v2/stocks/{sym}/trades/latest?feed=sip")
        t = r["trade"]
        return float(t["p"]), _t(t["t"])

    def option_quote(self, contract: Contract) -> Quote:
        r = self._get(f"{self.data}/v1beta1/options/snapshots?symbols={contract.occ}&feed=opra")
        s = (r.get("snapshots") or {}).get(contract.occ) or {}
        q = s.get("latestQuote") or {}
        return Quote(q.get("bp"), q.get("ap"), _t(q.get("t")))


class FakeBroker:
    """In-memory paper broker for tests (fills limit buys at or above the ask, sells at or below the bid)."""

    def __init__(self, equity=1000.0):
        self.cash = equity
        self.last_equity = equity
        self.pos: dict[str, Position] = {}
        self.orders: list[Order] = []
        self.placed: list[tuple] = []
        self.quotes: dict[str, Quote] = {}
        self.stock: dict[str, tuple] = {}
        self.equity_override = None
        self.clock_value = None

    def account(self):
        eq = self.equity_override if self.equity_override is not None else self.cash + sum(
            p.qty * 100 * ((self.quotes.get(p.contract.occ) or Quote(p.avg_price, p.avg_price, None)).bid or 0) for p in self.pos.values())
        return dict(equity=eq, last_equity=self.last_equity, cash=self.cash, options_buying_power=self.cash)

    def positions(self): return list(self.pos.values())

    def open_orders(self): return [o for o in self.orders if o.is_open]

    def clock(self):
        if self.clock_value is None: raise BrokerError("no clock")
        return self.clock_value

    def place(self, contract, side, qty, limit, client_id=None):
        self.placed.append((contract.occ, side, qty, limit))
        q = self.quotes.get(contract.occ)
        oid = f"F{len(self.placed)}"
        filled = q is not None and q.two_sided and ((side == "buy_to_open" and limit >= q.ask) or (side == "sell_to_close" and limit <= q.bid))
        if filled:
            px = q.ask if side == "buy_to_open" else q.bid
            p = self.pos.get(contract.occ)
            if side == "buy_to_open":
                self.cash -= qty * px * 100
                self.pos[contract.occ] = Position(contract, (p.qty if p else 0) + qty, px)
            else:
                self.cash += qty * px * 100
                left = (p.qty if p else 0) - qty
                if left > 0: self.pos[contract.occ] = Position(contract, left, p.avg_price)
                else: self.pos.pop(contract.occ, None)
        o = Order(oid, contract, side, qty, limit, "filled" if filled else "new")
        self.orders.append(o)
        return o

    def cancel(self, order_id):
        self.orders = [Order(o.id, o.contract, o.side, o.qty, o.limit, "canceled") if o.id == order_id else o for o in self.orders]
        return True

    def stock_last(self, sym): return self.stock[sym]

    def option_quote(self, contract): return self.quotes.get(contract.occ, Quote(None, None, None))
