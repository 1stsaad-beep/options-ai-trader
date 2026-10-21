"""Stage 3: model client + pricing/cap, strong-model session (thesis before order, guards, snapshots), Haiku watcher
(no tools), schedule 08:45 / 09:46 / event / 16:15, outcomes to the journal + ATLAS outbox, dossiers, owner switch."""
import datetime as dt
import json
import unittest

from oat_agent import agent as AG, llm, nyse
from oat_agent.agent_tools import AgentTools, TOOL_SCHEMAS
from oat_agent.atlas_client import AtlasClient, JournalOutbox
from oat_agent.broker import FakeBroker
from oat_agent.config import OwnerSettings
from oat_agent.costs import CostCap
from oat_agent.dossiers import Dossiers, stats_from_daily
from oat_agent.events import Events
from oat_agent.executor import Executor
from oat_agent.models import Contract, Quote
from oat_agent.net import Http
from oat_agent.outcomes import Outcomes
from oat_agent.session import run_session
from oat_agent.shadow import ShadowLedger
from oat_agent.sizetools import UnavailableSizeTools
from oat_agent.store import Store
from oat_agent.tools import ToolBox
from tests.fakes import FakeData

NOW = nyse.utc(2026, 10, 19, 15)
TODAY = dt.date(2026, 10, 19)
OCC = Contract("AAPL", "call", TODAY, 255.0).occ


class Clock:
    def __init__(self, t): self.t = t
    def __call__(self): return self.t


class FakeClaude:
    """Scripted Messages API: each call pops the next response; usage is priced like the real client."""
    def __init__(self, cap, clock, script):
        self.cap, self.clock, self.script, self.calls = cap, clock, list(script), []

    def create(self, **kw):
        if self.cap.reached(self.clock()): raise llm.CapReached("cap")
        self.calls.append(kw)
        r = self.script.pop(0) if self.script else {"content": [{"type": "text", "text": "done"}]}
        r.setdefault("usage", {"input_tokens": 1000, "output_tokens": 100})
        self.cap.record(self.clock(), llm.cost_usd(kw["model"], r["usage"], llm.PRICES), model=kw["model"], purpose=kw.get("purpose"))
        return r


def tool_use(i, name, inp):
    return {"type": "tool_use", "id": f"t{i}", "name": name, "input": inp}


def world(t=NOW, enabled=True):
    clk = Clock(t)
    b, s, d = FakeBroker(1000), Store(), FakeData()
    x = Executor(b, s, OwnerSettings(), clk, shadow=ShadowLedger(s, d, "seed"))
    ob = JournalOutbox(s, AtlasClient(Http(), env={}), live=False)
    x.on_exit_done = Outcomes(s, ob, clk).on_exit_done
    tb = ToolBox(d, UnavailableSizeTools(), Events(env={}), clk, ["AAPL"])
    tools = AgentTools(tb, x, s, ob, Dossiers(s), clk, "claude-fable-5-1")
    s.put("agent_enabled", enabled)
    d.snap["AAPL"] = dict(last=250.0, last_ts=t - dt.timedelta(seconds=2), bid=249.9, ask=250.1, quote_ts=t, day_open=249,
                          day_high=251, day_low=248, day_vwap=249.8, day_volume=1, prev_close=248)
    d.chain("AAPL", TODAY, [245.0, 250.0, 255.0], lambda r, k: (1.0, 1.1), t)
    b.quotes[OCC] = Quote(1.0, 1.1, t - dt.timedelta(seconds=1))
    b.stock["AAPL"] = (250.0, t - dt.timedelta(seconds=2))
    return clk, b, s, d, x, tools, ob


THESIS_ARGS = dict(sym="AAPL", scenarios=[{"name": "breakout", "primary": True, "confirm": "5m close > 251", "invalidation": 248.5,
                                           "targets": [{"price": 253.0, "check_target": "unavailable"}]},
                                          {"name": "fail", "primary": False, "confirm": "5m close < 248.5", "invalidation": 251.5, "targets": []}],
                   contract={"occ_symbol": OCC, "type": "call", "strike": 255.0, "expiry": TODAY.isoformat(), "bid": 1.0, "ask": 1.1},
                   entry_plan={"limit": 1.1, "reason": "reclaim"}, invalidation_level=248.5, exit_plan={"targets": [253.0], "time_exit": "15:50"},
                   expected_option_value_at_target=1.6, confidence_note="تحليل ذاتي غير مختبر")


