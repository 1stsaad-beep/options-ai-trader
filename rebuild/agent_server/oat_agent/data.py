"""Market data (Algo Trader Plus: SIP equities, OPRA options). Read-only; keys from the environment only.
Bars are returned oldest first as dicts {t (UTC bar start), o, h, l, c, v}; only COMPLETED bars are returned.
Intraday bars are regular-session only unless ext_hours=True. 1h bars are built from 5m regular-session bars in
ATLAS's D-1 buckets (09:30-10:00, then clock hours to 16:00), so the agent and ATLAS see the same hours."""
from __future__ import annotations
import datetime as dt
import os
from urllib.parse import urlencode
from . import config, nyse
from .broker import _t
from .net import Http

TF = {"1m": ("1Min", 1), "5m": ("5Min", 5), "15m": ("15Min", 15), "1d": ("1Day", None), "1w": ("1Week", None),
      "1M": ("1Month", None)}
TFS = ("1m", "5m", "15m", "1h", "1d", "1w", "1M")


class DataError(Exception):
    pass


def in_rth(t: dt.datetime) -> bool:
    s = nyse.session(nyse.wall(t).date())
    return s is not None and s.open_utc <= t < s.close_utc


def bar_end(b, tf):
    if tf in ("1m", "5m", "15m", "1h"):
        mins = {"1m": 1, "5m": 5, "15m": 15}.get(tf)
        if tf == "1h":
            w = nyse.wall(b["t"])
            end = nyse.to_utc(w.year, w.month, w.day, 10, 0) if (w.hour, w.minute) == (9, 30) else b["t"] + dt.timedelta(hours=1)
        else:
            end = b["t"] + dt.timedelta(minutes=mins)
        s = nyse.session(nyse.wall(b["t"]).date())
        return min(end, s.close_utc) if s and b["t"] < s.close_utc else end
    s = nyse.session(nyse.wall(b["t"] + dt.timedelta(hours=6)).date())
    if tf == "1d": return s.close_utc if s else b["t"] + dt.timedelta(days=1)
    return None                                            # weekly/monthly: caller keeps only fully past bars


def completed(bars, tf, now):
    if tf in ("1w", "1M"):
        return bars[:-1] if bars and _same_period(bars[-1]["t"], now, tf) else bars
    return [b for b in bars if bar_end(b, tf) <= now]


def _same_period(t, now, tf):
    a, b = nyse.wall(t), nyse.wall(now)
    return (a.isocalendar()[:2] == b.isocalendar()[:2]) if tf == "1w" else (a.year, a.month) == (b.year, b.month)


def to_hourly(bars5):
    """Aggregate 5m RTH bars into ATLAS D-1 hourly buckets."""
    out, cur, key = [], None, None
    for b in bars5:
        w = nyse.wall(b["t"])
        k = (w.date(), 9) if w.hour == 9 else (w.date(), w.hour)
        start = nyse.to_utc(w.year, w.month, w.day, 9, 30) if w.hour == 9 else nyse.to_utc(w.year, w.month, w.day, w.hour, 0)
        if k != key:
            if cur: out.append(cur)
            cur, key = dict(t=start, o=b["o"], h=b["h"], l=b["l"], c=b["c"], v=b["v"]), k
        else:
            cur["h"], cur["l"], cur["c"], cur["v"] = max(cur["h"], b["h"]), min(cur["l"], b["l"]), b["c"], cur["v"] + b["v"]
    if cur: out.append(cur)
    return out


class AlpacaData:
    def __init__(self, http: Http | None = None, env=None):
        env = env or os.environ
        self._h = {"APCA-API-KEY-ID": env.get("ALPACA_PAPER_KEY_ID", ""), "APCA-API-SECRET-KEY": env.get("ALPACA_PAPER_SECRET_KEY", "")}
        self.http = http or Http(env.get("ATLAS_BASE_URL"))

    def __repr__(self):
        return "AlpacaData(data.alpaca.markets)"

    def _get(self, base, path, params):
        code, body = self.http.request("GET", f"{base}{path}?{urlencode({k: v for k, v in params.items() if v is not None})}", self._h)
        if code >= 300: raise DataError(f"GET {path} -> {code}")
        return body

    # ------------------------------------------------------------------ bars
    def raw_bars(self, sym, tf, start, end, limit=10000):
        out, token = [], None
        while True:
            r = self._get(config.MARKET_DATA_URL, f"/v2/stocks/{sym}/bars",
                          dict(timeframe=TF[tf][0], start=start.isoformat().replace("+00:00", "Z"),
                               end=end.isoformat().replace("+00:00", "Z"), limit=limit, feed="sip", adjustment="split",
                               page_token=token))
            out += [dict(t=_t(b["t"]), o=b["o"], h=b["h"], l=b["l"], c=b["c"], v=b["v"]) for b in (r.get("bars") or [])]
            token = r.get("next_page_token")
            if not token: return out

    def bars(self, sym, tf, n, now, ext_hours=False):
        if tf not in TFS: raise DataError(f"timeframe not supported: {tf}")
        src = "5m" if tf == "1h" else tf
        per_day = {"1m": 390, "5m": 78, "15m": 26, "1d": 1, "1w": 0.2, "1M": 0.05}[src]
        need = n * (12 if tf == "1h" else 1)
        days = int(need / per_day * 1.6) + 5
        bars = self.raw_bars(sym, src, now - dt.timedelta(days=days), now)
        if src in ("1m", "5m", "15m") and not ext_hours:
            bars = [b for b in bars if in_rth(b["t"])]
        if tf == "1h": bars = to_hourly(bars)
        return completed(bars, tf, now)[-n:]

    # ------------------------------------------------------------------ quote
    def snapshot(self, sym):
        r = self._get(config.MARKET_DATA_URL, f"/v2/stocks/{sym}/snapshot", dict(feed="sip"))
        tr, q, d, p = r.get("latestTrade") or {}, r.get("latestQuote") or {}, r.get("dailyBar") or {}, r.get("prevDailyBar") or {}
        return dict(last=tr.get("p"), last_ts=_t(tr.get("t")), bid=q.get("bp"), ask=q.get("ap"), quote_ts=_t(q.get("t")),
                    day_open=d.get("o"), day_high=d.get("h"), day_low=d.get("l"), day_vwap=d.get("vw"), day_volume=d.get("v"),
                    prev_close=p.get("c"))

    # ------------------------------------------------------------------ options
    def option_contracts(self, sym, expiry: dt.date):
        out, token = [], None
        while True:
            r = self._get(config.PAPER_TRADING_URL, "/v2/options/contracts",
                          dict(underlying_symbols=sym, expiration_date=expiry.isoformat(), limit=1000, page_token=token))
            out += r.get("option_contracts") or []
            token = r.get("next_page_token")
            if not token: return out

    def option_snapshots(self, sym, expiry: dt.date):
        out, token = {}, None
        while True:
            r = self._get(config.MARKET_DATA_URL, f"/v1beta1/options/snapshots/{sym}",
                          dict(feed="opra", expiration_date=expiry.isoformat(), limit=1000, page_token=token))
            out.update(r.get("snapshots") or {})
            token = r.get("next_page_token")
            if not token: return out
