"""Stage 2: indicators in code, data tools (bars, quote with age, chain), size-tool stub, events, shadow ledger,
decision snapshots."""
import datetime as dt
import json
import math
import random
import unittest

from oat_agent import data as D, indicators as I, nyse, shadow as SH
from oat_agent.broker import FakeBroker
from oat_agent.config import OwnerSettings
from oat_agent.events import Events
from oat_agent.executor import Executor
from oat_agent.models import Contract, EntryRequest, Quote
from oat_agent.net import Http
from oat_agent.sizetools import UnavailableSizeTools
from oat_agent.store import Store
from oat_agent.tools import Recorder, ToolBox, save_decision
from tests.fakes import FakeData, bars_5m

try:
    import pandas as pd
except ImportError:  # pragma: no cover
    pd = None

NOW = nyse.utc(2026, 10, 19, 15)
TODAY = dt.date(2026, 10, 19)


class Clock:
    def __init__(self, t): self.t = t
    def __call__(self): return self.t


def series(n=300, seed=1):
    rnd = random.Random(seed)
    c = [100.0]
    for _ in range(n - 1): c.append(c[-1] * (1 + rnd.gauss(0, 0.01)))
    h = [x * (1 + abs(rnd.gauss(0, 0.004))) for x in c]
    l = [x * (1 - abs(rnd.gauss(0, 0.004))) for x in c]
    return h, l, c


class Indicators(unittest.TestCase):
    def test_simple_identities(self):
        self.assertEqual(I.sma([1, 2, 3, 4], 2), [None, 1.5, 2.5, 3.5])
        self.assertEqual(I.rsi(list(range(1, 40)))[-1], 100.0)
        m, u, lo, w = I.bollinger([5.0] * 25)
        self.assertEqual((u[-1], lo[-1], w[-1]), (5.0, 5.0, 0.0))
        self.assertAlmostEqual(I.relative_strength([100, 110], [100, 105]), 5.0)

    @unittest.skipIf(pd is None, "pandas not installed")
    def test_against_pandas_reference(self):
        h, l, c = series()
        s = pd.Series(c)
        # EMA seeded with SMA: compare after warm-up with pandas ewm (adjust=False) seeded the same way
        e = I.ema(c, 20)
        ref = pd.concat([pd.Series([s[:20].mean()]), s[20:]]).ewm(span=20, adjust=False).mean().tolist()
        self.assertAlmostEqual(e[-1], ref[-1], places=9)
        # Bollinger with population sd
        m, u, lo, w = I.bollinger(c)
        sd = s.rolling(20).std(ddof=0).iloc[-1]
        self.assertAlmostEqual(u[-1], s.rolling(20).mean().iloc[-1] + 2 * sd, places=9)
        # Wilder RSI
        d = s.diff()
        g, ls = d.clip(lower=0), (-d).clip(lower=0)
        ag = [None] * len(c); al = [None] * len(c)
        ag[14], al[14] = g[1:15].mean(), ls[1:15].mean()
        for i in range(15, len(c)):
            ag[i] = (ag[i - 1] * 13 + g[i]) / 14; al[i] = (al[i - 1] * 13 + ls[i]) / 14
        self.assertAlmostEqual(I.rsi(c)[-1], 100 - 100 / (1 + ag[-1] / al[-1]), places=9)
        # MACD line = EMA12 - EMA26
        line, sig, hist = I.macd(c)
        self.assertAlmostEqual(line[-1], I.ema(c, 12)[-1] - I.ema(c, 26)[-1], places=12)
        self.assertAlmostEqual(hist[-1], line[-1] - sig[-1], places=12)

    def test_atr_adx_keltner_ranges(self):
        h, l, c = series()
        a = I.atr(h, l, c)[-1]
        self.assertGreater(a, 0)
        adx_, p, q = I.adx(h, l, c)
        self.assertTrue(0 <= adx_[-1] <= 100 and 0 <= p[-1] <= 100 and 0 <= q[-1] <= 100)
        m, u, lo = I.keltner(h, l, c)
        self.assertAlmostEqual(u[-1] - m[-1], 2 * I.atr(h, l, c, 10)[-1])

    def test_vwap_resets_each_session_and_bands(self):
        b = bars_5m(TODAY, [10, 11, 12]) + bars_5m(dt.date(2026, 10, 20), [20, 20])
        v = I.session_vwap(b)
        self.assertAlmostEqual(v[2]["vwap"], 11.0)
        self.assertAlmostEqual(v[3]["vwap"], 20.0)
        self.assertGreater(v[2]["up1"], v[2]["vwap"])
        self.assertAlmostEqual(I.anchored_vwap(b, b[1]["t"])[2], 11.5)

    def test_volume_profile_and_rvol(self):
        b = bars_5m(TODAY, [10] * 10 + [12] * 2)
        vp = I.volume_profile(b, bins=10)
        self.assertLess(abs(vp["poc"] - 10), 0.5)
        self.assertLessEqual(vp["val"], vp["poc"]); self.assertGreaterEqual(vp["vah"], vp["poc"])
        prev = bars_5m(dt.date(2026, 10, 16), [10] * 6, vol=1000)
        cur = bars_5m(TODAY, [10] * 6, vol=2000)
        self.assertAlmostEqual(I.relative_volume(prev + cur), 2.0)


