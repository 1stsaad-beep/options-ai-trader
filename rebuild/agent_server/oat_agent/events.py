"""Events (spec §4 get_events): earnings (Finnhub, owner key later), CPI and FOMC dates. Dates only; a warning in the
thesis, never a block. Macro dates come from the owner variable OAT_MACRO_EVENTS_JSON
([{"date": "YYYY-MM-DD", "kind": "CPI"|"FOMC", "note": "..."}]) — no dates are invented here."""
from __future__ import annotations
import datetime as dt
import json
import os
from urllib.parse import urlencode


class Events:
    def __init__(self, http=None, env=None):
        env = env or os.environ
        self.http = http
        self._fin = env.get("FINNHUB_API_KEY", "")
        self.macro = json.loads(env.get("OAT_MACRO_EVENTS_JSON", "[]") or "[]")

    def get(self, sym: str, today: dt.date, days: int = 5):
        end = today + dt.timedelta(days=days)
        macro = [e for e in self.macro if today.isoformat() <= e["date"] <= end.isoformat()]
        out = dict(sym=sym, from_=today.isoformat(), to=end.isoformat(), macro=macro, earnings=[], earnings_source=None)
        if not self.macro: out["macro_note"] = "لا توجد تواريخ CPI/FOMC مُدخلة من المالك"
        if self._fin and self.http is not None:
            q = urlencode({"from": today.isoformat(), "to": end.isoformat(), "symbol": sym})
            code, body = self.http.request("GET", f"https://finnhub.io/api/v1/calendar/earnings?{q}", {"X-Finnhub-Token": self._fin})
            if code < 300:
                out["earnings"] = [dict(date=e.get("date"), hour=e.get("hour")) for e in (body or {}).get("earningsCalendar", [])]
                out["earnings_source"] = "finnhub"
        else:
            out["earnings_note"] = "مفتاح Finnhub غير مُدخل بعد — تواريخ الأرباح غير متاحة"
        return out