class Pricing(unittest.TestCase):
    def test_costs_from_the_published_table(self):
        self.assertAlmostEqual(llm.cost_usd("claude-opus-5-5", {"input_tokens": 1_000_000, "output_tokens": 100_000}, llm.PRICES), 4 + 2)
        self.assertAlmostEqual(llm.cost_usd("claude-haiku-5-5", {"input_tokens": 50_000, "output_tokens": 1000}, llm.PRICES), 0.005 + 0.0005)
        self.assertAlmostEqual(llm.cost_usd("claude-haiku-5-5", {"input_tokens": 150_000, "output_tokens": 0}, llm.PRICES), 0.075)
        with self.assertRaises(llm.LLMError):
            llm.cost_usd("claude-unknown", {}, llm.PRICES)

    def test_client_refuses_at_cap_and_unknown_models_without_calling(self):
        s, clk, called = Store(), Clock(NOW), []
        cap = CostCap(s, 300)
        c = llm.Claude(Http(opener=lambda *a, **k: called.append(1)), cap, clk, env={"ANTHROPIC_API_KEY": "sk-test-0000000000"})
        with self.assertRaises(llm.LLMError):
            c.create(model="gpt-x", system="s", messages=[])
        cap.record(NOW, 300.0)
        with self.assertRaises(llm.CapReached):
            c.create(model="claude-haiku-5-5", system="s", messages=[])
        self.assertEqual(called, [])

    def test_client_posts_to_anthropic_and_records_cost(self):
        seen = []

        class R:
            status = 200
            def read(self): return json.dumps({"content": [{"type": "text", "text": "hi"}], "usage": {"input_tokens": 2000, "output_tokens": 500}}).encode()
            def __enter__(self): return self
            def __exit__(self, *a): return False
        s, clk = Store(), Clock(NOW)
        cap = CostCap(s, 300)
        c = llm.Claude(Http(opener=lambda req, timeout: (seen.append(req), R())[1]), cap, clk, env={"ANTHROPIC_API_KEY": "sk-test-0000000000"})
        c.create(model="claude-opus-5-5", system="sys", messages=[{"role": "user", "content": "x"}], purpose="t")
        self.assertEqual(seen[0].full_url, "https://api.anthropic.com/v1/messages")
        self.assertEqual(seen[0].get_header("Anthropic-version"), "2023-06-01")
        self.assertAlmostEqual(cap.month_spend(NOW), (2000 * 4 + 500 * 20) / 1e6)
        self.assertEqual(repr(c), "Claude(api.anthropic.com)")