class DataLayer(unittest.TestCase):
    def test_hourly_atlas_buckets_and_rth(self):
        b = bars_5m(TODAY, [float(i) for i in range(78)])
        h = D.to_hourly(b)
        self.assertEqual([nyse.hm(x["t"]) for x in h], ["09:30", "10:00", "11:00", "12:00", "13:00", "14:00", "15:00"])
        self.assertEqual(h[0]["v"], 6000)
        self.assertEqual(h[1]["v"], 12000)
        self.assertTrue(D.in_rth(nyse.utc(2026, 10, 19, 13, 30)))
        self.assertFalse(D.in_rth(nyse.utc(2026, 10, 19, 13, 25)))

    def test_only_completed_bars(self):
        b = bars_5m(TODAY, [1.0] * 6)                     # 09:30..09:55
        now = nyse.utc(2026, 10, 19, 13, 57)              # 09:57: the 09:55 bar is still forming
        self.assertEqual(len(D.completed(b, "5m", now)), 5)
        h = D.to_hourly(bars_5m(TODAY, [1.0] * 12))
        self.assertEqual(len(D.completed(h, "1h", nyse.utc(2026, 10, 19, 14, 30))), 1)   # 10:30: only 09:30-10:00 done

    def test_alpaca_bars_request_is_sip_on_data_host_with_paging(self):
        calls = []

        class R:
            status = 200
            def __init__(self, b): self.b = b
            def read(self): return json.dumps(self.b).encode()
            def __enter__(self): return self
            def __exit__(self, *a): return False

        pages = [{"bars": [{"t": "2026-10-19T13:30:00Z", "o": 1, "h": 2, "l": 0.5, "c": 1.5, "v": 10}], "next_page_token": "p2"},
                 {"bars": [{"t": "2026-10-19T13:35:00Z", "o": 1.5, "h": 2, "l": 1, "c": 1.8, "v": 12}], "next_page_token": None}]

        def opener(req, timeout):
            calls.append(req.full_url); return R(pages[len(calls) - 1])
        d = D.AlpacaData(http=Http(opener=opener), env={"ALPACA_PAPER_KEY_ID": "k" * 8, "ALPACA_PAPER_SECRET_KEY": "s" * 8})
        bars = d.bars("AAPL", "5m", 10, nyse.utc(2026, 10, 19, 15))
        self.assertEqual(len(bars), 2)
        self.assertTrue(all(u.startswith("https://data.alpaca.markets/v2/stocks/AAPL/bars?") for u in calls))
        self.assertIn("feed=sip", calls[0]); self.assertIn("page_token=p2", calls[1])
        self.assertNotIn("s" * 8, repr(d))


