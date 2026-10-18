"""Download OHLCV from Yahoo Finance's public chart API into data/<tf>/<SYM>.csv.

  d1 : 2012-01-01 -> today (split/dividend adjusted via adjclose)
  h1 : last ~730 days (Yahoo limit)
  m5 : last 60 days
  m1 : last ~30 days (Yahoo serves 1-minute data in <= 8-day requests)

Intraday rows are regular-session bars only (includePrePost=false), time = bar
start in UTC. Usage: python fetch_yahoo.py [SYMBOLS...]
"""
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
BASE = "https://query1.finance.yahoo.com/v8/finance/chart/"
DEFAULT = ["SPY", "QQQ", "IWM", "AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "TSLA", "AMD", "JPM", "XOM",
           "UNH", "COST", "^VIX"]


def get(sym: str, params: dict) -> dict:
    q = "&".join(f"{k}={v}" for k, v in params.items())
    url = f"{BASE}{urllib.parse.quote(sym)}?{q}"
    for attempt in range(5):
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=40) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < 4:
                time.sleep(5 * (attempt + 1))
                continue
            raise
    raise RuntimeError("unreachable")


def rows(js: dict, adjusted: bool):
    res = js["chart"]["result"][0]
    ts = res.get("timestamp") or []
    q = res["indicators"]["quote"][0]
    adj = (res["indicators"].get("adjclose") or [{}])[0].get("adjclose") if adjusted else None
    out = []
    for i, t in enumerate(ts):
        o, h, l, c, v = (q[k][i] for k in ("open", "high", "low", "close", "volume"))
        if None in (o, h, l, c):
            continue
        f = (adj[i] / c) if adj and adj[i] and c else 1.0
        out.append((t, o * f, h * f, l * f, c * f, v or 0))
    return out


def save(path: Path, data, note: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    data = sorted({r[0]: r for r in data}.values())
    with path.open("w") as f:
        f.write(f"# Source: Yahoo Finance chart API; {note}; fetched {datetime.now(timezone.utc):%Y-%m-%d}; time = bar start UTC\n")
        f.write("time,open,high,low,close,volume\n")
        for t, o, h, l, c, v in data:
            f.write(f"{datetime.fromtimestamp(t, timezone.utc):%Y-%m-%dT%H:%M:%SZ},{o:.4f},{h:.4f},{l:.4f},{c:.4f},{int(v)}\n")
    return len(data)


def main(symbols):
    out = Path(__file__).parent / "data"
    now = int(time.time())
    p1 = int(datetime(2012, 1, 1, tzinfo=timezone.utc).timestamp())
    for sym in symbols:
        name = sym.replace("^", "")
        try:
            n = save(out / "d1" / f"{name}.csv",
                     rows(get(sym, {"period1": p1, "period2": now, "interval": "1d", "events": "div%7Csplit",
                                    "includeAdjustedClose": "true"}), True), "daily, dividend/split adjusted")
            msg = f"{sym}: d1={n}"
            if sym != "^VIX":
                n = save(out / "h1" / f"{name}.csv",
                         rows(get(sym, {"range": "730d", "interval": "1h", "includePrePost": "false"}), False), "1h RTH, split adjusted")
                msg += f" h1={n}"
                n = save(out / "m5" / f"{name}.csv",
                         rows(get(sym, {"range": "60d", "interval": "5m", "includePrePost": "false"}), False), "5m RTH")
                msg += f" m5={n}"
                m1 = []
                end = now
                for _ in range(4):  # 4 x 7 days ~= the 30-day 1m window
                    start = end - 7 * 86400
                    try:
                        m1 += rows(get(sym, {"period1": start, "period2": end, "interval": "1m", "includePrePost": "false"}), False)
                    except Exception as e:  # older chunks may be outside Yahoo's window
                        print(f"  {sym} m1 chunk skipped: {e}")
                        break
                    end = start
                    time.sleep(0.7)
                n = save(out / "m1" / f"{name}.csv", m1, "1m RTH")
                msg += f" m1={n}"
            print(msg, flush=True)
        except Exception as e:
            print(f"{sym}: FAILED {e}", flush=True)
        time.sleep(1.0)


if __name__ == "__main__":
    import urllib.parse  # noqa: F401
    main(sys.argv[1:] or DEFAULT)
