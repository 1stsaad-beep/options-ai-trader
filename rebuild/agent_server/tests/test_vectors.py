"""Runs tests/vectors/guard_vectors.json against the Python guards (one subTest per vector)."""
import copy
import datetime as dt
import json
import unittest
from pathlib import Path

from oat_agent import guards, net, nyse
from oat_agent.config import OwnerSettings
from oat_agent.models import Contract, EntryRequest, GuardState, Order, Position, Quote

VEC = json.loads((Path(__file__).parent / "vectors" / "guard_vectors.json").read_text(encoding="utf-8"))


def T(s):
    return None if s is None else dt.datetime.fromisoformat(s.replace("Z", "+00:00"))


def iso(t):
    return t.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def merge(base, over):
    out = copy.deepcopy(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict) and k not in ("quote",):
            out[k] = {**out[k], **v}
        else:
            out[k] = v
    return out


def positions(rows): return [Position(Contract.from_occ(r["occ"]), r["qty"], 1.0) for r in rows]


def orders(rows): return [Order(f"o{i}", Contract.from_occ(r["occ"]), r["side"], 1, 1.0, r["status"]) for i, r in enumerate(rows)]


def build(ctx):
    c = merge(VEC["entry_baseline"], ctx)
    now = T(c["now"])
    s = OwnerSettings(**c["settings"])
    st_raw = c["state"]
    st = GuardState(day_key=st_raw.get("day_key"), day_start_equity=st_raw.get("day_start_equity"),
                    orders_day_key=st_raw.get("orders_day_key"), orders_today=st_raw.get("orders_today", 0),
                    last_trade_at={k: T(v) for k, v in st_raw.get("last_trade_at", {}).items()},
                    paused=st_raw.get("paused", False))
    guards.on_snapshot(st, now, c["equity"])          # what the engine does at the start of every cycle
    q = c["quote"]
    r = c["req"]
    exp = nyse.wall(now).date() if r["expiry"] == "today" else dt.date.fromisoformat(r["expiry"])
    req = EntryRequest(Contract(r["underlying"], r["right"], exp, r["strike"]), r["qty"], r["limit"], r["side"],
                       r["order_type"], r["journal_id"], r["invalidation"])
    age = c["underlying_age_s"]
    return dict(now=now, settings=s, st=st, equity=c["equity"], positions=positions(c["positions"]),
                orders=orders(c["orders"]), underlying_price=c["underlying_price"],
                underlying_ts=None if age is None else now - dt.timedelta(seconds=age),
                quote=Quote(q["bid"], q["ask"], None if q.get("age_s") is None else now - dt.timedelta(seconds=q["age_s"])),
                req=req, spend=c["month_spend_usd"])


def run(v):
    fn, a = v["fn"], v.get("args", {})
    if fn == "offset_hours": return nyse.offset_hours(T(a["t"]))
    if fn == "dst_start_utc": return iso(nyse.dst_start_utc(a["year"]))
    if fn == "dst_end_utc": return iso(nyse.dst_end_utc(a["year"]))
    if fn == "to_utc": return iso(nyse.to_utc(a["y"], a["m"], a["d"], a["h"], a["mi"]))
    if fn == "hm": return nyse.hm(T(a["t"]))
    if fn == "date_key": return nyse.date_key(T(a["t"]))
    if fn == "rules_match_official":
        y = a["year"]
        return (set(nyse.rule_holidays(y)) == {d for d in nyse.OFFICIAL_HOLIDAYS if d.year == y}
                and nyse.rule_early_closes(y) == {d for d in nyse.OFFICIAL_EARLY if d.year == y})
    if fn == "is_trading_day": return nyse.is_trading_day(dt.date.fromisoformat(a["d"]))
    if fn == "holiday_name_contains": return a["text"] in (nyse.holiday_name(dt.date.fromisoformat(a["d"])) or "")
    if fn == "phase": return nyse.status_at(T(a["t"])).phase
    if fn == "today_early_close": return nyse.status_at(T(a["t"])).today.early_close
    if fn == "next_open": return iso(nyse.status_at(T(a["t"])).next_open)
    if fn == "next_close": return iso(nyse.status_at(T(a["t"])).next_close)
    if fn == "closed_reason": return nyse.status_at(T(a["t"])).closed_reason_ar
    if fn == "gate":
        b = a["broker"]
        if b is None: src = None
        elif b == "error":
            def src(): raise RuntimeError("down")
        else:
            def src(b=b): return nyse.BrokerClock(b["is_open"], T(b["next_open"]), T(b["next_close"]))
        s = nyse.MarketHoursGate(src).status(T(a["now"]))
        return {"is_open": s.is_open, "source": s.source, "has_note": s.note_ar is not None}
    if fn == "lock":
        return guards.direction_lock(a["symbol"], a["right"], positions(a["positions"]), orders(a["orders"])) is None
    if fn == "url_allowed":
        try:
            net.check_url(a["url"], net.allowed_hosts(None)); return True
        except net.ForbiddenHost:
            return False
    if fn in ("entry", "exit"):
        b = build(v.get("ctx", {}))
        status = nyse.MarketHoursGate().status(b["now"])
        if fn == "exit":
            verdict = guards.check_exit(status=status)
        else:
            verdict = guards.check_entry(b["req"], now=b["now"], status=status, settings=b["settings"], st=b["st"],
                                         equity=b["equity"], positions=b["positions"], orders=b["orders"],
                                         underlying_price=b["underlying_price"], underlying_ts=b["underlying_ts"],
                                         option_quote=b["quote"], month_spend_usd=b["spend"])
        return verdict
    raise KeyError(fn)


class Vectors(unittest.TestCase):
    def test_all_vectors(self):
        for i, v in enumerate(VEC["vectors"]):
            with self.subTest(i=i, group=v["group"], source=v["source"]):
                got = run(v)
                if v["fn"] in ("entry", "exit"):
                    e = v["expect"]
                    self.assertEqual(got.allowed, e["allowed"], got.reasons)
                    for code in e.get("codes_include", []):
                        self.assertIn(code, got.codes)
                else:
                    self.assertEqual(got, v["expect"])

    def test_every_group_present(self):
        groups = {v["group"] for v in VEC["vectors"]}
        for g in ("rth_only", "daily_loss", "max_open_positions", "kill_switch", "daily_order_cap", "cooldown",
                  "direction_lock", "live_guard", "stale_quote", "cost_cap", "calendar", "market_gate"):
            self.assertIn(g, groups)


if __name__ == "__main__":
    unittest.main()