def toolbox(clock=None, data=None):
    data = data or FakeData()
    return ToolBox(data, UnavailableSizeTools(), Events(env={}), clock or Clock(NOW), ["AAPL", "NVDA"]), data


class Tools(unittest.TestCase):
    def test_quote_reports_age(self):
        tb, d = toolbox()
        d.snap["AAPL"] = dict(last=250.0, last_ts=NOW - dt.timedelta(seconds=42), bid=249.9, ask=250.1, quote_ts=NOW,
                              day_open=248, day_high=251, day_low=247, day_vwap=249.5, day_volume=1, prev_close=247.5)
        q = tb.call("get_quote", {"sym": "AAPL"})
        self.assertEqual(q["last_age_s"], 42.0)
        self.assertEqual(q["day_vwap"], 249.5)

    def test_chain_merges_contracts_quotes_and_straddle(self):
        tb, d = toolbox()
        d.snap["AAPL"] = dict(last=250.0, last_ts=NOW, bid=None, ask=None, quote_ts=None, day_open=None, day_high=None,
                              day_low=None, day_vwap=None, day_volume=None, prev_close=None)
        d.chain("AAPL", TODAY, [240.0, 245.0, 250.0, 255.0, 260.0, 300.0],
                lambda r, k: (1.0, 1.2) if k == 250.0 else (0.5, 0.6), NOW - dt.timedelta(seconds=3))
        c = tb.call("get_chain", {"sym": "AAPL", "expiries": [TODAY.isoformat()]})
        e = c["expiries"][0]
        self.assertNotIn(300.0, [r["strike"] for r in e["contracts"]])            # outside the +/-8 % window
        self.assertEqual(e["straddle"]["strike"], 250.0)
        self.assertAlmostEqual(e["straddle"]["implied_move"], 2.2)
        r = next(x for x in e["contracts"] if x["strike"] == 255.0 and x["type"] == "call")
        self.assertEqual((r["oi"], r["quote_age_s"], r["delta"]), (355, 3.0, 0.3))

    def test_tradable_today_from_the_real_chain(self):
        tb, d = toolbox()
        d.contracts[("AAPL", TODAY)] = [dict(symbol="AAPL261019C00250000")]
        d.contracts[("NVDA", dt.date(2026, 10, 20))] = [dict(symbol="NVDA261020C00200000")]
        t = tb.call("tradable_today", {})
        self.assertEqual(t["next_session"], "2026-10-20")
        self.assertEqual({s["sym"]: s["expiries"] for s in t["symbols"]}, {"AAPL": ["2026-10-19"], "NVDA": ["2026-10-20"]})

    def test_indicators_tool_and_errors(self):
        tb, d = toolbox(Clock(nyse.utc(2026, 10, 19, 20)))
        d.bar_map[("AAPL", "5m")] = bars_5m(TODAY, [100 + math.sin(i / 5) for i in range(78)])
        out = tb.call("get_indicators", {"sym": "AAPL", "tf": "5m", "names": ["rsi", "macd", "vwap", "ema20", "volume_profile"]})
        self.assertEqual(out["bars"], 78)
        self.assertEqual(len(out["rsi"]), 3)
        self.assertIn("vwap", out["vwap"])
        with self.assertRaises(ValueError):
            tb.call("get_indicators", {"sym": "AAPL", "tf": "5m", "names": ["magic"]})

    def test_size_tools_are_stubbed_until_atlas_contract(self):
        tb, _ = toolbox()
        self.assertFalse(tb.call("expected_range", {"sym": "AAPL"})["available"])
        self.assertFalse(tb.call("check_target", {"sym": "AAPL", "price": 260})["available"])

    def test_events_never_invent_dates(self):
        e = Events(env={}).get("AAPL", TODAY, 5)
        self.assertEqual((e["macro"], e["earnings"]), ([], []))
        self.assertIn("macro_note", e); self.assertIn("earnings_note", e)
        e2 = Events(env={"OAT_MACRO_EVENTS_JSON": json.dumps([{"date": "2026-10-21", "kind": "CPI"}, {"date": "2026-11-30", "kind": "FOMC"}])}).get("AAPL", TODAY, 5)
        self.assertEqual([m["kind"] for m in e2["macro"]], ["CPI"])

    def test_decision_snapshot_is_replayable(self):
        tb, d = toolbox()
        d.snap["AAPL"] = dict(last=250.0, last_ts=NOW, bid=1, ask=2, quote_ts=NOW, day_open=1, day_high=1, day_low=1, day_vwap=1,
                              day_volume=1, prev_close=1)
        s = Store()
        tb.recorder = Recorder()
        q = tb.call("get_quote", {"sym": "AAPL"})
        sid = save_decision(s, NOW, "entry", tb.recorder, journal_id="J1", model_id="claude-x", prompt_version="p1")
        snap = s.snapshot_get(sid)
        self.assertEqual((snap["model_id"], snap["prompt_version"], snap["journal_id"]), ("claude-x", "p1", "J1"))
        self.assertEqual(snap["payload"]["calls"][0]["result"], json.loads(json.dumps(q, default=str)))
        self.assertEqual(s.snapshots_for("J1"), [sid])


