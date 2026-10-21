"""Stage 1: executor guards wiring, code layer (alerts, invalidation exits, time exits, cap, kill switch), paper-only
networking, secret hygiene, control API."""
import datetime as dt
import io
import json
import logging
import sqlite3
import threading
import unittest
import urllib.request

from oat_agent import alerts as AL, config, net, nyse, redact
from oat_agent.broker import AlpacaPaper, FakeBroker
from oat_agent.code_layer import CodeLayer
from oat_agent.config import OwnerSettings
from oat_agent.control_api import serve
from oat_agent.executor import Executor
from oat_agent.models import Contract, EntryRequest, Position, Quote
from oat_agent.store import Store

MON_1100 = nyse.utc(2026, 10, 19, 15)          # Monday 11:00 EDT, market open
TODAY = dt.date(2026, 10, 19)


class Clock:
    def __init__(self, t): self.t = t
    def __call__(self): return self.t


def setup(settings=None, t=MON_1100):
    clk = Clock(t)
    b = FakeBroker(1000)
    s = Store()
    x = Executor(b, s, settings or OwnerSettings(), clk)
    return clk, b, s, x


def call(strike=255.0, exp=TODAY, sym="AAPL", right="call"):
    return Contract(sym, right, exp, strike)


def ready(b, clk, c, bid=1.0, ask=1.1, px=250.0):
    b.quotes[c.occ] = Quote(bid, ask, clk() - dt.timedelta(seconds=2))
    b.stock[c.underlying] = (px, clk() - dt.timedelta(seconds=3))


class Networking(unittest.TestCase):
    def test_live_host_is_unreachable_even_through_the_client(self):
        called = []
        h = net.Http(opener=lambda *a, **k: called.append(1))
        for url in ("https://api.alpaca.markets/v2/orders", "https://broker-api.alpaca.markets/v1/x",
                    "http://paper-api.alpaca.markets/v2/orders", "https://evil.example/v2"):
            with self.assertRaises(net.ForbiddenHost):
                h.request("POST", url, body={})
        self.assertEqual(called, [])

    def test_paper_url_is_hard_coded(self):
        self.assertEqual(config.PAPER_TRADING_URL, "https://paper-api.alpaca.markets")
        b = AlpacaPaper(env={"ALPACA_PAPER_KEY_ID": "KEYID123456", "ALPACA_PAPER_SECRET_KEY": "SECRET987654"})
        self.assertEqual(b.base, config.PAPER_TRADING_URL)
        self.assertNotIn("KEYID123456", repr(b))
        self.assertNotIn("SECRET987654", repr(b))

    def test_orders_go_to_paper_host_as_limit_orders(self):
        seen = []

        class R:
            status = 200
            def __init__(self, body): self.b = body
            def read(self): return json.dumps(self.b).encode()
            def __enter__(self): return self
            def __exit__(self, *a): return False

        def opener(req, timeout):
            seen.append(req)
            return R({"id": "o1", "status": "new"})
        b = AlpacaPaper(http=net.Http(opener=opener), env={"ALPACA_PAPER_KEY_ID": "k" * 10, "ALPACA_PAPER_SECRET_KEY": "s" * 10})
        o = b.place(call(), "buy_to_open", 1, 1.05)
        req = seen[0]
        self.assertTrue(req.full_url.startswith("https://paper-api.alpaca.markets/v2/orders"))
        body = json.loads(req.data)
        self.assertEqual(body["type"], "limit")
        self.assertEqual(body["side"], "buy")
        self.assertEqual(body["symbol"], "AAPL261019C00255000")
        self.assertEqual(o.status, "new")
        with self.assertRaises(Exception):
            b.place(call(), "sell_to_open", 1, 1.0)