class Session(unittest.TestCase):
    def script_entry(self, jid_holder):
        return [
            {"content": [tool_use(1, "get_quote", {"sym": "AAPL"}), tool_use(2, "get_chain", {"sym": "AAPL", "expiries": [TODAY.isoformat()]})]},
            {"content": [tool_use(3, "journal_write", THESIS_ARGS)]},
        ]

    def test_thesis_then_order_through_guards_with_snapshot(self):
        clk, b, s, d, x, tools, ob = world()
        cap = x.cost
        script = self.script_entry(None)
        fc = FakeClaude(cap, clk, script)

        def place_after_thesis(**kw):
            r = FakeClaude.create(fc, **kw)
            return r
        r = run_session(fc, tools, s, clk, kind="event", prompt="go", model="claude-fable-5-1", max_steps=2)
        jid = next(iter(tools.touched))
        self.assertTrue(jid.startswith("J20261019"))
        fc.script = [{"content": [tool_use(4, "place_order", {"journal_id": jid, "occ_symbol": OCC, "qty": 1, "limit": 1.1})]}]
        r = run_session(fc, tools, s, clk, kind="event", prompt="enter", model="claude-fable-5-1")
        self.assertEqual(b.placed[0][:3], (OCC, "buy_to_open", 1))
        self.assertTrue(s.snapshots_for(jid))
        snap = s.snapshot_get(s.snapshots_for(jid)[0])
        self.assertEqual(snap["model_id"], "claude-fable-5-1")
        self.assertEqual(ob.pending()[0]["kind"], "thesis")
        self.assertEqual(ob.pending()[0]["body"]["invalidation_level"], "248.5")
        self.assertIn("tools", fc.calls[0])

    def test_order_refused_without_owner_switch(self):
        clk, b, s, d, x, tools, ob = world(enabled=False)
        jid = tools.call("journal_write", THESIS_ARGS)["journal_id"]
        r = tools.call("place_order", {"journal_id": jid, "occ_symbol": OCC, "qty": 1, "limit": 1.1})
        self.assertEqual(r["codes"], ["AGENT_NOT_ENABLED"])
        self.assertEqual(b.placed, [])

    def test_order_needs_its_own_thesis_and_contract(self):
        clk, b, s, d, x, tools, ob = world()
        self.assertEqual(tools.call("place_order", {"journal_id": "J-missing-000", "occ_symbol": OCC, "qty": 1, "limit": 1.1})["codes"], ["NO_JOURNAL"])
        jid = tools.call("journal_write", THESIS_ARGS)["journal_id"]
        other = Contract("AAPL", "call", TODAY, 250.0).occ
        self.assertEqual(tools.call("place_order", {"journal_id": jid, "occ_symbol": other, "qty": 1, "limit": 1.1})["codes"], ["CONTRACT_MISMATCH"])
        self.assertEqual(b.placed, [])

    def test_guard_block_is_returned_to_the_model(self):
        clk, b, s, d, x, tools, ob = world()
        jid = tools.call("journal_write", THESIS_ARGS)["journal_id"]
        b.stock["AAPL"] = (250.0, clk.t - dt.timedelta(seconds=90))
        r = tools.call("place_order", {"journal_id": jid, "occ_symbol": OCC, "qty": 1, "limit": 1.1})
        self.assertFalse(r["ok"])
        self.assertIn("STALE_PRICE", r["codes"])

    def test_incomplete_thesis_is_refused(self):
        clk, b, s, d, x, tools, ob = world()
        r = tools.call("journal_write", {**THESIS_ARGS, "scenarios": []})
        self.assertFalse(r["ok"])

    def test_tool_errors_go_back_to_the_model_and_steps_are_bounded(self):
        clk, b, s, d, x, tools, ob = world()
        fc = FakeClaude(x.cost, clk, [{"content": [tool_use(i, "get_quote", {"sym": "ZZZZ"})]} for i in range(10)])
        r = run_session(fc, tools, s, clk, kind="event", prompt="x", model="claude-fable-5-1", max_steps=3)
        self.assertEqual((r["steps"], r["error"]), (3, "max_steps"))
        res = fc.calls[1]["messages"][-1]["content"][0]["content"]
        self.assertIn("KeyError", res)

    def test_session_stops_at_the_cap(self):
        clk, b, s, d, x, tools, ob = world()
        x.cost.record(clk.t, 300)
        r = run_session(FakeClaude(x.cost, clk, []), tools, s, clk, kind="plan", prompt="x", model="claude-fable-5-1")
        self.assertEqual(r["error"], "cap_reached")

    def test_tool_list_matches_the_spec(self):
        names = {t["name"] for t in TOOL_SCHEMAS}
        for n in ("get_bars", "get_indicators", "get_quote", "get_chain", "expected_range", "check_target", "get_events",
                  "place_order", "modify", "close", "set_alert", "journal_write", "journal_read", "dossier_read",
                  "dossier_write", "hypothesis_add"):
            self.assertIn(n, names)
        self.assertNotIn("run_engines", names); self.assertNotIn("wave_count", names)