class Shadow(unittest.TestCase):
    def test_seed_is_deterministic_and_logged(self):
        self.assertEqual(SH.random_direction("m1", "J1"), SH.random_direction("m1", "J1"))
        dirs = [SH.random_direction("m1", f"J{i}") for i in range(2000)]
        share = dirs.count("call") / len(dirs)
        self.assertTrue(0.45 < share < 0.55, share)

    def test_pick_strike_mirrors_the_otm_distance(self):
        strikes = [240.0, 245.0, 250.0, 255.0, 260.0]
        self.assertEqual(SH.pick_strike(strikes, 250.4, 4.6, "call"), 255.0)
        self.assertEqual(SH.pick_strike(strikes, 250.4, 4.6, "put"), 245.0)
        self.assertEqual(SH.pick_strike(strikes, 250.4, 0.1, "put"), 250.0)       # nearest OTM

    def setup_exec(self):
        clk = Clock(NOW)
        b, s, d = FakeBroker(1000), Store(), FakeData()
        led = SH.ShadowLedger(s, d, "master-seed-1")
        x = Executor(b, s, OwnerSettings(), clk, shadow=led)
        d.chain("AAPL", TODAY, [240.0, 245.0, 250.0, 255.0, 260.0], lambda r, k: (1.0, 1.1), NOW)
        c = Contract("AAPL", "call", TODAY, 255.0)
        b.quotes[c.occ] = Quote(1.0, 1.1, NOW - dt.timedelta(seconds=1))
        b.stock["AAPL"] = (250.0, NOW - dt.timedelta(seconds=2))
        return clk, b, s, d, x, c

    def test_agent_trade_and_shadow_share_entry_and_exit_time(self):
        clk, b, s, d, x, c = self.setup_exec()
        jid = s.journal_add(NOW, "thesis", {})
        self.assertTrue(x.enter(EntryRequest(c, 1, 1.10, journal_id=jid, invalidation=248.0)).ok)
        r = s.shadow_get(jid)
        self.assertEqual(r["status"], "pending_fill")
        self.assertEqual(r["body"]["seed"], SH.seed_for("master-seed-1", jid))
        self.assertEqual(r["body"]["entry_ts"], NOW.isoformat())
        self.assertEqual(r["body"]["shadow"]["strike"], 255.0 if r["body"]["direction"] == "call" else 245.0)
        x.reconcile()
        self.assertEqual(s.shadow_get(jid)["status"], "open")
        clk.t = NOW + dt.timedelta(minutes=30)
        b.quotes[c.occ] = Quote(1.5, 1.6, clk.t)
        d.chain("AAPL", TODAY, [240.0, 245.0, 250.0, 255.0, 260.0], lambda r, k: (0.4, 0.5), clk.t)
        self.assertTrue(x.exit(b.positions()[0], "INVALIDATION", "x").ok)
        r = s.shadow_get(jid)
        self.assertEqual(r["status"], "closed")
        self.assertEqual(r["body"]["exit_ts"], clk.t.isoformat())
        self.assertEqual(r["body"]["exit_reason"], "INVALIDATION")
        self.assertAlmostEqual(r["body"]["agent"]["pnl_realistic"], (1.5 - 1.1) * 100)
        self.assertAlmostEqual(r["body"]["shadow"]["pnl_realistic"], (0.4 - 1.1) * 100)
        x.reconcile()
        self.assertEqual(s.shadow_get(jid)["body"]["agent"]["alpaca_exit_fill"], 1.5)
        cmp_ = SH.comparison(s)
        self.assertEqual((cmp_["trades"], cmp_["skill_claim_allowed"]), (1, False))

    def test_unfilled_agent_order_voids_the_shadow(self):
        clk, b, s, d, x, c = self.setup_exec()
        jid = s.journal_add(NOW, "thesis", {})
        self.assertTrue(x.enter(EntryRequest(c, 1, 1.05, journal_id=jid, invalidation=248.0)).ok)   # below ask: rests
        oid = b.orders[-1].id
        b.cancel(oid)
        x.reconcile()
        self.assertEqual(s.shadow_get(jid)["status"], "void")
        self.assertIsNone(s.meta(c.occ))

    def test_order_check_snapshot_is_saved_for_every_entry_attempt(self):
        clk, b, s, d, x, c = self.setup_exec()
        jid = s.journal_add(NOW, "thesis", {})
        b.stock["AAPL"] = (250.0, NOW - dt.timedelta(seconds=120))           # stale -> blocked
        r = x.enter(EntryRequest(c, 1, 1.10, journal_id=jid, invalidation=248.0))
        self.assertFalse(r.ok)
        snap = s.snapshot_get(s.snapshots_for(jid)[0])
        self.assertEqual(snap["kind"], "order_check")
        self.assertIn("STALE_PRICE", snap["payload"]["guard_codes"])