class Secrets(unittest.TestCase):
    def test_log_lines_are_scrubbed(self):
        env = {"ANTHROPIC_API_KEY": "sk-ant-verysecret", "ALPACA_PAPER_SECRET_KEY": "alpacasecretvalue"}
        lg = logging.getLogger("oat.test.secrets")
        buf = io.StringIO()
        h = logging.StreamHandler(buf)
        lg.addHandler(h)
        lg.addFilter(redact.RedactFilter(env))
        lg.setLevel(logging.INFO)
        lg.info("calling with key %s and %s", "sk-ant-verysecret", "alpacasecretvalue")
        out = buf.getvalue()
        self.assertNotIn("verysecret", out)
        self.assertNotIn("alpacasecretvalue", out)
        self.assertIn("***", out)

    def test_settings_reject_unknown_keys(self):
        with self.assertRaises(ValueError):
            OwnerSettings.from_env({"OAT_SETTINGS_JSON": json.dumps({"allow_live": True})})
        s = OwnerSettings.from_env({"OAT_SETTINGS_JSON": json.dumps({"max_open_positions": 2})})
        self.assertEqual(s.max_open_positions, 2)
        with self.assertRaises(Exception):
            s.max_open_positions = 9          # frozen: nothing can change it at run time


class ExecutorEntries(unittest.TestCase):
    def test_entry_passes_all_guards_and_is_journaled(self):
        clk, b, s, x = setup()
        c = call(); ready(b, clk, c)
        jid = s.journal_add(clk(), "thesis", {"sym": "AAPL"}, sym="AAPL")
        r = x.enter(EntryRequest(c, 1, 1.10, journal_id=jid, invalidation=248.0))
        self.assertTrue(r.ok, r.reasons_ar)
        self.assertEqual(b.placed, [(c.occ, "buy_to_open", 1, 1.10)])
        self.assertEqual(s.meta(c.occ)["invalidation"], 248.0)
        self.assertEqual(s.guard_state().orders_today, 1)

    def test_unknown_journal_id_blocks(self):
        clk, b, s, x = setup()
        c = call(); ready(b, clk, c)
        r = x.enter(EntryRequest(c, 1, 1.10, journal_id="J-does-not-exist", invalidation=248.0))
        self.assertFalse(r.ok)
        self.assertIn("NO_JOURNAL", r.codes)
        self.assertEqual(b.placed, [])

    def test_blocked_entry_places_nothing_and_logs_reasons(self):
        clk, b, s, x = setup()
        c = call(); ready(b, clk, c)
        b.stock["AAPL"] = (250.0, clk() - dt.timedelta(seconds=90))      # stale
        jid = s.journal_add(clk(), "thesis", {})
        r = x.enter(EntryRequest(c, 1, 1.10, journal_id=jid, invalidation=248.0))
        self.assertFalse(r.ok)
        self.assertIn("STALE_PRICE", r.codes)
        self.assertEqual(b.placed, [])
        self.assertEqual(s.events("entry_blocked")[0]["body"]["codes"], list(r.codes))

    def test_broker_price_failure_blocks_entry(self):
        clk, b, s, x = setup()
        c = call(); b.quotes[c.occ] = Quote(1.0, 1.1, clk())
        jid = s.journal_add(clk(), "thesis", {})
        r = x.enter(EntryRequest(c, 1, 1.10, journal_id=jid, invalidation=248.0))   # no stock price at all
        self.assertIn("STALE_PRICE", r.codes)