class Outcome(unittest.TestCase):
    def test_outcome_after_the_exit_fill(self):
        clk, b, s, d, x, tools, ob = world()
        jid = tools.call("journal_write", THESIS_ARGS)["journal_id"]
        self.assertTrue(tools.call("place_order", {"journal_id": jid, "occ_symbol": OCC, "qty": 1, "limit": 1.1})["ok"])
        x.reconcile()
        clk.t += dt.timedelta(minutes=20)
        b.quotes[OCC] = Quote(1.4, 1.5, clk.t)
        self.assertTrue(tools.call("close", {"occ_symbol": OCC, "reason": "target"})["ok"])
        x.reconcile()
        out = [r for r in s.journal(50) if r["kind"] == "outcome"]
        self.assertEqual(len(out), 1)
        o = out[0]["body"]
        self.assertEqual((o["exit_reason"], o["pnl_realistic"], o["pnl_alpaca_fill"]), ("DISCRETIONARY", "30", "30"))
        self.assertEqual([i["kind"] for i in ob.pending()], ["thesis", "outcome"])
        x.on_exit_done(jid, b.orders[-1])
        self.assertEqual(len([r for r in s.journal(50) if r["kind"] == "outcome"]), 1)    # idempotent


class Schedule(unittest.TestCase):
    def test_jobs_at_0845_0946_1615_trading_days_only(self):
        t = lambda h, m, d=19: nyse.to_utc(2026, 10, d, h, m)
        self.assertEqual(AG.due_jobs(t(8, 44), set()), [])
        self.assertEqual(AG.due_jobs(t(8, 45), set()), ["plan"])
        self.assertEqual(AG.due_jobs(t(9, 46), {"plan"}), ["replan"])
        self.assertEqual(AG.due_jobs(t(16, 14), {"plan", "replan"}), [])
        self.assertEqual(AG.due_jobs(t(16, 15), {"plan", "replan"}), ["review"])
        self.assertEqual(AG.due_jobs(t(10, 0, 18), set()), [])                                   # Sunday
        self.assertEqual(AG.due_jobs(nyse.to_utc(2026, 11, 26, 9, 0), set()), [])              # Thanksgiving
        self.assertEqual(AG.due_jobs(nyse.to_utc(2026, 11, 27, 13, 15), {"plan", "replan"}), ["review"])   # early close

    def agent(self, clk, s, x, tools, script):
        fc = FakeClaude(x.cost, clk, script)
        return AG.Agent(s, fc, tools, Dossiers(s), tools.tb.data, clk, strong_model="claude-fable-5-1",
                        watcher_model="claude-haiku-5-5", universe=["AAPL"]), fc

    def test_disabled_agent_never_calls_a_model(self):
        clk, b, s, d, x, tools, ob = world(t=nyse.to_utc(2026, 10, 19, 8, 45), enabled=False)
        a, fc = self.agent(clk, s, x, tools, [])
        self.assertEqual(a.tick(), [])
        self.assertEqual(fc.calls, [])

    def test_plan_runs_once_a_day(self):
        clk, b, s, d, x, tools, ob = world(t=nyse.to_utc(2026, 10, 19, 8, 50))
        a, fc = self.agent(clk, s, x, tools, [])
        self.assertEqual([r["kind"] for r in a.tick()], ["plan"])
        self.assertEqual(a.tick(), [])
        self.assertEqual(fc.calls[0]["model"], "claude-fable-5-1")

    def test_alert_goes_to_watcher_which_wakes_the_strong_model_with_gap(self):
        clk, b, s, d, x, tools, ob = world(t=nyse.to_utc(2026, 10, 19, 11, 0))
        s.put("jobs:2026-10-19", ["plan", "replan"])
        wake = {"content": [{"type": "text", "text": '{"wake": true, "reason": "breakout confirmed"}'}]}
        a, fc = self.agent(clk, s, x, tools, [wake, {"content": [{"type": "text", "text": "no trade"}]}])
        a.push_alert({"id": "A1", "sym": "AAPL", "cond": "5m close > 251"}, 251.2)
        ran = a.tick()
        self.assertEqual([r["kind"] for r in ran], ["event"])
        self.assertEqual(fc.calls[0]["model"], "claude-haiku-5-5")
        self.assertNotIn("tools", fc.calls[0])                                   # the watcher can never trade
        self.assertEqual(fc.calls[1]["model"], "claude-fable-5-1")
        fc.script = [wake]
        a.push_alert({"id": "A2", "sym": "AAPL", "cond": "last > 252"}, 252.1)
        clk.t += dt.timedelta(minutes=1)
        self.assertEqual(a.tick(), [])                                           # woken less than 3 min ago

    def test_watcher_noise_and_garbage_do_not_wake(self):
        clk, b, s, d, x, tools, ob = world(t=nyse.to_utc(2026, 10, 19, 11, 0))
        s.put("jobs:2026-10-19", ["plan", "replan"])
        a, fc = self.agent(clk, s, x, tools, [{"content": [{"type": "text", "text": "maybe?"}]}])
        a.push_alert({"id": "A1", "sym": "AAPL", "cond": "last > 1"}, 2)
        self.assertEqual(a.tick(), [])
        self.assertEqual(s.events("watcher")[0]["body"]["reason"], "unparseable watcher answer")

    def test_position_check_every_5_minutes(self):
        clk, b, s, d, x, tools, ob = world(t=nyse.to_utc(2026, 10, 19, 11, 0))
        s.put("jobs:2026-10-19", ["plan", "replan"])
        jid = tools.call("journal_write", THESIS_ARGS)["journal_id"]
        tools.call("place_order", {"journal_id": jid, "occ_symbol": OCC, "qty": 1, "limit": 1.1})
        no = {"content": [{"type": "text", "text": '{"wake": false, "reason": "fine"}'}]}
        a, fc = self.agent(clk, s, x, tools, [no, no, no])
        a.tick(); clk.t += dt.timedelta(minutes=2); a.tick()
        self.assertEqual(len(fc.calls), 1)
        clk.t += dt.timedelta(minutes=3); a.tick()
        self.assertEqual(len(fc.calls), 2)


