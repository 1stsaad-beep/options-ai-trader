"""Client of the ATLAS agent routes (AI-LAYERS.md "Agent routes"; ATLAS = the eyes, ER3/BV1 sizes + the journal layer
«صفقات الوكيل»). No ATLAS engine code here — only HTTPS calls.

- Base URL: ATLAS_BASE_URL (Railway variable; never in the repo). Auth: Authorization: Bearer BRIDGE_TOKEN.
- Signatures both ways over the exact raw body: X-Atlas-Ts (UTC epoch ms), X-Atlas-Sig = hex(HMAC-SHA256(secret,
  ts + "\\n" + body)), X-Atlas-Key-Id. BRIDGE_HMAC_KEY = "secret" or "k1:s1[,k2:s2]" (sign with the first, verify with
  any; secrets shorter than 16 characters are ignored, as on the ATLAS side).
- Every response must carry a valid signature and a timestamp within 60 s, otherwise it is rejected.
- Until the owner says ATLAS is live (OAT_ATLAS_LIVE=1) the size tools stay on the stub and journal posts wait in a
  local outbox."""
from __future__ import annotations
import hashlib
import hmac
import json
import os
import re
import time
from decimal import Decimal, InvalidOperation
from urllib.parse import urlencode

REPLAY_S = 60
JID = re.compile(r"^[A-Za-z0-9_.:-]{6,80}$")
TICKER = re.compile(r"^[A-Z][A-Z0-9.]{0,9}$")
THESIS_KEYS = ("journal_id", "ts", "sym", "model_id", "prompt_version", "data_age_s", "scenarios", "er3", "bv1", "events_near",
               "contract", "entry_plan", "invalidation_level", "exit_plan", "expected_option_value_at_target", "confidence_note")
OUTCOME_KEYS = ("journal_id", "fills", "exit_reason", "pnl_realistic", "pnl_alpaca_fill")


class AtlasError(Exception):
    def __init__(self, code, message=""):
        super().__init__(f"{code}: {message}")
        self.code = code


def parse_keys(raw):
    out = []
    for i, part in enumerate(x.strip() for x in (raw or "").split(",") if x.strip()):
        kid, sec = part.split(":", 1) if ":" in part else (f"k{i + 1}", part)
        if kid and len(sec) >= 16:
            out.append((kid.strip(), sec.encode()))
    return out


def sign(secret: bytes, ts: str, body: bytes) -> str:
    return hmac.new(secret, ts.encode() + b"\n" + body, hashlib.sha256).hexdigest()


def verify(keys, ts: str, body: bytes, sig: str, key_id: str | None) -> bool:
    ok = False
    for kid, sec in keys:
        if key_id and kid != key_id: continue
        ok |= hmac.compare_digest(sign(sec, ts, body), (sig or "").lower())
    return ok


def dec(x, places=4):
    """Prices as decimal strings (ATLAS contract)."""
    if x is None: return None
    d = Decimal(str(round(float(x), places)))
    return format(d.normalize(), "f") if d == d.to_integral() else format(d, "f")


def _D(x):
    try:
        d = Decimal(str(x))
        return d if d.is_finite() else None
    except (InvalidOperation, ValueError):
        return None


def validate_journal(kind, body):
    """Same checks as the ATLAS server (agent.validate_journal), run locally before sending."""
    keys = THESIS_KEYS if kind == "thesis" else OUTCOME_KEYS
    missing = [k for k in keys if k not in body]
    if missing: raise AtlasError("LOCAL_BAD_REQUEST", f"missing keys {missing}")
    if not isinstance(body["journal_id"], str) or not JID.match(body["journal_id"]):
        raise AtlasError("LOCAL_BAD_REQUEST", "journal_id must be 6-80 chars [A-Za-z0-9_.:-]")
    if kind == "thesis":
        if not isinstance(body["sym"], str) or not TICKER.match(body["sym"]): raise AtlasError("LOCAL_BAD_REQUEST", "sym")
        if not isinstance(body["scenarios"], list) or not body["scenarios"]: raise AtlasError("LOCAL_BAD_REQUEST", "scenarios")
        if not isinstance(body["contract"], dict): raise AtlasError("LOCAL_BAD_REQUEST", "contract")
        if _D(body["invalidation_level"]) is None: raise AtlasError("LOCAL_BAD_REQUEST", "invalidation_level")