class CodeLayerTests(unittest.TestCase):
    def open_position(self, right="call", inv=248.0, exp=TODAY, strike=None):
        clk, b, s, x = setup()
        c = call(strike=strike or (255.0 if right == "call" else 245.0), right=right, exp=exp)
        ready(b, clk, c)
        jid = s.journal_add(clk(), "thesis", {})
        self.assertTrue(x.enter(EntryRequest(c, 1, 1.10, journal_id=jid, invalidation=inv)).ok)
        self.assertEqual(len(b.positions()), 1)
        return clk, b, s, x, CodeLayer(x, s, x.s, clk), c

    def test_invalidation_exit_on_5m_close_only(self):
        clk, b, s, x, L, c = self.open_position()
        L.on_bar("AAPL", "1m", 247.0, clk())               # 1m close below: no exit
        self.assertEqual(len(b.positions()), 1)
        L.on_bar("AAPL", "5m", 248.0, clk())               # exactly at the level: not broken
        self.assertEqual(len(b.positions()), 1)
        _, exits = L.on_bar("AAPL", "5m", 247.9, clk())
        self.assertTrue(exits and exits[0][1].ok)
        self.assertEqual(b.placed[-1][1], "sell_to_close")
        self.assertEqual(b.placed[-1][3], 1.0)              # at the bid
        self.assertEqual(b.positions(), [])
        self.assertEqual(s.events("exit_submitted")[0]["body"]["reason"], "INVALIDATION")

    def test_invalidation_for_a_put_is_mirrored(self):
        clk, b, s, x, L, c = self.open_position(right="put", inv=252.0)
        L.on_bar("AAPL", "5m", 251.0, clk())
        self.assertEqual(len(b.positions()), 1)
        L.on_bar("AAPL", "5m", 252.5, clk())
        self.assertEqual(b.positions(), [])

    def test_time_exit_1550_for_same_day_expiry_only(self):
        clk, b, s, x, L, c = self.open_position()
        clk.t = nyse.utc(2026, 10, 19, 19, 49)             # 15:49 EDT
        self.assertEqual(L.tick(), [])
        clk.t = nyse.utc(2026, 10, 19, 19, 50)             # 15:50 EDT
        out = L.tick()
        self.assertEqual(out[0][1], "TIME_EXIT")
        self.assertEqual(b.positions(), [])

    def test_tomorrow_expiry_is_not_time_exited(self):
        clk, b, s, x, L, c = self.open_position(exp=dt.date(2026, 10, 20))
        clk.t = nyse.utc(2026, 10, 19, 19, 55)
        self.assertEqual(L.tick(), [])
        self.assertEqual(len(b.positions()), 1)

    def test_time_exit_on_early_close_day(self):
        L = CodeLayer(None, None, OwnerSettings(), Clock(MON_1100))
        self.assertEqual(L.time_exit_at(dt.date(2026, 11, 27)), nyse.utc(2026, 11, 27, 17, 50))   # 12:50 EST
        self.assertEqual(L.time_exit_at(dt.date(2026, 10, 19)), nyse.utc(2026, 10, 19, 19, 50))

    def test_cap_closes_open_trades_and_blocks_entries(self):
        clk, b, s, x, L, c = self.open_position()
        x.cost.record(clk(), 300.0, model="test", purpose="test")
        out = L.tick()
        self.assertEqual(out[0][1], "COST_CAP")
        self.assertEqual(b.positions(), [])
        c2 = call(sym="NVDA", strike=200.0); ready(b, clk, c2, px=190.0)
        clk.t += dt.timedelta(minutes=20)
        ready(b, clk, c2, px=190.0)
        jid = s.journal_add(clk(), "thesis", {})
        r = x.enter(EntryRequest(c2, 1, 1.10, journal_id=jid, invalidation=185.0))
        self.assertIn("COST_CAP", r.codes)

    def test_kill_blocks_entries_but_exits_still_run(self):
        clk, b, s, x, L, c = self.open_position()
        st = s.guard_state(); st.paused = True; s.save_guard_state(st)
        L.on_bar("AAPL", "5m", 240.0, clk())
        self.assertEqual(b.positions(), [])                 # invalidation exit still happened
        clk.t += dt.timedelta(minutes=20)
        c2 = call(sym="NVDA", strike=200.0); ready(b, clk, c2, px=190.0)
        jid = s.journal_add(clk(), "thesis", {})
        self.assertIn("KILL", x.enter(EntryRequest(c2, 1, 1.10, journal_id=jid, invalidation=185.0)).codes)

    def test_flatten_closes_everything_then_clears_the_flag(self):
        clk, b, s, x, L, c = self.open_position()
        s.put("flatten_requested", True)
        out = L.tick()
        self.assertEqual(out[0][1], "KILL_FLATTEN")
        self.assertEqual(b.positions(), [])
        L.tick()
        self.assertFalse(s.get("flatten_requested"))

    def test_exits_outside_rth_are_not_sent(self):
        clk, b, s, x, L, c = self.open_position()
        clk.t = nyse.utc(2026, 10, 19, 21)
        r = x.exit(b.positions()[0], "TEST", "x")
        self.assertIn("MARKET_CLOSED", r.codes)

    def test_no_bid_exit_is_retried_not_forced(self):
        clk, b, s, x, L, c = self.open_position()
        b.quotes[c.occ] = Quote(None, 1.2, clk())
        r = x.exit(b.positions()[0], "TEST", "x")
        self.assertIn("NO_BID", r.codes)
        self.assertEqual(len(b.positions()), 1)


