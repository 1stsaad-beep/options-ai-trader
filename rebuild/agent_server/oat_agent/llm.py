"""Claude Messages API client (stdlib HTTP through the allow-listed client). Every call is priced and logged against
the monthly cap BEFORE the next call; at the cap no model is called. Unknown models are refused (no price = no cap)."""
from __future__ import annotations
import json
import os
from .config import ANTHROPIC_URL

# USD per million tokens — platform.claude.com/docs/en/about-claude/pricing, read 2026-10-21.
# Owner override: OAT_MODEL_PRICES_JSON = {"model": {"in":..,"out":..,"cache_write":..,"cache_read":..}}.
PRICES = {
    "claude-fable-5-1": {"in": 10.0, "out": 50.0, "cache_write": 12.5, "cache_read": 0.25},
    "claude-opus-5-5": {"in": 4.0, "out": 20.0, "cache_write": 5.0, "cache_read": 0.20},
    "claude-sonnet-5-5": {"in": 2.0, "out": 10.0, "cache_write": 2.5, "cache_read": 0.10},
    "claude-haiku-5-5": {"in": 0.10, "out": 0.50, "cache_write": 0.125, "cache_read": 0.01,
                         "long": {"above": 100_000, "in": 0.50, "out": 2.50, "cache_write": 0.625, "cache_read": 0.05}},
}


class LLMError(Exception):
    pass


class CapReached(LLMError):
    pass


def prices(env=None):
    env = os.environ if env is None else env
    p = {k: dict(v) for k, v in PRICES.items()}
    p.update(json.loads(env.get("OAT_MODEL_PRICES_JSON", "{}") or "{}"))
    return p


def cost_usd(model, usage, table):
    if model not in table: raise LLMError(f"no price for model {model}; refusing to call it")
    t = table[model]
    inp, out = usage.get("input_tokens", 0), usage.get("output_tokens", 0)
    cw, cr = usage.get("cache_creation_input_tokens", 0) or 0, usage.get("cache_read_input_tokens", 0) or 0
    if "long" in t and inp + cw + cr > t["long"]["above"]: t = t["long"]
    return (inp * t["in"] + out * t["out"] + cw * t["cache_write"] + cr * t["cache_read"]) / 1_000_000


class Claude:
    def __init__(self, http, cost_cap, clock, env=None):
        env = os.environ if env is None else env
        self.http, self.cap, self.clock = http, cost_cap, clock
        self._key = env.get("ANTHROPIC_API_KEY", "")
        self.table = prices(env)

    def __repr__(self):
        return "Claude(api.anthropic.com)"

    def create(self, *, model, system, messages, tools=None, max_tokens=4096, purpose="", temperature=None):
        now = self.clock()
        if self.cap.reached(now): raise CapReached("monthly cap reached")
        if model not in self.table: raise LLMError(f"no price for model {model}; refusing to call it")
        if not self._key: raise LLMError("ANTHROPIC_API_KEY not set")
        body = {"model": model, "max_tokens": max_tokens,
                "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}], "messages": messages}
        if tools: body["tools"] = tools
        if temperature is not None: body["temperature"] = temperature
        code, r = self.http.request("POST", f"{ANTHROPIC_URL}/v1/messages",
                                    {"x-api-key": self._key, "anthropic-version": "2023-06-01"}, body)
        if code >= 300:
            raise LLMError(f"messages API {code}: {(r or {}).get('error', {}).get('type', '')}")
        usd = cost_usd(model, r.get("usage") or {}, self.table)
        u = r.get("usage") or {}
        self.cap.record(now, usd, model=model, input_tokens=u.get("input_tokens", 0), output_tokens=u.get("output_tokens", 0), purpose=purpose)
        return r