class DossierStats(unittest.TestCase):
    def test_gap_and_range_statistics(self):
        bars = [dict(o=100, h=101, l=99, c=100), dict(o=102, h=103, l=99.5, c=101), dict(o=99, h=100, l=98, c=98.5)]
        st = stats_from_daily(bars)
        self.assertEqual(st["gaps"], 2)
        self.assertEqual(st["gap_fill_rate"], 0.5)          # up-gap filled (low 99.5 <= 100), down-gap not (high 100 < 101)
        self.assertGreater(st["avg_range_pct"], 0)


class OwnerSwitch(unittest.TestCase):
    def test_agent_on_off_via_control_api(self):
        import threading, urllib.request
        from oat_agent.control_api import serve
        clk, b, s, d, x, tools, ob = world(enabled=False)
        srv = serve(s, x, port=0, env={"OWNER_TOKEN": "owner-token-123456"})
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.shutdown)
        req = urllib.request.Request(f"http://127.0.0.1:{srv.server_address[1]}/agent/on", method="POST", data=b"",
                                     headers={"Authorization": "Bearer owner-token-123456"})
        with urllib.request.urlopen(req, timeout=5) as r:
            self.assertTrue(json.loads(r.read())["agent_enabled"])
        self.assertTrue(s.get("agent_enabled"))


class ServiceBuild(unittest.TestCase):
    def test_build_and_cycle_with_fakes(self):
        from oat_agent.service import build, cycle
        b, d = FakeBroker(1000), FakeData()
        parts = build(env={"OAT_DB_PATH": ":memory:"}, store=Store(), broker=b, data=d, clock=Clock(NOW))
        self.assertFalse(parts["agent"].enabled())
        self.assertEqual(parts["settings"].strong_model, "claude-fable-5-1")
        cycle(parts)
        self.assertTrue(parts["store"].get("shadow_master_seed"))


if __name__ == "__main__":
    unittest.main()


class Caching(unittest.TestCase):
    def test_single_moving_breakpoint(self):
        from oat_agent.session import _cache_tail
        msgs = [{"role": "user", "content": "start"}]
        _cache_tail(msgs)
        msgs += [{"role": "assistant", "content": [{"type": "text", "text": "a"}]},
                 {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "x"}]}]
        _cache_tail(msgs)
        marks = [b for m in msgs for b in (m["content"] if isinstance(m["content"], list) else []) if "cache_control" in b]
        self.assertEqual(len(marks), 1)
        self.assertEqual(marks[0]["type"], "tool_result")
