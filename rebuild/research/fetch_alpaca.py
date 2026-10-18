"""Download split/dividend-adjusted regular-session bars from Alpaca (SIP feed).

Keys are read from the environment (APCA_KEY_ID / APCA_SECRET) or from the file in
$ALPACA_ENV (default /root/.secrets/alpaca.env). They are never printed or written to
the repository.

python fetch_alpaca.py 5Min 2016-01-01 [SYM ...]  -> data/m5a/SYM.csv (time = bar start, UTC)
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

SYMS = ["SPY", "QQQ", "IWM", "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "AMD", "JPM", "XOM", "UNH", "COST"]


def keys():
    kid, sec = os.environ.get("APCA_KEY_ID"), os.environ.get("APCA_SECRET")
    if not (kid and sec):
        for line in Path(os.environ.get("ALPACA_ENV", "/root/.secrets/alpaca.env")).read_text().splitlines():
            k, _, v = line.partition("=")
            if k == "APCA_KEY_ID":
                kid = v.strip()
            if k == "APCA_SECRET":
                sec = v.strip()
    return kid, sec


def fetch(sym, tf, start, end, kid, sec):
    rows, token = [], None
    while True:
        q = dict(timeframe=tf, start=start, end=end, limit=10000, adjustment="all", feed="sip")
        if token:
            q["page_token"] = token
        url = f"https://data.alpaca.markets/v2/stocks/{sym}/bars?" + urllib.parse.urlencode(q)
        req = urllib.request.Request(url, headers={"APCA-API-KEY-ID": kid, "APCA-API-SECRET-KEY": sec})
        for attempt in range(6):
            try:
                with urllib.request.urlopen(req, timeout=60) as r:
                    d = json.load(r)
                break
            except Exception as e:  # rate limit / transient
                code = getattr(e, "code", type(e).__name__)
                print(f"  {sym} retry {attempt}: {code}", file=sys.stderr, flush=True)
                time.sleep(2 + 5 * attempt)
        else:
            raise RuntimeError(f"{sym}: failed")
        rows += d.get("bars") or []
        token = d.get("next_page_token")
        if not token:
            return rows
        time.sleep(0.31)  # < 200 requests/min


def main():
    tf = sys.argv[1] if len(sys.argv) > 1 else "5Min"
    start = (sys.argv[2] if len(sys.argv) > 2 else "2016-01-01") + "T00:00:00Z"
    syms = sys.argv[3:] or SYMS
    from datetime import timedelta
    end = (datetime.now(timezone.utc) - timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%SZ")  # free plan: no SIP for the last 15 min
    kid, sec = keys()
    out = Path("data") / ("m5a" if tf == "5Min" else tf.lower())
    out.mkdir(parents=True, exist_ok=True)
    import pandas as pd
    for s in syms:
        rows = fetch(s, tf, start, end, kid, sec)
        df = pd.DataFrame(rows)
        t = pd.to_datetime(df["t"], utc=True)
        ny = t.dt.tz_convert("America/New_York")
        mins = ny.dt.hour * 60 + ny.dt.minute
        keep = (mins >= 570) & (mins < 960)  # 09:30 <= start < 16:00
        df = df[keep.to_numpy()]
        t = t[keep.to_numpy()]
        o = pd.DataFrame({"time": t.dt.strftime("%Y-%m-%dT%H:%M:%SZ").to_numpy(), "open": df["o"].to_numpy(), "high": df["h"].to_numpy(),
                          "low": df["l"].to_numpy(), "close": df["c"].to_numpy(), "volume": df["v"].to_numpy()})
        p = out / f"{s}.csv"
        with p.open("w") as f:
            f.write(f"# Source: Alpaca SIP {tf} bars, adjustment=all, regular session; fetched {end[:10]}; time = bar start UTC\n")
            o.to_csv(f, index=False)
        print(s, len(o), o["time"].iloc[0], o["time"].iloc[-1], flush=True)


if __name__ == "__main__":
    main()
