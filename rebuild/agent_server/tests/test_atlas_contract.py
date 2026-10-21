"""Contract tests for the ATLAS agent routes with fixtures signed by ATLAS's own sign() (valid, tampered, stale,
rotated key, NO_RANGE, unsigned NOT_CONFIGURED) and the exact signature ATLAS expects on our POSTs."""
import datetime as dt
import io
import json
import unittest
from pathlib import Path

from oat_agent import atlas_client as AC
from oat_agent.net import ForbiddenHost, Http
from oat_agent.store import Store

FX = json.loads((Path(__file__).parent / "vectors" / "atlas_agent_fixtures.json").read_text(encoding="utf-8"))
BASE = "https://atlas.test.invalid"
ENV = {"ATLAS_BASE_URL": BASE, "BRIDGE_TOKEN": "bridge-token-test-000", "BRIDGE_HMAC_KEY": FX["bridge_hmac_key"]}


class Resp:
    def __init__(self, status, headers, body):
        self.status, self._h, self._b = status, headers, body.encode()
        self.headers = self
    def items(self): return self._h.items()
    def read(self): return self._b
    def __enter__(self): return self
    def __exit__(self, *a): return False


def opener_for(name, seen):
    import urllib.error
    f = FX["responses"][name]

    def op(req, timeout):
        seen.append(req)
        if f["status"] >= 300:
            raise urllib.error.HTTPError(req.full_url, f["status"], "x", Resp(f["status"], f["headers"], f["body"]), io.BytesIO(f["body"].encode()))
        return Resp(f["status"], f["headers"], f["body"])
    return op


class HTTPErrorHeaders(dict):
    pass


def client(name, seen=None, now_ms=None, env=None):
    seen = [] if seen is None else seen
    http = Http(atlas_base_url=BASE, opener=opener_for(name, seen))
    return AC.AtlasClient(http, env=ENV if env is None else env, now_ms=lambda: now_ms or FX["now_ms"]), seen


class Signatures(unittest.TestCase):
    def test_fixture_clock_is_the_test_session(self):
        self.assertEqual(dt.datetime.fromtimestamp(FX["now_ms"] / 1000, dt.timezone.utc), dt.datetime(2026, 10, 19, 15, tzinfo=dt.timezone.utc))

    def test_our_post_signature_equals_atlas(self):
        p = FX["post_signature"]
        keys = AC.parse_keys(FX["bridge_hmac_key"])
        self.assertEqual(AC.sign(keys[0][1], p["ts"], p["raw_body"].encode()), p["atlas_sig"])
        self.assertTrue(p["atlas_verifies"])

    def test_key_parsing_matches_atlas_rules(self):
        self.assertEqual([k for k, _ in AC.parse_keys("k1:aaaaaaaaaaaaaaaa,k2:bbbbbbbbbbbbbbbb")], ["k1", "k2"])
        self.assertEqual([k for k, _ in AC.parse_keys("aaaaaaaaaaaaaaaa")], ["k1"])
        self.assertEqual(AC.parse_keys("k1:short"), [])                       # < 16 chars ignored