class AtlasClient:
    def __init__(self, http, env=None, now_ms=None):
        env = os.environ if env is None else env
        self.base = (env.get("ATLAS_BASE_URL") or "").rstrip("/")
        self._token = env.get("BRIDGE_TOKEN", "")
        self._keys = parse_keys(env.get("BRIDGE_HMAC_KEY"))
        self.http = http
        self.now_ms = now_ms or (lambda: int(time.time() * 1000))

    def __repr__(self):
        return "AtlasClient(<ATLAS_BASE_URL>)"

    @property
    def configured(self):
        return bool(self.base and self._token and self._keys)

    def _check_response(self, code, headers, raw):
        ts, sig, kid = headers.get("x-atlas-ts", ""), headers.get("x-atlas-sig", ""), headers.get("x-atlas-key-id")
        if not sig or not ts.isdigit():
            raise AtlasError("UNSIGNED_RESPONSE", f"http {code}")
        if abs(self.now_ms() - int(ts)) > REPLAY_S * 1000:
            raise AtlasError("STALE_RESPONSE", f"http {code}")
        if not verify(self._keys, ts, raw, sig, kid):
            raise AtlasError("BAD_RESPONSE_SIGNATURE", f"http {code}")
        body = json.loads(raw) if raw else {}
        if code >= 300:
            raise AtlasError(body.get("code", f"HTTP_{code}"), body.get("message_ar", ""))
        return body

    def _get(self, path, params):
        if not self.configured: raise AtlasError("NOT_CONFIGURED", "ATLAS_BASE_URL / BRIDGE_TOKEN / BRIDGE_HMAC_KEY")
        code, headers, raw = self.http.request_raw("GET", f"{self.base}{path}?{urlencode(params)}",
                                                   {"Authorization": f"Bearer {self._token}"})
        return self._check_response(code, headers, raw)

    def expected_range(self, sym):
        return self._get("/v1/agent/expected_range", {"symbol": sym})

    def check_target(self, sym, price):
        return self._get("/v1/agent/check_target", {"symbol": sym, "price": dec(price)})

    def post_journal(self, kind, body):
        if not self.configured: raise AtlasError("NOT_CONFIGURED", "ATLAS_BASE_URL / BRIDGE_TOKEN / BRIDGE_HMAC_KEY")
        validate_journal(kind, body)
        raw = json.dumps({"kind": kind, "body": body}, ensure_ascii=False, separators=(",", ":")).encode()
        ts = str(self.now_ms())
        kid, sec = self._keys[0]
        headers = {"Authorization": f"Bearer {self._token}", "X-Atlas-Ts": ts, "X-Atlas-Sig": sign(sec, ts, raw), "X-Atlas-Key-Id": kid}
        code, rh, rraw = self.http.request_raw("POST", f"{self.base}/v1/agent/journal", headers, raw)
        return self._check_response(code, rh, rraw)


class AtlasSizeTools:
    """SizeTools backed by ATLAS. Any failure (unconfigured, AGENT_NO_RANGE, bad signature, network) = unavailable —
    a target is NEVER reported as 'within' without a verified answer."""

    def __init__(self, client: AtlasClient):
        self.c = client

    def expected_range(self, sym):
        try:
            r = self.c.expected_range(sym)
            return {"available": bool((r.get("er3") or {}).get("available") or (r.get("bv1") or {}).get("available")), **r}
        except AtlasError as e:
            return {"available": False, "sym": sym, "error": e.code}
        except Exception as e:  # noqa: BLE001
            return {"available": False, "sym": sym, "error": f"NETWORK: {type(e).__name__}"}

    def check_target(self, sym, price):
        try:
            r = self.c.check_target(sym, price)
            if r.get("verdict") not in ("within_1h", "within_today", "within_2_sessions", "outside"):
                return {"available": False, "sym": sym, "price": price, "error": "BAD_VERDICT"}
            return {"available": True, **r}
        except AtlasError as e:
            return {"available": False, "sym": sym, "price": price, "error": e.code}
        except Exception as e:  # noqa: BLE001
            return {"available": False, "sym": sym, "price": price, "error": f"NETWORK: {type(e).__name__}"}


class JournalOutbox:
    """Thesis / outcome posts to ATLAS. Queued locally (kv 'atlas_outbox'), sent in order when ATLAS is live.
    A thesis is always sent before its outcome; an outcome answered AGENT_NOT_FOUND stays queued."""

    def __init__(self, store, client: AtlasClient, live: bool):
        self.store, self.c, self.live = store, client, live

    def enqueue(self, kind, body):
        validate_journal(kind, body)
        q = self.store.get("atlas_outbox", [])
        q.append({"kind": kind, "body": body, "attempts": 0, "last_error": None})
        self.store.put("atlas_outbox", q)

    def pending(self):
        return self.store.get("atlas_outbox", [])

    def flush(self, max_items=20):
        if not self.live or not self.c.configured: return {"sent": 0, "queued": len(self.pending())}
        q, keep, sent = self.pending(), [], 0
        for item in q:
            if sent >= max_items:
                keep.append(item); continue
            try:
                self.c.post_journal(item["kind"], item["body"])
                sent += 1
            except AtlasError as e:
                item["attempts"] += 1; item["last_error"] = e.code
                if e.code in ("AGENT_BAD_REQUEST", "LOCAL_BAD_REQUEST"):
                    self.store.event_safe("atlas_journal_rejected", {"kind": item["kind"], "error": e.code,
                                                                     "journal_id": item["body"].get("journal_id")})
                else:
                    keep.append(item)
            except Exception as e:  # noqa: BLE001
                item["attempts"] += 1; item["last_error"] = type(e).__name__; keep.append(item)
        self.store.put("atlas_outbox", keep)
        return {"sent": sent, "queued": len(keep)}


def size_tools_from_env(env=None):
    """Stub until the owner sets OAT_ATLAS_LIVE=1 (ATLAS deployed); then the signed ATLAS routes."""
    from .net import Http
    from .sizetools import UnavailableSizeTools
    env = os.environ if env is None else env
    if env.get("OAT_ATLAS_LIVE") != "1":
        return UnavailableSizeTools(), None
    client = AtlasClient(Http(env.get("ATLAS_BASE_URL")), env=env)
    return AtlasSizeTools(client), client