class Alerts(unittest.TestCase):
    def test_grammar(self):
        self.assertEqual(AL.parse("5m close > 219.75"), AL.Condition("5m", ">", 219.75))
        self.assertEqual(AL.parse("last <= 210"), AL.Condition(None, "<=", 210.0))
        for bad in ("5m close ~ 2", "rsi > 70", "", "2m close > 1"):
            with self.assertRaises(ValueError):
                AL.parse(bad)

    def test_alert_fires_once_on_its_timeframe(self):
        clk, b, s, x = setup()
        L = CodeLayer(x, s, x.s, clk, on_alert=lambda a, v: hits.append((a["id"], v)))
        hits = []
        aid = s.alert_add(clk(), "AAPL", "5m close > 219.75", "break of the range")
        L.on_bar("AAPL", "1m", 230.0, clk())
        L.on_bar("AAPL", "5m", 219.70, clk())
        self.assertEqual(hits, [])
        L.on_bar("AAPL", "5m", 219.80, clk())
        L.on_bar("AAPL", "5m", 221.00, clk())
        self.assertEqual(hits, [(aid, 219.80)])
        self.assertEqual(s.alerts_active(), [])


class StoreTests(unittest.TestCase):
    def test_journal_and_events_are_append_only(self):
        s = Store()
        jid = s.journal_add(MON_1100, "thesis", {"a": 1})
        with self.assertRaises(sqlite3.DatabaseError):
            s._x("update journal set body='{}' where id=?", (jid,))
        with self.assertRaises(sqlite3.DatabaseError):
            s._x("delete from journal")
        s.event(MON_1100, "x", {})
        with self.assertRaises(sqlite3.DatabaseError):
            s._x("delete from events")


class ControlApi(unittest.TestCase):
    def start(self, env):
        clk, b, s, x = setup()
        srv = serve(s, x, port=0, env=env)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.shutdown)
        return f"http://127.0.0.1:{srv.server_address[1]}", s

    def req(self, url, method="GET", token=None):
        r = urllib.request.Request(url, method=method, data=b"" if method == "POST" else None)
        if token: r.add_header("Authorization", f"Bearer {token}")
        try:
            with urllib.request.urlopen(r, timeout=5) as resp:
                return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def test_auth_and_kill_switch(self):
        base, s = self.start({"OWNER_TOKEN": "owner-token-123456"})
        self.assertEqual(self.req(base + "/health")[0], 200)
        self.assertEqual(self.req(base + "/status")[0], 401)
        self.assertEqual(self.req(base + "/kill", "POST", "wrong")[0], 401)
        code, body = self.req(base + "/kill", "POST", "owner-token-123456")
        self.assertEqual((code, body["paused"]), (200, True))
        self.assertTrue(s.guard_state().paused)
        code, body = self.req(base + "/flatten", "POST", "owner-token-123456")
        self.assertTrue(body["flatten_requested"])
        code, body = self.req(base + "/resume", "POST", "owner-token-123456")
        self.assertEqual((body["paused"], body["flatten_requested"]), (False, False))
        code, st = self.req(base + "/status", token="owner-token-123456")
        self.assertEqual(code, 200)
        self.assertTrue(st["paper_only"])
        self.assertNotIn("owner-token-123456", json.dumps(st))

    def test_no_token_configured_refuses(self):
        base, _ = self.start({})
        self.assertEqual(self.req(base + "/kill", "POST", "anything")[0], 503)


if __name__ == "__main__":
    unittest.main()
