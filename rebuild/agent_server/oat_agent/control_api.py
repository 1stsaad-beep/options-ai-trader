"""Owner control API (phone / browser): health, status, kill switch, resume, kill-and-flatten.
Auth: Authorization: Bearer <OWNER_TOKEN> (Railway variable). No endpoint returns or logs a secret."""
from __future__ import annotations
import hmac
import json
import os
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def make_handler(store, executor, env=None):
    token = (env or os.environ).get("OWNER_TOKEN", "")

    class H(BaseHTTPRequestHandler):
        server_version = "oat-agent"

        def log_message(self, *a):          # no request logging (headers may carry the token)
            pass

        def _send(self, code, body):
            raw = json.dumps(body, ensure_ascii=False, default=str).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def _auth(self):
            if not token: self._send(503, {"error": "OWNER_TOKEN not configured"}); return False
            got = self.headers.get("Authorization", "")
            if not hmac.compare_digest(got.encode(), f"Bearer {token}".encode()):
                self._send(401, {"error": "unauthorized"}); return False
            return True

        def do_GET(self):
            if self.path == "/health": return self._send(200, {"ok": True, "paper_only": True})
            if self.path == "/status":
                if not self._auth(): return
                now = executor.clock()
                st = store.guard_state()
                return self._send(200, dict(
                    paper_only=True, paused=st.paused, flatten_requested=bool(store.get("flatten_requested", False)),
                    settings=asdict(executor.s), month_spend_usd=round(executor.cost.month_spend(now), 4),
                    day_spend_usd=round(executor.cost.day_spend(now), 4), cap_reached=executor.cost.reached(now),
                    agent_enabled=bool(store.get("agent_enabled", False)), orders_today=st.orders_today, day_start_equity=st.day_start_equity,
                    positions=len(executor.broker.positions()), market_open=executor.status(now).is_open))
            self._send(404, {"error": "not found"})

        def do_POST(self):
            if self.path not in ("/kill", "/resume", "/flatten", "/agent/on", "/agent/off"): return self._send(404, {"error": "not found"})
            if not self._auth(): return
            now = executor.clock()
            st = store.guard_state()
            if self.path in ("/agent/on", "/agent/off"):
                store.put("agent_enabled", self.path == "/agent/on")
                store.event(now, "owner_control", {"action": self.path[1:]})
                return self._send(200, {"ok": True, "agent_enabled": bool(store.get("agent_enabled", False))})
            if self.path == "/kill": st.paused = True
            elif self.path == "/resume":
                st.paused = False
                store.put("flatten_requested", False)
            else:
                st.paused = True
                store.put("flatten_requested", True)
            store.save_guard_state(st)
            store.event(now, "owner_control", {"action": self.path[1:]})
            self._send(200, {"ok": True, "paused": st.paused, "flatten_requested": bool(store.get("flatten_requested", False))})

    return H


def serve(store, executor, port=None, env=None):
    srv = ThreadingHTTPServer(("0.0.0.0", int(port or (env or os.environ).get("PORT", 8080))), make_handler(store, executor, env))
    return srv
