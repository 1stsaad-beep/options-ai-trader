"""One strong-model session (plan / replan / event / review): tool loop with a step limit, every tool call recorded,
one decision snapshot saved per session (model id, prompt version, all tool results — replayable)."""
from __future__ import annotations
import json
from .agent_tools import TOOL_SCHEMAS
from .llm import CapReached, LLMError
from .prompts import PROMPT_VERSION, STRONG_SYSTEM
from .tools import Recorder, save_decision

MAX_STEPS = 24
MAX_RESULT_CHARS = 30_000


def _result_text(r):
    t = json.dumps(r, ensure_ascii=False, default=str)
    return t if len(t) <= MAX_RESULT_CHARS else t[:MAX_RESULT_CHARS] + '…"truncated"'


def _cache_tail(messages):
    """Prompt caching: one moving cache breakpoint on the newest message, so each step re-reads the conversation from
    cache (about a tenth of the input price) instead of paying for it again."""
    for m in messages:
        if isinstance(m["content"], list):
            for b in m["content"]:
                if isinstance(b, dict): b.pop("cache_control", None)
    last = messages[-1]
    if isinstance(last["content"], str):
        last["content"] = [{"type": "text", "text": last["content"]}]
    last["content"][-1]["cache_control"] = {"type": "ephemeral"}


def run_session(claude, tools, store, clock, *, kind, prompt, model, max_steps=MAX_STEPS):
    rec = Recorder()
    tools.tb.recorder = rec
    tools.touched = set()
    messages = [{"role": "user", "content": prompt}]
    final, steps, error = "", 0, None
    try:
        while steps < max_steps:
            steps += 1
            _cache_tail(messages)
            r = claude.create(model=model, system=STRONG_SYSTEM, messages=messages, tools=TOOL_SCHEMAS, purpose=f"strong:{kind}")
            blocks = r.get("content") or []
            messages.append({"role": "assistant", "content": blocks})
            uses = [b for b in blocks if b.get("type") == "tool_use"]
            final = "\n".join(b.get("text", "") for b in blocks if b.get("type") == "text").strip() or final
            if not uses: break
            results = []
            for u in uses:
                try:
                    out = tools.call(u["name"], u.get("input") or {})
                except Exception as e:  # noqa: BLE001 — a tool error goes back to the model, never crashes the loop
                    out = {"ok": False, "error": f"{type(e).__name__}: {e}"}
                if u["name"] not in ("get_bars", "get_indicators", "get_quote", "get_chain", "expected_range", "check_target",
                                     "get_events", "tradable_today"):
                    rec.add(clock(), u["name"], u.get("input"), out)
                results.append({"type": "tool_result", "tool_use_id": u["id"], "content": _result_text(out)})
            messages.append({"role": "user", "content": results})
        else:
            error = "max_steps"
    except CapReached:
        error = "cap_reached"
    except LLMError as e:
        error = f"llm_error: {e}"
    finally:
        tools.tb.recorder = None
    sid = save_decision(store, clock(), f"session:{kind}", rec, model_id=model, prompt_version=PROMPT_VERSION,
                        extra=dict(prompt=prompt, final=final, steps=steps, error=error, journal_ids=sorted(tools.touched)))
    for jid in tools.touched:
        store.snapshot_link(sid, jid)
    store.event(clock(), "session", dict(kind=kind, steps=steps, error=error, snapshot=sid, journal_ids=sorted(tools.touched)))
    return dict(kind=kind, final=final, steps=steps, error=error, snapshot=sid)