class Responses(unittest.TestCase):
    def test_valid_expected_range(self):
        c, seen = client("expected_range_valid")
        r = c.expected_range("NVDA")
        self.assertEqual(r["er3"]["h4"]["path_hi"], "244.10")
        req = seen[0]
        self.assertEqual(req.full_url, f"{BASE}/v1/agent/expected_range?symbol=NVDA")
        self.assertEqual(req.get_header("Authorization"), "Bearer bridge-token-test-000")

    def test_tampered_body_is_rejected(self):
        c, _ = client("expected_range_tampered")
        with self.assertRaises(AC.AtlasError) as e:
            c.expected_range("NVDA")
        self.assertEqual(e.exception.code, "BAD_RESPONSE_SIGNATURE")

    def test_stale_response_is_rejected(self):
        c, _ = client("expected_range_stale")
        with self.assertRaises(AC.AtlasError) as e:
            c.expected_range("NVDA")
        self.assertEqual(e.exception.code, "STALE_RESPONSE")

    def test_rotated_key_verifies_only_when_we_know_it(self):
        c, _ = client("expected_range_rotated_key")
        self.assertEqual(c.expected_range("NVDA")["symbol"], "NVDA")
        only_k1 = {**ENV, "BRIDGE_HMAC_KEY": FX["bridge_hmac_key"].split(",")[0]}
        c2, _ = client("expected_range_rotated_key", env=only_k1)
        with self.assertRaises(AC.AtlasError):
            c2.expected_range("NVDA")

    def test_check_target_and_never_within_on_failure(self):
        c, seen = client("check_target_valid")
        t = AC.AtlasSizeTools(c).check_target("NVDA", 243.5)
        self.assertEqual((t["available"], t["verdict"]), (True, "within_1h"))
        self.assertIn("price=243.5", seen[0].full_url)
        for bad in ("no_range", "expected_range_tampered", "not_configured_unsigned"):
            c, _ = client(bad)
            t = AC.AtlasSizeTools(c).check_target("NVDA", 243.5)
            self.assertFalse(t["available"], bad)
            self.assertNotIn("verdict", t)

    def test_no_range_is_unavailable(self):
        c, _ = client("no_range")
        r = AC.AtlasSizeTools(c).expected_range("NVDA")
        self.assertEqual((r["available"], r["error"]), (False, "AGENT_NO_RANGE"))

    def test_unsigned_error_is_not_trusted(self):
        c, _ = client("not_configured_unsigned")
        with self.assertRaises(AC.AtlasError) as e:
            c.expected_range("NVDA")
        self.assertEqual(e.exception.code, "UNSIGNED_RESPONSE")

    def test_unconfigured_client_never_calls(self):
        c, seen = client("expected_range_valid", env={})
        self.assertFalse(AC.AtlasSizeTools(c).expected_range("NVDA")["available"])
        self.assertEqual(seen, [])

    def test_atlas_host_comes_only_from_the_variable(self):
        with self.assertRaises(ForbiddenHost):
            Http(atlas_base_url=None).request_raw("GET", f"{BASE}/v1/agent/expected_range?symbol=NVDA")


THESIS = {"journal_id": "J20261019150000-ab12cd34", "ts": "2026-10-19T15:00:00Z", "sym": "NVDA", "model_id": "m", "prompt_version": "p1",
          "data_age_s": 3, "scenarios": [{"name": "A", "primary": True, "confirm": "x", "invalidation": "239.5", "targets": []}],
          "er3": {}, "bv1": {}, "events_near": [], "contract": {"occ_symbol": "NVDA261019C00245000"},
          "entry_plan": {"limit": "1.10", "reason": "x"}, "invalidation_level": "239.5", "exit_plan": {},
          "expected_option_value_at_target": "2.00", "confidence_note": "x"}


class Journal(unittest.TestCase):
    def test_signed_post_and_signed_answer(self):
        c, seen = client("journal_stored")
        r = c.post_journal("thesis", THESIS)
        self.assertTrue(r["stored"])
        req = seen[0]
        raw = req.data
        keys = AC.parse_keys(FX["bridge_hmac_key"])
        self.assertEqual(req.get_header("X-atlas-sig"), AC.sign(keys[0][1], req.get_header("X-atlas-ts"), raw))
        self.assertEqual(req.get_header("X-atlas-key-id"), "k1")
        self.assertEqual(json.loads(raw)["kind"], "thesis")

    def test_local_validation_matches_atlas(self):
        for k in AC.THESIS_KEYS:
            b = {x: v for x, v in THESIS.items() if x != k}
            with self.assertRaises(AC.AtlasError):
                AC.validate_journal("thesis", b)
        with self.assertRaises(AC.AtlasError):
            AC.validate_journal("thesis", {**THESIS, "journal_id": "x"})
        with self.assertRaises(AC.AtlasError):
            AC.validate_journal("thesis", {**THESIS, "invalidation_level": "abc"})
        AC.validate_journal("outcome", {"journal_id": THESIS["journal_id"], "fills": [], "exit_reason": "TIME_EXIT",
                                        "pnl_realistic": "-1", "pnl_alpaca_fill": "0"})

    def test_outbox_waits_until_live_then_sends_in_order(self):
        s = Store()
        c, seen = client("journal_stored")
        ob = AC.JournalOutbox(s, c, live=False)
        ob.enqueue("thesis", THESIS)
        self.assertEqual(ob.flush(), {"sent": 0, "queued": 1})
        self.assertEqual(seen, [])
        ob.live = True
        self.assertEqual(ob.flush(), {"sent": 1, "queued": 0})

    def test_decimal_strings(self):
        self.assertEqual(AC.dec(222.16), "222.16")
        self.assertEqual(AC.dec(1.1), "1.1")
        self.assertEqual(AC.dec(250.0), "250")


if __name__ == "__main__":
    unittest.main()
