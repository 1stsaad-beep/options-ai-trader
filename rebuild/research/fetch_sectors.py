"""Sector ETF 5-minute bars (Alpaca SIP, 2016+) -> data/m5s/ (for breadth in strategy B)."""
from pathlib import Path
from datetime import datetime, timezone, timedelta
import pandas as pd
import fetch_alpaca as A
SECT = ["XLB", "XLE", "XLF", "XLI", "XLK", "XLP", "XLU", "XLV", "XLY"]
kid, sec = A.keys()
end = (datetime.now(timezone.utc) - timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
for s in SECT:
    df = pd.DataFrame(A.fetch(s, "5Min", "2016-01-01T00:00:00Z", end, kid, sec))
    t = pd.to_datetime(df["t"], utc=True); ny = t.dt.tz_convert("America/New_York"); m = ny.dt.hour * 60 + ny.dt.minute
    k = ((m >= 570) & (m < 960)).to_numpy(); df, t = df[k], t[k]
    o = pd.DataFrame({"time": t.dt.strftime("%Y-%m-%dT%H:%M:%SZ").to_numpy(), "open": df["o"].to_numpy(), "high": df["h"].to_numpy(),
                      "low": df["l"].to_numpy(), "close": df["c"].to_numpy(), "volume": df["v"].to_numpy()})
    p = Path("data/m5s") / f"{s}.csv"; p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w") as f:
        f.write(f"# Source: Alpaca SIP 5Min, adjustment=all; fetched {end[:10]}; time = bar start UTC\n"); o.to_csv(f, index=False)
    print(s, len(o), flush=True)