if __name__ == "__main__":
    unittest.main()


class Feed(unittest.TestCase):
    def test_new_5m_bars_drive_invalidation_exits_once(self):
        from oat_agent.bar_feed import BarFeed
        from oat_agent.code_layer import CodeLayer
        clk = Clock(nyse.utc(2026, 10, 19, 14, 0))
        b, s, d = FakeBroker(1000), Store(), FakeData()
        x = Executor(b, s, OwnerSettings(), clk)
        c = Contract("AAPL", "call", TODAY, 255.0)
        b.quotes[c.occ] = Quote(1.0, 1.1, clk.t)
        b.stock["AAPL"] = (250.0, clk.t)
        jid = s.journal_add(clk.t, "thesis", {})
        self.assertTrue(x.enter(EntryRequest(c, 1, 1.10, journal_id=jid, invalidation=248.0)).ok)
        layer = CodeLayer(x, s, x.s, clk)
        feed = BarFeed(d, s, b, layer, clk)
        d.bar_map[("AAPL", "5m")] = bars_5m(TODAY, [250.0] * 6)        # up to 09:55
        self.assertEqual(len(feed.poll()), 1)
        self.assertEqual(feed.poll(), [])                              # nothing new
        d.bar_map[("AAPL", "5m")] += [dict(t=nyse.utc(2026, 10, 19, 14, 0), o=249, h=249, l=247, c=247.5, v=1)]
        clk.t = nyse.utc(2026, 10, 19, 14, 6)
        self.assertEqual(len(feed.poll()), 1)
        self.assertEqual(b.positions(), [])                            # 5m close 247.5 < 248 -> exited
